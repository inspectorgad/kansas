"""Race ratings from the three main handicappers.

Low volume — these move a handful of times a cycle — but a rating change is one
of the more newsworthy events in a race, so it is worth watching. Each source is
a small scrape of a single page; any that fails is skipped rather than fatal,
because a missing rating is a cosmetic gap while a failed run is not.
"""

from __future__ import annotations

import re

from config import RATING_SOURCES
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


def parse_rating(html: str) -> tuple[str, Party | None] | None:
    """Find the first rating phrase in a page, normalised for display."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    match = RATING_PATTERN.search(text)
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
