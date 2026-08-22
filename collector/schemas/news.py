"""news.json — headlines only.

We store title, source, link and timestamp. We do not copy article bodies from
paywalled outlets; the app opens the publisher's own page.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Attribution, Payload, Strict


class NewsItem(Strict):
    id: str = Field(description="Hash of the canonical URL, for dedup.")
    title: str
    source: str
    url: str
    published_at: datetime | None = None
    summary: str | None = Field(
        default=None, description="Only when the feed itself supplies one."
    )
    mentions: list[str] = Field(
        default_factory=list, description="Candidate ids detected in the headline."
    )


class NewsPayload(Payload):
    items: list[NewsItem]
    attribution: list[Attribution] = []
