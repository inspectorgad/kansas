"""Primitives for reading Wikipedia's polling tables.

Wikipedia is the most complete free structured source of state-level polling —
there is no free polling API — but it is prose-adjacent markup written by hand,
so every value needs defensive parsing. Anything unparseable is skipped and
reported rather than guessed at.
"""

from __future__ import annotations

import re
from datetime import date

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

DASHES = "–—−-"  # en dash, em dash, minus, hyphen

_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL | re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_EXT_LINK = re.compile(r"\[https?://\S+?\s+([^\]]+)\]")
_BARE_LINK = re.compile(r"\[https?://\S+?\]")
_WIKI_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def clean(cell: str) -> str:
    """Strip wiki markup, refs, templates and tags down to readable text."""
    text = _COMMENT.sub(" ", cell)
    text = _REF.sub(" ", text)
    for _ in range(3):  # templates nest a couple of levels deep in practice
        text = _TEMPLATE.sub(" ", text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _BARE_LINK.sub(" ", text)
    text = _WIKI_LINK.sub(r"\1", text)
    text = text.replace("<br />", " ").replace("<br/>", " ").replace("<br>", " ")
    text = _TAG.sub(" ", text)
    text = text.replace("'''", "").replace("''", "")
    text = text.replace("&nbsp;", " ").replace("&ndash;", "–").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def strip_cell_attributes(cell: str) -> str:
    """Drop table-cell styling, e.g. `style="background:#f00" | 46%` -> `46%`."""
    if "|" not in cell:
        return cell
    head, _, tail = cell.partition("|")
    # An attribute head contains an = but no wiki link syntax.
    if "=" in head and "[" not in head and "{" not in head:
        return tail
    return cell


def iter_tables(wikitext: str) -> list[str]:
    """Return the body of each top-level wikitable, outermost only."""
    tables, depth, start = [], 0, None
    i = 0
    while i < len(wikitext) - 1:
        pair = wikitext[i : i + 2]
        if pair == "{|":
            if depth == 0:
                start = i
            depth += 1
            i += 2
            continue
        if pair == "|}":
            depth -= 1
            if depth == 0 and start is not None:
                tables.append(wikitext[start : i + 2])
                start = None
            i += 2
            continue
        i += 1
    return tables


def split_rows(table: str) -> list[list[str]]:
    """Split a wikitable into rows of raw cell strings."""
    rows: list[list[str]] = []
    for chunk in re.split(r"\n\|-+", table)[1:]:
        chunk = chunk.split("\n|}")[0]
        cells: list[str] = []
        for line in chunk.split("\n"):
            line = line.strip()
            if not line or line.startswith("|+"):
                continue
            if line.startswith("!"):
                parts = re.split(r"!!", line.lstrip("!"))
            elif line.startswith("|"):
                parts = re.split(r"\|\|", line.lstrip("|"))
            else:
                # A continuation line belongs to the previous cell.
                if cells:
                    cells[-1] += " " + line
                continue
            cells.extend(strip_cell_attributes(p) for p in parts)
        if cells:
            rows.append(cells)
    return rows


def header_row(table: str) -> list[str] | None:
    """The first row that looks like a header (`!` cells)."""
    for chunk in table.split("\n"):
        if chunk.strip().startswith("!"):
            parts = re.split(r"!!", chunk.strip().lstrip("!"))
            return [clean(strip_cell_attributes(p)) for p in parts]
    return None


def parse_percent(cell: str) -> float | None:
    """`'''46%'''` -> 46.0. Returns None for dashes, blanks and non-numbers."""
    text = clean(cell)
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    # Some tables omit the % sign entirely.
    match = re.fullmatch(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def parse_sample(cell: str) -> tuple[int | None, str | None]:
    """`1,024 (LV)` -> (1024, 'LV')."""
    text = clean(cell)
    size = None
    match = re.search(r"(\d[\d,]*)", text)
    if match:
        try:
            size = int(match.group(1).replace(",", ""))
        except ValueError:
            size = None
    population = None
    pop_match = re.search(r"\b(LV|RV|V|A)\b", text, re.IGNORECASE)
    if pop_match:
        population = pop_match.group(1).upper()
    return size, population


def parse_margin_of_error(cell: str) -> float | None:
    text = clean(cell)
    match = re.search(r"(\d+(?:\.\d+)?)\s*%?", text.replace("±", " "))
    if not match:
        return None
    value = float(match.group(1))
    # A "margin of error" above 25 is a parse artefact, not a real MoE.
    return value if 0 < value <= 25 else None


def parse_date_range(cell: str, default_year: int) -> tuple[date, date] | None:
    """Parse the many shapes of Wikipedia's date column.

    Handles `August 8, 2026`, `August 6-8, 2026`, `July 28 - August 2, 2026`,
    and `December 30, 2025 - January 3, 2026`.
    """
    text = clean(cell)
    if not text:
        return None
    text = re.sub(f"[{DASHES}]", "-", text)

    # Full date on both sides of the dash.
    both = re.search(
        r"([A-Za-z]+)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?\s*-\s*([A-Za-z]+)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?",
        text,
    )
    if both:
        m1, d1, y1, m2, d2, y2 = both.groups()
        month1, month2 = MONTHS.get(m1.lower()), MONTHS.get(m2.lower())
        if month1 and month2:
            year2 = int(y2) if y2 else default_year
            # An unstated start year rolls back when the range crosses New Year.
            year1 = int(y1) if y1 else (year2 - 1 if month1 > month2 else year2)
            try:
                return date(year1, month1, int(d1)), date(year2, month2, int(d2))
            except ValueError:
                return None

    # Single month, day range: `August 6-8, 2026`.
    same_month = re.search(
        r"([A-Za-z]+)\.?\s+(\d{1,2})\s*-\s*(\d{1,2})(?:,\s*(\d{4}))?", text
    )
    if same_month:
        name, d1, d2, year = same_month.groups()
        month = MONTHS.get(name.lower())
        if month:
            try:
                y = int(year) if year else default_year
                return date(y, month, int(d1)), date(y, month, int(d2))
            except ValueError:
                return None

    # Single date.
    single = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:,\s*(\d{4}))?", text)
    if single:
        name, day, year = single.groups()
        month = MONTHS.get(name.lower())
        if month:
            try:
                d = date(int(year) if year else default_year, month, int(day))
                return d, d
            except ValueError:
                return None
    return None
