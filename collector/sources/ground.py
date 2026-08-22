"""Voter registration and advance-ballot returns.

Coverage here is genuinely partial, and the payload says so rather than
implying a statewide picture. Kansas publishes no statewide daily early-vote
feed, so advance-ballot figures come from the five county election offices that
run public dashboards. Those five hold roughly half the state's registered
voters and skew more urban than Kansas as a whole, so their returns are not a
state sample and must never be presented as one.

None of these pages could be inspected where this was written, so extraction is
generic first — a set of phrasings county dashboards commonly use — with
`diagnose()` printing every number-bearing phrase it found on a page so a
county-specific rule can be written in minutes once someone can see it. A county
that cannot be read is reported as uncovered, never as zero: "no dashboard
reachable" and "no ballots returned" are opposite facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from config import ADVANCE_DASHBOARDS, ADVANCE_VOTING_OPENS, KS_SOS_REGISTRATION
from fetch import SourceError, get_text
from schemas import Attribution
from schemas.ground import AdvanceBallots, CountyAdvance, CountyRegistration, Registration

SOS_ATTRIBUTION = Attribution(
    name="Kansas Secretary of State — voter registration statistics",
    url="https://sos.ks.gov/elections/",
    license="U.S. state government work",
)

TAG = re.compile(r"<[^>]+>")
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)

PARTY_HEADERS = {
    "republican": "republican",
    "rep": "republican",
    "gop": "republican",
    "democratic": "democrat",
    "democrat": "democrat",
    "dem": "democrat",
    "unaffiliated": "unaffiliated",
    "una": "unaffiliated",
    "independent": "unaffiliated",
    "libertarian": "libertarian",
    "lib": "libertarian",
    "total": "total",
}

# County dashboards write prose, not structured data, so extraction anchors on a
# phrase and then takes the nearest number to it. That is far more robust than one
# long regex trying to span "16,000 registered voters had cast early ballots at
# advance voting locations" in a single match.
ADVANCE_ANCHORS: dict[str, tuple[str, ...]] = {
    "mail_ballots_sent": (
        r"ballots?\s+(?:were\s+)?mailed",
        r"mailed\s+(?:out\s+)?(?:advance\s+)?ballots?",
        r"mail\s+ballots?\s+(?:sent|issued)",
        r"applications?\s+(?:approved|processed)",
        # Last resort: the bare verb, for "the office mailed 14,195 ballots".
        r"\bmailed\b",
    ),
    "mail_ballots_returned": (
        r"mail\s+ballots?\s+(?:had\s+been\s+)?returned",
        r"ballots?\s+returned",
        r"returned\s+(?:mail|advance)\s+ballots?",
    ),
    "in_person_votes": (
        r"(?:early|advance)\s+(?:in[-\s]person|voting\s+locations?)",
        r"(?:cast|voted)\s+(?:early|advance)",
        r"in[-\s]person\s+(?:early|advance)?\s*(?:voting|votes?|ballots?)",
        r"voted\s+in\s+person",
    ),
}

# How far from the anchor phrase a number may sit and still belong to it.
ANCHOR_WINDOW = 90

NUMBER = re.compile(r"\b\d{1,3}(?:,\d{3})+\b|\b\d{3,7}\b")


def _number_near(
    text: str, anchor: re.Match[str], claimed: set[int] | None = None
) -> tuple[int, int] | None:
    """The number nearest an anchor phrase, as (value, position).

    Nearest by character distance, not preceding-first: county dashboards write
    both "6,900 mail ballots returned" and "Mail ballots returned: 8,455", and a
    preceding-first rule reads the latter as whatever number happened to sit on
    the line above. A tie goes to the preceding number, which is the more common
    phrasing.

    `claimed` holds positions already assigned to another field, so two fields
    cannot both report the same figure — the failure mode that made "ballots
    sent" and "ballots returned" come back identical.
    """
    claimed = claimed or set()
    best: tuple[int, int, int] | None = None  # (distance, position, value)

    window_start = max(0, anchor.start() - ANCHOR_WINDOW)
    window_end = anchor.end() + ANCHOR_WINDOW

    for match in NUMBER.finditer(text, window_start, window_end):
        position = match.start()
        if position in claimed:
            continue
        value = _to_int(match.group(0))
        if value is None:
            continue

        if match.end() <= anchor.start():
            distance = anchor.start() - match.end()
            tie_break = 0  # preceding wins a tie
        elif position >= anchor.end():
            distance = position - anchor.end()
            tie_break = 1
        else:
            continue  # a number inside the anchor phrase itself

        candidate = (distance * 2 + tie_break, position, value)
        if best is None or candidate < best:
            best = candidate

    return (best[2], best[1]) if best else None


@dataclass
class GroundResult:
    registration: Registration = field(default_factory=Registration)
    advance_ballots: AdvanceBallots = field(default_factory=AdvanceBallots)
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", html).replace("&nbsp;", " "))


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    try:
        parsed = int(digits)
    except ValueError:
        return None
    # A county advance count above the state's whole electorate is a parse
    # artefact — usually a phone number or a year swept up by a regex.
    return parsed if 0 <= parsed <= 2_000_000 else None


def _cells(row_html: str) -> list[str]:
    return [_text(cell).strip() for cell in CELL.findall(row_html)]


def parse_registration_table(html: str) -> Registration | None:
    """Read a county-by-party registration table, keyed on header names."""
    from .results import KANSAS_COUNTIES

    columns: dict[str, int] = {}
    for row_html in ROW.findall(html):
        cells = [c.lower() for c in _cells(row_html)]
        found: dict[str, int] = {}
        for index, cell in enumerate(cells):
            for token, party in PARTY_HEADERS.items():
                if re.fullmatch(rf"{token}s?\.?", cell.strip()) and party not in found:
                    found[party] = index
        # A real header row names at least the two major parties.
        if "republican" in found and "democrat" in found:
            columns = found
            break

    if not columns:
        return None

    counties: list[CountyRegistration] = []
    statewide: CountyRegistration | None = None

    for row_html in ROW.findall(html):
        cells = _cells(row_html)
        if not cells:
            continue
        label = cells[0].strip().title()

        def value(party: str, cells: list[str] = cells) -> int:
            index = columns.get(party)
            if index is None or index >= len(cells):
                return 0
            return _to_int(cells[index]) or 0

        record = CountyRegistration(
            county=label,
            republican=value("republican"),
            democrat=value("democrat"),
            unaffiliated=value("unaffiliated"),
            libertarian=value("libertarian"),
            total=value("total"),
        )
        if record.total == 0:
            record.total = (
                record.republican + record.democrat + record.unaffiliated + record.libertarian
            )
        if record.total == 0:
            continue

        if label in KANSAS_COUNTIES:
            counties.append(record)
        elif label.lower() in ("total", "statewide", "state total", "totals"):
            record.county = "Statewide"
            statewide = record

    if not counties and statewide is None:
        return None

    if statewide is None and counties:
        statewide = CountyRegistration(
            county="Statewide",
            republican=sum(c.republican for c in counties),
            democrat=sum(c.democrat for c in counties),
            unaffiliated=sum(c.unaffiliated for c in counties),
            libertarian=sum(c.libertarian for c in counties),
            total=sum(c.total for c in counties),
        )

    return Registration(
        statewide=statewide,
        by_county=sorted(counties, key=lambda c: c.county),
        source_url=KS_SOS_REGISTRATION,
    )


def parse_advance(html: str, county: str, source_url: str) -> CountyAdvance | None:
    """Pull advance-vote figures out of a county dashboard's prose."""
    text = _text(html)
    found: dict[str, int] = {}
    claimed: set[int] = set()

    for field_name, anchors in ADVANCE_ANCHORS.items():
        for pattern in anchors:
            for anchor in re.finditer(pattern, text, re.IGNORECASE):
                hit = _number_near(text, anchor, claimed)
                if hit is not None:
                    found[field_name], position = hit
                    claimed.add(position)
                    break
            if field_name in found:
                break

    if not found:
        return None

    mail_returned = found.get("mail_ballots_returned")
    in_person = found.get("in_person_votes")
    total = None
    if mail_returned is not None or in_person is not None:
        total = (mail_returned or 0) + (in_person or 0)

    return CountyAdvance(
        county=county,
        mail_ballots_sent=found.get("mail_ballots_sent"),
        mail_ballots_returned=mail_returned,
        in_person_votes=in_person,
        total_advance=total,
        as_of=datetime.now(UTC),
        source_url=source_url,
    )


def collect() -> GroundResult:
    warnings: list[str] = []
    result = GroundResult(warnings=warnings)

    try:
        registration = parse_registration_table(get_text(KS_SOS_REGISTRATION))
        if registration:
            result.registration = registration
            result.attribution.append(SOS_ATTRIBUTION)
        else:
            warnings.append(
                "Kansas SoS registration page served no parseable table — "
                "the statistics are often published as PDF or XLSX; run --probe-ground"
            )
    except SourceError as exc:
        warnings.append(f"registration statistics unavailable: {exc}")

    covered: list[CountyAdvance] = []
    today = datetime.now(UTC).date()
    if today < ADVANCE_VOTING_OPENS:
        # Whatever these pages are showing now is not general-election advance
        # voting. The first live run matched figures on two of them in August;
        # those were primary numbers, and publishing them here would have been
        # confidently wrong rather than merely empty.
        warnings.append(
            f"advance voting opens {ADVANCE_VOTING_OPENS.isoformat()}; "
            "county dashboards not read yet"
        )
        result.advance_ballots = AdvanceBallots(counties_covered=[], counties=[])
        return result

    for dashboard in ADVANCE_DASHBOARDS:
        try:
            html = get_text(dashboard.url)
        except SourceError as exc:
            warnings.append(f"{dashboard.county} County dashboard unreachable: {exc}")
            continue

        parsed = parse_advance(html, dashboard.county, dashboard.url)
        if parsed is None:
            # Uncovered, not zero. Conflating the two would understate turnout.
            warnings.append(
                f"{dashboard.county} County: no advance figures recognised on the page "
                "(reported as uncovered, not as zero)"
            )
            continue
        covered.append(parsed)
        result.attribution.append(
            Attribution(name=f"{dashboard.county} County Election Office", url=dashboard.url)
        )

    result.advance_ballots = AdvanceBallots(
        counties_covered=[c.county for c in covered],
        counties=covered,
    )
    return result


def diagnose() -> str:
    """Print the number-bearing phrases on each page, to write rules against."""
    lines = ["Ground-game probe", "=" * 40]

    lines.append(f"\n[registration] {KS_SOS_REGISTRATION}")
    try:
        html = get_text(KS_SOS_REGISTRATION)
        parsed = parse_registration_table(html)
        if parsed:
            total = parsed.statewide.total if parsed.statewide else 0
            lines.append(f"  OK: {len(parsed.by_county)} counties, statewide total {total:,}")
        else:
            lines.append(f"  MISS: no table matched ({len(html)} bytes fetched)")
            lines.append(f"  served: {_text(html)[:400]}…")
    except SourceError as exc:
        lines.append(f"  FAILED: {exc}")

    for dashboard in ADVANCE_DASHBOARDS:
        lines.append(f"\n[{dashboard.county}] {dashboard.url}")
        try:
            html = get_text(dashboard.url)
        except SourceError as exc:
            lines.append(f"  FAILED: {exc}")
            continue

        parsed = parse_advance(html, dashboard.county, dashboard.url)
        if parsed:
            lines.append(
                f"  OK: sent={parsed.mail_ballots_sent} returned={parsed.mail_ballots_returned} "
                f"in-person={parsed.in_person_votes}"
            )
            continue

        lines.append("  MISS: add a pattern for one of these phrases —")
        text = _text(html)
        for match in list(re.finditer(r"[^.]{0,70}\b\d{2,3}(?:,\d{3})+\b[^.]{0,40}", text))[:8]:
            lines.append(f"    · {match.group(0).strip()}")
    return "\n".join(lines)
