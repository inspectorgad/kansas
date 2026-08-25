"""The HTTP layer: polite, retrying, and replayable from fixtures.

Two design points matter here.

First, politeness: one shared client, a descriptive User-Agent, bounded retries
with backoff, and a per-host delay. We are a guest on other people's servers,
several of them small newsrooms and county election offices.

Second, replayability: with KS_FIXTURES set, every request is served from
collector/tests/fixtures instead of the network. That is how the parsers are
tested in environments (including the one this was written in) that cannot reach
the live APIs at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    THROTTLE_BACKOFF_BASE,
    THROTTLE_BACKOFF_CAP,
    USER_AGENT,
)

FIXTURE_DIR = Path(__file__).parent / "tests" / "fixtures"
_MIN_HOST_INTERVAL = 0.5  # seconds between requests to the same host
_last_request_at: dict[str, float] = {}
_client: httpx.Client | None = None


class SourceError(RuntimeError):
    """A source could not be fetched or parsed.

    Raised rather than swallowed: a source that breaks must surface as a failed
    CI job, never as a silently stale number in the app.
    """


def fixture_mode() -> bool:
    return bool(os.environ.get("KS_FIXTURES"))


def fixture_name(url: str, params: dict[str, Any] | None = None) -> str:
    """Stable filename for a request, so recorded fixtures are reproducible."""
    key = url
    if params:
        key += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hashlib.sha1(key.encode()).hexdigest()[:10]
    host = httpx.URL(url).host.replace(".", "_")
    return f"{host}-{digest}"


def _client_or_create() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        )
    return _client


def _throttle(url: str) -> None:
    host = httpx.URL(url).host
    elapsed = time.monotonic() - _last_request_at.get(host, 0.0)
    if elapsed < _MIN_HOST_INTERVAL:
        time.sleep(_MIN_HOST_INTERVAL - elapsed)
    _last_request_at[host] = time.monotonic()


def _retry_delay(error: Exception, attempt: int) -> float:
    """How long to wait before retrying, in seconds.

    Throttling is a different failure from a transient server error and needs a
    different wait: a 5xx clears on its own, while a 429 clears only once we stop
    asking. See config.THROTTLE_BACKOFF_BASE for what the plain schedule got wrong.
    """
    response = getattr(error, "response", None)
    if response is None:
        return float(2**attempt)

    asked = 0.0
    try:
        # Retry-After may also be an HTTP date, which we do not honour: a
        # server that wants us back at a wall-clock time gets our own backoff
        # instead, which is never shorter than the base.
        asked = float(response.headers.get("Retry-After", ""))
    except ValueError:
        asked = 0.0

    # A server that asks for longer gets it whatever the status; only a 429 also
    # raises our own floor, because only a 429 says the wait itself is the point.
    floor = THROTTLE_BACKOFF_BASE if response.status_code == 429 else 1.0
    return min(max(asked, floor * 2**attempt), THROTTLE_BACKOFF_CAP)


def get_text(url: str, params: dict[str, Any] | None = None) -> str:
    """GET a URL and return its body, or replay a recorded fixture."""
    if fixture_mode():
        for suffix in (".json", ".xml", ".html", ".txt"):
            path = FIXTURE_DIR / f"{fixture_name(url, params)}{suffix}"
            if path.exists():
                return path.read_text()
        raise SourceError(
            f"no fixture for {url} (expected {fixture_name(url, params)}.*). "
            "Record one with `python -m collector.record <url>`."
        )

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            _throttle(url)
            response = _client_or_create().get(url, params=params)
            # 429 and 5xx are worth retrying; 4xx generally is not.
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(_retry_delay(exc, attempt))
    raise SourceError(f"GET {url} failed after {MAX_RETRIES} attempts: {last_error}")


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    body = get_text(url, params)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SourceError(f"GET {url} returned non-JSON: {exc}") from exc


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
