"""Collector entry point.

Run modes:

    python collector/run.py                 collect everything, write data/
    python collector/run.py --only polls    collect one source
    python collector/run.py --live-check    hit live endpoints, verify shapes, write nothing
    python collector/run.py --dry-run       collect but do not write

Failure policy: a source that breaks does not stop the others. Each failure is
recorded, the remaining files are still published, and the process exits
non-zero so CI shows red. The alternative — swallowing errors — would leave the
app serving stale numbers that look current, which is worse than a visible
failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config  # noqa: E402
import publish  # noqa: E402
from fetch import SourceError, close  # noqa: E402
from schemas import (  # noqa: E402
    ELECTION_DATE,
    AdsPayload,
    FinancePayload,
    GroundPayload,
    MarketsPayload,
    NewsPayload,
    PollsPayload,
    RacePayload,
    ResultsPayload,
)
from schemas.results import ResultsStatus  # noqa: E402

SOURCES = ("race", "polls", "markets", "finance", "news", "ads", "ground", "results")

# Collected on every scheduled run. `results` is deliberately excluded until the
# election is near: probing a dormant endpoint every 20 minutes for months would
# fill the log with misses, and the dormant placeholder serves the app fine.
DEFAULT_SOURCES = ("race", "polls", "markets", "finance", "news", "ads", "ground")

# Days before election day at which results collection switches on by itself.
RESULTS_WINDOW_DAYS = 3


@dataclass
class RunReport:
    started_at: datetime
    collected: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        lines = [
            f"collected: {', '.join(self.collected) or 'nothing'}",
            f"changed:   {', '.join(self.changed) or 'nothing'}",
        ]
        if self.warnings:
            lines.append("warnings:")
            lines.extend(f"  - {w}" for w in self.warnings)
        if self.failed:
            lines.append("FAILED:")
            lines.extend(f"  - {name}: {err}" for name, err in self.failed.items())
        return "\n".join(lines)


def days_until_election(today: date | None = None) -> int:
    return (ELECTION_DATE - (today or datetime.now(UTC).date())).days


def _resolved_fec_ids(data_dir: str) -> dict[str, str]:
    """Read the FEC candidate ids the finance collector actually resolved.

    The ids in config are hints used only to steer that lookup, and one of them
    was wrong: config guessed S0KS00232 for Marshall while the API returned
    S0KS00315. Publishing the hint in race.json meant two files disagreeing about
    the same fact, so race.json now carries the resolved id or none at all.
    """
    existing = Path(data_dir) / "finance.json"
    if not existing.exists():
        return {}
    try:
        previous = json.loads(existing.read_text())
    except json.JSONDecodeError:
        return {}
    return {
        cid: record["fec_candidate_id"]
        for cid, record in (previous.get("candidates") or {}).items()
        if record.get("fec_candidate_id")
    }


def collect_race(report: RunReport, data_dir: str) -> RacePayload:
    from sources.ratings import collect as collect_ratings

    ratings = []
    try:
        ratings, rating_notes = collect_ratings()
        report.warnings.extend(rating_notes)
    except SourceError as exc:
        report.warnings.append(f"race ratings unavailable: {exc}")
    if not ratings:
        report.warnings.append(
            "no race ratings: scraping is off because Cook, Sabato and Inside "
            "Elections all answer 403, and collector/manual/ratings.json is empty "
            "(add an entry there, or run --probe-ratings to retry the pages)"
            if not config.RATINGS_ENABLED
            else "no race ratings parsed — the handicappers' pages may have changed"
        )

    resolved = _resolved_fec_ids(data_dir)
    candidates = [
        candidate.model_copy(update={"fec_candidate_id": resolved.get(candidate.id)})
        for candidate in config.CANDIDATES
    ]

    return RacePayload(
        generated_at=publish.now(),
        election_date=ELECTION_DATE,
        days_until_election=days_until_election(),
        candidates=candidates,
        ratings=ratings,
    )


def _prior_first_seen(data_dir: str, report: RunReport) -> dict[str, str]:
    """Map poll id -> when we first saw it, from the previously published file."""
    existing = Path(data_dir) / "polls.json"
    if not existing.exists():
        return {}
    try:
        previous = json.loads(existing.read_text())
    except json.JSONDecodeError as exc:
        report.warnings.append(f"could not read prior polls.json: {exc}")
        return {}
    return {
        poll["id"]: poll["added_at"]
        for poll in previous.get("polls", [])
        if poll.get("id") and poll.get("added_at")
    }


def collect_polls(report: RunReport, data_dir: str) -> PollsPayload:
    from aggregate import aggregate_polls
    from sources.polls import collect

    result = collect()
    for note in result.skipped:
        report.warnings.append(f"poll row skipped: {note}")
    for note in result.notes:
        report.warnings.append(f"poll row kept, worth checking: {note}")

    # Carry added_at forward for polls we have already seen. Stamping it fresh
    # each run would make every run look like a change, which would both bloat
    # the history directory and make the change signal useless for notifying on
    # genuinely new polls.
    first_seen = _prior_first_seen(data_dir, report)
    for poll in result.polls:
        if poll.id in first_seen:
            poll.added_at = datetime.fromisoformat(first_seen[poll.id])

    return PollsPayload(
        generated_at=publish.now(),
        polls=result.polls,
        aggregate=aggregate_polls(result.polls, datetime.now(UTC).date()),
        attribution=result.attribution,
    )


def collect_markets(report: RunReport, data_dir: str) -> MarketsPayload:
    from schemas.markets import MarketPoint
    from sources.markets import collect

    # Carry the existing series forward so the sparkline survives a fresh run.
    history: list[MarketPoint] = []
    existing = Path(data_dir) / "markets.json"
    if existing.exists():
        try:
            previous = json.loads(existing.read_text())
            history = [
                MarketPoint.model_validate(point)
                for point in (previous.get("consensus") or {}).get("history", [])
            ]
        except (json.JSONDecodeError, ValueError) as exc:
            report.warnings.append(f"could not read prior market history: {exc}")

    # Points from before the epoch answered a different question and cannot be
    # made comparable, so they are dropped rather than carried forward. See
    # config.MARKET_HISTORY_EPOCH for what was wrong with them.
    kept = [point for point in history if point.t >= config.MARKET_HISTORY_EPOCH]
    if len(kept) != len(history):
        report.warnings.append(
            f"discarded {len(history) - len(kept)} market history point(s) "
            f"recorded before {config.MARKET_HISTORY_EPOCH.isoformat()}"
        )
    history = kept[-config.INLINE_HISTORY_POINTS :]

    result = collect(history)
    report.warnings.extend(result.warnings)
    return MarketsPayload(
        generated_at=publish.now(),
        markets=result.markets,
        consensus=result.consensus,
        margin=result.margin,
        attribution=result.attribution,
    )


def collect_finance(report: RunReport) -> FinancePayload:
    from sources.finance import collect

    result = collect()
    report.warnings.extend(result.warnings)
    return FinancePayload(
        generated_at=publish.now(),
        cycle=config.FEC_CYCLE,
        candidates=result.candidates,
        outside_spending=result.outside_spending,
        filings=result.filings,
        attribution=result.attribution,
    )


def collect_news(report: RunReport, data_dir: str) -> NewsPayload:
    from schemas.common import Attribution
    from schemas.news import NewsItem
    from sources.news import collect

    # Carry the previous file forward. news.json is an archive: feeds are short
    # windows, and a feed that fails must not take its stories out of the app. One
    # 503 from Google News took the published file from 78 items to 10.
    previous: list[NewsItem] = []
    credits: list[Attribution] = []
    existing = Path(data_dir) / "news.json"
    if existing.exists():
        try:
            prior = json.loads(existing.read_text())
            previous = [NewsItem.model_validate(item) for item in prior.get("items", [])]
            credits = [Attribution.model_validate(c) for c in prior.get("attribution", [])]
        except (json.JSONDecodeError, ValueError) as exc:
            report.warnings.append(f"could not read prior news.json: {exc}")

    result = collect(previous, credits)
    report.warnings.extend(result.warnings)
    return NewsPayload(
        generated_at=publish.now(),
        items=result.items,
        attribution=result.attribution,
    )


# Collectors that need to read their own prior output to stay idempotent.
NEEDS_DATA_DIR = {"race", "polls", "markets", "news"}

def collect_ads(report: RunReport) -> AdsPayload:
    from sources.ads import collect

    result = collect()
    report.warnings.extend(result.warnings)
    return AdsPayload(
        generated_at=publish.now(),
        broadcast=result.broadcast,
        digital=result.digital,
        attribution=result.attribution,
    )


def collect_ground(report: RunReport) -> GroundPayload:
    from sources.ground import collect

    result = collect()
    report.warnings.extend(result.warnings)
    return GroundPayload(
        generated_at=publish.now(),
        registration=result.registration,
        advance_ballots=result.advance_ballots,
        attribution=result.attribution,
    )


def collect_results(report: RunReport) -> ResultsPayload:
    """Election-night returns.

    Publishes a dormant file rather than failing when there is nothing to report,
    because for all but a few hours of the cycle "no results yet" is the correct
    answer. Every probe attempt is recorded as a warning so a format change shows
    up in the run log well before it matters.
    """
    from sources.results import collect

    data = collect()
    for attempt in data.probes:
        if not attempt.ok:
            report.warnings.append(f"results probe [{attempt.shape}]: {attempt.detail}")

    if data.status == ResultsStatus.PENDING:
        report.warnings.append("no results published yet (expected until election night)")

    return ResultsPayload(
        generated_at=publish.now(),
        status=data.status,
        statewide=data.statewide,
        total_votes=data.total_votes,
        precincts_reporting=data.precincts_reporting,
        precincts_total=data.precincts_total,
        pct_reporting=data.pct_reporting,
        counties=data.counties,
        last_updated=publish.now() if data.statewide else None,
        source_url=data.source_url,
        attribution=data.attribution,
    )


COLLECTORS = {
    "race": ("race.json", collect_race),
    "polls": ("polls.json", collect_polls),
    "markets": ("markets.json", collect_markets),
    "finance": ("finance.json", collect_finance),
    "news": ("news.json", collect_news),
    "ads": ("ads.json", collect_ads),
    "ground": ("ground.json", collect_ground),
    "results": ("results.json", collect_results),
}


def ensure_placeholders(data_dir: str, report: RunReport) -> None:
    """Publish empty-but-valid ads/ground/results so the app never 404s.

    The app must degrade to "no data yet" rather than to an error screen for the
    trackers that are not collecting yet, and results.json in particular sits
    dormant until election night.
    """
    root = Path(data_dir)
    for name, payload in (
        ("ads.json", AdsPayload(generated_at=publish.now())),
        ("ground.json", GroundPayload(generated_at=publish.now())),
        ("results.json", ResultsPayload(generated_at=publish.now())),
    ):
        if name in report.collected:
            continue
        if not (root / name).exists():
            publish.write(name, payload, data_dir)
            report.collected.append(name)


def default_targets(today: date | None = None) -> list[str]:
    """The sources a scheduled run collects, adding results near election day."""
    targets = list(DEFAULT_SOURCES)
    if days_until_election(today) <= RESULTS_WINDOW_DAYS:
        targets.append("results")
    return targets


def run(only: list[str] | None, data_dir: str, write: bool) -> RunReport:
    report = RunReport(started_at=publish.now())
    targets = only or default_targets()

    for name in targets:
        if name not in COLLECTORS:
            report.failed[name] = f"unknown source (known: {', '.join(SOURCES)})"
            continue
        filename, collector = COLLECTORS[name]
        try:
            payload = (
                collector(report, data_dir)
                if name in NEEDS_DATA_DIR
                else collector(report)
            )
            report.collected.append(filename)
            if write and publish.write(filename, payload, data_dir):
                report.changed.append(filename)
        except SourceError as exc:
            report.failed[name] = str(exc)
        except Exception as exc:  # a parser bug must not take down the run
            report.failed[name] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc(file=sys.stderr)

    if write:
        ensure_placeholders(data_dir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Kansas Senate 2026 data collector")
    parser.add_argument("--only", nargs="+", choices=SOURCES, help="collect only these sources")
    parser.add_argument("--data-dir", default=config.DATA_DIR)
    parser.add_argument("--dry-run", action="store_true", help="collect but write nothing")
    parser.add_argument(
        "--probe-markets",
        action="store_true",
        help="list what the prediction-market platforms offer, and exit",
    )
    parser.add_argument(
        "--probe-ads",
        action="store_true",
        help="report what the FCC political-file API actually serves, and exit",
    )
    parser.add_argument(
        "--probe-ground",
        action="store_true",
        help="report what the registration and county dashboards serve, and exit",
    )
    parser.add_argument(
        "--probe-results",
        action="store_true",
        help="diagnose the Kansas election-night results format and exit",
    )
    parser.add_argument(
        "--probe-ratings",
        action="store_true",
        help="report what the handicappers' rating pages actually serve, and exit",
    )
    parser.add_argument(
        "--probe-news",
        action="store_true",
        help="report what each news feed serves and what the filter drops, and exit",
    )
    parser.add_argument(
        "--probe-donors",
        action="store_true",
        help="dump the raw FEC rows behind the largest donors, and exit",
    )
    parser.add_argument(
        "--live-check",
        action="store_true",
        help="verify live endpoints still match the contract; writes nothing",
    )
    args = parser.parse_args()

    probes = {
        "probe_results": ("sources.results", "diagnose"),
        "probe_markets": ("sources.markets", "diagnose"),
        "probe_ads": ("sources.ads", "diagnose"),
        "probe_ground": ("sources.ground", "diagnose"),
        "probe_donors": ("sources.finance", "diagnose"),
        "probe_ratings": ("sources.ratings", "diagnose"),
        "probe_news": ("sources.news", "diagnose"),
    }
    for flag, (module_name, function_name) in probes.items():
        if getattr(args, flag):
            import importlib

            module = importlib.import_module(module_name)
            try:
                print(getattr(module, function_name)())
            finally:
                close()
            return 0

    try:
        report = run(args.only, args.data_dir, write=not (args.dry_run or args.live_check))
    finally:
        close()

    print(report.summary())

    if args.live_check:
        # In live-check mode a warning is also a signal worth surfacing, but only
        # an outright failure fails the job.
        print(f"\nlive-check: {'PASS' if report.ok() else 'FAIL'}")

    return 0 if report.ok() else 1


if __name__ == "__main__":
    raise SystemExit(main())
