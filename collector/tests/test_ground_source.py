"""Tests for registration and advance-ballot extraction.

County election offices publish prose, not data, and they do not agree on
phrasing — some write "6,900 mail ballots had been returned", others "Mail
ballots returned: 8,455". Extraction anchors on a phrase and takes the nearest
number, which is the only rule that reads both correctly.

The distinction these tests protect hardest: a county whose page cannot be read
is *uncovered*, never zero. Reporting an unreadable dashboard as zero returned
ballots would understate turnout while looking like data.
"""

import pytest

from sources.ground import parse_advance, parse_registration_table

REGISTRATION_HTML = """
<table>
  <tr><th>County</th><th>Republican</th><th>Democratic</th><th>Unaffiliated</th>
      <th>Libertarian</th><th>Total</th></tr>
  <tr><td>Johnson</td><td>142,301</td><td>118,904</td><td>121,455</td><td>3,101</td><td>385,761</td></tr>
  <tr><td>Sedgwick</td><td>128,455</td><td>84,203</td><td>96,120</td><td>2,880</td><td>311,658</td></tr>
  <tr><td>Wyandotte</td><td>18,902</td><td>44,301</td><td>25,880</td><td>701</td><td>89,784</td></tr>
  <tr><td>Total</td><td>289,658</td><td>247,408</td><td>243,455</td><td>6,682</td><td>787,203</td></tr>
</table>
"""


class TestRegistration:
    def test_reads_counties_and_the_statewide_row(self):
        registration = parse_registration_table(REGISTRATION_HTML)
        assert [c.county for c in registration.by_county] == ["Johnson", "Sedgwick", "Wyandotte"]
        assert registration.statewide.total == 787_203
        assert registration.statewide.republican == 289_658

    def test_finds_columns_by_header_name_not_position(self):
        reordered = REGISTRATION_HTML.replace(
            "<th>Republican</th><th>Democratic</th>", "<th>Democratic</th><th>Republican</th>"
        ).replace(
            "<td>142,301</td><td>118,904</td>", "<td>118,904</td><td>142,301</td>"
        )
        registration = parse_registration_table(reordered)
        johnson = next(c for c in registration.by_county if c.county == "Johnson")
        assert johnson.republican == 142_301
        assert johnson.democrat == 118_904

    def test_derives_a_statewide_row_when_the_page_has_none(self):
        without_total = REGISTRATION_HTML.replace(
            "<tr><td>Total</td><td>289,658</td><td>247,408</td><td>243,455</td>"
            "<td>6,682</td><td>787,203</td></tr>",
            "",
        )
        registration = parse_registration_table(without_total)
        assert registration.statewide.total == 385_761 + 311_658 + 89_784

    def test_derives_a_county_total_when_the_column_is_missing(self):
        no_total_column = """
        <table>
          <tr><th>County</th><th>Republican</th><th>Democratic</th></tr>
          <tr><td>Douglas</td><td>18,000</td><td>32,000</td></tr>
        </table>
        """
        registration = parse_registration_table(no_total_column)
        assert registration.by_county[0].total == 50_000

    def test_a_page_with_no_table_returns_none(self):
        assert parse_registration_table("<p>Statistics are published as a PDF.</p>") is None

    def test_a_table_about_something_else_returns_none(self):
        other = """
        <table><tr><th>County</th><th>Polling places</th></tr>
        <tr><td>Johnson</td><td>142</td></tr></table>
        """
        assert parse_registration_table(other) is None


class TestAdvanceBallots:
    PROSE = """
    <p>The Election Office mailed 14,195 advance ballots to voters who applied to vote
    by mail, and more than 6,900 mail ballots had been returned. As of Friday, more than
    16,000 registered voters had cast early ballots at advance voting locations.</p>
    """

    LABELLED = """
    <p>Mail ballots sent: 20,104<br>Mail ballots returned: 8,455<br>
    In-person early voting: 12,300</p>
    """

    def test_reads_prose_where_the_verb_precedes_the_number(self):
        advance = parse_advance(self.PROSE, "Sedgwick", "https://example.org")
        assert advance.mail_ballots_sent == 14_195
        assert advance.mail_ballots_returned == 6_900
        assert advance.in_person_votes == 16_000

    def test_reads_a_label_colon_value_layout(self):
        """The nearest number wins; a preceding-first rule read this wrong."""
        advance = parse_advance(self.LABELLED, "Johnson", "https://example.org")
        assert advance.mail_ballots_sent == 20_104
        assert advance.mail_ballots_returned == 8_455
        assert advance.in_person_votes == 12_300

    def test_two_fields_never_report_the_same_figure(self):
        advance = parse_advance(self.LABELLED, "Johnson", "https://example.org")
        values = [
            advance.mail_ballots_sent,
            advance.mail_ballots_returned,
            advance.in_person_votes,
        ]
        assert len(set(values)) == len(values)

    def test_total_advance_is_returned_plus_in_person_not_including_sent(self):
        """Ballots mailed out are not votes cast."""
        advance = parse_advance(self.PROSE, "Sedgwick", "https://example.org")
        assert advance.total_advance == 6_900 + 16_000

    def test_an_unreadable_page_is_uncovered_not_zero(self):
        assert parse_advance("<p>Polls open at 7am.</p>", "Douglas", "u") is None

    def test_a_phone_number_is_not_a_ballot_count(self):
        assert parse_advance("<p>Call 316-555-0199 for information.</p>", "Shawnee", "u") is None

    @pytest.mark.parametrize(
        "html",
        [
            "<p>2,004 ballots returned so far.</p>",
            "<p>Ballots returned: 2,004</p>",
            "<p>Returned mail ballots — 2,004</p>",
        ],
    )
    def test_equivalent_phrasings_all_yield_the_same_number(self, html):
        advance = parse_advance(html, "Wyandotte", "u")
        assert advance is not None
        assert advance.mail_ballots_returned == 2_004

    def test_a_partial_page_reports_only_what_it_found(self):
        advance = parse_advance("<p>Mail ballots returned: 8,455</p>", "Johnson", "u")
        assert advance.mail_ballots_returned == 8_455
        assert advance.mail_ballots_sent is None
        assert advance.in_person_votes is None
        assert advance.total_advance == 8_455


class TestAdvanceVotingWindow:
    """County dashboards are not read before general-election advance voting opens.

    The first live run matched figures on two county dashboards in August. Those
    were primary numbers. Publishing them as general-election early vote would
    have been confidently wrong rather than merely empty, which is the worse of
    the two failures.
    """

    def test_the_window_opens_twenty_days_before_the_election(self):
        from config import ADVANCE_VOTING_OPENS
        from schemas import ELECTION_DATE

        assert ADVANCE_VOTING_OPENS < ELECTION_DATE
        assert (ELECTION_DATE - ADVANCE_VOTING_OPENS).days == 20

    def test_dashboards_are_not_read_before_the_window(self, monkeypatch):
        import sources.ground as ground

        calls: list[str] = []

        def fail_if_called(url):
            calls.append(url)
            raise AssertionError("county dashboards must not be fetched yet")

        monkeypatch.setattr(ground, "get_text", fail_if_called)
        monkeypatch.setattr(ground, "parse_registration_table", lambda _html: None)

        # Registration is still attempted, so let that one fetch fail cleanly.
        from fetch import SourceError

        def registration_only(url):
            if "sos.ks.gov" in url:
                raise SourceError("skipped in test")
            return fail_if_called(url)

        monkeypatch.setattr(ground, "get_text", registration_only)

        result = ground.collect()
        assert result.advance_ballots.counties == []
        assert result.advance_ballots.counties_covered == []
        assert any("advance voting opens" in w for w in result.warnings)
        assert calls == []


class TestAYearIsNotAVoteCount:
    """The probe reported "in-person=2026" for Johnson and Sedgwick.

    That is the year, sitting beside the phrase "advance voting" in a heading,
    read as a turnout figure. Harmless only because advance voting is gated until
    October 14 — from that date it would have published 2,026 in-person votes in
    two of the largest counties in Kansas.

    The discriminator comes from the pages themselves: they write counts as 14,195
    and 8,455, and years as 2026.
    """

    def test_a_heading_year_yields_nothing(self):
        from sources.ground import parse_advance

        page = "<h1>Advance Voting 2026</h1><p>Check back for turnout figures.</p>"
        assert parse_advance(page, "Johnson", "u") is None

    def test_real_figures_parse_alongside_a_year(self):
        """The year must be skipped without taking the real numbers with it."""
        from sources.ground import parse_advance

        page = (
            "<h2>Advance Voting 2026 General Election</h2>"
            "<p>Mail ballots sent: 14,195</p>"
            "<p>Mail ballots returned: 8,455</p>"
            "<p>Voted in person: 6,900</p>"
        )
        parsed = parse_advance(page, "Johnson", "u")
        assert parsed.mail_ballots_sent == 14195
        assert parsed.mail_ballots_returned == 8455
        assert parsed.in_person_votes == 6900
        assert parsed.total_advance == 15355

    def test_a_separated_two_thousand_and_twenty_six_still_counts(self):
        from sources.ground import parse_advance

        parsed = parse_advance("<p>Voted in person: 2,026</p>", "Sedgwick", "u")
        assert parsed.in_person_votes == 2026

    def test_a_bare_year_shaped_count_is_given_up_on_purpose(self):
        """A visible gap beats a confident wrong number."""
        from sources.ground import parse_advance

        assert parse_advance("<p>Voted in person: 2026</p>", "Sedgwick", "u") is None

    @pytest.mark.parametrize("raw,is_year", [
        ("2026", True), ("1990", True), ("2099", True),
        ("1989", False), ("2100", False),
        ("2,026", False), ("41205", False), ("900", False), ("14,195", False),
    ])
    def test_the_year_test_itself(self, raw, is_year):
        from sources.ground import _is_year

        assert _is_year(raw) is is_year

    def test_five_digit_counts_are_unaffected(self):
        from sources.ground import parse_advance

        parsed = parse_advance("<p>Voted in person: 41205</p>", "Sedgwick", "u")
        assert parsed.in_person_votes == 41205
