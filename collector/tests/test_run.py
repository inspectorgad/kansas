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


class TestMarketHistoryEpoch:
    """History from before the epoch is dropped, not carried forward.

    The 17:28 run on 2026-08-22 published Marshall .3727 from the KXMIDTERMMOV
    margin ladder. The series is read back from the previous markets.json each
    run, so that one point would have ridden forward for as long as the inline
    window held it — a phantom forty-point swing on the sparkline and a poisoned
    24h delta for a day.
    """

    def _published(self, tmp_path, timestamp: str, marshall: float) -> None:
        (tmp_path / "markets.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": timestamp,
                    "markets": [],
                    "consensus": {
                        "as_of": timestamp,
                        "marshall": marshall,
                        "hamilton": round(1.0 - marshall, 4),
                        "platforms": ["kalshi"],
                        "history": [
                            {"t": timestamp, "marshall": marshall,
                             "hamilton": round(1.0 - marshall, 4)}
                        ],
                    },
                }
            )
        )

    def _history_seen_by_collect(self, monkeypatch, tmp_path):
        """Capture the series actually handed to the collector.

        Asserting on the republished file would prove nothing here: there is no
        Kalshi fixture, so the collection fails and the seeded file is correctly
        left untouched. What matters is which points reach the consensus, so that
        is what is captured.
        """
        seen: list = []

        import sources.markets as markets_module

        def fake_collect(history=None):
            seen.append(list(history or []))
            raise SourceError("no network in tests")

        monkeypatch.setattr(markets_module, "collect", fake_collect)
        return seen

    def test_a_pre_epoch_point_is_discarded_and_reported(
        self, fixtures, tmp_path, monkeypatch
    ):
        seen = self._history_seen_by_collect(monkeypatch, tmp_path)
        self._published(tmp_path, "2026-08-22T17:28:06.677338Z", 0.3727)
        report = run.run(["markets"], str(tmp_path), write=True)

        assert any("discarded 1 market history point" in w for w in report.warnings), (
            report.warnings
        )
        assert seen == [[]]

    def test_a_post_epoch_point_is_kept(self, fixtures, tmp_path, monkeypatch):
        seen = self._history_seen_by_collect(monkeypatch, tmp_path)
        self._published(tmp_path, "2026-08-23T09:00:00Z", 0.61)
        report = run.run(["markets"], str(tmp_path), write=True)

        assert not any("discarded" in w for w in report.warnings), report.warnings
        assert [point.marshall for point in seen[0]] == [0.61]

    def test_a_failed_collection_leaves_the_published_file_alone(
        self, fixtures, tmp_path, monkeypatch
    ):
        """Dropping bad history must not become a way to lose good data."""
        self._history_seen_by_collect(monkeypatch, tmp_path)
        self._published(tmp_path, "2026-08-23T09:00:00Z", 0.61)
        before = (tmp_path / "markets.json").read_text()
        run.run(["markets"], str(tmp_path), write=True)
        assert (tmp_path / "markets.json").read_text() == before


class TestOutsideSpendingFromRows:
    """The for/against split comes from each row's own indicator.

    The by_candidate aggregate was wrong two different ways on the first live run
    with a real FEC key. For Marshall it ignored support_oppose_indicator and
    returned the identical $214,014.88 as both supporting and opposing him. For
    Hamilton it returned nothing at all, while the row-level endpoint showed over
    $1.1M of television placed against him in the same run.
    """

    MARSHALL_ID = "S0KS00315"
    HAMILTON_ID = "S6KS00312"

    def _rows(self, monkeypatch, by_fec_id, committees=None, count=None):
        """Serve schedule E rows per candidate and record every path called."""
        import sources.finance as finance

        calls: list[str] = []

        def fake_get(path, params=None):
            params = params or {}
            calls.append(path)
            if path == "/schedules/schedule_e/":
                rows = by_fec_id.get(params.get("candidate_id"), [])
                return {
                    "results": rows,
                    "pagination": {"count": count if count is not None else len(rows)},
                }
            if path == "/committees/":
                wanted = params.get("committee_id") or []
                return {
                    "results": [
                        {"committee_id": cid, "name": name}
                        for cid, name in (committees or {}).items()
                        if cid in wanted
                    ]
                }
            return {"results": []}

        monkeypatch.setattr(finance, "_get", fake_get)
        return finance, calls

    def _row(self, committee_id, amount, indicator, day="2026-08-06", **extra):
        row = {
            "committee_id": committee_id,
            "expenditure_amount": amount,
            "support_oppose_indicator": indicator,
            "expenditure_date": day,
            "expenditure_description": "PLACED MEDIA: TV",
        }
        row.update(extra)
        return row

    def test_hamilton_appears_in_the_breakdown(self, monkeypatch):
        """The bug: he was absent while over $1.1M was spent against him."""
        finance, _ = self._rows(
            monkeypatch,
            {
                self.HAMILTON_ID: [
                    self._row("C00957928", 586399.0, "O", sub_id="1"),
                    self._row("C00957928", 549123.1, "O", day="2026-08-05", sub_id="2"),
                ]
            },
        )
        warnings: list[str] = []
        result = finance.outside_spending({"hamilton": self.HAMILTON_ID}, warnings)

        assert result.opposing == {"hamilton": 1135522.1}
        assert result.supporting == {}
        assert result.total == 1135522.1

    def test_both_candidates_are_counted_on_their_own_sides(self, monkeypatch):
        finance, _ = self._rows(
            monkeypatch,
            {
                self.MARSHALL_ID: [self._row("C00448696", 1000.0, "S", sub_id="m1")],
                self.HAMILTON_ID: [self._row("C00957928", 4000.0, "O", sub_id="h1")],
            },
        )
        result = finance.outside_spending(
            {"marshall": self.MARSHALL_ID, "hamilton": self.HAMILTON_ID}, []
        )

        assert result.supporting == {"marshall": 1000.0}
        assert result.opposing == {"hamilton": 4000.0}
        assert result.total == 5000.0

    def test_the_same_money_is_never_counted_on_both_sides(self, monkeypatch):
        """The exact failure that shipped: total was twice the real figure."""
        finance, _ = self._rows(
            monkeypatch,
            {self.MARSHALL_ID: [self._row("C00448696", 214014.88, "S", sub_id="x")]},
        )
        result = finance.outside_spending({"marshall": self.MARSHALL_ID}, [])

        assert result.supporting == {"marshall": 214014.88}
        assert result.opposing == {}
        assert result.total == 214014.88
        spender = result.top_spenders[0]
        assert spender.supports == "marshall"
        assert spender.opposes is None

    def test_the_broken_aggregate_endpoint_is_not_used(self, monkeypatch):
        """Regression guard: by_candidate must not come back."""
        finance, calls = self._rows(
            monkeypatch, {self.MARSHALL_ID: [self._row("C1", 1.0, "S", sub_id="a")]}
        )
        finance.outside_spending({"marshall": self.MARSHALL_ID}, [])
        assert not any("by_candidate" in path for path in calls), calls

    def test_a_row_with_no_indicator_is_skipped_not_assumed_against(self, monkeypatch):
        """The old code defaulted to "O", filing support as opposition."""
        finance, _ = self._rows(
            monkeypatch,
            {self.MARSHALL_ID: [self._row("C1", 5000.0, None, sub_id="n1")]},
        )
        warnings: list[str] = []
        result = finance.outside_spending({"marshall": self.MARSHALL_ID}, warnings)

        assert result.supporting == {} and result.opposing == {}
        assert any("no support/oppose indicator" in w for w in warnings), warnings

    def test_committee_names_are_looked_up(self, monkeypatch):
        finance, _ = self._rows(
            monkeypatch,
            {self.MARSHALL_ID: [self._row("C00448696", 900.0, "S", sub_id="s1")]},
            committees={"C00448696": "SENATE CONSERVATIVES FUND"},
        )
        result = finance.outside_spending({"marshall": self.MARSHALL_ID}, [])

        assert result.top_spenders[0].committee_name == "SENATE CONSERVATIVES FUND"
        assert result.recent[0].committee_name == "SENATE CONSERVATIVES FUND"

    def test_repeated_filings_of_one_expenditure_collapse(self, monkeypatch):
        duplicate = self._row("C00957928", 586399.0, "O")
        finance, _ = self._rows(
            monkeypatch, {self.HAMILTON_ID: [duplicate, dict(duplicate)]}
        )
        result = finance.outside_spending({"hamilton": self.HAMILTON_ID}, [])
        assert len(result.recent) == 1

    def test_a_truncated_read_is_reported_as_a_floor(self, monkeypatch):
        """Silently understating the money in the race is the thing to avoid."""
        finance, _ = self._rows(
            monkeypatch,
            {self.MARSHALL_ID: [self._row("C1", 100.0, "S", sub_id="p1")]},
            count=5000,
        )
        warnings: list[str] = []
        finance.outside_spending({"marshall": self.MARSHALL_ID}, warnings)
        assert any("a floor, not a total" in w for w in warnings), warnings

    def test_a_repeated_page_stops_the_walk(self, monkeypatch):
        """A cursor that never advances must not burn the whole page budget."""
        import sources.finance as finance

        pages: list[int] = []

        def fake_get(path, params=None):
            if path == "/schedules/schedule_e/":
                pages.append(1)
                return {
                    "results": [self._row("C1", 10.0, "S", sub_id="same")],
                    "pagination": {"count": 999},
                }
            return {"results": []}

        monkeypatch.setattr(finance, "_get", fake_get)
        finance.outside_spending({"marshall": self.MARSHALL_ID}, [])
        assert len(pages) == 2, f"walked {len(pages)} pages; should stop on the repeat"


class TestDonorDetail:
    """Who funds each campaign, within what disclosure actually allows."""

    COMMITTEE = "C00576173"

    def _patched(self, monkeypatch, *, rows=(), count=None, employers=(),
                 occupations=(), sizes=(), refunds=()):
        import sources.finance as finance

        calls: list[str] = []

        def fake_get(path, params=None):
            params = params or {}
            calls.append(path)
            if path == "/schedules/schedule_a/":
                # The refunds pass asks for negatives with max_amount; serving the
                # positive rows to both would add every contribution twice.
                if params.get("max_amount") is not None:
                    return {"results": list(refunds), "pagination": {"count": len(refunds)}}
                return {
                    "results": list(rows),
                    "pagination": {"count": count if count is not None else len(rows)},
                }
            if path == "/schedules/schedule_a/by_employer/":
                return {"results": list(employers)}
            if path == "/schedules/schedule_a/by_occupation/":
                return {"results": list(occupations)}
            if path == "/schedules/schedule_a/by_size/":
                return {"results": list(sizes)}
            return {"results": []}

        monkeypatch.setattr(finance, "_get", fake_get)
        return finance, calls

    def _gift(self, name, amount, city="WICHITA", state="KS", **extra):
        row = {
            "contributor_name": name,
            "contribution_receipt_amount": amount,
            "contributor_city": city,
            "contributor_state": state,
            "contributor_employer": "SELF-EMPLOYED",
            "contributor_occupation": "RANCHER",
            "contribution_receipt_date": "2026-06-01",
        }
        row.update(extra)
        return row

    def test_one_donor_giving_twice_is_one_entry(self, monkeypatch):
        finance, _ = self._patched(
            monkeypatch,
            rows=[
                self._gift("SMITH, JANE", 2500.0, sub_id="1"),
                self._gift("SMITH, JANE", 1500.0, sub_id="2"),
            ],
        )
        detail = finance._donor_detail(self.COMMITTEE, [])

        assert len(detail.large_donors) == 1
        donor = detail.large_donors[0]
        assert donor.amount == 4000.0
        assert donor.gifts == 2

    def test_spacing_and_case_do_not_split_a_donor(self, monkeypatch):
        """FEC strings vary between filings; grouping on the raw value understates."""
        finance, _ = self._patched(
            monkeypatch,
            rows=[
                self._gift("SMITH, JANE", 2500.0, sub_id="1"),
                self._gift("smith,   jane", 1000.0, sub_id="2"),
            ],
        )
        detail = finance._donor_detail(self.COMMITTEE, [])
        assert len(detail.large_donors) == 1
        assert detail.large_donors[0].amount == 3500.0

    def test_donors_are_ranked_by_total(self, monkeypatch):
        finance, _ = self._patched(
            monkeypatch,
            rows=[
                self._gift("SMALL, SAM", 1000.0, sub_id="1"),
                self._gift("BIG, BEA", 3300.0, sub_id="2"),
                self._gift("MID, MO", 2000.0, sub_id="3"),
            ],
        )
        names = [d.name for d in finance._donor_detail(self.COMMITTEE, []).large_donors]
        assert names == ["BIG, BEA", "MID, MO", "SMALL, SAM"]

    def test_employer_and_occupation_come_from_the_aggregate_endpoints(self, monkeypatch):
        finance, calls = self._patched(
            monkeypatch,
            employers=[
                {"employer": "KOCH INDUSTRIES", "total": 55000.0, "count": 30},
                {"employer": "RETIRED", "total": 120000.0, "count": 400},
            ],
            occupations=[{"occupation": "ATTORNEY", "total": 44000.0, "count": 60}],
        )
        detail = finance._donor_detail(self.COMMITTEE, [])

        assert [g.label for g in detail.top_employers] == ["RETIRED", "KOCH INDUSTRIES"]
        assert detail.top_employers[0].donors == 400
        assert detail.top_occupations[0].label == "ATTORNEY"
        assert "/schedules/schedule_a/by_employer/" in calls

    def test_itemized_totals_come_from_the_fec_not_from_the_buckets(self, monkeypatch):
        """The size buckets are a distribution, not a source for these two totals.

        This test used to assert the opposite, and the assertion was wrong rather
        than the code: the live probe showed the "Under $200" bucket holding
        $896,843 for Hamilton against a true unitemized figure of $767,189, the
        difference being itemized receipts that happened to be small. Summing the
        buckets above it therefore understated itemized money by the same amount.
        For Marshall the derived figure was $2.63M against the $1.72M the FEC
        reports. The FEC publishes both numbers directly; they are read, not
        rebuilt.
        """
        finance, _ = self._patched(
            monkeypatch,
            sizes=[
                {"size": 0, "total": 900000.0, "count": None},
                {"size": 200, "total": 300000.0, "count": 900},
                {"size": 2000, "total": 700000.0, "count": 350},
            ],
        )
        detail = finance._donor_detail(
            self.COMMITTEE, [], itemized=1030000.0, unitemized=870000.0
        )

        assert detail.itemized_total == 1030000.0
        assert detail.unitemized_total == 870000.0
        # The buckets still describe the shape of the giving.
        assert {b.label for b in detail.size_buckets} >= {"Under $200", "$200 to $499"}

    def test_the_totals_are_absent_rather_than_guessed(self, monkeypatch):
        """A caller that cannot supply the FEC figures gets nothing, not a guess."""
        finance, _ = self._patched(
            monkeypatch, sizes=[{"size": 0, "total": 900000.0, "count": None}]
        )
        detail = finance._donor_detail(self.COMMITTEE, [])
        assert detail.itemized_total is None
        assert detail.unitemized_total is None

    def test_cities_are_labelled_as_large_money_only(self, monkeypatch):
        """openFEC groups geography by state and ZIP, never by city."""
        finance, _ = self._patched(
            monkeypatch,
            rows=[
                self._gift("A, A", 5000.0, city="OVERLAND PARK", sub_id="1"),
                self._gift("B, B", 2000.0, city="WICHITA", sub_id="2"),
                self._gift("C, C", 1000.0, city="WICHITA", sub_id="3"),
            ],
        )
        cities = finance._donor_detail(self.COMMITTEE, []).top_cities

        assert cities[0].label == "Overland Park, KS"
        assert cities[0].amount == 5000.0
        assert cities[1].label == "Wichita, KS"
        assert cities[1].donors == 2

    def test_the_itemization_caveat_travels_with_the_data(self, monkeypatch):
        """A screen must not be able to render these lists without it."""
        finance, _ = self._patched(monkeypatch, rows=[self._gift("A, A", 1000.0, sub_id="1")])
        detail = finance._donor_detail(self.COMMITTEE, [])
        assert "$200" in detail.itemized_note
        assert detail.threshold == 1000.0

    def test_a_truncated_scan_says_what_it_missed(self, monkeypatch):
        finance, _ = self._patched(
            monkeypatch, rows=[self._gift("A, A", 9999.0, sub_id="1")], count=50000
        )
        coverage = finance._donor_detail(self.COMMITTEE, []).large_donor_coverage
        assert "smaller gifts" in coverage

    def test_a_complete_scan_still_states_the_limit(self, monkeypatch):
        """Even complete, the ranking misses donors who accumulated in small gifts."""
        finance, _ = self._patched(monkeypatch, rows=[self._gift("A, A", 1000.0, sub_id="1")])
        coverage = finance._donor_detail(self.COMMITTEE, []).large_donor_coverage
        assert "smaller gifts" in coverage

    def test_a_failed_lookup_degrades_rather_than_raising(self, monkeypatch):
        import sources.finance as finance
        from fetch import SourceError

        def fake_get(path, params=None):
            raise SourceError("429 rate limited")

        monkeypatch.setattr(finance, "_get", fake_get)
        warnings: list[str] = []
        detail = finance._donor_detail(self.COMMITTEE, warnings)

        assert detail.large_donors == []
        assert detail.top_employers == []
        assert len(warnings) >= 3


class TestNonAnswerLabels:
    """"NONE" is not an employer and "NULL" is not an occupation.

    The first live run with donor detail ranked "NONE" as Marshall's largest
    employer at $69,200 and "NULL" as his fourth occupation at $60,322. Both are
    what the form carries when nobody filled it in, presented as findings.
    """

    @pytest.mark.parametrize(
        "label",
        ["NONE", "None", "null", "N/A", "n/a", "NOT APPLICABLE", "INFORMATION REQUESTED",
         "UNKNOWN", "REFUSED", "  ", "-", "--", ".", "Best Efforts"],
    )
    def test_non_answers_are_rejected(self, label):
        from sources.finance import _is_non_answer

        assert _is_non_answer(label)

    @pytest.mark.parametrize(
        "label",
        ["RETIRED", "HOMEMAKER", "SELF-EMPLOYED", "NOT EMPLOYED", "ATTORNEY",
         "KOCH INDUSTRIES", "CEO", "Physician", "EURONET"],
    )
    def test_real_answers_are_kept(self, label):
        """Retired and homemaker are real answers, and informative ones."""
        from sources.finance import _is_non_answer

        assert not _is_non_answer(label)

    def test_placeholders_are_dropped_from_the_published_groups(self, monkeypatch):
        import sources.finance as finance

        def fake_get(path, params=None):
            if path == "/schedules/schedule_a/by_employer/":
                return {
                    "results": [
                        {"employer": "NONE", "total": 69200.0, "count": 40},
                        {"employer": "KOCH INDUSTRIES", "total": 21000.0, "count": 7},
                        {"employer": "NULL", "total": 15000.0, "count": 9},
                        {"employer": "SELF-EMPLOYED", "total": 25300.0, "count": 12},
                    ]
                }
            return {"results": []}

        monkeypatch.setattr(finance, "_get", fake_get)
        groups = finance._donor_groups(
            "/schedules/schedule_a/by_employer/",
            "C00576173",
            ("employer",),
            [],
            "employer",
        )
        labels = [g.label for g in groups]
        assert "NONE" not in labels and "NULL" not in labels
        assert labels == ["SELF-EMPLOYED", "KOCH INDUSTRIES"]


class TestIdenticalAmountAudit:
    """Several donors at an identical total is the shape a double count makes.

    Marshall's top five each came back at exactly $31,500 over exactly three
    gifts — five different people, five different states. $10,500 apiece is above
    the per-election individual limit, so either joint-fundraising structure
    explains it or rows are being summed that should not be. Only fields no total
    carries can tell the two apart, so the rows get fetched and reported.
    """

    def _audit(self, monkeypatch, donors, rows=()):
        import sources.finance as finance

        calls: list[dict] = []

        def fake_get(path, params=None):
            calls.append({"path": path, "params": params or {}})
            return {"results": list(rows), "pagination": {"count": len(rows)}}

        monkeypatch.setattr(finance, "_get", fake_get)
        warnings: list[str] = []
        finance._identical_amount_audit("C00576173", donors, warnings)
        return warnings, calls

    def _donor(self, name, amount=31500.0, gifts=3):
        from schemas.finance import LargeDonor

        return LargeDonor(name=name, amount=amount, gifts=gifts)

    def test_a_cluster_is_flagged_and_audited(self, monkeypatch):
        donors = [self._donor(n) for n in ("A, A", "B, B", "C, C", "D, D", "E, E")]
        rows = [
            {"sub_id": "1", "contribution_receipt_amount": 10500.0, "receipt_type": "15E",
             "line_number": "11AI", "memo_code": "X"},
            {"sub_id": "2", "contribution_receipt_amount": 10500.0, "receipt_type": "15E",
             "line_number": "11AI"},
        ]
        warnings, calls = self._audit(monkeypatch, donors, rows)

        assert any("5 donors share an identical total" in w for w in warnings), warnings
        audit = next(w for w in warnings if w.startswith("audit of"))
        assert "memo-coded 1" in audit
        assert "un-memoed 1" in audit
        assert "distinct sub_id" in audit
        assert calls[0]["params"]["contributor_name"] == "A, A"

    def test_distinct_amounts_are_not_audited(self, monkeypatch):
        """Hamilton's list looks like this, and must cost no extra request."""
        donors = [
            self._donor("A, A", 21000.0, 6),
            self._donor("B, B", 12597.0, 4),
            self._donor("C, C", 11552.0, 4),
        ]
        warnings, calls = self._audit(monkeypatch, donors)
        assert warnings == []
        assert calls == []

    def test_two_matching_donors_are_not_enough(self, monkeypatch):
        """Two people giving the same round number is unremarkable."""
        donors = [self._donor("A, A", 7000.0), self._donor("B, B", 7000.0)]
        warnings, calls = self._audit(monkeypatch, donors)
        assert warnings == []
        assert calls == []

    def test_a_failed_audit_degrades(self, monkeypatch):
        import sources.finance as finance
        from fetch import SourceError

        def fake_get(path, params=None):
            raise SourceError("429")

        monkeypatch.setattr(finance, "_get", fake_get)
        warnings: list[str] = []
        finance._identical_amount_audit(
            "C1", [self._donor(n) for n in ("A, A", "B, B", "C, C")], warnings
        )
        assert any("could not fetch rows" in w for w in warnings)


class TestRefundsAndReattributions:
    """Donor totals must be net of money that was given back.

    The audit of Marshall's $17,500 donor found one un-memoed $14,000 row and
    three memo-coded rows summing to minus $7,000. Refunds and reattributions file
    as negative amounts, and the min_amount floor that finds large contributions
    excludes every one of them, so the collector was publishing gross giving. A
    donor whose contribution was refunded stayed on the list at full value.
    """

    def _run(self, monkeypatch, rows, refunds):
        import sources.finance as finance

        def fake_get(path, params=None):
            params = params or {}
            if path != "/schedules/schedule_a/":
                return {"results": []}
            if params.get("max_amount") is not None:
                return {"results": list(refunds), "pagination": {"count": len(refunds)}}
            return {"results": list(rows), "pagination": {"count": len(rows)}}

        monkeypatch.setattr(finance, "_get", fake_get)
        return finance._large_donors("C00576173", [])

    def _row(self, name, amount, sub_id, city="WICHITA"):
        return {
            "contributor_name": name,
            "contribution_receipt_amount": amount,
            "contributor_city": city,
            "contributor_state": "KS",
            "contribution_receipt_date": "2026-06-01",
            "sub_id": sub_id,
        }

    def test_a_refund_is_subtracted(self, monkeypatch):
        donors, coverage = self._run(
            monkeypatch,
            [self._row("VANDERGRIEND, DAVID J.", 14000.0, "1")],
            [self._row("VANDERGRIEND, DAVID J.", -7000.0, "2")],
        )
        assert [d.amount for d in donors] == [7000.0]
        assert "net of refunds" in coverage
        assert "1 correction(s)" in coverage

    def test_a_fully_refunded_donor_drops_off_the_list(self, monkeypatch):
        """Below the threshold once netted, so not a large donor at all."""
        donors, _ = self._run(
            monkeypatch,
            [self._row("GAVE, THEN, TOOK", 5000.0, "1")],
            [self._row("GAVE, THEN, TOOK", -4500.0, "2")],
        )
        assert donors == []

    def test_a_refund_to_someone_not_on_the_list_is_ignored(self, monkeypatch):
        donors, _ = self._run(
            monkeypatch,
            [self._row("BIG, DONOR", 9000.0, "1")],
            [self._row("SMALL, PERSON", -50.0, "2", city="TOPEKA")],
        )
        assert [(d.name, d.amount) for d in donors] == [("BIG, DONOR", 9000.0)]

    def test_no_refunds_still_says_totals_are_net(self, monkeypatch):
        """The reader should not have to guess whether netting happened."""
        donors, coverage = self._run(
            monkeypatch, [self._row("CLEAN, DONOR", 7000.0, "1")], []
        )
        assert [d.amount for d in donors] == [7000.0]
        assert "net of refunds." in coverage

    def test_the_positive_rows_are_not_counted_twice(self, monkeypatch):
        """The refunds query must not be served the contributions."""
        donors, _ = self._run(
            monkeypatch, [self._row("ONCE, ONLY", 3000.0, "1")], []
        )
        assert [d.amount for d in donors] == [3000.0]


class TestRatingsAreScopedToKansas:
    """A rating must belong to this race, not to whichever row came first.

    parse_rating took the first rating phrase anywhere on the page. These
    handicappers publish one page listing every Senate contest, so that was
    whichever state sorts first — Alabama or Alaska — published as Kansas's
    rating. The same failure as reading Arkansas as Kansas, and it would have
    looked entirely plausible on the one field whose purpose is to be quoted.
    """

    SENATE_TABLE = """
    <table>
     <tr><td>Alabama</td><td>Solid Republican</td></tr>
     <tr><td>Alaska</td><td>Likely Republican</td></tr>
     <tr><td>Arkansas</td><td>Solid Republican</td></tr>
     <tr><td>Georgia</td><td>Lean Democratic</td></tr>
     <tr><td>Kansas</td><td>Toss-up</td></tr>
     <tr><td>Maine</td><td>Lean Republican</td></tr>
    </table>
    """

    def test_the_kansas_row_wins_not_the_first_row(self):
        from sources.ratings import parse_rating

        assert parse_rating(self.SENATE_TABLE) == ("Toss-up", None)

    def test_a_race_specific_page_still_parses(self):
        from schemas.common import Party
        from sources.ratings import parse_rating

        page = "<h1>Kansas Senate</h1><p>Our rating: <b>Lean Republican</b></p>"
        assert parse_rating(page) == ("Lean Republican", Party.REPUBLICAN)

    def test_a_rating_before_the_state_name_is_found(self):
        """Some layouts put the label first."""
        from sources.ratings import parse_rating

        assert parse_rating("<p>Toss-up &mdash; Kansas Senate</p>") == ("Toss-up", None)

    def test_a_page_never_naming_kansas_yields_nothing(self):
        from sources.ratings import parse_rating

        assert parse_rating("<tr><td>Alabama</td><td>Solid Republican</td></tr>") is None

    def test_arkansas_is_not_kansas_here_either(self):
        from sources.ratings import parse_rating

        assert parse_rating("<tr><td>Arkansas</td><td>Solid Republican</td></tr>") is None

    def test_kansas_with_no_rating_nearby_yields_nothing(self):
        """Better empty than another state's label."""
        from sources.ratings import parse_rating

        assert parse_rating("<p>Kansas holds its primary in August.</p>") is None

    def test_a_distant_rating_is_out_of_reach(self):
        from sources.ratings import parse_rating

        page = "<p>Kansas Senate</p>" + ("<p>filler. </p>" * 60) + "<p>Solid Republican</p>"
        assert parse_rating(page) is None


class TestRatingsAreParked:
    """Off until a handicapper answers, and saying so rather than looking empty.

    A live probe got 403 Forbidden from Cook, Sabato and Inside Elections — a
    block, not a moved page. Three requests per run were being spent to fail, and
    the warning fired every twenty minutes about something no parser change can
    fix. A log that always carries the same complaint is a log nobody reads, which
    is how "3,075 votes, 100% reporting" survived a day as a reported success.
    """

    def test_collect_makes_no_requests_while_parked(self, monkeypatch):
        """Parked means no network, whatever the manual file happens to hold."""
        import sources.ratings as ratings

        def explode(*args, **kwargs):
            raise AssertionError("a parked source must not fetch anything")

        monkeypatch.setattr(ratings, "get_text", explode)
        ratings.collect()  # must not raise

    def test_the_parser_is_still_reachable_for_the_probe(self):
        """Parked means not fetched, not deleted — the probe still exercises it."""
        from sources.ratings import parse_rating

        assert parse_rating("<tr><td>Kansas</td><td>Toss-up</td></tr>") == ("Toss-up", None)

    def test_the_reason_is_reported_when_there_is_nothing_to_show(
        self, fixtures, tmp_path, monkeypatch
    ):
        """With scraping off and no manual entries, say why rather than nothing.

        Pointed at an empty file on purpose. The first version of this test read
        the shipped one, which passed only while that file happened to be empty
        and broke the moment real ratings were added — a test pinned to a moment
        rather than to a contract.
        """
        import config

        empty = tmp_path / "none.json"
        empty.write_text(json.dumps({"ratings": []}))
        monkeypatch.setattr(config, "MANUAL_RATINGS_PATH", empty)
        import sources.ratings as ratings

        monkeypatch.setattr(ratings, "MANUAL_RATINGS_PATH", empty)

        report = run.run(["race"], str(tmp_path), write=True)
        assert any("403" in note for note in report.warnings), report.warnings
        assert any("manual/ratings.json" in note for note in report.warnings)

    def test_re_enabling_restores_the_old_diagnosis(self, fixtures, tmp_path, monkeypatch):
        """The flag is the only thing standing between parked and live."""
        import config

        monkeypatch.setattr(config, "RATINGS_ENABLED", True)
        report = run.run(["race"], str(tmp_path), write=True)
        assert not any("403" in note for note in report.warnings), report.warnings


class TestManualRatings:
    """Ratings typed by a person, since every handicapper answers 403.

    The route exists because a move from Lean R to Toss-up is among the more
    newsworthy things that happens in a race, and scraping cannot reach it. The
    risks it introduces are its own: a typed value can look live, and it goes
    stale silently. Both are handled here rather than left to whoever reads it.
    """

    def _file(self, tmp_path, entries, key="ratings"):
        path = tmp_path / "ratings.json"
        path.write_text(json.dumps({key: entries}))
        return path

    def _entry(self, **overrides):
        entry = {
            "source": "Cook Political Report",
            "rating": "Toss Up",
            "lean": None,
            "as_of": "2026-08-20",
            "url": "https://www.cookpolitical.com/senate/race/488581",
        }
        entry.update(overrides)
        return entry

    def test_a_typed_rating_loads_and_is_flagged(self, tmp_path):
        from datetime import date

        from sources.ratings import load_manual

        ratings, notes = load_manual(
            self._file(tmp_path, [self._entry()]), today=date(2026, 8, 24)
        )
        assert len(ratings) == 1
        assert ratings[0].entered_by_hand is True
        assert ratings[0].rating == "Toss Up"
        assert notes == []

    def test_a_stale_entry_is_reported_but_still_published(self, tmp_path):
        """An old rating with its date shown beats no rating at all."""
        from datetime import date

        from sources.ratings import load_manual

        ratings, notes = load_manual(
            self._file(tmp_path, [self._entry(as_of="2026-01-05")]),
            today=date(2026, 8, 24),
        )
        assert len(ratings) == 1
        assert any("days old" in note for note in notes), notes

    def test_a_missing_date_is_reported(self, tmp_path):
        from datetime import date

        from sources.ratings import load_manual

        entry = self._entry()
        del entry["as_of"]
        ratings, notes = load_manual(self._file(tmp_path, [entry]), today=date(2026, 8, 24))
        assert len(ratings) == 1
        assert any("no as_of date" in note for note in notes), notes

    def test_a_bad_entry_is_skipped_and_named(self, tmp_path):
        """One typo must not take the other ratings down with it."""
        from datetime import date

        from sources.ratings import load_manual

        entries = [self._entry(), {"source": "Sabato", "lean": "R"}]  # no rating
        ratings, notes = load_manual(self._file(tmp_path, entries), today=date(2026, 8, 24))
        assert [r.source for r in ratings] == ["Cook Political Report"]
        assert any("Sabato" in note and "rejected" in note for note in notes), notes

    def test_a_malformed_file_is_not_silently_empty(self, tmp_path):
        from sources.ratings import load_manual

        path = tmp_path / "ratings.json"
        path.write_text("{ truncated")
        ratings, notes = load_manual(path)
        assert ratings == []
        assert any("unreadable" in note for note in notes), notes

    def test_a_missing_file_is_simply_empty(self, tmp_path):
        from sources.ratings import load_manual

        ratings, notes = load_manual(tmp_path / "absent.json")
        assert ratings == [] and notes == []

    def test_a_file_without_the_list_says_so(self, tmp_path):
        from sources.ratings import load_manual

        ratings, notes = load_manual(self._file(tmp_path, [], key="entries"))
        assert ratings == []
        assert any("no 'ratings' list" in note for note in notes), notes

    def test_a_previous_label_survives_for_change_detection(self, tmp_path):
        from datetime import date

        from sources.ratings import load_manual

        ratings, _ = load_manual(
            self._file(tmp_path, [self._entry(previous="Lean Republican")]),
            today=date(2026, 8, 24),
        )
        assert ratings[0].previous == "Lean Republican"

    def test_the_shipped_file_holds_what_it_claims(self):
        """The real entries, read off the live pages in a browser on 2026-08-24.

        Both handicappers are at Likely R, both dated, so this file should now
        load with no warnings at all. Cook showed the move from Solid R, which is
        why it carries `previous`. Sabato's date does not appear on the map and was
        supplied separately; it is their publication date, not the day it was read.
        """
        import config
        from sources.ratings import load_manual

        ratings, notes = load_manual(config.MANUAL_RATINGS_PATH)
        by_source = {r.source: r for r in ratings}
        assert set(by_source) == {"Cook Political Report", "Sabato's Crystal Ball"}
        assert all(r.entered_by_hand for r in ratings)
        assert all(r.rating == "Likely R" for r in ratings)

        cook = by_source["Cook Political Report"]
        assert cook.as_of.isoformat() == "2026-08-05"
        assert cook.previous == "Solid R"

        sabato = by_source["Sabato's Crystal Ball"]
        assert sabato.as_of.isoformat() == "2026-08-19"
        # Both dated and both recent, so nothing should be flagged.
        assert notes == [], notes


class TestMemoEntriesAreNotSummed:
    """A memo row itemizes money already reported on a parent transaction.

    The live file published Marshall's top three donors at $21,000 each, from five
    rows apiece: an un-memoed $14,000, a memo-coded $14,000 repeating it, and memo
    rows moving money between the primary and general and reattributing half to a
    spouse. Adding the memo copy to its parent is what produced the extra $7,000.
    """

    COMMITTEE = "C00576173"

    def _row(self, name, amount, sub_id, memo=None, city="WICHITA"):
        row = {
            "contributor_name": name,
            "contribution_receipt_amount": amount,
            "sub_id": sub_id,
            "contributor_city": city,
            "contributor_state": "KS",
        }
        if memo:
            row["memo_code"] = memo
        return row

    def _run(self, monkeypatch, positives, negatives):
        from sources import finance

        def fake_get(path, params=None):
            params = params or {}
            if "max_amount" in params:
                return {"results": negatives, "pagination": {}}
            return {"results": positives, "pagination": {"count": len(positives)}}

        monkeypatch.setattr(finance, "_get", fake_get)
        return finance._large_donors(self.COMMITTEE, [])

    def test_a_memo_copy_is_not_added_to_its_parent(self, monkeypatch):
        donors, _ = self._run(
            monkeypatch,
            [
                self._row("MARSHALL, TIFFANY", 14000.0, "1"),
                self._row("MARSHALL, TIFFANY", 14000.0, "2", memo="X"),
                self._row("MARSHALL, TIFFANY", 3500.0, "3", memo="X"),
            ],
            [
                self._row("MARSHALL, TIFFANY", -7000.0, "4", memo="X"),
                self._row("MARSHALL, TIFFANY", -3500.0, "5", memo="X"),
            ],
        )
        assert [(d.name, d.amount) for d in donors] == [("MARSHALL, TIFFANY", 14000.0)]

    def test_a_genuine_refund_still_lands(self, monkeypatch):
        # Only memo rows are skipped. An un-memoed negative is a real refund and
        # must still come off the total.
        donors, _ = self._run(
            monkeypatch,
            [self._row("GIVER, GREG", 10000.0, "1")],
            [self._row("GIVER, GREG", -2500.0, "2")],
        )
        assert [d.amount for d in donors] == [7500.0]

    def test_the_negative_memo_rows_are_skipped_too(self, monkeypatch):
        # Applying the negative memo rows while dropping the positive ones they
        # pair with is a different wrong answer, not a partial fix.
        donors, _ = self._run(
            monkeypatch,
            [self._row("SPLIT, SAM", 14000.0, "1")],
            [self._row("SPLIT, SAM", -3500.0, "2", memo="X")],
        )
        assert [d.amount for d in donors] == [14000.0]

    def test_the_coverage_note_says_memos_are_excluded(self, monkeypatch):
        _, coverage = self._run(
            monkeypatch, [self._row("ANY, ONE", 5000.0, "1")], []
        )
        assert "Memo entries are excluded" in coverage
