"""Tests for ad-buy attribution and aggregation.

Attribution is the part that can be wrong in a way nobody notices: station
filings name the *advertiser*, and a super PAC's name usually says nothing about
who it helps. The rule under test is that we only attribute what we can justify,
and everything else is reported as unattributed rather than guessed into a
candidate's column.
"""

from datetime import date

import pytest

from schemas import HAMILTON, MARSHALL
from schemas.ads import AdFiling
from sources.ads import aggregate, attribute, parse_money, week_start


class TestAttribution:
    def test_an_authorised_committee_is_the_candidates_own_money(self):
        assert attribute("Marshall for Kansas") == (MARSHALL, False)
        assert attribute("Adam Hamilton for Senate") == (HAMILTON, False)

    def test_an_outside_group_naming_one_candidate_is_attributed_as_outside(self):
        candidate, outside = attribute("Kansas Values PAC supporting Roger Marshall")
        assert candidate == MARSHALL
        assert outside is True

    def test_a_group_naming_neither_candidate_is_left_unattributed(self):
        """A PAC name alone cannot tell us who it helps."""
        assert attribute("Sunflower Values Fund") == (None, True)
        assert attribute("Americans for Prosperity") == (None, True)

    def test_an_ad_naming_both_candidates_is_left_unattributed(self):
        """An attack ad names its target as well as its beneficiary."""
        assert attribute("Marshall vs Hamilton comparison ad") == (None, True)

    def test_an_empty_advertiser_is_left_unattributed(self):
        assert attribute("") == (None, True)


class TestParseMoney:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("$12,450.00", 12450.0),
            ("12450", 12450.0),
            ("$1,200", 1200.0),
            ("Gross: $980.50", 980.50),
            ("$0.00", 0.0),
        ],
    )
    def test_reads_dollar_figures(self, text, expected):
        assert parse_money(text) == expected

    def test_an_unreadable_amount_is_none_not_zero(self):
        """Zero is a real filing; unknown is not, and they must not merge."""
        assert parse_money("see attached") is None
        assert parse_money(None) is None
        assert parse_money("") is None
        assert parse_money("$0.00") == 0.0


class TestWeekStart:
    def test_buckets_to_monday(self):
        # 2026-08-22 is a Saturday.
        assert week_start(date(2026, 8, 22)) == date(2026, 8, 17)
        assert week_start(date(2026, 8, 17)) == date(2026, 8, 17)

    def test_days_in_one_week_share_a_bucket(self):
        week = {week_start(date(2026, 8, d)) for d in range(17, 24)}
        assert len(week) == 1


def filing(
    advertiser: str,
    amount: float | None,
    market: str = "Wichita-Hutchinson",
    start: date = date(2026, 8, 17),
) -> AdFiling:
    side, outside = attribute(advertiser)
    return AdFiling(
        id=advertiser.replace(" ", "-").lower(),
        station="KWCH",
        market=market,
        advertiser=advertiser,
        side=side,
        is_outside_group=outside,
        amount=amount,
        flight_start=start,
    )


class TestAggregate:
    def test_campaign_and_outside_money_are_kept_apart(self):
        totals = aggregate(
            [
                filing("Marshall for Kansas", 50_000.0),
                filing("Kansas Values PAC supporting Roger Marshall", 200_000.0),
            ]
        ).total_by_side
        assert totals[MARSHALL] == 50_000.0
        assert totals["outside"] == 200_000.0

    def test_unattributed_money_gets_its_own_bucket(self):
        totals = aggregate([filing("Sunflower Values Fund", 75_000.0)]).total_by_side
        # Unattributable money is outside money, and is not assigned to a candidate.
        assert totals.get("outside") == 75_000.0
        assert MARSHALL not in totals
        assert HAMILTON not in totals

    def test_a_filing_with_no_amount_is_excluded_from_totals(self):
        result = aggregate(
            [filing("Marshall for Kansas", None), filing("Marshall for Kansas", 10_000.0)]
        )
        assert result.total_by_side[MARSHALL] == 10_000.0
        # But it is still listed, so the buy is visible even without a figure.
        assert len(result.filings) == 2

    def test_weekly_buckets_split_by_flight_week(self):
        result = aggregate(
            [
                filing("Marshall for Kansas", 10_000.0, start=date(2026, 8, 17)),
                filing("Marshall for Kansas", 15_000.0, start=date(2026, 8, 20)),
                filing("Adam Hamilton for Senate", 20_000.0, start=date(2026, 8, 24)),
            ]
        )
        assert [w.week_start for w in result.by_week] == [date(2026, 8, 17), date(2026, 8, 24)]
        assert result.by_week[0].marshall == 25_000.0
        assert result.by_week[0].hamilton == 0.0
        assert result.by_week[1].hamilton == 20_000.0

    def test_market_breakdown_separates_media_markets(self):
        result = aggregate(
            [
                filing("Marshall for Kansas", 10_000.0, market="Wichita-Hutchinson"),
                filing("Marshall for Kansas", 30_000.0, market="Kansas City"),
                filing("Adam Hamilton for Senate", 40_000.0, market="Kansas City"),
            ]
        )
        markets = {m.market: m for m in result.by_market}
        assert markets["Wichita-Hutchinson"].marshall == 10_000.0
        assert markets["Kansas City"].marshall == 30_000.0
        assert markets["Kansas City"].hamilton == 40_000.0

    def test_empty_input_produces_an_empty_but_valid_rollup(self):
        result = aggregate([])
        assert result.total_by_side == {}
        assert result.by_week == []
        assert result.filings == []
