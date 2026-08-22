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
from datetime import date, datetime, timezone
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

SOURCES = ("race", "polls", "markets", "finance", "news")


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
    return (ELECTION_DATE - (today or datetime.now(timezone.utc).date())).days


def collect_race(report: RunReport) -> RacePayload:
    from sources.ratings import collect as collect_ratings

    ratings = []
    try:
        ratings = collect_ratings()
    except SourceError as exc:
        report.warnings.append(f"race ratings unavailable: {exc}")

    return RacePayload(
        generated_at=publish.now(),
        election_date=ELECTION_DATE,
        days_until_election=days_until_election(),
        candidates=config.CANDIDATES,
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
        aggregate=aggregate_polls(result.polls, datetime.now(timezone.utc).date()),
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
    history = history[-config.INLINE_HISTORY_POINTS :]

    result = collect(history)
    report.warnings.extend(result.warnings)
    return MarketsPayload(
        generated_at=publish.now(),
        markets=result.markets,
        consensus=result.consensus,
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


def collect_news(report: RunReport) -> NewsPayload:
    from sources.news import collect

    result = collect()
    report.warnings.extend(result.warnings)
    return NewsPayload(
        generated_at=publish.now(),
        items=result.items,
        attribution=result.attribution,
    )


# Collectors that need to read their own prior output to stay idempotent.
NEEDS_DATA_DIR = {"polls", "markets"}

COLLECTORS = {
    "race": ("race.json", collect_race),
    "polls": ("polls.json", collect_polls),
    "markets": ("markets.json", collect_markets),
    "finance": ("finance.json", collect_finance),
    "news": ("news.json", collect_news),
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
        if not (root / name).exists():
            publish.write(name, payload, data_dir)
            report.collected.append(name)


def run(only: list[str] | None, data_dir: str, write: bool) -> RunReport:
    report = RunReport(started_at=publish.now())
    targets = only or list(SOURCES)

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
        "--live-check",
        action="store_true",
        help="verify live endpoints still match the contract; writes nothing",
    )
    args = parser.parse_args()

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
