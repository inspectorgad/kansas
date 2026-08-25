"""Tests for the finance collector's pure helpers.

Most of this module talks to openFEC and is exercised in CI against the live API,
because the shapes it parses cannot be reached from where it was written. What is
testable here is the reasoning applied to a row once it has arrived.
"""

from __future__ import annotations

from sources.finance import _money_fields


class TestMoneyFields:
    """The probe prints every number an FEC totals record carries.

    Selecting fields is what caused the problem being investigated: the file
    reports individual contributions twice, from two endpoints, and the two
    disagree by $0.9M. A probe that picked fields again would reproduce the choice
    under investigation instead of exposing it.
    """

    def test_lists_every_non_zero_number(self):
        record = {"receipts": 100.0, "disbursements": 40, "refunds": 0}
        assert _money_fields(record) == [("disbursements", 40.0), ("receipts", 100.0)]

    def test_skips_text_and_dates(self):
        record = {"receipts": 5.0, "coverage_end_date": "2026-06-30", "name": "x"}
        assert _money_fields(record) == [("receipts", 5.0)]

    def test_skips_booleans(self):
        # True is an int in Python, and "is_amended: 1.00" in a money column would
        # read as a dollar figure.
        assert _money_fields({"is_amended": True, "receipts": 2.0}) == [("receipts", 2.0)]

    def test_sorted_by_name_so_two_runs_can_be_compared(self):
        record = {"zeta": 1.0, "alpha": 2.0, "mid": 3.0}
        assert [name for name, _ in _money_fields(record)] == ["alpha", "mid", "zeta"]

    def test_an_empty_record_is_not_an_error(self):
        assert _money_fields({}) == []
