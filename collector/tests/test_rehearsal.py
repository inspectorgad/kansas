"""The election-night rehearsal, run as a test.

This exercises the full results path against recorded pages, so CI catches a
regression in the one code path that gets a single live outing. The fixtures are
deterministic, and they are built so that the count *flips* between the early and
final stages — urban counties report first, so an early Democratic lead narrows
and then reverses.

That is not a quirk of the fixture. It is the single most likely way a reader
misreads this app on election night, and it is why percent-reporting sits beside
every figure on the results screen.
"""

import pytest

from rehearse import STAGES, check, describe, rehearse_stage


@pytest.fixture(params=STAGES)
def stage(request):
    return request.param


def test_every_stage_parses_and_passes_its_checks(stage, tmp_path):
    payload, problems = rehearse_stage(stage, tmp_path)
    assert problems == [], f"{stage}: {problems}"
    assert payload.statewide
    assert payload.total_votes > 0


def test_every_stage_publishes_a_valid_file(stage, tmp_path):
    import json

    rehearse_stage(stage, tmp_path)
    written = json.loads((tmp_path / "results.json").read_text())
    assert written["schema_version"] == 1
    assert written["status"] in ("live", "final")


def test_candidate_shares_always_sum_to_one_hundred(stage, tmp_path):
    payload, _ = rehearse_stage(stage, tmp_path)
    assert sum(row.pct for row in payload.statewide) == pytest.approx(100.0, abs=0.5)


def test_county_votes_reconcile_with_the_statewide_total(stage, tmp_path):
    """Statewide is derived from the counties, so a mismatch means a parse bug."""
    payload, _ = rehearse_stage(stage, tmp_path)
    county_sum = sum(c.marshall_votes + c.hamilton_votes for c in payload.counties)
    assert county_sum == payload.total_votes


def test_the_count_grows_monotonically_through_the_night(tmp_path):
    totals = [rehearse_stage(stage, tmp_path)[0].total_votes for stage in STAGES]
    assert totals == sorted(totals)
    assert totals[0] < totals[-1]


def test_precinct_reporting_climbs_toward_complete(tmp_path):
    pcts = [rehearse_stage(stage, tmp_path)[0].pct_reporting for stage in STAGES]
    assert all(p is not None for p in pcts)
    assert pcts == sorted(pcts)
    assert pcts[-1] > 95.0


def test_the_early_lead_reverses_by_the_final_count(tmp_path):
    """The fixture reproduces the trap: urban counties report first.

    If this ever stops holding, the fixtures no longer exercise the case the
    results screen was designed around, and the ordering should be restored
    rather than the assertion relaxed.
    """
    early, _ = rehearse_stage("early", tmp_path)
    final, _ = rehearse_stage("final", tmp_path)

    def leader(payload):
        return max(payload.statewide, key=lambda r: r.votes).candidate_id

    assert leader(early) == "hamilton"
    assert leader(final) == "marshall"


def test_only_final_is_marked_final(tmp_path):
    """Leaving status at "live" would keep the app polling every minute forever."""
    assert rehearse_stage("final", tmp_path)[0].status.value == "final"
    assert rehearse_stage("mid", tmp_path)[0].status.value == "live"


def test_kansas_counties_named_after_candidates_are_counted_once(tmp_path):
    """Marshall and Hamilton counties must appear as counties, not candidates."""
    payload, _ = rehearse_stage("final", tmp_path)
    names = [c.county for c in payload.counties]
    assert "Marshall" in names
    assert "Hamilton" in names
    assert len(names) == len(set(names))


def test_check_catches_shares_that_do_not_add_up(tmp_path):
    """The rehearsal's own checks must fail on bad data, not just pass on good."""
    payload, _ = rehearse_stage("final", tmp_path)
    payload.statewide[0].pct = 80.0
    payload.statewide[1].pct = 80.0
    problems = check(payload)
    assert any("sum to" in p for p in problems)


def test_check_catches_a_county_statewide_mismatch(tmp_path):
    payload, _ = rehearse_stage("final", tmp_path)
    payload.total_votes += 5_000
    assert any("county votes sum to" in p for p in check(payload))


def test_check_catches_a_row_that_is_not_a_kansas_county(tmp_path):
    from schemas.results import CountyResult

    payload, _ = rehearse_stage("final", tmp_path)
    payload.counties.append(CountyResult(county="Cook", marshall_votes=1, total_votes=1))
    payload.total_votes += 1
    assert any("not Kansas counties" in p for p in check(payload))


def test_describe_renders_without_error(stage, tmp_path):
    payload, _ = rehearse_stage(stage, tmp_path)
    rendered = describe(payload)
    assert "status:" in rendered
    assert "marshall" in rendered and "hamilton" in rendered
