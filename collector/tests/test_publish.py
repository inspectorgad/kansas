"""Tests for the publisher: contract enforcement and change detection."""

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import publish
from schemas import ELECTION_DATE, MarketsPayload, RacePayload
from schemas.common import Candidate, Party


def race(generated_at: datetime | None = None, days: int = 73) -> RacePayload:
    return RacePayload(
        generated_at=generated_at or publish.now(),
        election_date=ELECTION_DATE,
        days_until_election=days,
        candidates=[Candidate(id="marshall", name="Roger Marshall", party=Party.REPUBLICAN)],
    )


def test_writes_a_valid_payload(tmp_path):
    assert publish.write("race.json", race(), tmp_path) is True
    written = json.loads((tmp_path / "race.json").read_text())
    assert written["schema_version"] == 1
    assert written["candidates"][0]["name"] == "Roger Marshall"


def test_rejects_a_file_outside_the_contract(tmp_path):
    with pytest.raises(KeyError, match="not part of the published contract"):
        publish.write("mystery.json", race(), tmp_path)


def test_rejects_a_payload_of_the_wrong_type(tmp_path):
    wrong = MarketsPayload(generated_at=publish.now(), markets=[])
    with pytest.raises(TypeError, match="race.json expects RacePayload"):
        publish.write("race.json", wrong, tmp_path)


def test_unchanged_content_is_not_a_change_even_with_a_new_timestamp(tmp_path):
    """A run that finds nothing new must not spam the history directory."""
    assert publish.write("race.json", race(publish.now()), tmp_path) is True
    later = publish.now() + timedelta(hours=1)
    assert publish.write("race.json", race(later), tmp_path) is False


def test_real_change_is_detected(tmp_path):
    publish.write("race.json", race(days=73), tmp_path)
    assert publish.write("race.json", race(days=72), tmp_path) is True


def test_changed_content_is_snapshotted_for_history(tmp_path):
    publish.write("race.json", race(days=73), tmp_path)
    publish.write("race.json", race(days=72), tmp_path)
    snapshots = sorted((tmp_path / "history" / "race").glob("*.json"))
    assert len(snapshots) == 2


def test_unchanged_content_adds_no_snapshot(tmp_path):
    publish.write("race.json", race(publish.now()), tmp_path)
    publish.write("race.json", race(publish.now() + timedelta(hours=1)), tmp_path)
    snapshots = list((tmp_path / "history" / "race").glob("*.json"))
    assert len(snapshots) == 1


def test_load_history_returns_snapshots_oldest_first(tmp_path):
    publish.write("race.json", race(days=75), tmp_path)
    publish.write("race.json", race(days=74), tmp_path)
    publish.write("race.json", race(days=73), tmp_path)
    history = publish.load_history("race.json", tmp_path)
    assert [h["days_until_election"] for h in history] == [75, 74, 73]


def test_load_history_is_empty_before_any_run(tmp_path):
    assert publish.load_history("race.json", tmp_path) == []


def test_a_corrupt_snapshot_does_not_break_history(tmp_path):
    publish.write("race.json", race(days=73), tmp_path)
    (tmp_path / "history" / "race" / "corrupt.json").write_text("{ not json")
    assert len(publish.load_history("race.json", tmp_path)) == 1
