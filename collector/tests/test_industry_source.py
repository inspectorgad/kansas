"""Tests for the OpenSecrets helpers.

The API is unreachable from here, so what is tested is the parsing and the
matching — including the two shapes that have already broken parsers in this
project: a single result arriving as an object instead of a list, and a surname
matched as a substring.
"""

from __future__ import annotations

import pytest

from fetch import SourceError
from sources.industry import Budget, Legislator, _rows, match_legislator


def _payload(rows):
    return {"response": {"industries": {"industry": rows}}}


class TestRows:
    def test_reads_values_out_of_the_attributes_wrapper(self):
        payload = _payload([{"@attributes": {"industry_name": "Oil & Gas", "total": "12"}}])
        assert _rows(payload, "industries", "industry") == [
            {"industry_name": "Oil & Gas", "total": "12"}
        ]

    def test_a_lone_result_arrives_as_an_object_not_a_list(self):
        # This JSON is converted from XML, where one child and a list of one are
        # indistinguishable. A parser assuming a list reads the dict's keys.
        payload = _payload({"@attributes": {"industry_name": "Health", "total": "9"}})
        assert _rows(payload, "industries", "industry") == [
            {"industry_name": "Health", "total": "9"}
        ]

    def test_missing_containers_are_empty_not_an_error(self):
        assert _rows({}, "industries", "industry") == []
        assert _rows({"response": {}}, "industries", "industry") == []
        assert _rows({"response": {"industries": {}}}, "industries", "industry") == []


class TestMatchLegislator:
    ROSTER = [
        Legislator(cid="N00000001", name="Jerry Moran", fec_id="S4KS00071"),
        Legislator(cid="N00033378", name="Roger Marshall", fec_id="S0KS00315"),
    ]

    def test_the_fec_id_wins_because_it_is_an_identifier(self):
        match = match_legislator(self.ROSTER, "Wrong Name", "S0KS00315")
        assert match and match.cid == "N00033378"

    def test_the_surname_is_the_fallback(self):
        match = match_legislator(self.ROSTER, "Roger Marshall", None)
        assert match and match.cid == "N00033378"

    def test_the_surname_must_be_a_whole_word(self):
        # Substring matching in this project has already turned Kansas into
        # Arkansas once. "Moran" must not match "Moranis".
        roster = [Legislator(cid="N1", name="Rick Moranis", fec_id=None)]
        assert match_legislator(roster, "Jerry Moran", None) is None

    def test_an_absent_challenger_returns_nothing(self):
        # getLegislators lists sitting members, so this is the expected answer for
        # Hamilton and the reason industry data may cover one side only.
        assert match_legislator(self.ROSTER, "Adam Hamilton", None) is None


class TestBudget:
    def test_stops_at_the_limit(self):
        budget = Budget(limit=2)
        budget.spend()
        budget.spend()
        with pytest.raises(SourceError, match="budget"):
            budget.spend()

    def test_counts_what_it_spent(self):
        budget = Budget(limit=5)
        budget.spend()
        assert budget.used == 1
