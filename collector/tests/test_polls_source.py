"""Tests for the Wikipedia polling-table parser.

The fixture is synthetic but structured like the real article, and deliberately
contains the awkward cases: bolded leaders, refs and templates in cells, a
missing sample size, an en-dash for a missing value, a cross-month range, a
cross-year range, a campaign-sponsored poll, and a non-poll aggregate row.
"""

from datetime import date
from pathlib import Path

import pytest

from fetch import SourceError
from sources.polls import parse_polls, poll_id

FIXTURE = Path(__file__).parent / "fixtures" / "polling_table.wikitext"
MULTILINE = Path(__file__).parent / "fixtures" / "polling_table_multiline.wikitext"


@pytest.fixture(scope="module")
def parsed():
    return parse_polls(FIXTURE.read_text())


def test_parses_every_poll_row(parsed):
    assert len(parsed.polls) == 6
    assert parsed.skipped == []


def test_ignores_the_primary_table(parsed):
    """The primary table lacks a Hamilton column and must not be read."""
    assert all("Some Challenger" not in p.pollster for p in parsed.polls)
    assert not any(p.pollster == "Example Research" for p in parsed.polls)


def test_ignores_the_aggregate_footer_row(parsed):
    assert not any("aggregate" in p.pollster.lower() for p in parsed.polls)


def test_polls_are_newest_first(parsed):
    dates = [p.end_date for p in parsed.polls]
    assert dates == sorted(dates, reverse=True)


def test_reads_candidate_numbers_through_bold_markup(parsed):
    ppp = next(p for p in parsed.polls if p.pollster == "Public Policy Polling")
    assert ppp.results.marshall == 46.0
    assert ppp.results.hamilton == 45.0
    assert ppp.undecided == 7.0
    assert ppp.other == 2.0


def test_reads_sample_size_and_population(parsed):
    emerson = next(
        p for p in parsed.polls if p.pollster == "Emerson College" and p.end_date == date(2026, 8, 2)
    )
    assert emerson.sample_size == 1024
    assert emerson.population == "RV"
    assert emerson.margin_of_error == 3.0


def test_handles_a_missing_sample_size(parsed):
    cygnal = next(p for p in parsed.polls if p.pollster == "Cygnal")
    assert cygnal.sample_size is None
    assert cygnal.margin_of_error is None


def test_handles_an_en_dash_for_a_missing_value(parsed):
    survey = next(p for p in parsed.polls if p.pollster == "SurveyUSA")
    assert survey.other is None
    assert survey.undecided == 9.0


def test_parses_a_cross_month_date_range(parsed):
    emerson = next(
        p for p in parsed.polls if p.pollster == "Emerson College" and p.end_date == date(2026, 8, 2)
    )
    assert emerson.start_date == date(2026, 7, 28)


def test_parses_a_cross_year_date_range(parsed):
    """`December 29, 2025 - January 3, 2026` must not land both ends in one year."""
    poll = next(p for p in parsed.polls if p.end_date == date(2026, 1, 3))
    assert poll.start_date == date(2025, 12, 29)


def test_strips_refs_and_templates_from_the_pollster_cell(parsed):
    gbao = next(p for p in parsed.polls if p.pollster == "GBAO")
    assert "cite" not in gbao.pollster
    assert "ref" not in gbao.pollster


def test_extracts_a_campaign_sponsor(parsed):
    gbao = next(p for p in parsed.polls if p.pollster == "GBAO")
    assert gbao.sponsor == "for Hamilton campaign"
    assert gbao.partisan is not None and gbao.partisan.value == "D"


def test_flags_a_known_partisan_pollster_without_a_sponsor(parsed):
    cygnal = next(p for p in parsed.polls if p.pollster == "Cygnal")
    assert cygnal.partisan is not None and cygnal.partisan.value == "R"


def test_ids_are_stable_and_unique(parsed):
    ids = [p.id for p in parsed.polls]
    assert len(set(ids)) == len(ids)
    ppp = next(p for p in parsed.polls if p.pollster == "Public Policy Polling")
    assert ppp.id == poll_id("Public Policy Polling", date(2026, 8, 6), date(2026, 8, 8))


def test_duplicate_rows_collapse_to_one_poll():
    """Re-listing the same poll must not double-count it in the average."""
    table = """
{| class="wikitable"
! Poll source !! Date(s) !! Marshall (R) !! Hamilton (D)
|-
| Repeat Research || August 5, 2026 || 46% || 45%
|-
| Repeat Research || August 5, 2026 || 46% || 45%
|}
"""
    assert len(parse_polls(table).polls) == 1


def test_missing_table_raises_loudly():
    """A structural change upstream must fail the run, not silently return zero polls."""
    with pytest.raises(SourceError, match="no Marshall-vs-Hamilton polling table"):
        parse_polls("== Some article with no polling table ==\n")


def test_row_with_unparseable_date_is_skipped_and_reported():
    table = """
{| class="wikitable"
! Poll source !! Date(s) !! Marshall (R) !! Hamilton (D)
|-
| Good Poll || August 5, 2026 || 46% || 45%
|-
| Bad Poll || sometime last spring || 44% || 47%
|}
"""
    result = parse_polls(table)
    assert len(result.polls) == 1
    assert len(result.skipped) == 1
    assert "Bad Poll" in result.skipped[0]


class TestMultiLineHeaders:
    """Wikipedia's real header style: one cell per line.

    This is the form the live article uses, and reading only the first header
    line saw a single column and reported "no polling table found" — while the
    single-line fixture passed. The fixture had been shaped to the parser instead
    of to the source.
    """

    @pytest.fixture
    def parsed(self):
        return parse_polls(MULTILINE.read_text())

    def test_finds_the_table(self, parsed):
        assert len(parsed.polls) == 3
        assert parsed.skipped == []

    def test_reads_candidate_columns_through_style_attributes(self, parsed):
        """Real header cells carry party-shading style attributes."""
        emerson = next(p for p in parsed.polls if p.pollster == "Emerson College")
        assert emerson.results.marshall == 47.0
        assert emerson.results.hamilton == 46.0

    def test_reads_the_other_columns_too(self, parsed):
        emerson = next(p for p in parsed.polls if p.pollster == "Emerson College")
        assert emerson.sample_size == 1000
        assert emerson.population == "LV"
        assert emerson.margin_of_error == 3.0
        assert emerson.undecided == 4.0

    def test_ignores_the_table_caption(self, parsed):
        assert not any("2026 Kansas" in p.pollster for p in parsed.polls)

    def test_header_helper_returns_every_cell(self):
        from sources.wikitext import header_row, iter_tables

        header = header_row(iter_tables(MULTILINE.read_text())[0])
        assert len(header) == 8
        assert any("Marshall" in cell for cell in header)
        assert any("Hamilton" in cell for cell in header)

    def test_both_header_styles_yield_the_same_header(self):
        """The one-line and one-cell-per-line forms must parse identically."""
        from sources.wikitext import header_row, iter_tables

        single = header_row(iter_tables(FIXTURE.read_text())[0])
        multi = header_row(iter_tables(MULTILINE.read_text())[0])
        assert single == multi
