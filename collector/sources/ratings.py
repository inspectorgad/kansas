"""Race ratings from the three main handicappers.

Low volume — these move a handful of times a cycle — but a rating change is one
of the more newsworthy events in a race, so it is worth watching. Each source is
a small scrape of a single page; any that fails is skipped rather than fatal,
because a missing rating is a cosmetic gap while a failed run is not.
"""

from __future__ import annotations

import re

from config import RATING_SOURCES, RATINGS_ENABLED
from fetch import SourceError, get_text
from schemas import Party, Rating

# Ratings vocabulary shared across all three handicappers.
RATING_PATTERN = re.compile(
    r"\b(Solid|Safe|Likely|Lean|Leans|Tilt|Tilts)\s+(Republican|Democratic|Democrat|R|D)\b"
    r"|\b(Toss[\s-]?up|Tossup)\b",
    re.IGNORECASE,
)

LEANS = {"r": Party.REPUBLICAN, "republican": Party.REPUBLICAN,
         "d": Party.DEMOCRAT, "democratic": Party.DEMOCRAT, "democrat": Party.DEMOCRAT}


# How far from the word "Kansas" a rating phrase may sit and still be this
# race's. Wide enough to cross a table row or a card, narrow enough that the next
# state's rating is out of reach.
KANSAS_WINDOW = 220
STATE = re.compile(r"(?:^|[^a-z])kansas(?:[^a-z]|$)", re.IGNORECASE)


def _plain_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def parse_rating(html: str) -> tuple[str, Party | None] | None:
    """Find this race's rating phrase, normalised for display.

    Scoped to the neighbourhood of the word "Kansas". These handicappers publish
    one page listing every Senate race, and the previous version took the first
    rating phrase anywhere on it — which is whichever contest happens to appear
    first, typically Alabama or Alaska. That would have published another state's
    rating as this race's, the same failure as reading Arkansas as Kansas, and it
    would have looked entirely plausible on screen.

    A page that never says Kansas yields nothing rather than its first rating,
    and so does a page that says Kansas with no rating near it. Both are better
    than a confident wrong label on the one field whose whole purpose is to be
    quoted.
    """
    text = _plain_text(html)

    # The nearest rating phrase to a Kansas mention, not the first one in the
    # window. Searching the window from its start reads backwards into the row
    # above: on a table ordered Alabama, Alaska, Arkansas, Georgia, Kansas, the
    # first phrase within reach of "Kansas" is Georgia's. Distance is what makes
    # "Kansas | Toss-up" resolve to Toss-up, and a forward phrase wins a tie
    # because that is the order these tables put them in.
    best: re.Match[str] | None = None
    best_distance = KANSAS_WINDOW + 1
    for hit in STATE.finditer(text):
        window_start = max(0, hit.start() - KANSAS_WINDOW)
        window_end = hit.end() + KANSAS_WINDOW
        for candidate in RATING_PATTERN.finditer(text, window_start, window_end):
            if candidate.start() >= hit.end():
                distance = candidate.start() - hit.end()
            else:
                # Behind the state name, so measure from the phrase's end and
                # break ties against it.
                distance = hit.start() - candidate.end() + 1
            if distance < best_distance:
                best, best_distance = candidate, distance
    match = best
    if not match:
        return None
    if match.group(3):
        return "Toss-up", None
    qualifier = match.group(1).title().rstrip("s") if match.group(1) else ""
    party_text = (match.group(2) or "").lower()
    party = LEANS.get(party_text)
    label = f"{qualifier} {party_text.title()}".strip()
    return label, party


def collect() -> list[Rating]:
    """Ratings, or nothing while every handicapper refuses the request.

    See config.RATINGS_ENABLED. The caller reports the reason rather than showing
    an empty list as though the handicappers had no view.
    """
    if not RATINGS_ENABLED:
        return []

    ratings: list[Rating] = []
    for source, url in RATING_SOURCES.items():
        try:
            html = get_text(url)
        except SourceError:
            continue  # a handicapper's page being down is not worth failing over
        parsed = parse_rating(html)
        if parsed:
            label, party = parsed
            ratings.append(Rating(source=source, rating=label, lean=party, url=url))
    return ratings


def diagnose() -> str:
    """Report what each handicapper's page actually serves.

    ratings has published as an empty list on every run since the collector
    started, with only "no race ratings parsed" to show for it. That covers a page
    that blocks scrapers, a page whose wording this pattern does not match, and a
    page that no longer mentions Kansas at all — three different problems needing
    three different responses.
    """
    lines = ["Race ratings probe", "=" * 72]

    for source, url in RATING_SOURCES.items():
        lines.append(f"\n[{source}]")
        lines.append(f"  {url}")
        try:
            html = get_text(url)
        except SourceError as exc:
            lines.append(f"  FAILED: {exc}")
            continue

        text = _plain_text(html)
        lines.append(f"  {len(html):,} bytes of html, {len(text):,} of text")

        hits = list(STATE.finditer(text))
        lines.append(f"  mentions Kansas: {len(hits)}")
        if not hits:
            # Most likely a client-rendered page, so the ratings live in a script
            # payload rather than the markup.
            lines.append("  (nothing to scope a rating to — is the page JavaScript-rendered?)")
            sample = text.strip()[:300]
            lines.append(f"  first 300 chars: {sample!r}")
            continue

        for hit in hits[:3]:
            start = max(0, hit.start() - KANSAS_WINDOW)
            window = text[start : hit.end() + KANSAS_WINDOW]
            found = RATING_PATTERN.search(window)
            lines.append(f"  window: ...{window.strip()[:200]}...")
            lines.append(f"    rating phrase in window: {found.group(0) if found else 'NONE'}")

        anywhere = [m.group(0) for m in RATING_PATTERN.finditer(text)][:6]
        lines.append(f"  rating phrases anywhere on the page: {anywhere}")
        parsed = parse_rating(html)
        lines.append(f"  parse_rating returns: {parsed}")

    return "\n".join(lines)
