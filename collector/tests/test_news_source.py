"""Tests for news relevance and dedup.

Relevance is the interesting part. Both candidates share their surnames with
Kansas counties, "Marshall" is an ordinary noun, Lewis Hamilton is a household
name, and Adam Hamilton was a nationally known pastor long before he ran for
office — so a bare name match would fill the feed with noise.
"""

import pytest

from sources.news import (
    _is_syndicated,
    _outlet,
    _reject_reason,
    canonical_url,
    is_relevant,
    item_id,
    mentions,
)


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
        # Marshall's full name now stands alone, so the "no context" branch is
        # reachable only through Hamilton — see news.SELF_SUFFICIENT.
        assert "full name" in _reject_reason("Adam Hamilton preaches on stewardship")

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
            RSS.format(a="Adam Hamilton preaches on stewardship", b="Wichita weather"),
        )
        assert any("named a candidate and were dropped" in w for w in warnings)

    def test_ordinary_local_news_raises_no_drift_warning(self, monkeypatch):
        warnings = self._run(monkeypatch, RSS.format(a="Local fair", b="Traffic stop"))
        assert not any("named a candidate" in w for w in warnings)


class TestSelfSufficientNames:
    """Marshall's full name stands alone; Hamilton's does not.

    Ten real stories were being dropped before the Google News feed exposed them,
    most of them ordinary coverage of the incumbent that simply never used the word
    "Senate". The asymmetry is deliberate: he holds the office, while Adam Hamilton
    is written about constantly as a pastor.
    """

    @pytest.mark.parametrize(
        "headline",
        [
            "Roger Marshall tells Kansas voters to look at 'who hates me'",
            "Roger Marshall selling Florida vacation house 2 years after hurricane",
            "Roger Marshall: Kansas town halls have become 'dangerous'",
            "Sen. Marshall tours a Hutchinson salt mine",
        ],
    )
    def test_marshall_by_full_name_is_enough(self, headline):
        assert is_relevant(headline)

    @pytest.mark.parametrize(
        "headline",
        [
            "Hamilton honored for connectional leadership",
            "Adam Hamilton preaches on stewardship at church conference",
            "Adam Hamilton's congregation dedicates a new building",
        ],
    )
    def test_hamilton_still_needs_the_race_attached(self, headline):
        assert not is_relevant(headline)

    def test_hamilton_with_race_context_is_kept(self):
        assert is_relevant("Adam Hamilton touts shared values with voting bloc")

    def test_a_bare_marshall_surname_is_still_not_enough(self):
        assert not is_relevant("Marshall County fair opens Saturday")


class TestSyndicatedItems:
    """Google News is a search feed: it names the publisher and links via redirect."""

    def test_a_google_link_is_syndicated_and_an_outlet_link_is_not(self):
        assert _is_syndicated("https://news.google.com/rss/articles/CBMiabc")
        assert not _is_syndicated("https://kansasreflector.com/2026/08/19/story/")

    def test_the_outlet_comes_from_the_source_element(self):
        entry = {"source": {"title": "Kansas City Star"}}
        name, title = _outlet(entry, "Marshall sells Florida house - Kansas City Star")
        assert (name, title) == ("Kansas City Star", "Marshall sells Florida house")

    def test_the_title_suffix_is_the_fallback(self):
        name, title = _outlet({}, "Marshall sells Florida house - Kansas City Star")
        assert (name, title) == ("Kansas City Star", "Marshall sells Florida house")

    def test_an_entry_naming_no_outlet_keeps_its_title(self):
        assert _outlet({}, "Marshall sells Florida house") == (None, "Marshall sells Florida house")

    def test_a_dash_inside_the_headline_survives(self):
        entry = {"source": {"title": "KCUR"}}
        name, title = _outlet(entry, "Kansas Senate race set - and it is close - KCUR")
        assert (name, title) == ("KCUR", "Kansas Senate race set - and it is close")


class TestCrossFeedDedup:
    """The same story from an outlet and from Google News must publish once."""

    def _feed(self, *items):
        body = ['<?xml version="1.0"?><rss version="2.0"><channel>']
        for title, link, source in items:
            src = f"<source>{source}</source>" if source else ""
            body.append(f"<item><title>{title}</title><link>{link}</link>{src}</item>")
        body.append("</channel></rss>")
        return "".join(body)

    def test_the_publisher_link_wins_over_the_redirect(self, monkeypatch):
        import config
        from sources import news

        headline = "Marshall and Hamilton spar over Senate debate"
        direct = self._feed((headline, "https://kansasreflector.com/a/", None))
        via = self._feed(
            (f"{headline} - Kansas Reflector", "https://news.google.com/rss/articles/CB", None)
        )
        feeds = [
            config.Feed("Google News", "https://news.google.com/rss/search?q=x"),
            config.Feed("Kansas Reflector", "https://kansasreflector.com/feed/"),
        ]
        monkeypatch.setattr(news, "NEWS_FEEDS", feeds)
        bodies = {feeds[0].url: via, feeds[1].url: direct}
        monkeypatch.setattr(news, "get_text", lambda url, params=None: bodies[url])

        warnings: list[str] = []
        items, _ = news.from_feeds(warnings)
        assert len(items) == 1
        assert items[0].url == "https://kansasreflector.com/a"
        assert any("more than one feed" in w for w in warnings)

    def test_the_aggregator_is_not_credited_for_a_story_it_lost(self, monkeypatch):
        import config
        from sources import news

        headline = "Marshall and Hamilton spar over Senate debate"
        feeds = [
            config.Feed("Google News", "https://news.google.com/rss/search?q=x"),
            config.Feed("Kansas Reflector", "https://kansasreflector.com/feed/"),
        ]
        bodies = {
            feeds[0].url: self._feed(
                (f"{headline} - Kansas Reflector", "https://news.google.com/rss/articles/CB", None)
            ),
            feeds[1].url: self._feed((headline, "https://kansasreflector.com/a/", None)),
        }
        monkeypatch.setattr(news, "NEWS_FEEDS", feeds)
        monkeypatch.setattr(news, "get_text", lambda url, params=None: bodies[url])

        _, attribution = news.from_feeds([])
        assert [a.name for a in attribution] == ["Kansas Reflector"]

    def test_the_aggregator_is_credited_for_a_story_only_it_has(self, monkeypatch):
        import config
        from sources import news

        feeds = [config.Feed("Google News", "https://news.google.com/rss/search?q=x")]
        body = self._feed(
            (
                "Marshall leads Hamilton in new Senate poll - Wichita Eagle",
                "https://news.google.com/rss/articles/CB",
                None,
            )
        )
        monkeypatch.setattr(news, "NEWS_FEEDS", feeds)
        monkeypatch.setattr(news, "get_text", lambda url, params=None: body)

        items, attribution = news.from_feeds([])
        assert [a.name for a in attribution] == ["Google News"]
        assert attribution[0].note and "credited to the outlet" in attribution[0].note
        # The item itself carries the publisher, not the aggregator.
        assert items[0].source == "Wichita Eagle"
        assert items[0].title == "Marshall leads Hamilton in new Senate poll"
