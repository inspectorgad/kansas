"""Tests for the prediction-market parsers.

The critical property is normalisation: whatever shape a platform quotes in, the
published pair must be two probabilities summing to 1. A market that rendered as
"72% vs 41%" would be indefensible, and it is the easiest bug to introduce here.
"""

from datetime import UTC

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

        now = datetime.now(UTC)
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

        now = datetime.now(UTC)
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
                        hamilton=0.30, fetched_at=datetime.now(UTC))
        consensus = build_consensus([market], [])
        assert consensus.change_24h is None
        assert consensus.change_7d is None


class TestStateAndTickerMatching:
    """Matching added after a live run scanned 2,500 markets and matched none.

    Two ways to get this wrong, and both were live risks rather than theory:
    requiring the literal "kansas" misses exchange tickers, which spell the state
    KS and concatenate it (KXSENATEKS-26); loosening the boundary far enough to
    catch those starts matching NHL *Senators* markets, because "Blackhawks" ends
    in "ks" and "Senators" satisfies the office half.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Kansas Senate election 2026",
            "KXSENATEKS-26-RM Roger Marshall",
            "KXSENKS-26 Marshall",
            "Senate KS 2026",
            "Will Marshall beat Hamilton in Kansas?",
        ],
    )
    def test_identifies_this_race(self, title):
        assert _matches_race(title)

    @pytest.mark.parametrize(
        "title",
        [
            "Texas Senate 2026",
            "KXSENATETX-26 John Doe",
            "Kansas governor race",
            "Senate control 2026",
            "KXNBAKS-26 Kansas basketball",
        ],
    )
    def test_rejects_other_races(self, title):
        assert not _matches_race(title)

    @pytest.mark.parametrize(
        "title",
        [
            "Will the Senators beat the Blackhawks?",
            "Ottawa Senators vs Chicago Blackhawks",
            "KSS earnings beat",
            "New York Knicks title",
            "",
        ],
    )
    def test_rejects_sports_and_tickers_that_merely_contain_ks(self, title):
        assert not _matches_race(title)

    def test_a_ticker_naming_office_and_state_settles_both_halves(self):
        """KXSENATEKS-26 says Senate and Kansas in one word."""
        from sources.markets import _ticker_identifies_race

        assert _ticker_identifies_race("KXSENATEKS-26-RM")
        assert not _ticker_identifies_race("KXSENATETX-26")
        assert not _ticker_identifies_race("KXNBAKS-26")

    def test_state_abbreviation_needs_both_word_boundaries(self):
        from sources.markets import _mentions_state

        assert _mentions_state("senate ks 2026")
        assert not _mentions_state("chicago blackhawks")


class TestScanReport:
    """Diagnostics for a market search that finds nothing.

    Two live runs failed here, and a bare "nothing matched" could not tell them
    apart: the first was short pagination, the second an unmatched title. So the
    report measures distinct titles against scanned rows, because pagination that
    refetches page one looks exactly like a thorough search in a plain count.
    """

    def test_a_healthy_scan_is_not_flagged(self):
        from sources.markets import ScanReport

        report = ScanReport("kalshi", scanned=400, titles=[f"Market {i}" for i in range(400)])
        assert report.distinct == 400
        assert not report.pagination_stalled

    def test_pagination_that_never_advanced_is_flagged(self):
        from sources.markets import ScanReport

        # 2,400 rows fetched but only 200 unique: page one, twelve times.
        report = ScanReport(
            "kalshi", scanned=2400, titles=[f"Market {i % 200}" for i in range(2400)]
        )
        assert report.distinct == 200
        assert report.pagination_stalled
        assert "PAGINATION STALLED" in report.describe()

    def test_an_empty_scan_is_not_flagged_as_stalled(self):
        from sources.markets import ScanReport

        assert not ScanReport("kalshi").pagination_stalled

    def test_office_mentions_are_surfaced(self):
        from sources.markets import ScanReport

        report = ScanReport(
            "polymarket",
            scanned=3,
            titles=["Texas Senate 2026", "Ohio Senate 2026", "Weather in Wichita"],
        )
        assert report.office_mentions() == ["Ohio Senate 2026", "Texas Senate 2026"]
        assert "Weather" not in report.describe()

    def test_a_sample_is_shown_when_nothing_mentions_the_office(self):
        from sources.markets import ScanReport

        report = ScanReport("kalshi", scanned=2, titles=["Bitcoin above 100k", "Rain in Miami"])
        described = report.describe()
        assert "no office mentions" in described
        assert "Bitcoin" in described

    def test_blank_titles_are_not_counted_as_distinct(self):
        from sources.markets import ScanReport

        assert ScanReport("kalshi", scanned=3, titles=["", "  ", "Real"]).distinct == 1


class TestRealTickersFromLiveRuns:
    """Ticker matching, pinned against tickers actually observed in CI.

    The Alaska cases are the ones that matter. Kalshi spells that race
    KXAKSENGOVCOMBO — KX + AK + SEN — and "AKSEN" contains "KS" as a substring
    that means nothing. A "contains SEN and KS" rule collected Alaska's whole
    Senate slate as this race, which is the worst kind of wrong: real market
    prices, confidently attributed to the wrong contest.

    That same output revealed the naming scheme (KX + state + SEN + qualifier),
    so Kansas reads KXKSSEN... — which is why these are pinned rather than
    reasoned about.
    """

    ALASKA = (
        "Will Alaska Governor winner be Republican party and Alaska Senate winner "
        "be Republican party? Republicans sweep [KXAKSENGOVCOMBO-26NOV-REPREP]"
    )
    ALASKA_RUNOFF = (
        "Will Carol Hafner qualify for the runoff in the 2026 Alaska Senate race? "
        "Carol Hafner [KXAKSENADVANCE-26AUG18-CHAF]"
    )

    @pytest.mark.parametrize(
        "title",
        [
            "KXKSSEN-26NOV-RM Roger Marshall",
            "KXKSSENGOVCOMBO-26NOV-REPREP",
            "KXSENATEKS-26-RM",
        ],
    )
    def test_matches_kansas_ticker_forms(self, title):
        assert _matches_race(title)

    @pytest.mark.parametrize("title", [ALASKA, ALASKA_RUNOFF, "KXAKSENGOVCOMBO-26NOV-DEMDEM"])
    def test_rejects_alaska(self, title):
        assert not _matches_race(title)

    @pytest.mark.parametrize(
        "title",
        [
            "2026 Balance of Power: R Senate, R House",
            "Mitch McConnell steps down from Senate before his term ends?",
        ],
    )
    def test_rejects_national_senate_markets(self, title):
        """Chamber-control and individual-senator markets are not this race."""
        assert not _matches_race(title)

    def test_the_ticker_rule_itself_rejects_the_alaska_prefix(self):
        from sources.markets import _ticker_identifies_race

        assert _ticker_identifies_race("KXKSSEN-26NOV")
        assert not _ticker_identifies_race("KXAKSENGOVCOMBO-26NOV")
        assert not _ticker_identifies_race("KXAKSENADVANCE-26AUG18")


class TestCursorExtraction:
    """Pagination that never advances is worse than pagination that stops.

    A live run reported 2,400 events scanned and 118 distinct: the cursor was
    read from a key the response did not have, so page one came back twelve
    times and the large scan count read as thoroughness.
    """

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"cursor": "abc"}, "abc"),
            ({"next_cursor": "def"}, "def"),
            ({"nextCursor": "ghi"}, "ghi"),
            ({"pagination": {"next_cursor": "jkl"}}, "jkl"),
        ],
    )
    def test_finds_the_cursor_wherever_it_sits(self, payload, expected):
        from sources.markets import _extract_cursor

        assert _extract_cursor(payload) == expected

    @pytest.mark.parametrize("payload", [{}, {"events": []}, {"cursor": ""}, {"cursor": None}])
    def test_absent_or_empty_cursor_reads_as_no_more_pages(self, payload):
        from sources.markets import _extract_cursor

        assert _extract_cursor(payload) is None


class TestPartyQuotedMarkets:
    """Kalshi quotes this race by party, not by candidate.

    The live listing offers "Will Kansas Senate winner be Republican party",
    never a contract named for Marshall. Each candidate is their party's nominee,
    so the mapping is sound — but it is a mapping, and the payload says so rather
    than implying the market named the candidate.
    """

    def test_a_party_contract_maps_to_the_nominee(self):
        payload = {
            "markets": [
                {
                    "ticker": "KXKSSEN-26NOV-REP",
                    "title": "Will Kansas Senate winner be Republican party?",
                    "yes_sub_title": "Republican party",
                    "last_price": 72,
                    "volume": 50000,
                }
            ]
        }
        market = _kalshi_markets(payload)[0]
        assert market.marshall == pytest.approx(0.72)
        assert market.hamilton == pytest.approx(0.28)

    def test_a_democratic_contract_maps_to_hamilton(self):
        payload = {
            "markets": [
                {
                    "ticker": "KXKSSEN-26NOV-DEM",
                    "title": "Will Kansas Senate winner be Democratic party?",
                    "yes_sub_title": "Democratic party",
                    "last_price": 28,
                }
            ]
        }
        market = _kalshi_markets(payload)[0]
        assert market.marshall == pytest.approx(0.72)
        assert market.hamilton == pytest.approx(0.28)

    def test_the_wrong_cycle_is_rejected(self):
        """Kalshi also lists a 2028 Kansas Senate race, which matches every other rule."""
        from sources.markets import _is_this_cycle

        assert _is_this_cycle("KXKSSEN-26NOV-REP")
        assert not _is_this_cycle("SENATEKS-28-D")

        payload = {
            "markets": [
                {
                    "ticker": "SENATEKS-28-D",
                    "title": "Will Democratics win the Senate race in Kansas?",
                    "yes_sub_title": "Democratic party",
                    "last_price": 30,
                }
            ]
        }
        assert _kalshi_markets(payload) == []

    def test_two_office_combos_are_skipped_not_converted(self):
        """A governor-and-senate combo needs marginalising, which is modelling."""
        from sources.markets import _is_combo

        assert _is_combo("KXKSSENGOVCOMBO-26NOV-DEMDEM")
        assert not _is_combo("KXKSSEN-26NOV-REP")

        payload = {
            "markets": [
                {
                    "ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM",
                    "title": "Will Kansas Governor winner be Democratic and Senate winner be Democratic?",
                    "yes_sub_title": "Democrats sweep",
                    "last_price": 12,
                }
            ]
        }
        assert _kalshi_markets(payload) == []


class TestStallMetric:
    """The stall flag must compare like with like.

    It once counted Kalshi *events* as `scanned` while `titles` held the markets
    drawn from the matching few, so 2,400 events yielding 40 markets was reported
    as stalled pagination when pagination was working correctly.
    """

    def test_events_walked_do_not_trip_the_stall_flag(self):
        from sources.markets import ScanReport

        report = ScanReport(
            "kalshi",
            scanned=40,
            titles=[f"market {i}" for i in range(40)],
            containers_scanned=2400,
        )
        assert not report.pagination_stalled
        assert "events=2400" in report.describe()

    def test_genuinely_repeated_pages_still_trip_it(self):
        from sources.markets import ScanReport

        report = ScanReport(
            "kalshi", scanned=2400, titles=[f"m{i % 200}" for i in range(2400)]
        )
        assert report.pagination_stalled
