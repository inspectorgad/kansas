"""Headlines from Kansas outlets plus a wider GDELT sweep.

We store the title, the outlet, the link and the timestamp — nothing more. Some
of these outlets are paywalled and all of them pay reporters, so the app sends
readers to the publisher's own page rather than reproducing their work.

Relevance filtering is stricter than a name match: "Marshall" and "Hamilton" are
both common words (and both Kansas place names), so a headline must pair a
candidate with race context, or name both candidates, to be kept.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from config import GDELT_DOC_API, GDELT_QUERY, NEWS_FEEDS
from fetch import SourceError, get_json, get_text
from schemas import Attribution, HAMILTON, MARSHALL
from schemas.news import NewsItem

MAX_ITEMS = 120

# A candidate surname alone is not enough: Marshall County and Hamilton County
# are both in Kansas, and "marshall" is an ordinary noun.
RACE_CONTEXT = (
    "senate", "senator", "sen.", "campaign", "election", "ballot", "poll",
    "candidate", "primary", "race", "democrat", "republican", "gop",
)
CANDIDATE_TERMS = {
    MARSHALL: ("roger marshall", "sen. marshall", "senator marshall", "marshall"),
    HAMILTON: ("adam hamilton", "hamilton"),
}
STRONG_TERMS = ("roger marshall", "adam hamilton", "sen. marshall", "senator marshall")


@dataclass
class NewsResult:
    items: list[NewsItem] = field(default_factory=list)
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def canonical_url(url: str) -> str:
    """Drop tracking parameters and fragments so the same story dedups."""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    return urlunparse((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "", ""))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:12]


def mentions(text: str) -> list[str]:
    lowered = (text or "").lower()
    found = [cid for cid, terms in CANDIDATE_TERMS.items() if any(t in lowered for t in terms)]
    return sorted(found)


def is_relevant(title: str, summary: str = "") -> bool:
    """Keep a story only if it is plausibly about this race."""
    text = f"{title} {summary}".lower()
    named = mentions(text)
    if not named:
        return False
    # Both candidates named together is unambiguous.
    if len(named) == 2:
        return True
    # A full name plus any race context.
    if any(term in text for term in STRONG_TERMS) and any(c in text for c in RACE_CONTEXT):
        return True
    # A bare surname needs the office named explicitly.
    return "senate" in text or "senator" in text


def _parse_feed_time(entry) -> datetime | None:
    import calendar

    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None) or entry.get(key)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def from_feeds(warnings: list[str]) -> tuple[list[NewsItem], list[Attribution]]:
    import feedparser

    items: dict[str, NewsItem] = {}
    attribution: list[Attribution] = []

    for feed in NEWS_FEEDS:
        try:
            body = get_text(feed.url)
        except SourceError as exc:
            warnings.append(f"{feed.name} feed unavailable: {exc}")
            continue

        parsed = feedparser.parse(body)
        if parsed.bozo and not parsed.entries:
            warnings.append(f"{feed.name} feed did not parse")
            continue

        matched = 0
        for entry in parsed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")[:400]
            if not is_relevant(title, summary):
                continue
            identifier = item_id(link)
            items[identifier] = NewsItem(
                id=identifier,
                title=title,
                source=feed.name,
                url=canonical_url(link),
                published_at=_parse_feed_time(entry),
                # Paywalled outlets get headline-only treatment.
                summary=None if feed.paywalled else (summary.strip() or None),
                mentions=mentions(f"{title} {summary}"),
            )
            matched += 1

        if matched:
            attribution.append(
                Attribution(
                    name=feed.name,
                    url=feed.url,
                    note="Headline and link only." if feed.paywalled else None,
                )
            )

    return list(items.values()), attribution


def from_gdelt(warnings: list[str]) -> list[NewsItem]:
    """A wider sweep than the local feeds, for coverage they miss."""
    try:
        payload = get_json(
            GDELT_DOC_API,
            {
                "query": GDELT_QUERY,
                "mode": "artlist",
                "format": "json",
                "maxrecords": 75,
                "sort": "datedesc",
            },
        )
    except SourceError as exc:
        warnings.append(f"GDELT unavailable: {exc}")
        return []

    items: dict[str, NewsItem] = {}
    for article in payload.get("articles", []):
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        if not title or not url or not is_relevant(title):
            continue
        when = None
        stamp = article.get("seendate")
        if stamp:
            try:
                when = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                when = None
        identifier = item_id(url)
        items[identifier] = NewsItem(
            id=identifier,
            title=title,
            source=article.get("domain") or "GDELT",
            url=canonical_url(url),
            published_at=when,
            mentions=mentions(title),
        )
    return list(items.values())


def collect() -> NewsResult:
    warnings: list[str] = []
    feed_items, attribution = from_feeds(warnings)
    gdelt_items = from_gdelt(warnings)

    # Named outlets win over GDELT's domain-only attribution for the same story.
    merged: dict[str, NewsItem] = {item.id: item for item in gdelt_items}
    merged.update({item.id: item for item in feed_items})

    if gdelt_items:
        attribution.append(
            Attribution(
                name="GDELT Project",
                url="https://www.gdeltproject.org/",
                note="Global news index, used to catch coverage the local feeds miss.",
            )
        )

    items = sorted(
        merged.values(),
        key=lambda i: i.published_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:MAX_ITEMS]

    if not items:
        warnings.append("no matching news items found across any feed")

    return NewsResult(items=items, attribution=attribution, warnings=warnings)
