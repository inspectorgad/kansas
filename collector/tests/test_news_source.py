"""Tests for news relevance and dedup.

Relevance is the interesting part. Both candidates share their surnames with
Kansas counties, "Marshall" is an ordinary noun, Lewis Hamilton is a household
name, and Adam Hamilton was a nationally known pastor long before he ran for
office — so a bare name match would fill the feed with noise.
"""

import pytest

from sources.news import _reject_reason, canonical_url, is_relevant, item_id, mentions


class TestRelevance:
    @pytest.mark.parametrize(
        "headline",
        [
            "Kansas Senate race tightens as Hamilton, Marshall trade attacks",
            "Roger Marshall votes against farm bill in Senate",
            "Hamilton wins Democratic primary for U.S. Senate",
            "Sen. Marshall faces questions over Florida residency in campaign ad",
            "Adam Hamilton outraises Marshall for a third straight quarter",
        ],
    )
    def test_keeps_race_coverage(self, headline):
        assert is_relevant(headline)

    @pytest.mark.parametrize(
        "headline",
        [
            "Marshall County fair opens Saturday",
            "Lewis Hamilton wins the Grand Prix",
            "Adam Hamilton preaches on stewardship at church conference",
            "Hamilton the musical comes to Wichita",
            "Wichita weather forecast for the weekend",
            "",
        ],
    )
    def test_rejects_coincidental_name_matches(self, headline):
        assert not is_relevant(headline)

    def test_a_bare_surname_needs_the_office_named(self):
        assert not is_relevant("Marshall announces new grant program")
        assert is_relevant("Marshall announces Senate re-election bid")

    def test_context_can_come_from_the_summary(self):
        assert is_relevant("Marshall in Topeka", "The senator addressed his campaign schedule.")


class TestMentions:
    def test_detects_both_candidates(self):
        assert mentions("Marshall and Hamilton debate in Wichita") == ["hamilton", "marshall"]

    def test_detects_one_candidate(self):
        assert mentions("Roger Marshall on the farm bill") == ["marshall"]

    def test_empty_when_neither_appears(self):
        assert mentions("Kansas weather") == []


class TestDedup:
    def test_strips_tracking_parameters_and_fragments(self):
        assert canonical_url("https://ex.com/a/b/?utm_source=rss#top") == "https://ex.com/a/b"

    def test_same_story_with_different_tracking_gets_one_id(self):
        a = item_id("https://ex.com/story?utm_campaign=x")
        b = item_id("https://ex.com/story/")
        assert a == b

    def test_different_stories_get_different_ids(self):
        assert item_id("https://ex.com/a") != item_id("https://ex.com/b")


class TestRejectReason:
    """The probe's explanation must agree with the filter it explains.

    _reject_reason mirrors is_relevant's branches by hand, so the two can drift.
    A probe that reported a different verdict than the collector applies would
    send someone off fixing the wrong rule.
    """

    @pytest.mark.parametrize(
        "headline",
        [
            "Kansas Senate race tightens as Hamilton, Marshall trade attacks",
            "Marshall announces Senate re-election bid",
            "Marshall County fair opens Saturday",
            "Wichita weather forecast for the weekend",
            "Lewis Hamilton wins the Grand Prix",
            "",
        ],
    )
    def test_agrees_with_is_relevant(self, headline):
        assert (_reject_reason(headline) is None) == is_relevant(headline)

    def test_names_the_test_that_failed(self):
        assert _reject_reason("Wichita weather forecast") == "no candidate named"
        assert "bare surname" in _reject_reason("Marshall announces new grant program")
        assert "full name" in _reject_reason("Roger Marshall tours a Hutchinson salt mine")

    def test_says_which_candidate_was_matched(self):
        assert "marshall" in _reject_reason("Marshall County fair opens Saturday")
        assert "hamilton" in _reject_reason("Lewis Hamilton wins the Grand Prix")


RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>{a}</title><link>https://ex.test/1</link></item>
<item><title>{b}</title><link>https://ex.test/2</link></item>
</channel></rss>"""


class TestFeedYieldReporting:
    """Per-feed yield is reported on ordinary runs, not only under a probe.

    A tracker showing one outlet and nothing for five days needed a hand-run probe
    to explain itself, while the numbers that explained it were already being
    computed and discarded.
    """

    def _run(self, monkeypatch, body):
        import config
        from sources import news

        monkeypatch.setattr(config, "NEWS_FEEDS", [config.Feed("Test Wire", "https://ex.test/f")])
        monkeypatch.setattr(news, "NEWS_FEEDS", config.NEWS_FEEDS)
        monkeypatch.setattr(news, "get_text", lambda url, params=None: body)
        warnings: list[str] = []
        news.from_feeds(warnings)
        return warnings

    def test_reports_kept_over_total(self, monkeypatch):
        warnings = self._run(
            monkeypatch,
            RSS.format(a="Marshall and Hamilton debate", b="Wichita weather"),
        )
        assert any("feed yield (kept/entries): Test Wire 1/2" in w for w in warnings)

    def test_a_feed_yielding_nothing_still_reports(self, monkeypatch):
        warnings = self._run(monkeypatch, RSS.format(a="Local fair", b="Traffic stop"))
        assert any("Test Wire 0/2" in w for w in warnings)

    def test_a_dropped_headline_naming_a_candidate_is_flagged(self, monkeypatch):
        # The signature of filter drift, and the only rejection worth a warning.
        warnings = self._run(
            monkeypatch,
            RSS.format(a="Roger Marshall tours a salt mine", b="Wichita weather"),
        )
        assert any("named a candidate and were dropped" in w for w in warnings)

    def test_ordinary_local_news_raises_no_drift_warning(self, monkeypatch):
        warnings = self._run(monkeypatch, RSS.format(a="Local fair", b="Traffic stop"))
        assert not any("named a candidate" in w for w in warnings)
