"""Tests for the retry schedule.

A 429 is not a transient error — it clears only once we stop asking — so it needs
a longer wait than a 5xx. The plain 2**attempt schedule slept 1s then 2s, inside
the window it was waiting out, and GDELT answered 429 on all three attempts of
every run for days as a result.
"""

import httpx
import pytest

from config import THROTTLE_BACKOFF_BASE, THROTTLE_BACKOFF_CAP
from fetch import _retry_delay


def _error(status: int, retry_after: str | None = None) -> httpx.HTTPStatusError:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    request = httpx.Request("GET", "https://example.test/feed")
    response = httpx.Response(status, headers=headers, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


class TestRetryDelay:
    def test_a_server_error_keeps_the_short_schedule(self):
        assert _retry_delay(_error(503), 0) == 1.0
        assert _retry_delay(_error(503), 1) == 2.0

    def test_a_throttle_waits_longer_than_the_window_it_tripped(self):
        assert _retry_delay(_error(429), 0) == THROTTLE_BACKOFF_BASE
        assert _retry_delay(_error(429), 1) == THROTTLE_BACKOFF_BASE * 2

    def test_the_server_can_ask_for_longer(self):
        assert _retry_delay(_error(429, "20"), 0) == 20.0

    def test_the_server_cannot_ask_for_shorter(self):
        # Honouring a small Retry-After would put us back inside the window.
        assert _retry_delay(_error(429, "1"), 0) == THROTTLE_BACKOFF_BASE

    def test_an_http_date_falls_back_to_our_own_backoff(self):
        assert _retry_delay(_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 0) == (
            THROTTLE_BACKOFF_BASE
        )

    def test_the_wait_is_capped(self):
        assert _retry_delay(_error(429, "86400"), 0) == THROTTLE_BACKOFF_CAP
        assert _retry_delay(_error(429), 9) == THROTTLE_BACKOFF_CAP

    def test_a_transport_error_carries_no_response(self):
        # httpx.ConnectError has no .response; the schedule must still work.
        assert _retry_delay(httpx.ConnectError("no route"), 0) == 1.0


class TestCandidateFeeds:
    """The candidate list must stay a probe-only list.

    Its whole purpose is that nothing in it is fetched on a scheduled run until
    someone has seen it answer. A URL that leaked into NEWS_FEEDS by a copy-paste
    would spend a request per run failing, which is what the four dropped feeds
    and the four FCC paths already cost.
    """

    def test_candidates_are_not_collected(self):
        from config import CANDIDATE_NEWS_FEEDS, NEWS_FEEDS

        adopted = {feed.url for feed in NEWS_FEEDS}
        assert not adopted & {feed.url for feed in CANDIDATE_NEWS_FEEDS}

    def test_candidate_names_are_distinct(self):
        from config import CANDIDATE_NEWS_FEEDS, NEWS_FEEDS

        names = [feed.name for feed in (*NEWS_FEEDS, *CANDIDATE_NEWS_FEEDS)]
        assert len(names) == len(set(names))

    @pytest.mark.parametrize("attr", ["name", "url"])
    def test_every_candidate_is_filled_in(self, attr):
        from config import CANDIDATE_NEWS_FEEDS

        assert all(getattr(feed, attr).strip() for feed in CANDIDATE_NEWS_FEEDS)
