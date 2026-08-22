"""Tests for news relevance and dedup.

Relevance is the interesting part. Both candidates share their surnames with
Kansas counties, "Marshall" is an ordinary noun, Lewis Hamilton is a household
name, and Adam Hamilton was a nationally known pastor long before he ran for
office — so a bare name match would fill the feed with noise.
"""

import pytest

from sources.news import canonical_url, is_relevant, item_id, mentions


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
