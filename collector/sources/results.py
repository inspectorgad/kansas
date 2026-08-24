"""Election-night returns from the Kansas Secretary of State.

This module is written against an endpoint nobody has been able to inspect yet:
`ent.sos.ks.gov` was unreachable from the environment this was built in, and it
only serves live data for a few hours on election night anyway. Guessing at one
parser and hoping would be the wrong bet on the one night the app matters most.

So instead of a single parser this is a **probe**: it tries the plausible shapes
in order of preference, reports precisely what it found, and fails loudly rather
than inventing numbers. `python collector/run.py --probe-results` runs it against
the archived August 2026 primary and prints a diagnosis, which is how the format
gets pinned down well before November 3.

The shapes it handles:

  1. A JSON feed — most modern ENR systems back their page with one.
  2. Embedded JSON inside the HTML (a `var results = {...}` bootstrap).
  3. An HTML table, matched by county name rather than column position.

If all three miss, `diagnose()` returns what was actually served so the gap can
be closed quickly, and AP's paid Elections API remains the documented fallback.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from config import KS_ENR_BASE, KS_ENR_FALLBACK
from fetch import SourceError, get_text
from schemas import HAMILTON, MARSHALL, Attribution
from schemas.results import CandidateResult, CountyResult, ResultsStatus

ATTRIBUTION = Attribution(
    name="Kansas Secretary of State — unofficial election night results",
    url="https://ent.sos.ks.gov/",
    note="Unofficial returns. Official canvass follows in the weeks after election day.",
)

# Candidate matching is by surname, because ENR pages label rows inconsistently
# ("MARSHALL, ROGER", "Roger Marshall (R)", "R. Marshall").
SURNAME_TO_ID = {"marshall": MARSHALL, "hamilton": HAMILTON}

# Every Kansas county, so a table row can be recognised as a county row without
# depending on the page's own markup or column order.
KANSAS_COUNTIES = (
    "Allen", "Anderson", "Atchison", "Barber", "Barton", "Bourbon", "Brown",
    "Butler", "Chase", "Chautauqua", "Cherokee", "Cheyenne", "Clark", "Clay",
    "Cloud", "Coffey", "Comanche", "Cowley", "Crawford", "Decatur", "Dickinson",
    "Doniphan", "Douglas", "Edwards", "Elk", "Ellis", "Ellsworth", "Finney",
    "Ford", "Franklin", "Geary", "Gove", "Graham", "Grant", "Gray", "Greeley",
    "Greenwood", "Hamilton", "Harper", "Harvey", "Haskell", "Hodgeman",
    "Jackson", "Jefferson", "Jewell", "Johnson", "Kearny", "Kingman", "Kiowa",
    "Labette", "Lane", "Leavenworth", "Lincoln", "Linn", "Logan", "Lyon",
    "Marion", "Marshall", "McPherson", "Meade", "Miami", "Mitchell",
    "Montgomery", "Morris", "Morton", "Nemaha", "Neosho", "Ness", "Norton",
    "Osage", "Osborne", "Ottawa", "Pawnee", "Phillips", "Pottawatomie",
    "Pratt", "Rawlins", "Reno", "Republic", "Rice", "Riley", "Rooks", "Rush",
    "Russell", "Saline", "Scott", "Sedgwick", "Seward", "Shawnee", "Sheridan",
    "Sherman", "Smith", "Stafford", "Stanton", "Stevens", "Sumner", "Thomas",
    "Trego", "Wabaunsee", "Wallace", "Washington", "Wichita", "Wilson",
    "Woodson", "Wyandotte",
)

# Kansas has a Hamilton County and a Marshall County. On a page that lists both
# counties and candidates, a bare surname match would attribute county rows to
# candidates. Any candidate match must therefore be corroborated.
AMBIGUOUS_NAMES = {"hamilton", "marshall"}

SENATE_CONTEST_TERMS = ("united states senator", "us senator", "u.s. senator", "senate")


@dataclass
class ResultsProbe:
    """What one attempt at reading the ENR page found."""

    shape: str
    ok: bool
    detail: str
    body_sample: str = ""


@dataclass
class ResultsData:
    status: ResultsStatus = ResultsStatus.PENDING
    statewide: list[CandidateResult] = field(default_factory=list)
    counties: list[CountyResult] = field(default_factory=list)
    total_votes: int = 0
    precincts_reporting: int | None = None
    precincts_total: int | None = None
    pct_reporting: float | None = None
    source_url: str | None = None
    probes: list[ResultsProbe] = field(default_factory=list)
    attribution: list[Attribution] = field(default_factory=lambda: [ATTRIBUTION])


def _to_int(value) -> int | None:
    if value is None:
        return None
    text = re.sub(r"[^\d-]", "", str(value))
    if not text or text == "-":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _candidate_id(label: str) -> str | None:
    """Map a candidate label to an id, refusing ambiguous bare county names."""
    lowered = label.lower()
    for surname, candidate_id in SURNAME_TO_ID.items():
        if surname not in lowered:
            continue
        if surname in AMBIGUOUS_NAMES:
            # Require corroboration: a first name, an honorific, or a party tag.
            corroborated = any(
                token in lowered
                for token in ("roger", "adam", "sen.", "senator", "(r)", "(d)", ", r", ", d")
            )
            if not corroborated:
                return None
        return candidate_id
    return None


# --- shape 1: a JSON feed -----------------------------------------------------

JSON_CANDIDATE_PATHS = (
    "/api/results/senate.json",
    "/results/senate.json",
    "/api/contests.json",
    "/data/results.json",
)


def _parse_json_results(payload: object) -> ResultsData | None:
    """Read a JSON structure of unknown shape by walking it for candidate rows.

    ENR vendors differ wildly in structure, so rather than assume a schema we
    search the tree for objects that look like a candidate result: something
    naming one of our two candidates alongside a vote count.
    """
    found: dict[str, int] = {}
    counties: dict[str, dict[str, int]] = {}

    def walk(node: object, county: str | None) -> None:
        if isinstance(node, dict):
            label = " ".join(
                str(node.get(key, ""))
                for key in ("name", "candidate", "candidate_name", "ballot_name", "title")
            )
            votes = None
            for key in ("votes", "vote_count", "total_votes", "count"):
                votes = _to_int(node.get(key))
                if votes is not None:
                    break
            candidate_id = _candidate_id(label) if label.strip() else None
            if candidate_id and votes is not None:
                if county:
                    counties.setdefault(county, {})[candidate_id] = votes
                else:
                    found[candidate_id] = found.get(candidate_id, 0) + votes

            # A node naming a county scopes everything beneath it.
            county_name = None
            for key in ("county", "county_name", "jurisdiction"):
                value = node.get(key)
                if isinstance(value, str) and value.strip().title() in KANSAS_COUNTIES:
                    county_name = value.strip().title()
                    break

            for value in node.values():
                walk(value, county_name or county)
        elif isinstance(node, list):
            for item in node:
                walk(item, county)

    walk(payload, None)
    if not found and not counties:
        return None

    data = ResultsData(status=ResultsStatus.LIVE)
    data.statewide = _statewide_from(found)
    data.total_votes = sum(found.values())
    data.counties = [
        CountyResult(
            county=name,
            marshall_votes=rows.get(MARSHALL, 0),
            hamilton_votes=rows.get(HAMILTON, 0),
            total_votes=sum(rows.values()),
        )
        for name, rows in sorted(counties.items())
    ]
    return data


def _statewide_from(votes: dict[str, int]) -> list[CandidateResult]:
    total = sum(votes.values())
    return [
        CandidateResult(
            candidate_id=candidate_id,
            votes=count,
            pct=round(count / total * 100, 2) if total else 0.0,
        )
        for candidate_id, count in sorted(votes.items())
    ]


# --- shape 2: JSON embedded in the page --------------------------------------

EMBEDDED_JSON = re.compile(
    r"(?:var|let|const)\s+\w+\s*=\s*(\{.*?\}|\[.*?\])\s*;", re.DOTALL
)


def _parse_embedded_json(html: str) -> ResultsData | None:
    for match in EMBEDDED_JSON.finditer(html):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        parsed = _parse_json_results(payload)
        if parsed:
            return parsed
    return None


# --- shape 3: an HTML table --------------------------------------------------

TAG = re.compile(r"<[^>]+>")
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)


def _cells(row_html: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", TAG.sub(" ", cell)).replace("&nbsp;", " ").strip()
        for cell in CELL.findall(row_html)
    ]


def _parse_html_table(html: str) -> ResultsData | None:
    """Read a county-by-county table, keyed on county names not column order."""
    counties: dict[str, dict[str, int]] = {}
    statewide: dict[str, int] = {}

    # Column order is discovered from whichever header row names both candidates.
    marshall_col = hamilton_col = None
    for row_html in ROW.findall(html):
        cells = _cells(row_html)
        lowered = [c.lower() for c in cells]
        m = next((i for i, c in enumerate(lowered) if _candidate_id(c) == MARSHALL), None)
        h = next((i for i, c in enumerate(lowered) if _candidate_id(c) == HAMILTON), None)
        if m is not None and h is not None:
            marshall_col, hamilton_col = m, h
            break

    for row_html in ROW.findall(html):
        cells = _cells(row_html)
        if not cells:
            continue
        first = cells[0].strip().title()

        if first in KANSAS_COUNTIES and marshall_col is not None and hamilton_col is not None:
            marshall = _to_int(cells[marshall_col]) if marshall_col < len(cells) else None
            hamilton = _to_int(cells[hamilton_col]) if hamilton_col < len(cells) else None
            if marshall is not None or hamilton is not None:
                counties[first] = {MARSHALL: marshall or 0, HAMILTON: hamilton or 0}
            continue

        # A two-column candidate/votes layout for the statewide total.
        if len(cells) >= 2:
            candidate_id = _candidate_id(cells[0])
            votes = _to_int(cells[1])
            if candidate_id and votes is not None and first not in KANSAS_COUNTIES:
                statewide[candidate_id] = votes

    if not counties and not statewide:
        return None

    if not statewide and counties:
        statewide = {
            MARSHALL: sum(rows.get(MARSHALL, 0) for rows in counties.values()),
            HAMILTON: sum(rows.get(HAMILTON, 0) for rows in counties.values()),
        }

    data = ResultsData(status=ResultsStatus.LIVE)
    data.statewide = _statewide_from(statewide)
    data.total_votes = sum(statewide.values())
    data.counties = [
        CountyResult(
            county=name,
            marshall_votes=rows.get(MARSHALL, 0),
            hamilton_votes=rows.get(HAMILTON, 0),
            total_votes=sum(rows.values()),
        )
        for name, rows in sorted(counties.items())
    ]
    return data


# --- precinct reporting ------------------------------------------------------

PRECINCT_PATTERNS = (
    re.compile(r"(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*)\s*precincts", re.IGNORECASE),
    re.compile(r"precincts\s*report(?:ing|ed)?[^\d]{0,12}(\d[\d,]*)\s*(?:of|/)\s*(\d[\d,]*)", re.IGNORECASE),
)


def _precincts(text: str) -> tuple[int | None, int | None]:
    for pattern in PRECINCT_PATTERNS:
        match = pattern.search(text)
        if match:
            return _to_int(match.group(1)), _to_int(match.group(2))
    return None, None


# --- the probe ---------------------------------------------------------------

# Kansas cast about 1.35 million votes for Senate in 2020 and a little over a
# million in the 2022 midterm. A completed statewide count cannot be in the
# thousands, and the probe needs a number to say so with.
MIN_PLAUSIBLE_STATEWIDE = 300_000

# Below this share of precincts a partial count legitimately looks nothing like a
# final one, so the vote-total check is held back until here. The structural
# checks apply throughout.
REPORTING_FLOOR = 5.0


def implausible(data: ResultsData) -> str | None:
    """Why this parse cannot be a statewide Senate result, or None if it could be.

    The probe used to accept any non-empty parse, and against the live fallback
    page on 2026-08-24 that meant declaring success on this:

        hamilton: 3,075 (100.0%)
        counties: 0 of 105
        precincts reporting: 100.0%

    One candidate, three thousand votes, every precinct in. On election night
    that publishes a called race for Hamilton off some stray table, and the app
    has no way to know it is wrong. A parser that reports success on nonsense is
    worse than one that fails, because failure is visible and this is not.

    None of these checks are judgement calls about the politics. They are
    arithmetic and structure: both candidates appear in a two-candidate race, a
    finished count is not in the thousands, and a hundred per cent reporting with
    no counties parsed contradicts itself.
    """
    votes = {row.candidate_id: row.votes for row in data.statewide}
    if not votes:
        return "no candidate rows"

    reporting = data.pct_reporting
    total = sum(votes.values())
    missing = [candidate for candidate in (MARSHALL, HAMILTON) if candidate not in votes]

    # A single row is always a parse artefact, at any stage of the count. An ENR
    # feed enumerates a contest's candidates from the first precinct, so a
    # candidate with no votes appears as a zero rather than being absent. The
    # first version of this check only fired above REPORTING_FLOOR, which let a
    # lone candidate through early in the night — exactly when nobody would be
    # watching closely enough to catch it.
    if missing:
        return (
            f"only {sorted(votes)} present, {missing} missing"
            + (f" at {reporting}% reporting" if reporting is not None else "")
        )

    if reporting is not None and reporting >= 99.0:
        if total < MIN_PLAUSIBLE_STATEWIDE:
            return (
                f"{total:,} votes with {reporting}% of precincts in; a finished "
                f"Kansas Senate count is above {MIN_PLAUSIBLE_STATEWIDE:,}"
            )
        if not data.counties:
            return f"{reporting}% of precincts in but no county rows parsed"

    return None


def probe(url: str | None = None) -> ResultsData:
    """Try each known shape against the ENR page, recording what happened."""
    data = ResultsData()
    base = (url or KS_ENR_BASE).rstrip("/")

    for path in JSON_CANDIDATE_PATHS:
        candidate_url = f"{base}{path}"
        try:
            payload = json.loads(get_text(candidate_url))
        except (SourceError, json.JSONDecodeError) as exc:
            data.probes.append(ResultsProbe("json-feed", False, f"{candidate_url}: {exc}"))
            continue
        parsed = _parse_json_results(payload)
        if parsed:
            reason = implausible(parsed)
            if reason:
                data.probes.append(
                    ResultsProbe("json-feed", False, f"{candidate_url}: rejected — {reason}")
                )
                continue
            parsed.probes = data.probes + [ResultsProbe("json-feed", True, candidate_url)]
            parsed.source_url = candidate_url
            parsed.attribution = data.attribution
            return parsed
        data.probes.append(
            ResultsProbe("json-feed", False, f"{candidate_url}: served JSON with no candidate rows")
        )

    for page_url in (base + "/", KS_ENR_FALLBACK):
        try:
            html = get_text(page_url)
        except SourceError as exc:
            data.probes.append(ResultsProbe("html", False, f"{page_url}: {exc}"))
            continue

        reporting, total = _precincts(TAG.sub(" ", html))

        for shape, parser in (("embedded-json", _parse_embedded_json), ("html-table", _parse_html_table)):
            parsed = parser(html)
            if parsed:
                # Populated before the plausibility check, which reads them.
                parsed.precincts_reporting = reporting
                parsed.precincts_total = total
                if reporting is not None and total:
                    parsed.pct_reporting = round(reporting / total * 100, 2)

                reason = implausible(parsed)
                if reason:
                    data.probes.append(
                        ResultsProbe(shape, False, f"{page_url}: rejected — {reason}")
                    )
                    continue

                parsed.probes = data.probes + [ResultsProbe(shape, True, page_url)]
                parsed.source_url = page_url
                parsed.attribution = data.attribution
                return parsed
            data.probes.append(ResultsProbe(shape, False, f"{page_url}: no match"))

        data.probes.append(
            ResultsProbe(
                "html", False, f"{page_url}: fetched {len(html)} bytes, no shape matched",
                body_sample=re.sub(r"\s+", " ", TAG.sub(" ", html))[:600],
            )
        )

    return data


def diagnose(url: str | None = None) -> str:
    """Human-readable probe report, for pinning the format down before Nov 3."""
    data = probe(url)
    lines = ["Kansas ENR probe", "=" * 40]
    for attempt in data.probes:
        lines.append(f"[{'OK  ' if attempt.ok else 'MISS'}] {attempt.shape}: {attempt.detail}")
        if attempt.body_sample:
            lines.append(f"        served: {attempt.body_sample[:300]}…")
    lines.append("")
    if data.statewide:
        lines.append(f"PARSED via {next(p.shape for p in data.probes if p.ok)}")
        for row in data.statewide:
            lines.append(f"  {row.candidate_id}: {row.votes:,} ({row.pct}%)")
        lines.append(f"  counties: {len(data.counties)} of {len(KANSAS_COUNTIES)}")
        if data.pct_reporting is not None:
            lines.append(f"  precincts reporting: {data.pct_reporting}%")
    else:
        lines.append("NO USABLE RESULT. Every shape either failed to match or was")
        lines.append("rejected as implausible — a rejection line above says which and")
        lines.append("why. Add a parser for what was served, or switch to the AP")
        lines.append("Elections API (paid) as documented in docs/ELECTION_NIGHT.md.")
    return "\n".join(lines)


def collect(url: str | None = None) -> ResultsData:
    """Collect returns. Returns a dormant payload before results exist."""
    data = probe(url)
    if not data.statewide:
        # Before 5pm on election day there is genuinely nothing to report, so a
        # dormant file is the correct output rather than an error.
        data.status = ResultsStatus.PENDING
    return data
