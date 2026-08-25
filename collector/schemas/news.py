"""news.json — headlines only.

We store title, source, link and timestamp. We do not copy article bodies from
paywalled outlets; the app opens the publisher's own page.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import Attribution, Payload, Strict


class SourceKind(StrEnum):
    """Where an item came from, which is not the same as what it is about.

    A press release from the incumbent's Senate office is genuinely about this
    race and belongs in the feed, but it is the officeholder's own words rather
    than reporting, and the challenger has no equivalent — he holds no office. The
    app says which is which rather than letting the two sit indistinguishably in
    one list.
    """

    NEWS = "news"
    OFFICIAL = "official"


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
    kind: SourceKind = Field(
        default=SourceKind.NEWS,
        description="Whether this is reporting or an official government release.",
    )


class NewsPayload(Payload):
    items: list[NewsItem]
    attribution: list[Attribution] = []
