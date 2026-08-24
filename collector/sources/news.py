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
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

from config import CANDIDATE_NEWS_FEEDS, GDELT_DOC_API, GDELT_QUERY, NEWS_FEEDS
from fetch import SourceError, get_json, get_text
from schemas import HAMILTON, MARSHALL, Attribution
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
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
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
                when = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
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
        key=lambda i: i.published_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:MAX_ITEMS]

    if not items:
        warnings.append("no matching news items found across any feed")

    return NewsResult(items=items, attribution=attribution, warnings=warnings)


def _reject_reason(title: str, summary: str = "") -> str | None:
    """Why is_relevant turned a story down, or None if it kept it.

    is_relevant answers yes/no, which is all the collector needs but not enough to
    tell a dead feed from an over-strict filter. This mirrors its branches so the
    probe can say which test a headline failed.
    """
    if is_relevant(title, summary):
        return None
    text = f"{title} {summary}".lower()
    named = mentions(text)
    if not named:
        return "no candidate named"
    who = ", ".join(named)
    if any(term in text for term in STRONG_TERMS):
        return f"full name ({who}) but no race context word"
    return f"bare surname ({who}) and the office is not named"


def _probe_feed(feed, lines: list[str]) -> None:
    """Report one feed: did it answer, what did it carry, what did we keep."""
    import feedparser

    lines.append(f"\n[{feed.name}]{' (paywalled)' if feed.paywalled else ''}")
    lines.append(f"  {feed.url}")
    try:
        body = get_text(feed.url)
    except SourceError as exc:
        lines.append(f"  FAILED: {exc}")
        return

    parsed = feedparser.parse(body)
    lines.append(f"  {len(body):,} bytes, {len(parsed.entries)} entries, bozo={parsed.bozo}")
    if parsed.bozo and getattr(parsed, "bozo_exception", None):
        lines.append(f"  bozo_exception: {parsed.bozo_exception}")
    if not parsed.entries:
        lines.append(f"  first 300 chars: {body.strip()[:300]!r}")
        return

    stamps = [t for t in (_parse_feed_time(e) for e in parsed.entries) if t]
    if stamps:
        lines.append(
            f"  newest entry: {max(stamps).isoformat()}   oldest: {min(stamps).isoformat()}"
        )
    else:
        lines.append("  no parseable dates on any entry")

    kept: list[str] = []
    near: list[str] = []
    far = 0
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")[:400]
        reason = _reject_reason(title, summary)
        if reason is None:
            kept.append(title)
        elif reason == "no candidate named":
            far += 1
        else:
            near.append(f"{title}  <-- {reason}")

    lines.append(f"  kept: {len(kept)}   near-miss: {len(near)}   no candidate at all: {far}")
    for title in kept[:5]:
        lines.append(f"    KEEP  {title[:110]}")
    # The near misses are the diagnostic ones: race coverage our own filter
    # dropped. Anything listed here is a candidate rule change.
    for note in near[:8]:
        lines.append(f"    DROP  {note[:150]}")
    if not kept and not near:
        lines.append("    (this feed carries no coverage naming either candidate)")
        for entry in parsed.entries[:5]:
            lines.append(f"    ----  {(entry.get('title') or '')[:110]}")


def diagnose() -> str:
    """Report what each news feed serves and what the relevance filter does to it.

    The 2026-08-24 run settled the first question this was built for: all four
    adopted feeds answered, none was stale, and across 180 entries there were zero
    near misses — not one headline named a candidate and got dropped. The filter is
    not the problem; the feeds are. Three of the four carry no politics at all and
    GDELT has never returned anything but 429.

    So the probe now also tests CANDIDATE_NEWS_FEEDS: feeds we do not collect,
    reported the same way, so a replacement is adopted on evidence that it answers
    and carries this race rather than on a guess about its URL.
    """
    lines = ["News probe", "=" * 72]
    lines.append("\nfilter: sources/news.py:is_relevant")

    lines.append("\n\nADOPTED — collected on every run")
    lines.append("-" * 72)
    for feed in NEWS_FEEDS:
        _probe_feed(feed, lines)

    lines.append("\n[GDELT]")
    lines.append(f"  {GDELT_DOC_API}")
    lines.append(f"  query: {GDELT_QUERY}")
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
        lines.append(f"  FAILED: {exc}")
        lines.append("  (429 here means rate-limited, not broken — GDELT throttles by IP)")
        payload = None

    if payload is not None:
        articles = payload.get("articles") or []
        lines.append(f"  {len(articles)} articles, other keys: {sorted(payload)}")
        kept_g: list[str] = []
        dropped_g: list[str] = []
        for article in articles:
            title = (article.get("title") or "").strip()
            if not title:
                continue
            reason = _reject_reason(title)
            (kept_g if reason is None else dropped_g).append(
                title if reason is None else f"{title}  <-- {reason}"
            )
        lines.append(f"  kept: {len(kept_g)}   dropped: {len(dropped_g)}")
        for title in kept_g[:5]:
            lines.append(f"    KEEP  {title[:110]}")
        for note in dropped_g[:5]:
            lines.append(f"    DROP  {note[:150]}")

    lines.append("\n\nCANDIDATES — not collected, tested here only")
    lines.append("-" * 72)
    lines.append("Adopt one by moving it into config.NEWS_FEEDS. A feed worth adopting")
    lines.append("answers, is more than a few days deep, and shows a non-zero kept count.")
    for feed in CANDIDATE_NEWS_FEEDS:
        _probe_feed(feed, lines)

    return "\n".join(lines)
