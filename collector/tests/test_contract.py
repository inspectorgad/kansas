"""The published contract itself.

Every file the app can request must have a model, and every model must be
constructible with nothing but a timestamp — that is what lets the collector
publish a valid empty placeholder for a tracker that has not started collecting
yet, so the app degrades to "no data" instead of an error screen.
"""

import json

import pytest

import publish
from schemas import FILES, SCHEMA_VERSION

# race.json genuinely requires more than a timestamp: a race with no election
# date or candidates is not a meaningful document.
REQUIRES_MORE_THAN_A_TIMESTAMP = {"race.json", "polls.json", "news.json"}


@pytest.mark.parametrize("name", sorted(FILES))
def test_every_contract_file_has_a_model(name):
    assert FILES[name] is not None


@pytest.mark.parametrize(
    "name", sorted(set(FILES) - REQUIRES_MORE_THAN_A_TIMESTAMP)
)
def test_placeholder_payloads_are_valid(name, tmp_path):
    """An empty tracker must still produce a publishable file."""
    payload = FILES[name](generated_at=publish.now())
    assert publish.write(name, payload, tmp_path) is True
    written = json.loads((tmp_path / name).read_text())
    assert written["schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize("name", sorted(FILES))
def test_models_reject_unknown_fields(name):
    """Extra fields must raise, so upstream shape drift is caught, not absorbed."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FILES[name](generated_at=publish.now(), some_unexpected_field="surprise")


def test_candidate_ids_are_the_json_keys_everywhere():
    from schemas import CANDIDATE_IDS, HAMILTON, MARSHALL

    assert CANDIDATE_IDS == (MARSHALL, HAMILTON)
    assert MARSHALL == "marshall" and HAMILTON == "hamilton"


def test_candidate_pair_margin_and_leader():
    from schemas import CandidatePair

    pair = CandidatePair(marshall=46.0, hamilton=45.0)
    assert pair.margin() == pytest.approx(1.0)
    assert pair.leader() == "marshall"
    flipped = CandidatePair(marshall=44.0, hamilton=48.0)
    assert flipped.margin() == pytest.approx(-4.0)
    assert flipped.leader() == "hamilton"
