"""Polls, read from the Wikipedia race article.

There is no free polling API, so this parses the article's polling tables. The
tables are hand-maintained markup, so the parser is deliberately conservative:
it locates candidate columns by matching surnames in the header rather than by
position, and it drops any row it cannot fully understand instead of guessing.
Rows dropped are reported back to the runner so a structural change upstream
shows up as a CI warning rather than a quietly shrinking poll list.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from config import PARTISAN_POLLSTERS, WIKIPEDIA_API, WIKIPEDIA_ARTICLE
from fetch import SourceError, get_json
from schemas import Attribution, Party
from schemas.common import CandidatePair
from schemas.polls import Poll

# Header keywords that identify each column, checked against the cleaned header.
POLLSTER_KEYS = ("poll source", "pollster", "poll", "source")
DATE_KEYS = ("date", "administered", "field")
SAMPLE_KEYS = ("sample", "size")
MOE_KEYS = ("margin of error", "moe", "error")
OTHER_KEYS = ("other", "someone else")
UNDECIDED_KEYS = ("undecided", "unsure", "no opinion", "don't know")

ATTRIBUTION = Attribution(
    name=f"Wikipedia — {WIKIPEDIA_ARTICLE}",
    url="https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Kansas",
    license="CC BY-SA 4.0",
    note="Poll table maintained by Wikipedia contributors; parsed, not modified.",
)


@dataclass
class PollsResult:
    polls: list[Poll]
    skipped: list[str] = field(default_factory=list)
    attribution: list[Attribution] = field(default_factory=lambda: [ATTRIBUTION])


def poll_id(pollster: str, start: date, end: date) -> str:
    key = f"{pollster.strip().lower()}|{start.isoformat()}|{end.isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def fetch_wikitext(article: str = WIKIPEDIA_ARTICLE) -> str:
    """Fetch an article's raw wikitext via the MediaWiki API."""
    payload = get_json(
        WIKIPEDIA_API,
        {
            "action": "query",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": article,
            "format": "json",
            "formatversion": "2",
        },
    )
    try:
        pages = payload["query"]["pages"]
        if not pages or pages[0].get("missing"):
            raise SourceError(f"Wikipedia article not found: {article}")
        return pages[0]["revisions"][0]["slots"]["main"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError(f"unexpected Wikipedia API shape: {exc}") from exc


def _find_column(header: list[str], keys: tuple[str, ...]) -> int | None:
    """Index of the first header cell containing any key, longest key first."""
    lowered = [h.lower() for h in header]
    for key in sorted(keys, key=len, reverse=True):
        for index, cell in enumerate(lowered):
            if key in cell:
                return index
    return None


def _find_candidate_column(header: list[str], surname: str) -> int | None:
    lowered = [h.lower() for h in header]
    for index, cell in enumerate(lowered):
        if surname in cell:
            return index
    return None


def _detect_partisan(pollster: str, sponsor: str | None) -> Party | None:
    lean = PARTISAN_POLLSTERS.get(pollster.strip().lower())
    if lean:
        return Party(lean)
    if sponsor:
        text = sponsor.lower()
        if "marshall" in text:
            return Party.REPUBLICAN
        if "hamilton" in text:
            return Party.DEMOCRAT
    return None


def _split_sponsor(pollster_cell: str) -> tuple[str, str | None]:
    """`Pollster (for Hamilton campaign)` -> ('Pollster', 'for Hamilton campaign')."""
    text = pollster_cell.strip()
    if text.endswith(")") and "(" in text:
        head, _, tail = text.rpartition("(")
        return head.strip(), tail[:-1].strip()
    return text, None


def parse_polls(wikitext: str, default_year: int = 2026) -> PollsResult:
    """Extract every general-election poll of this race from the article."""
    from .wikitext import (
        clean,
        header_row,
        iter_tables,
        parse_date_range,
        parse_margin_of_error,
        parse_percent,
        parse_sample,
        split_rows,
    )

    polls: dict[str, Poll] = {}
    skipped: list[str] = []
    tables_matched = 0

    for table in iter_tables(wikitext):
        header = header_row(table)
        if not header:
            continue
        marshall_col = _find_candidate_column(header, "marshall")
        hamilton_col = _find_candidate_column(header, "hamilton")
        if marshall_col is None or hamilton_col is None:
            continue  # not a head-to-head table for this race
        tables_matched += 1

        pollster_col = _find_column(header, POLLSTER_KEYS) or 0
        date_col = _find_column(header, DATE_KEYS)
        sample_col = _find_column(header, SAMPLE_KEYS)
        moe_col = _find_column(header, MOE_KEYS)
        other_col = _find_column(header, OTHER_KEYS)
        undecided_col = _find_column(header, UNDECIDED_KEYS)

        width = len(header)
        for row in split_rows(table):
            if len(row) < width - 1:
                continue  # header repeat, section divider, or a merged-cell note

            def cell(index: int | None, row: list[str] = row) -> str:
                """Read one cell, tolerating a short row or an absent column."""
                if index is None or index >= len(row):
                    return ""
                return row[index]

            pollster_text = clean(cell(pollster_col))
            if not pollster_text:
                continue
            pollster, sponsor = _split_sponsor(pollster_text)

            dates = parse_date_range(cell(date_col), default_year) if date_col is not None else None
            if dates is None:
                skipped.append(f"{pollster}: unparseable date {clean(cell(date_col))!r}")
                continue
            start, end = dates

            marshall = parse_percent(cell(marshall_col))
            hamilton = parse_percent(cell(hamilton_col))
            if marshall is None or hamilton is None:
                skipped.append(f"{pollster} ({end}): missing a candidate number")
                continue

            sample, population = parse_sample(cell(sample_col)) if sample_col is not None else (None, None)

            identifier = poll_id(pollster, start, end)
            polls[identifier] = Poll(
                id=identifier,
                pollster=pollster,
                sponsor=sponsor,
                partisan=_detect_partisan(pollster, sponsor),
                start_date=start,
                end_date=end,
                sample_size=sample,
                population=population,
                margin_of_error=parse_margin_of_error(cell(moe_col)) if moe_col is not None else None,
                results=CandidatePair(marshall=marshall, hamilton=hamilton),
                other=parse_percent(cell(other_col)) if other_col is not None else None,
                undecided=parse_percent(cell(undecided_col)) if undecided_col is not None else None,
                added_at=datetime.now(UTC),
            )

    if tables_matched == 0:
        raise SourceError(
            "no Marshall-vs-Hamilton polling table found in the article — "
            "the page structure has probably changed"
        )

    ordered = sorted(polls.values(), key=lambda p: (p.end_date, p.pollster), reverse=True)
    return PollsResult(polls=ordered, skipped=skipped)


def collect() -> PollsResult:
    return parse_polls(fetch_wikitext())
