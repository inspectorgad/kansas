"""End-to-end tests for the collector runner, replayed from fixtures.

These run the real code path — fetch, parse, aggregate, validate, publish — with
the network swapped for recorded fixtures, which is the only way to exercise it
in an environment with no access to the live APIs.
"""

import json

import pytest

import run
from fetch import SourceError


@pytest.fixture
def fixtures(monkeypatch):
    monkeypatch.setenv("KS_FIXTURES", "1")


def test_days_until_election_counts_down():
    from datetime import date

    assert run.days_until_election(date(2026, 11, 2)) == 1
    assert run.days_until_election(date(2026, 11, 3)) == 0
    assert run.days_until_election(date(2026, 8, 22)) == 73


def test_polls_run_writes_a_valid_file(fixtures, tmp_path):
    report = run.run(["polls"], str(tmp_path), write=True)
    assert report.ok(), report.summary()
    assert "polls.json" in report.changed

    payload = json.loads((tmp_path / "polls.json").read_text())
    assert len(payload["polls"]) == 6
    assert payload["aggregate"]["n_polls_used"] >= 1
    assert payload["aggregate"]["leader"] in ("marshall", "hamilton")
    assert payload["attribution"][0]["license"] == "CC BY-SA 4.0"


def test_second_run_reports_no_change(fixtures, tmp_path):
    run.run(["polls"], str(tmp_path), write=True)
    report = run.run(["polls"], str(tmp_path), write=True)
    assert report.ok()
    assert "polls.json" not in report.changed


def test_dry_run_writes_nothing(fixtures, tmp_path):
    report = run.run(["polls"], str(tmp_path), write=False)
    assert report.ok()
    assert not (tmp_path / "polls.json").exists()


def test_placeholders_are_published_so_the_app_never_404s(fixtures, tmp_path):
    run.run(["polls"], str(tmp_path), write=True)
    for name in ("ads.json", "ground.json", "results.json"):
        assert (tmp_path / name).exists(), f"{name} missing"
    results = json.loads((tmp_path / "results.json").read_text())
    assert results["status"] == "pending"


def test_placeholders_are_not_overwritten_once_real(fixtures, tmp_path):
    run.run(["polls"], str(tmp_path), write=True)
    real = json.loads((tmp_path / "results.json").read_text())
    real["status"] = "live"
    (tmp_path / "results.json").write_text(json.dumps(real))
    run.run(["polls"], str(tmp_path), write=True)
    assert json.loads((tmp_path / "results.json").read_text())["status"] == "live"


def test_a_missing_fixture_fails_the_run_rather_than_publishing_nothing(tmp_path, monkeypatch):
    """With fixtures on but none recorded, the source must fail loudly."""
    monkeypatch.setenv("KS_FIXTURES", "1")
    report = run.run(["markets"], str(tmp_path), write=True)
    assert not report.ok()
    assert "markets" in report.failed


def test_one_failing_source_does_not_stop_the_others(fixtures, tmp_path):
    report = run.run(["polls", "markets"], str(tmp_path), write=True)
    # polls has a fixture, markets does not.
    assert "polls.json" in report.collected
    assert "markets" in report.failed
    assert (tmp_path / "polls.json").exists()


def test_unknown_source_is_reported_not_crashed(tmp_path):
    report = run.run(["nonsense"], str(tmp_path), write=False)
    assert not report.ok()
    assert "unknown source" in report.failed["nonsense"]


def test_report_summary_is_readable(fixtures, tmp_path):
    report = run.run(["polls"], str(tmp_path), write=True)
    text = report.summary()
    assert "collected:" in text and "polls.json" in text


def test_first_seen_timestamps_survive_a_rerun(fixtures, tmp_path):
    """A poll's added_at must record when we first saw it, not when we last ran.

    Re-stamping it every run would make every run look like a change, which both
    bloats the history directory and destroys the signal the app uses to notify
    on genuinely new polls.
    """
    run.run(["polls"], str(tmp_path), write=True)
    first = {p["id"]: p["added_at"] for p in json.loads((tmp_path / "polls.json").read_text())["polls"]}

    run.run(["polls"], str(tmp_path), write=True)
    second = {p["id"]: p["added_at"] for p in json.loads((tmp_path / "polls.json").read_text())["polls"]}

    assert first == second


def test_a_new_poll_appearing_is_reported_as_a_change(fixtures, tmp_path, monkeypatch):
    run.run(["polls"], str(tmp_path), write=True)

    # Simulate the article gaining a poll between runs.
    from datetime import date

    import sources.polls as polls_source

    original = polls_source.collect

    def with_extra_poll():
        result = original()
        from conftest import make_poll

        result.polls.insert(0, make_poll("Brand New Poll", 45.0, 46.0, date(2026, 8, 20)))
        return result

    monkeypatch.setattr(polls_source, "collect", with_extra_poll)
    report = run.run(["polls"], str(tmp_path), write=True)
    assert "polls.json" in report.changed

    payload = json.loads((tmp_path / "polls.json").read_text())
    assert any(p["pollster"] == "Brand New Poll" for p in payload["polls"])


class TestResultsWindow:
    """Results collection switches itself on only as election day approaches."""

    def test_results_are_skipped_months_out(self):
        from datetime import date

        assert "results" not in run.default_targets(date(2026, 8, 22))

    def test_results_switch_on_within_the_window(self):
        from datetime import date

        assert "results" in run.default_targets(date(2026, 11, 1))
        assert "results" in run.default_targets(date(2026, 11, 3))

    def test_the_ordinary_sources_are_always_collected(self):
        from datetime import date

        for day in (date(2026, 8, 22), date(2026, 11, 3)):
            targets = run.default_targets(day)
            assert {"race", "polls", "markets", "finance", "news"} <= set(targets)

    def test_a_real_results_file_is_not_clobbered_by_the_placeholder(self, fixtures, tmp_path):
        """A collected results.json must survive ensure_placeholders."""
        run.run(["polls"], str(tmp_path), write=True)
        live = json.loads((tmp_path / "results.json").read_text())
        live["status"] = "live"
        live["total_votes"] = 801019
        (tmp_path / "results.json").write_text(json.dumps(live))

        run.run(["polls"], str(tmp_path), write=True)
        after = json.loads((tmp_path / "results.json").read_text())
        assert after["status"] == "live"
        assert after["total_votes"] == 801019


class TestResolvedFecIds:
    """race.json must not publish an unverified FEC id.

    config's ids are hints that steer the finance lookup, and one was wrong:
    it guessed S0KS00232 for Marshall while the API returned S0KS00315. The two
    published files then disagreed about the same fact.
    """

    def test_the_resolved_id_is_published_not_the_config_hint(self, fixtures, tmp_path):
        (tmp_path / "finance.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-08-22T15:00:00Z",
                    "candidates": {
                        "marshall": {
                            "candidate_id": "marshall",
                            "fec_candidate_id": "S0KS00315",
                        }
                    },
                }
            )
        )
        report = run.run(["race"], str(tmp_path), write=True)
        assert report.ok(), report.summary()

        published = json.loads((tmp_path / "race.json").read_text())
        marshall = next(c for c in published["candidates"] if c["id"] == "marshall")
        assert marshall["fec_candidate_id"] == "S0KS00315"

    def test_no_id_is_published_when_none_was_resolved(self, fixtures, tmp_path):
        """Better absent than confidently wrong."""
        report = run.run(["race"], str(tmp_path), write=True)
        assert report.ok(), report.summary()

        published = json.loads((tmp_path / "race.json").read_text())
        for candidate in published["candidates"]:
            assert "fec_candidate_id" not in candidate

    def test_a_corrupt_finance_file_does_not_break_the_race_payload(self, fixtures, tmp_path):
        (tmp_path / "finance.json").write_text("{ truncated")
        assert run.run(["race"], str(tmp_path), write=True).ok()
