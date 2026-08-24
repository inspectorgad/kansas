"""Tests for the election-night results probe.

The endpoint these run against has never been observed: ent.sos.ks.gov was
unreachable when this was written and only serves live data for a few hours on
election night. So these tests pin the *parsers* against every plausible shape,
and the probe's job in production is to say clearly which one it matched — or,
if none, exactly what it was served.

The sharpest trap in this data is that Kansas has both a Marshall County and a
Hamilton County. A naive surname match would read county rows as candidate
totals and roughly double the count.
"""

import pytest

from schemas import HAMILTON, MARSHALL
from schemas.results import ResultsStatus
from sources.results import (
    KANSAS_COUNTIES,
    _candidate_id,
    _parse_embedded_json,
    _parse_html_table,
    _parse_json_results,
    _precincts,
)


class TestCandidateMatching:
    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Roger Marshall (R)", MARSHALL),
            ("MARSHALL, ROGER", MARSHALL),
            ("Sen. Marshall", MARSHALL),
            ("Adam Hamilton (D)", HAMILTON),
            ("HAMILTON, ADAM", HAMILTON),
            ("Marshall, R", MARSHALL),
        ],
    )
    def test_matches_candidates_however_they_are_labelled(self, label, expected):
        assert _candidate_id(label) == expected

    @pytest.mark.parametrize("label", ["Marshall", "Hamilton", "Hamilton County", "Marshall County"])
    def test_refuses_bare_county_names(self, label):
        """Kansas has a Marshall County and a Hamilton County.

        Reading either as a candidate would inflate the statewide count, so a
        bare surname is rejected unless corroborated by a first name, honorific
        or party tag.
        """
        assert _candidate_id(label) is None

    def test_both_counties_are_in_the_county_list(self):
        assert "Marshall" in KANSAS_COUNTIES
        assert "Hamilton" in KANSAS_COUNTIES
        assert len(KANSAS_COUNTIES) == 105  # Kansas has 105 counties


class TestJsonFeed:
    def test_reads_statewide_totals(self):
        payload = {
            "contests": [
                {
                    "title": "United States Senator",
                    "candidates": [
                        {"name": "Roger Marshall (R)", "votes": 412905},
                        {"name": "Adam Hamilton (D)", "votes": 388114},
                    ],
                }
            ]
        }
        data = _parse_json_results(payload)
        assert data is not None
        assert data.status == ResultsStatus.LIVE
        assert data.total_votes == 801019
        marshall = next(r for r in data.statewide if r.candidate_id == MARSHALL)
        assert marshall.votes == 412905
        assert marshall.pct == pytest.approx(51.55, abs=0.01)

    def test_percentages_sum_to_one_hundred(self):
        payload = {"candidates": [
            {"name": "Roger Marshall (R)", "votes": 3},
            {"name": "Adam Hamilton (D)", "votes": 1},
        ]}
        data = _parse_json_results(payload)
        assert sum(r.pct for r in data.statewide) == pytest.approx(100.0, abs=0.01)

    def test_reads_counties_nested_under_jurisdictions(self):
        payload = {
            "jurisdictions": [
                {
                    "county": "Johnson",
                    "candidates": [
                        {"name": "Roger Marshall (R)", "votes": 90210},
                        {"name": "Adam Hamilton (D)", "votes": 115300},
                    ],
                },
                {
                    "county": "Sedgwick",
                    "candidates": [
                        {"name": "Roger Marshall (R)", "votes": 78400},
                        {"name": "Adam Hamilton (D)", "votes": 61200},
                    ],
                },
            ]
        }
        data = _parse_json_results(payload)
        assert [c.county for c in data.counties] == ["Johnson", "Sedgwick"]
        johnson = data.counties[0]
        assert johnson.hamilton_votes == 115300
        assert johnson.total_votes == 205510

    def test_handles_vote_counts_as_formatted_strings(self):
        payload = {"candidates": [
            {"candidate": "Roger Marshall (R)", "vote_count": "412,905"},
            {"candidate": "Adam Hamilton (D)", "vote_count": "388,114"},
        ]}
        data = _parse_json_results(payload)
        assert data.total_votes == 801019

    def test_returns_none_for_json_about_something_else(self):
        assert _parse_json_results({"weather": {"wichita": "hot"}}) is None
        assert _parse_json_results([]) is None


class TestEmbeddedJson:
    def test_reads_a_bootstrap_variable(self):
        html = (
            'var electionData = {"races":[{"candidates":['
            '{"candidate":"Adam Hamilton (D)","vote_count":"388,114"},'
            '{"candidate":"Roger Marshall (R)","vote_count":"412,905"}]}]};'
        )
        data = _parse_embedded_json(html)
        assert data is not None
        assert data.total_votes == 801019

    def test_ignores_unrelated_script_variables(self):
        assert _parse_embedded_json('var config = {"theme":"dark"};') is None


class TestHtmlTable:
    HTML = """
    <table>
      <tr><th>County</th><th>Roger Marshall (R)</th><th>Adam Hamilton (D)</th></tr>
      <tr><td>Johnson</td><td>90,210</td><td>115,300</td></tr>
      <tr><td>Sedgwick</td><td>78,400</td><td>61,200</td></tr>
      <tr><td>Marshall</td><td>3,120</td><td>1,004</td></tr>
      <tr><td>Hamilton</td><td>901</td><td>402</td></tr>
    </table>
    <p>3,102 of 3,540 precincts reporting</p>
    """

    def test_reads_every_county_row(self):
        data = _parse_html_table(self.HTML)
        assert {c.county for c in data.counties} == {"Johnson", "Sedgwick", "Marshall", "Hamilton"}

    def test_county_rows_named_after_candidates_are_counted_as_counties(self):
        """Marshall County's votes belong to the county table, once."""
        data = _parse_html_table(self.HTML)
        marshall_county = next(c for c in data.counties if c.county == "Marshall")
        assert marshall_county.marshall_votes == 3120
        assert marshall_county.hamilton_votes == 1004

    def test_statewide_is_the_sum_of_the_counties_counted_once(self):
        data = _parse_html_table(self.HTML)
        expected_marshall = 90210 + 78400 + 3120 + 901
        actual = next(r for r in data.statewide if r.candidate_id == MARSHALL)
        assert actual.votes == expected_marshall

    def test_finds_candidate_columns_regardless_of_order(self):
        flipped = self.HTML.replace(
            "<th>Roger Marshall (R)</th><th>Adam Hamilton (D)</th>",
            "<th>Adam Hamilton (D)</th><th>Roger Marshall (R)</th>",
        )
        data = _parse_html_table(flipped)
        johnson = next(c for c in data.counties if c.county == "Johnson")
        # The columns swapped, so the numbers must swap with them.
        assert johnson.marshall_votes == 115300
        assert johnson.hamilton_votes == 90210

    def test_returns_none_for_a_page_with_no_results(self):
        assert _parse_html_table("<html><body><p>Results at 5pm.</p></body></html>") is None


class TestPrecincts:
    @pytest.mark.parametrize(
        "text",
        [
            "3,102 of 3,540 precincts reporting",
            "3102 / 3540 precincts",
            "Precincts reporting: 3,102 of 3,540",
        ],
    )
    def test_reads_the_common_phrasings(self, text):
        assert _precincts(text) == (3102, 3540)

    def test_absent_precinct_counts_are_none_not_zero(self):
        assert _precincts("Unofficial results") == (None, None)


class TestImplausibleResultsAreRejected:
    """A parser that reports success on nonsense is worse than one that fails.

    Against the live fallback page on 2026-08-24 the probe declared success on:

        hamilton: 3,075 (100.0%)
        counties: 0 of 105
        precincts reporting: 100.0%

    One candidate, three thousand votes, every precinct in. On election night
    that publishes a called race off a stray table, and nothing downstream can
    tell it is wrong. Failure is visible; this was not.
    """

    def _data(self, rows, *, reporting=None, counties=()):
        from schemas.results import CandidateResult
        from sources.results import ResultsData

        data = ResultsData()
        total = sum(v for _, v in rows) or 1
        data.statewide = [
            CandidateResult(
                candidate_id=cid, votes=votes, pct=round(votes / total * 100, 2)
            )
            for cid, votes in rows
        ]
        data.pct_reporting = reporting
        data.counties = list(counties)
        return data

    def test_the_exact_live_case_is_rejected(self):
        from sources.results import implausible

        reason = implausible(self._data([("hamilton", 3075)], reporting=100.0))
        assert reason is not None
        assert "marshall" in reason

    def test_one_candidate_missing_is_rejected(self):
        from sources.results import implausible

        assert implausible(self._data([("marshall", 500000)], reporting=60.0)) is not None

    def test_a_finished_count_in_the_thousands_is_rejected(self):
        from sources.results import implausible

        reason = implausible(
            self._data([("marshall", 2000), ("hamilton", 1075)], reporting=100.0)
        )
        assert reason is not None
        assert "3,075" in reason

    def test_full_reporting_with_no_counties_is_rejected(self):
        """A hundred per cent of precincts in, and not one county parsed."""
        from sources.results import implausible

        reason = implausible(
            self._data([("marshall", 700000), ("hamilton", 650000)], reporting=100.0)
        )
        assert reason is not None
        assert "no county rows" in reason

    def test_a_real_finished_count_passes(self):
        from schemas.results import CountyResult
        from sources.results import implausible

        counties = [
            CountyResult(
                county=name, marshall_votes=1000, hamilton_votes=900, total_votes=1900
            )
            for name in ("Sedgwick", "Johnson", "Shawnee")
        ]
        assert implausible(
            self._data(
                [("marshall", 700000), ("hamilton", 650000)],
                reporting=100.0,
                counties=counties,
            )
        ) is None

    def test_an_early_partial_count_passes(self):
        """Small totals are correct at 2% in; only the structure is checked there."""
        from sources.results import implausible

        assert implausible(
            self._data([("marshall", 1800), ("hamilton", 1275)], reporting=2.0)
        ) is None

    def test_a_single_candidate_is_rejected_even_early(self):
        """An ENR feed lists both candidates from the first precinct."""
        from sources.results import implausible

        assert implausible(self._data([("hamilton", 40)], reporting=1.0)) is not None

    def test_an_empty_parse_is_rejected(self):
        from sources.results import implausible

        assert implausible(self._data([])) == "no candidate rows"

    def test_a_feed_without_reporting_figures_still_needs_both_candidates(self):
        from sources.results import implausible

        assert implausible(self._data([("marshall", 500)])) is not None
        assert implausible(self._data([("marshall", 500), ("hamilton", 400)])) is None
