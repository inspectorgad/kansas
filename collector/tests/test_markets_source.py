"""Tests for the prediction-market parsers.

The critical property is normalisation: whatever shape a platform quotes in, the
published pair must be two probabilities summing to 1. A market that rendered as
"72% vs 41%" would be indefensible, and it is the easiest bug to introduce here.
"""

import pytest

from sources.markets import (
    _kalshi_markets,
    _matches_race,
    _polymarket_markets,
    build_consensus,
    normalise,
)


class TestNormalise:
    def test_complements_a_one_sided_quote(self):
        assert normalise(0.72, None) == (0.72, 0.28)
        assert normalise(None, 0.28) == (0.72, 0.28)

    def test_scales_a_two_sided_quote_to_sum_to_one(self):
        marshall, hamilton = normalise(0.70, 0.32)
        assert marshall + hamilton == pytest.approx(1.0)
        assert marshall > hamilton

    def test_rejects_an_empty_book(self):
        assert normalise(None, None) is None
        assert normalise(0.0, 0.0) is None

    @pytest.mark.parametrize(
        "marshall,hamilton",
        [(0.72, None), (None, 0.28), (0.70, 0.32), (0.5, 0.5), (0.99, 0.02)],
    )
    def test_always_sums_to_one(self, marshall, hamilton):
        pair = normalise(marshall, hamilton)
        assert pair is not None
        assert sum(pair) == pytest.approx(1.0)


class TestRaceMatching:
    @pytest.mark.parametrize(
        "title",
        [
            "Kansas Senate election 2026",
            "Who will win the Kansas Senate race?",
            "Will Marshall beat Hamilton in Kansas?",
        ],
    )
    def test_matches_this_race(self, title):
        assert _matches_race(title)

    @pytest.mark.parametrize(
        "title",
        ["Texas Senate 2026", "Kansas governor race", "Senate control 2026", ""],
    )
    def test_rejects_other_races(self, title):
        assert not _matches_race(title)


class TestKalshi:
    def test_reads_a_marshall_market(self):
        payload = {
            "markets": [
                {
                    "ticker": "KXSENKS-26-RM",
                    "title": "Kansas Senate 2026",
                    "yes_sub_title": "Roger Marshall",
                    "last_price": 72,
                    "volume": 150000,
                    "open_interest": 42000,
                }
            ]
        }
        markets = _kalshi_markets(payload)
        assert len(markets) == 1
        market = markets[0]
        assert market.platform == "kalshi"
        assert market.marshall == pytest.approx(0.72)
        assert market.hamilton == pytest.approx(0.28)
        assert market.volume_usd == 150000
        assert market.url == "https://kalshi.com/markets/KXSENKS-26-RM"

    def test_reads_a_hamilton_market_as_the_complement(self):
        payload = {
            "markets": [
                {
                    "ticker": "KXSENKS-26-AH",
                    "title": "Kansas Senate 2026",
                    "yes_sub_title": "Adam Hamilton",
                    "last_price": 28,
                }
            ]
        }
        market = _kalshi_markets(payload)[0]
        assert market.marshall == pytest.approx(0.72)
        assert market.hamilton == pytest.approx(0.28)

    def test_falls_back_to_the_bid_when_no_trade_has_printed(self):
        payload = {
            "markets": [
                {
                    "ticker": "KXSENKS-26-RM",
                    "title": "Kansas Senate",
                    "yes_sub_title": "Marshall",
                    "last_price": None,
                    "yes_bid": 70,
                }
            ]
        }
        assert _kalshi_markets(payload)[0].marshall == pytest.approx(0.70)

    def test_skips_other_races_and_unattributable_markets(self):
        payload = {
            "markets": [
                {"ticker": "X", "title": "Texas Senate 2026", "yes_sub_title": "Someone", "last_price": 50},
                {"ticker": "Y", "title": "Kansas Senate 2026", "yes_sub_title": "Turnout over 50%", "last_price": 50},
                {"ticker": "Z", "title": "Kansas Senate 2026", "yes_sub_title": "Marshall", "last_price": None},
            ]
        }
        assert _kalshi_markets(payload) == []


class TestPolymarket:
    def test_reads_json_encoded_outcome_lists(self):
        """Gamma returns outcomes and prices as JSON strings, not arrays."""
        payload = [
            {
                "id": "512",
                "slug": "kansas-senate-2026",
                "question": "Kansas Senate Election 2026",
                "outcomes": '["Roger Marshall", "Adam Hamilton"]',
                "outcomePrices": '["0.71", "0.29"]',
                "volumeNum": 88000,
            }
        ]
        market = _polymarket_markets(payload)[0]
        assert market.platform == "polymarket"
        assert market.marshall == pytest.approx(0.71)
        assert market.hamilton == pytest.approx(0.29)
        assert market.url == "https://polymarket.com/event/kansas-senate-2026"

    def test_reads_a_yes_no_market_from_the_question(self):
        payload = [
            {
                "id": "77",
                "question": "Will Roger Marshall win the Kansas Senate race?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.68", "0.32"]',
            }
        ]
        market = _polymarket_markets(payload)[0]
        assert market.marshall == pytest.approx(0.68)
        assert market.hamilton == pytest.approx(0.32)

    def test_skips_a_market_with_mismatched_outcomes_and_prices(self):
        payload = [
            {
                "id": "1",
                "question": "Kansas Senate 2026",
                "outcomes": '["Marshall", "Hamilton", "Other"]',
                "outcomePrices": '["0.7", "0.3"]',
            }
        ]
        assert _polymarket_markets(payload) == []

    def test_accepts_a_wrapped_response(self):
        payload = {
            "data": [
                {
                    "id": "1",
                    "question": "Kansas Senate 2026",
                    "outcomes": '["Marshall", "Hamilton"]',
                    "outcomePrices": '["0.6", "0.4"]',
                }
            ]
        }
        assert len(_polymarket_markets(payload)) == 1


class TestConsensus:
    def test_none_without_markets(self):
        assert build_consensus([]) is None

    def test_weights_by_volume(self):
        from datetime import datetime, timezone

        from schemas.markets import Market

        now = datetime.now(timezone.utc)
        thin = Market(platform="kalshi", market_id="a", marshall=0.60, hamilton=0.40,
                      volume_usd=1_000, fetched_at=now)
        deep = Market(platform="polymarket", market_id="b", marshall=0.80, hamilton=0.20,
                      volume_usd=1_000_000, fetched_at=now)
        consensus = build_consensus([thin, deep])
        # The deep book dominates, so the blend sits near it, not at the midpoint.
        assert consensus.marshall > 0.75
        assert consensus.marshall + consensus.hamilton == pytest.approx(1.0)
        assert consensus.platforms == ["kalshi", "polymarket"]

    def test_reports_movement_against_prior_history(self):
        from datetime import datetime, timedelta, timezone

        from schemas.markets import Market, MarketPoint

        now = datetime.now(timezone.utc)
        history = [
            MarketPoint(t=now - timedelta(days=8), marshall=0.60, hamilton=0.40),
            MarketPoint(t=now - timedelta(days=2), marshall=0.65, hamilton=0.35),
            MarketPoint(t=now - timedelta(hours=3), marshall=0.68, hamilton=0.32),
        ]
        market = Market(platform="kalshi", market_id="a", marshall=0.70,
                        hamilton=0.30, volume_usd=5000, fetched_at=now)
        consensus = build_consensus([market], history)
        # Each delta compares against the newest point at or *before* the cutoff,
        # so change_24h reads from the 2-day-old point, not the 3-hour-old one.
        assert consensus.change_24h == pytest.approx(0.70 - 0.65, abs=1e-3)
        assert consensus.change_7d == pytest.approx(0.70 - 0.60, abs=1e-3)
        assert consensus.change_1h == pytest.approx(0.70 - 0.68, abs=1e-3)
        # The new point is appended to the series.
        assert consensus.history[-1].marshall == pytest.approx(0.70)
        assert len(consensus.history) == 4

    def test_movement_is_none_without_enough_history(self):
        from datetime import datetime, timezone

        from schemas.markets import Market

        market = Market(platform="kalshi", market_id="a", marshall=0.70,
                        hamilton=0.30, fetched_at=datetime.now(timezone.utc))
        consensus = build_consensus([market], [])
        assert consensus.change_24h is None
        assert consensus.change_7d is None
