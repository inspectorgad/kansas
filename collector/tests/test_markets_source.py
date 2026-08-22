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


class TestCombinationMarginalisation:
    """Deriving the Senate probability from Kalshi's governor-by-senate grid.

    A live scan of 2,400 Kalshi events and 1,200 Polymarket markets found no
    standalone 2026 Kansas Senate contract on either platform — only these four
    combination outcomes, plus a 2028 Kansas race. Since the four are mutually
    exclusive and exhaustive, P(Senate R) = P(gov D, sen R) + P(gov R, sen R) is
    exact arithmetic rather than a model.
    """

    GRID = [
        {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "last_price": 48},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-REPDEM", "last_price": 22},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMREP", "last_price": 19},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "last_price": 11},
    ]

    def test_sums_the_two_republican_senate_outcomes(self):
        from sources.markets import marginalise_combos

        marshall, hamilton = marginalise_combos(self.GRID)
        # REPREP + DEMREP = 48 + 19 = 67 of 100.
        assert marshall == pytest.approx(0.67, abs=1e-4)
        assert hamilton == pytest.approx(0.33, abs=1e-4)
        assert marshall + hamilton == pytest.approx(1.0)

    def test_the_governor_outcome_does_not_leak_in(self):
        """Governor-Republican mass must not be counted as Senate-Republican."""
        from sources.markets import marginalise_combos

        # Governor R in 70 of 100, Senate R in only 30.
        grid = [
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "last_price": 20},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPDEM", "last_price": 50},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMREP", "last_price": 10},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "last_price": 20},
        ]
        marshall, _ = marginalise_combos(grid)
        assert marshall == pytest.approx(0.30, abs=1e-4)

    def test_an_incomplete_grid_yields_nothing(self):
        """Missing mass is unknown; renormalising the rest would invent a number."""
        from sources.markets import marginalise_combos

        assert marginalise_combos(self.GRID[:3]) is None
        assert marginalise_combos(self.GRID[:1]) is None
        assert marginalise_combos([]) is None

    def test_prices_are_normalised_when_the_grid_does_not_sum_to_one(self):
        from sources.markets import marginalise_combos

        wide = [dict(m, last_price=m["last_price"] + 5) for m in self.GRID]
        marshall, hamilton = marginalise_combos(wide)
        assert marshall + hamilton == pytest.approx(1.0)

    def test_the_wrong_cycle_is_excluded_from_the_grid(self):
        from sources.markets import marginalise_combos

        stale = [dict(m, ticker=m["ticker"].replace("26NOV", "28NOV")) for m in self.GRID]
        assert marginalise_combos(stale) is None

    def test_a_grid_with_no_prices_yields_nothing(self):
        from sources.markets import marginalise_combos

        assert marginalise_combos([{"ticker": m["ticker"]} for m in self.GRID]) is None


class TestArkansasIsNotKansas:
    """The state name matched inside another state's name.

    Taken verbatim from the live run of 2026-08-22, which pulled these rows into
    this race's market set: "arkansas" ends with the letters "kansas", and the
    state test was a substring test. Forty markets were collected for a Kansas
    Senate race and some of them were Arkansas's.
    """

    ARKANSAS = (
        "Will Democratics win the Senate race in Arkansas? "
        "Democratic party [SENATEAR-28-D]"
    )
    KANSAS = (
        "Will Democratics win the Senate race in Kansas? "
        "Democratic party [SENATEKS-28-D]"
    )

    def test_arkansas_is_not_this_race(self):
        from sources.markets import _matches_race

        assert not _matches_race(self.ARKANSAS)

    def test_kansas_still_is(self):
        from sources.markets import _matches_race

        assert _matches_race(self.KANSAS)

    @pytest.mark.parametrize(
        "text",
        [
            "Will the Arkansas Senate seat flip?",
            "Arkansas Senate 2026 winner",
            "arkansas senate republican",
        ],
    )
    def test_no_arkansas_phrasing_matches(self, text):
        from sources.markets import _matches_race

        assert not _matches_race(text)

    def test_the_state_test_itself_rejects_the_longer_name(self):
        from sources.markets import _mentions_state

        assert _mentions_state("kansas senate")
        assert _mentions_state("Kansas Senate")
        assert not _mentions_state("arkansas senate")


class TestGridsAreNotPooledAcrossStates:
    """Two states' combination grids must never be summed together.

    The live grid keys were the outcome pair alone, so Arkansas's DEMDEM
    overwrote Kansas's. Four entries remained, which read as a complete
    partition, and the derived probability would have been assembled from two
    different races — real prices, wrong contest, nothing visibly wrong.
    """

    KANSAS = [
        {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "last_price": 11},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMREP", "last_price": 19},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-REPDEM", "last_price": 22},
        {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "last_price": 48},
    ]
    ARKANSAS = [
        {"ticker": "KXARSENGOVCOMBO-26NOV-DEMDEM", "last_price": 90},
        {"ticker": "KXARSENGOVCOMBO-26NOV-DEMREP", "last_price": 90},
        {"ticker": "KXARSENGOVCOMBO-26NOV-REPDEM", "last_price": 90},
        {"ticker": "KXARSENGOVCOMBO-26NOV-REPREP", "last_price": 90},
    ]

    def test_another_states_grid_does_not_move_the_number(self):
        from sources.markets import marginalise_combos

        alone = marginalise_combos(self.KANSAS)
        mixed = marginalise_combos(self.KANSAS + self.ARKANSAS)
        assert alone == mixed
        assert mixed[0] == pytest.approx(0.67, abs=1e-4)

    def test_another_states_grid_alone_yields_nothing(self):
        from sources.markets import marginalise_combos

        assert marginalise_combos(self.ARKANSAS) is None

    def test_two_partial_grids_do_not_add_up_to_one_complete_one(self):
        """Three Kansas cells plus one Arkansas cell is not a partition."""
        from sources.markets import marginalise_combos

        assert marginalise_combos(self.KANSAS[:3] + self.ARKANSAS[3:]) is None

    def test_the_grid_is_grouped_by_series(self):
        from sources.markets import combo_grid

        grids = combo_grid(self.KANSAS + self.ARKANSAS, kansas_only=False)
        assert set(grids) == {"KXKSSENGOVCOMBO-26NOV", "KXARSENGOVCOMBO-26NOV"}
        assert len(grids["KXKSSENGOVCOMBO-26NOV"]) == 4

    def test_only_kansas_series_are_kept_by_default(self):
        from sources.markets import combo_grid

        assert set(combo_grid(self.KANSAS + self.ARKANSAS)) == {"KXKSSENGOVCOMBO-26NOV"}


class TestGridDiagnostic:
    """The warning must name the missing cells rather than say "nothing matched".

    A capped title sample could not distinguish a race nobody quotes from a grid
    one cell short, and guessing which cost two rounds.
    """

    def test_missing_cells_are_named(self):
        from sources.markets import describe_grid

        note = describe_grid(TestGridsAreNotPooledAcrossStates.KANSAS[:3])
        assert "KXKSSENGOVCOMBO-26NOV" in note
        assert "kansas" in note
        assert "REPREP" in note.split("missing=")[1]

    def test_other_states_are_labelled_not_hidden(self):
        from sources.markets import describe_grid

        note = describe_grid(TestGridsAreNotPooledAcrossStates.ARKANSAS)
        assert "KXARSENGOVCOMBO-26NOV" in note
        assert "other-state" in note

    def test_a_scan_with_no_combos_says_so(self):
        from sources.markets import describe_grid

        assert describe_grid([{"ticker": "KXNBA-26-LAL"}]) == "no combination series found"


class TestKalshiPriceFields:
    """Which field the yes-side price is read from.

    The live run of 2026-08-22 listed all four Kansas combination outcomes and
    derived nothing from them: the rows carried neither last_price nor yes_bid,
    so the grid was rejected before it was grouped and the warning could only say
    "no combination series found".
    """

    def test_the_midpoint_is_preferred_over_a_stale_last_trade(self):
        """The mid is the current implied probability; a last trade can be hours old."""
        from sources.markets import kalshi_price

        assert kalshi_price({"yes_bid": 46, "yes_ask": 50, "last_price": 12}) == 0.48

    def test_falls_back_through_the_trade_fields(self):
        from sources.markets import kalshi_price

        assert kalshi_price({"last_price": 33}) == 0.33
        assert kalshi_price({"previous_price": 27}) == 0.27
        assert kalshi_price({"yes_bid": 41}) == 0.41

    def test_a_no_side_quote_implies_the_yes_price(self):
        from sources.markets import kalshi_price

        assert kalshi_price({"no_bid": 70, "no_ask": 74}) == pytest.approx(0.28)

    def test_a_row_with_no_price_at_all_yields_none(self):
        from sources.markets import kalshi_price

        assert kalshi_price({"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP"}) is None
        assert kalshi_price({"yes_bid": None, "last_price": None}) is None

    def test_a_genuine_zero_is_a_price_not_a_gap(self):
        from sources.markets import kalshi_price

        assert kalshi_price({"yes_bid": 0, "yes_ask": 0}) == 0.0

    def test_a_boolean_is_not_read_as_one_cent(self):
        """bool is an int subclass, so an unrelated flag would price at 1."""
        from sources.markets import kalshi_price

        assert kalshi_price({"last_price": True}) is None

    def test_a_grid_priced_only_on_the_book_still_marginalises(self):
        from sources.markets import marginalise_combos

        book = [
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "yes_bid": 10, "yes_ask": 12},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMREP", "yes_bid": 18, "yes_ask": 20},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPDEM", "yes_bid": 21, "yes_ask": 23},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "yes_bid": 47, "yes_ask": 49},
        ]
        marshall, hamilton = marginalise_combos(book)
        # Senate R = DEMREP 19 + REPREP 48 = 67 of 100.
        assert marshall == pytest.approx(0.67, abs=1e-4)
        assert marshall + hamilton == pytest.approx(1.0)


class TestUnpricedGridDiagnostic:
    """An unpriced grid must name the fields the rows actually carry.

    "No combination series found" covered both a race nobody quotes and rows
    whose price fields are named something else. Those need opposite responses,
    and guessing between them cost a round.
    """

    def test_unpriced_combination_rows_report_their_keys(self):
        from sources.markets import describe_grid

        note = describe_grid(
            [
                {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "status": "active", "volume": 0},
                {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "status": "active", "volume": 0},
            ]
        )
        assert "2 combination rows present, none priced" in note
        assert "KXKSSENGOVCOMBO-26NOV-REPREP" in note
        assert "status" in note and "volume" in note

    def test_a_scan_with_no_combination_rows_still_says_so(self):
        from sources.markets import describe_grid

        assert describe_grid([{"ticker": "KXNBA-26-LAL"}]) == "no combination series found"


class TestKalshiDollarFields:
    """Kalshi renamed every price field and changed its unit.

    The key list below is verbatim from the live row for
    KXKSSENGOVCOMBO-26NOV-REPREP on 2026-08-22: no yes_bid, no last_price, no
    volume, no open_interest. Prices are dollars per contract, so 48% reads 0.48,
    and the cent-era divide-by-a-hundred would have published half a percent
    instead of a half — a wrong number that renders perfectly.
    """

    LIVE_KEYS = [
        "can_close_early", "close_time", "created_time", "custom_strike",
        "early_close_condition", "event_ticker", "exchange_index",
        "expected_expiration_time", "expiration_time", "expiration_value",
        "last_price_dollars", "latest_expiration_time", "liquidity_dollars",
        "market_type", "no_ask_dollars", "no_bid_dollars", "no_sub_title",
        "notional_value_dollars", "occurrence_datetime", "open_interest_fp",
        "open_time", "previous_price_dollars", "previous_yes_ask_dollars",
        "previous_yes_bid_dollars", "price_level_structure", "price_ranges",
        "result", "rules_primary", "rules_secondary", "settlement_timer_seconds",
        "status", "strike_type", "ticker", "title", "updated_time",
        "volume_24h_fp", "volume_fp", "yes_ask_dollars", "yes_ask_size_fp",
        "yes_bid_dollars", "yes_bid_size_fp", "yes_sub_title",
    ]

    def _row(self, ticker: str, **overrides) -> dict:
        row = dict.fromkeys(self.LIVE_KEYS)
        row["ticker"] = ticker
        row.update(overrides)
        return row

    def test_dollar_prices_are_probabilities_already(self):
        from sources.markets import kalshi_price

        row = self._row("X", yes_bid_dollars=0.46, yes_ask_dollars=0.50)
        assert kalshi_price(row) == pytest.approx(0.48)

    def test_a_dollar_price_is_not_divided_by_a_hundred(self):
        """The failure this guards against renders as 0.5% and looks fine."""
        from sources.markets import kalshi_price

        assert kalshi_price(self._row("X", last_price_dollars=0.48)) == pytest.approx(0.48)

    def test_strings_parse(self):
        from sources.markets import kalshi_price

        assert kalshi_price(self._row("X", last_price_dollars="0.48")) == pytest.approx(0.48)

    def test_the_no_side_in_dollars_implies_the_yes_price(self):
        from sources.markets import kalshi_price

        row = self._row("X", no_bid_dollars=0.70, no_ask_dollars=0.74)
        assert kalshi_price(row) == pytest.approx(0.28)

    def test_a_row_of_the_live_shape_with_no_prices_yields_none(self):
        from sources.markets import kalshi_price

        assert kalshi_price(self._row("KXKSSENGOVCOMBO-26NOV-REPREP")) is None

    def test_a_dollar_value_above_one_is_refused_not_clamped(self):
        """Out of range means the unit is wrong; a clamp would hide that."""
        from sources.markets import kalshi_price

        assert kalshi_price(self._row("X", last_price_dollars=48)) is None

    def test_the_real_grid_marginalises(self):
        from sources.markets import marginalise_combos

        grid = [
            self._row("KXKSSENGOVCOMBO-26NOV-DEMDEM", yes_bid_dollars=0.10, yes_ask_dollars=0.12),
            self._row("KXKSSENGOVCOMBO-26NOV-DEMREP", yes_bid_dollars=0.18, yes_ask_dollars=0.20),
            self._row("KXKSSENGOVCOMBO-26NOV-REPDEM", yes_bid_dollars=0.21, yes_ask_dollars=0.23),
            self._row("KXKSSENGOVCOMBO-26NOV-REPREP", yes_bid_dollars=0.47, yes_ask_dollars=0.49),
        ]
        marshall, hamilton = marginalise_combos(grid)
        # Senate R = DEMREP 0.19 + REPREP 0.48 = 0.67.
        assert marshall == pytest.approx(0.67, abs=1e-4)
        assert marshall + hamilton == pytest.approx(1.0)

    def test_volume_and_open_interest_come_from_the_renamed_fields(self):
        from sources.markets import _kalshi_markets

        row = self._row(
            "KXKSSEN-26NOV-R",
            title="Will Kansas Senate winner be Republican party?",
            yes_sub_title="Republican party",
            yes_bid_dollars=0.55,
            yes_ask_dollars=0.57,
            volume_fp=1234.0,
            open_interest_fp=567.0,
        )
        market = _kalshi_markets({"markets": [row]})[0]
        assert market.marshall == pytest.approx(0.56)
        assert market.volume_usd == pytest.approx(1234.0)
        assert market.open_interest == pytest.approx(567.0)


class TestMarginLadderIsNotAWinProbability:
    """The ladder that actually reached markets.json, verbatim from the run.

    KXMIDTERMMOV-KSSENR-P3 asks whether the Republican margin will be at least
    three points. Its yes price is P(R wins by 3+), not P(R wins). Eleven rungs
    were attributed by party and volume-weighted into a published headline of
    Marshall .3727 / Hamilton .6273 — real Kansas Senate prices answering a
    question nobody asked, reading as Hamilton being the favourite.

    It also masked the combination grid: because the ladder counted as markets
    found, the marginalisation that produces the real number never ran.
    """

    LADDER = [
        (3, 0.745), (5, 0.635), (7, 0.485), (9, 0.34), (11, 0.205),
        (13, 0.14), (15, 0.0875), (17, 0.064), (19, 0.0455), (21, 0.039),
        (23, 0.0335),
    ]

    def _rung(self, points: int, price: float) -> dict:
        return {
            "ticker": f"KXMIDTERMMOV-KSSENR-P{points}",
            "title": (
                "Will the margin of victory for Republicans in the U.S. Senate "
                f"election in Kansas be at least {points} percentage points?"
            ),
            "yes_sub_title": "Republican party",
            "yes_bid_dollars": price - 0.01,
            "yes_ask_dollars": price + 0.01,
            "volume_fp": 1000.0,
        }

    def test_no_rung_is_read_as_a_win_probability(self):
        from sources.markets import _kalshi_markets

        rungs = [self._rung(points, price) for points, price in self.LADDER]
        assert _kalshi_markets({"markets": rungs}) == []

    def test_the_ladder_is_still_recognised_as_this_race(self):
        """It is about this race — that is why matching alone could not stop it."""
        from sources.markets import _matches_race

        assert _matches_race(self._rung(3, 0.745)["title"])

    def test_the_ticker_alone_is_enough_to_reject_it(self):
        from sources.markets import _asks_who_wins

        assert not _asks_who_wins("KXMIDTERMMOV-KSSENR-P3", "some other wording")

    def test_the_wording_alone_is_enough_to_reject_it(self):
        """A renamed ticker must not smuggle the same question back in."""
        from sources.markets import _asks_who_wins

        assert not _asks_who_wins("KXNEWTICKER-26", self._rung(9, 0.34)["title"])

    def test_a_real_winner_market_still_passes(self):
        from sources.markets import _asks_who_wins

        assert _asks_who_wins("KXKSSEN-26NOV-R", "Will Kansas Senate winner be Republican party?")
        assert _asks_who_wins("KXSENKS-26-RM", "Kansas Senate 2026 Roger Marshall")

    @pytest.mark.parametrize(
        "text",
        [
            "What will turnout be in the Kansas Senate election?",
            "Republican vote share in the Kansas Senate race",
            "How many votes will Roger Marshall receive?",
            "Will Republicans win the Kansas Senate seat by at least 5 points?",
        ],
    )
    def test_other_non_winner_questions_are_rejected(self, text):
        from sources.markets import _asks_who_wins

        assert not _asks_who_wins("KX-26", text)

    def test_the_combination_grid_is_reached_once_the_ladder_is_gone(self):
        """The ladder counting as "found" is what suppressed the real number."""
        from sources.markets import _kalshi_markets, marginalise_combos

        rungs = [self._rung(points, price) for points, price in self.LADDER]
        grid = [
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMDEM", "yes_bid_dollars": 0.10, "yes_ask_dollars": 0.12},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-DEMREP", "yes_bid_dollars": 0.18, "yes_ask_dollars": 0.20},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPDEM", "yes_bid_dollars": 0.21, "yes_ask_dollars": 0.23},
            {"ticker": "KXKSSENGOVCOMBO-26NOV-REPREP", "yes_bid_dollars": 0.47, "yes_ask_dollars": 0.49},
        ]
        rows = rungs + grid
        assert _kalshi_markets({"markets": rows}) == []
        marshall, hamilton = marginalise_combos(rows)
        assert marshall == pytest.approx(0.67, abs=1e-4)
        assert marshall + hamilton == pytest.approx(1.0)
