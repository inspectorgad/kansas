"""Election-night rehearsal.

Runs the whole results path — parse, aggregate, validate, publish — against
recorded pages representing three points in the night, without touching the
network. It answers the question you actually want answered in October: if the
Kansas page looks like this, does the app show the right thing?

    python collector/rehearse.py                  # all three stages
    python collector/rehearse.py --stage mid      # one stage
    python collector/rehearse.py --data-dir /tmp/x # leave the files behind

This is not a substitute for `run.py --probe-results`, which is the only thing
that can tell you what the real page looks like. It is the check that once the
shape is known, everything downstream of it holds.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import publish  # noqa: E402
from schemas import ResultsPayload  # noqa: E402
from schemas.results import ResultsStatus  # noqa: E402
from sources.results import KANSAS_COUNTIES, _parse_html_table, _precincts  # noqa: E402

FIXTURES = Path(__file__).parent / "tests" / "fixtures" / "enr"
STAGES = ("early", "mid", "final")


def rehearse_stage(stage: str, data_dir: str | Path) -> tuple[ResultsPayload, list[str]]:
    """Parse one stage and return the payload plus anything that looks wrong."""
    page = (FIXTURES / f"{stage}.html").read_text()
    parsed = _parse_html_table(page)
    if parsed is None:
        raise RuntimeError(f"{stage}: the results parser matched nothing")

    reporting, total = _precincts(page)
    pct = round(reporting / total * 100, 2) if reporting and total else None

    payload = ResultsPayload(
        generated_at=publish.now(),
        status=ResultsStatus.FINAL if stage == "final" else ResultsStatus.LIVE,
        statewide=parsed.statewide,
        total_votes=parsed.total_votes,
        precincts_reporting=reporting,
        precincts_total=total,
        pct_reporting=pct,
        counties=parsed.counties,
        last_updated=publish.now(),
        source_url="https://ent.sos.ks.gov/ (rehearsal fixture)",
        attribution=parsed.attribution,
    )
    publish.write("results.json", payload, data_dir)

    return payload, check(payload)


def check(payload: ResultsPayload) -> list[str]:
    """The assertions worth making about any published results file."""
    problems: list[str] = []

    if not payload.statewide:
        problems.append("no statewide totals")

    share_total = sum(row.pct for row in payload.statewide)
    if payload.statewide and abs(share_total - 100.0) > 0.5:
        problems.append(f"candidate shares sum to {share_total:.2f}, not 100")

    county_sum = sum(c.marshall_votes + c.hamilton_votes for c in payload.counties)
    if payload.counties and county_sum != payload.total_votes:
        # Both were found and they disagree, which is worse than finding one.
        problems.append(
            f"county votes sum to {county_sum:,} but statewide says {payload.total_votes:,}"
        )

    unknown = {c.county for c in payload.counties} - set(KANSAS_COUNTIES)
    if unknown:
        problems.append(f"rows that are not Kansas counties: {sorted(unknown)}")

    if len(payload.counties) != len({c.county for c in payload.counties}):
        problems.append("a county appears more than once")

    if payload.pct_reporting is not None and not 0 <= payload.pct_reporting <= 100:
        problems.append(f"precinct reporting out of range: {payload.pct_reporting}")

    return problems


def describe(payload: ResultsPayload) -> str:
    """Render what the app's Race tab would show, so it can be eyeballed."""
    lines = []
    reporting = (
        f"{payload.pct_reporting}% of precincts reporting"
        if payload.pct_reporting is not None
        else "precinct count not reported"
    )
    lines.append(f"  status: {payload.status.value}  ·  {reporting}")

    ranked = sorted(payload.statewide, key=lambda r: r.votes, reverse=True)
    for index, row in enumerate(ranked):
        marker = "→" if index == 0 else " "
        lines.append(f"  {marker} {row.candidate_id:9} {row.votes:>9,}  {row.pct:>5.2f}%")

    if len(ranked) == 2:
        gap = ranked[0].pct - ranked[1].pct
        lines.append(f"    lead: {ranked[0].candidate_id} by {gap:.2f} points")

    counted = [c for c in payload.counties if c.total_votes > 0]
    lines.append(f"  counties with votes: {len(counted)} of {len(payload.counties)} listed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse election night offline")
    parser.add_argument("--stage", choices=STAGES, help="rehearse one stage only")
    parser.add_argument(
        "--data-dir",
        help="write results.json here instead of a temporary directory",
    )
    args = parser.parse_args()

    stages = [args.stage] if args.stage else list(STAGES)
    data_dir = args.data_dir or tempfile.mkdtemp(prefix="ks-rehearsal-")

    print("Election-night rehearsal (offline, recorded pages)")
    print("=" * 52)

    failures = 0
    for stage in stages:
        print(f"\n[{stage}]")
        try:
            payload, problems = rehearse_stage(stage, data_dir)
        except Exception as exc:  # a parser crash is the thing we are looking for
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        print(describe(payload))
        if problems:
            failures += 1
            for problem in problems:
                print(f"  PROBLEM: {problem}")
        else:
            print("  checks passed")

    print(f"\nwrote results.json to {data_dir}")
    print("REHEARSAL PASSED" if not failures else f"REHEARSAL FAILED ({failures} stage(s))")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
