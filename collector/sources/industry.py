"""Industry and sector classification of a campaign's donors, via OpenSecrets.

The FEC records a donor's self-reported employer string and stops there, so the
app can say that $69,200 came from people who wrote "Koch Industries" and cannot
say what share came from energy. OpenSecrets maintains the mapping from employer
to industry to sector, which is the difference between reproducing a disclosure
form and answering the question a reader actually has.

Two things make this awkward, and both are handled here rather than discovered in
production.

The free key allows 200 calls a day against a collector that runs about forty
times a day, so this cannot ride along on every run. Industry mix changes when
filings land, not minute to minute.

More seriously, OpenSecrets identifies candidates by its own CRP id, and the only
public way to look one up is `getLegislators`, which returns *sitting members of
Congress*. Marshall is one. Hamilton is a challenger and holds no office, so he
may have no entry at all. An industry breakdown shown for the incumbent alone
would be the same asymmetry the news feed just had to label — one side's data
presented as if the two were comparable. Whether that is really the situation is
what the probe below is for; nothing is published until it says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import (
    CANDIDATES,
    FEC_CYCLE,
    OPENSECRETS_API,
    OPENSECRETS_API_KEY,
    OPENSECRETS_CALL_BUDGET,
)
from fetch import SourceError, get_json


class Budget:
    """A hard ceiling on calls, because the daily allowance is small.

    Counted rather than trusted to a loop bound: a paging change that spun would
    burn the day's quota in one run and leave the collector blind until midnight.
    """

    def __init__(self, limit: int = OPENSECRETS_CALL_BUDGET) -> None:
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise SourceError(f"OpenSecrets call budget of {self.limit} exhausted")
        self.used += 1


@dataclass
class Legislator:
    cid: str
    name: str
    fec_id: str | None = None


@dataclass
class IndustryResult:
    by_candidate: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _call(method: str, budget: Budget, **params: str) -> Any:
    """One OpenSecrets API call, as JSON."""
    if not OPENSECRETS_API_KEY:
        raise SourceError("no OPENSECRETS_API_KEY set")
    budget.spend()
    return get_json(
        OPENSECRETS_API,
        {"method": method, "apikey": OPENSECRETS_API_KEY, "output": "json", **params},
    )


def _attributes(node: Any) -> dict:
    """OpenSecrets' JSON is converted from XML, so values hide in @attributes."""
    if isinstance(node, dict):
        inner = node.get("@attributes")
        if isinstance(inner, dict):
            return inner
        return node
    return {}


def _rows(payload: Any, container: str, item: str) -> list[dict]:
    """The list under `container`/`item`, tolerating XML-to-JSON quirks.

    A single result comes back as an object rather than a one-element list, which
    is the classic way this conversion breaks a parser that assumes a list.
    """
    response = (payload or {}).get("response") or {}
    holder = response.get(container) or {}
    rows = holder.get(item) if isinstance(holder, dict) else None
    if rows is None:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [_attributes(row) for row in rows if isinstance(row, dict)]


def legislators(state: str, budget: Budget) -> list[Legislator]:
    """Sitting members of Congress for a state, with their CRP ids."""
    payload = _call("getLegislators", budget, id=state)
    found = []
    for row in _rows(payload, "legislators", "legislator"):
        cid = (row.get("cid") or "").strip()
        if not cid:
            continue
        found.append(
            Legislator(
                cid=cid,
                name=(row.get("firstlast") or row.get("lastname") or "").strip(),
                fec_id=(row.get("fecCandId") or "").strip() or None,
            )
        )
    return found


def match_legislator(rows: list[Legislator], name: str, fec_id: str | None) -> Legislator | None:
    """Find one candidate among a state's legislators.

    The FEC id is preferred because it is an identifier; the surname is the
    fallback and is checked as a whole word, since name matching in this project
    has already produced Arkansas for Kansas once.
    """
    if fec_id:
        for row in rows:
            if row.fec_id and row.fec_id.upper() == fec_id.upper():
                return row
    surname = name.split()[-1].lower()
    for row in rows:
        if surname in [part.lower() for part in row.name.replace(",", " ").split()]:
            return row
    return None


def industries(cid: str, budget: Budget, cycle: int = FEC_CYCLE) -> list[tuple[str, float]]:
    """Industry totals for one candidate, largest first."""
    payload = _call("candIndustry", budget, cid=cid, cycle=str(cycle))
    found: list[tuple[str, float]] = []
    for row in _rows(payload, "industries", "industry"):
        label = (row.get("industry_name") or "").strip()
        try:
            total = float(row.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if label and total > 0:
            found.append((label, round(total, 2)))
    found.sort(key=lambda pair: pair[1], reverse=True)
    return found


def diagnose() -> str:
    """Report what OpenSecrets serves for this race, and for which candidates.

    The open question is not the response shape — it is whether the challenger
    exists in this dataset at all. `getLegislators` returns sitting members, and
    Hamilton holds no office. If only the incumbent resolves, an industry
    breakdown cannot be published as though it described the race, and this probe
    is what settles which of those two situations we are in.
    """
    lines = ["Industry probe (OpenSecrets)", "=" * 72]
    if not OPENSECRETS_API_KEY:
        lines.append("")
        lines.append("No OPENSECRETS_API_KEY set, so nothing can be asked.")
        lines.append("Free key: https://www.opensecrets.org/api/admin/index.php?function=signup")
        lines.append("Add it as a repository secret named OPENSECRETS_API_KEY.")
        return "\n".join(lines)

    budget = Budget()
    try:
        roster = legislators("KS", budget)
    except SourceError as exc:
        lines.append(f"\ngetLegislators FAILED: {exc}")
        return "\n".join(lines)

    lines.append(f"\nKansas legislators returned: {len(roster)}")
    for row in roster:
        lines.append(f"  {row.cid}  fec={row.fec_id or '-':<10} {row.name}")

    for candidate in CANDIDATES:
        lines.append(f"\n[{candidate.name}]")
        match = match_legislator(roster, candidate.name, candidate.fec_candidate_id)
        if not match:
            lines.append("  NOT FOUND in the legislator roster.")
            lines.append("  Expected for a challenger: this endpoint lists sitting members.")
            lines.append("  If it stays unfound, industry data covers one side of this race")
            lines.append("  only, and must not be published as though it described both.")
            continue

        lines.append(f"  cid={match.cid} ({match.name})")
        for method, container, item in (
            ("candIndustry", "industries", "industry"),
            ("candSector", "sectors", "sector"),
        ):
            try:
                payload = _call(method, budget, cid=match.cid, cycle=str(FEC_CYCLE))
            except SourceError as exc:
                lines.append(f"  {method}: FAILED {exc}")
                continue
            rows = _rows(payload, container, item)
            lines.append(f"  {method}: {len(rows)} row(s)")
            for row in rows[:8]:
                lines.append(f"     {row}")
            if not rows:
                # The shape matters more than the absence: printing the envelope
                # says whether the cycle is wrong or the parse is.
                lines.append(f"     raw keys: {sorted((payload or {}).get('response', {}))}")

    lines.append(f"\ncalls used: {budget.used}/{budget.limit}")
    return "\n".join(lines)
