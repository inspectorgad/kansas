"""Campaign finance from the FEC's openFEC API.

Candidate ids are resolved at runtime from FEC candidate search rather than
trusted from config, because a wrong hardcoded id yields confidently wrong
money numbers — the worst failure mode this app has.

Outside spending gets equal billing with the candidates' own committees. In a
race projected near $50M, independent expenditures are frequently the larger
half, and a tracker that showed only the campaigns' own filings would understate
the money in the race by a wide margin.

Every sub-request degrades independently: a failed in-state breakdown leaves
that field null rather than losing the totals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from config import CANDIDATES, FEC_API, FEC_API_KEY, FEC_CYCLE, FEC_OFFICE, FEC_STATE
from fetch import SourceError, get_json
from schemas import Attribution
from schemas.finance import (
    CandidateFinance,
    Filing,
    IndependentExpenditure,
    OutsideSpending,
    TopSpender,
)

# api.data.gov's shared demo key allows only a handful of requests per hour, and
# the live run duly 429'd on every schedule-E and filings call. With no real key
# the deep sweeps are skipped rather than attempted and failed: the candidate
# totals still come through, and the log says why the rest did not.
USING_DEMO_KEY = FEC_API_KEY == "DEMO_KEY"

ATTRIBUTION = Attribution(
    name="Federal Election Commission (openFEC)",
    url="https://api.open.fec.gov/developers/",
    license="U.S. Government work, public domain",
)

MAX_RECENT_EXPENDITURES = 40
MAX_TOP_SPENDERS = 15
MAX_FILINGS = 25


@dataclass
class FinanceResult:
    candidates: dict[str, CandidateFinance] = field(default_factory=dict)
    outside_spending: OutsideSpending = field(default_factory=OutsideSpending)
    filings: list[Filing] = field(default_factory=list)
    attribution: list[Attribution] = field(default_factory=lambda: [ATTRIBUTION])
    warnings: list[str] = field(default_factory=list)


def _get(path: str, params: dict | None = None) -> dict:
    query = {"api_key": FEC_API_KEY, "per_page": 100}
    query.update(params or {})
    return get_json(f"{FEC_API}{path}", query)


def _as_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def resolve_candidate_id(name: str, hint: str | None = None) -> str | None:
    """Find a candidate's FEC id by surname, restricted to this race.

    The config hint is preferred only if the API confirms it, so a stale id
    cannot produce numbers for the wrong person.
    """
    surname = name.split()[-1]
    payload = _get(
        "/candidates/search/",
        {
            "q": surname,
            "state": FEC_STATE,
            "office": FEC_OFFICE,
            "election_year": FEC_CYCLE,
            "sort": "-first_file_date",
        },
    )
    results = payload.get("results", [])
    if not results:
        return None
    if hint:
        for row in results:
            if row.get("candidate_id") == hint:
                return hint
    # Otherwise take the best surname match with an active candidacy.
    for row in results:
        if surname.lower() in (row.get("name") or "").lower():
            return row.get("candidate_id")
    return results[0].get("candidate_id")


def _principal_committee(candidate_fec_id: str) -> tuple[str | None, str | None]:
    payload = _get(f"/candidate/{candidate_fec_id}/committees/", {"cycle": FEC_CYCLE})
    for row in payload.get("results", []):
        if row.get("designation") == "P":  # principal campaign committee
            return row.get("committee_id"), row.get("name")
    results = payload.get("results", [])
    if results:
        return results[0].get("committee_id"), results[0].get("name")
    return None, None


def _in_state_share(committee_id: str) -> tuple[float | None, float | None]:
    """Share of itemized individual contributions coming from Kansas."""
    payload = _get(
        "/schedules/schedule_a/by_state/",
        {"committee_id": committee_id, "cycle": FEC_CYCLE},
    )
    rows = payload.get("results", [])
    if not rows:
        return None, None
    total = sum(_as_float(r.get("total")) for r in rows)
    in_state = sum(
        _as_float(r.get("total")) for r in rows if (r.get("state") or "").upper() == FEC_STATE
    )
    if total <= 0:
        return None, None
    return in_state, round(in_state / total * 100.0, 1)


def _burn_rate(totals: dict, coverage_end: date | None) -> float | None:
    """Mean monthly disbursements across the cycle so far."""
    disbursements = _as_float(totals.get("disbursements"))
    if disbursements <= 0 or coverage_end is None:
        return None
    cycle_start = date(FEC_CYCLE - 2, 1, 1)
    months = max((coverage_end - cycle_start).days / 30.44, 1.0)
    return round(disbursements / months, 2)


def candidate_finance(candidate_id: str, name: str, hint: str | None, warnings: list[str]) -> CandidateFinance:
    record = CandidateFinance(candidate_id=candidate_id)

    fec_id = resolve_candidate_id(name, hint)
    if not fec_id:
        warnings.append(f"{name}: no FEC candidate record found for cycle {FEC_CYCLE}")
        return record
    record.fec_candidate_id = fec_id

    try:
        totals_payload = _get(f"/candidate/{fec_id}/totals/", {"cycle": FEC_CYCLE})
        totals = (totals_payload.get("results") or [{}])[0]
    except SourceError as exc:
        warnings.append(f"{name}: totals unavailable ({exc})")
        return record

    record.coverage_start_date = _as_date(totals.get("coverage_start_date"))
    record.coverage_end_date = _as_date(totals.get("coverage_end_date"))
    record.total_receipts = _as_float(totals.get("receipts"))
    record.total_disbursements = _as_float(totals.get("disbursements"))
    record.cash_on_hand = _as_float(totals.get("last_cash_on_hand_end_period"))
    record.debts_owed = _as_float(totals.get("last_debts_owed_by_committee"))
    record.individual_contributions = _as_float(totals.get("individual_contributions"))
    record.small_dollar_contributions = _as_float(
        totals.get("individual_unitemized_contributions")
    )
    record.pac_contributions = _as_float(totals.get("other_political_committee_contributions"))
    record.burn_rate_monthly = _burn_rate(totals, record.coverage_end_date)

    try:
        record.committee_id, record.committee_name = _principal_committee(fec_id)
    except SourceError as exc:
        warnings.append(f"{name}: committee lookup failed ({exc})")

    if record.committee_id:
        try:
            record.in_state_amount, record.in_state_pct = _in_state_share(record.committee_id)
        except SourceError as exc:
            warnings.append(f"{name}: in-state breakdown unavailable ({exc})")

    return record


def outside_spending(fec_ids: dict[str, str], warnings: list[str]) -> OutsideSpending:
    """Independent expenditures for and against each candidate."""
    result = OutsideSpending()
    spender_totals: dict[tuple[str, str | None], dict] = {}

    for candidate_id, fec_id in fec_ids.items():
        for indicator, bucket in (("S", result.supporting), ("O", result.opposing)):
            try:
                payload = _get(
                    "/schedules/schedule_e/by_candidate/",
                    {
                        "candidate_id": fec_id,
                        "cycle": FEC_CYCLE,
                        "support_oppose_indicator": indicator,
                    },
                )
            except SourceError as exc:
                warnings.append(f"{candidate_id}: schedule E ({indicator}) unavailable ({exc})")
                continue

            for row in payload.get("results", []):
                amount = _as_float(row.get("total"))
                bucket[candidate_id] = bucket.get(candidate_id, 0.0) + amount
                name = row.get("committee_name") or "Unidentified committee"
                key = (name, row.get("committee_id"))
                entry = spender_totals.setdefault(
                    key, {"amount": 0.0, "supports": None, "opposes": None}
                )
                entry["amount"] += amount
                if indicator == "S":
                    entry["supports"] = candidate_id
                else:
                    entry["opposes"] = candidate_id

        try:
            payload = _get(
                "/schedules/schedule_e/",
                {
                    "candidate_id": fec_id,
                    "cycle": FEC_CYCLE,
                    "sort": "-expenditure_date",
                    "per_page": MAX_RECENT_EXPENDITURES,
                },
            )
        except SourceError as exc:
            warnings.append(f"{candidate_id}: recent expenditures unavailable ({exc})")
            continue

        for row in payload.get("results", []):
            when = _as_date(row.get("expenditure_date"))
            if when is None:
                continue
            result.recent.append(
                IndependentExpenditure(
                    date=when,
                    committee_id=row.get("committee_id"),
                    committee_name=row.get("committee_name") or "Unidentified committee",
                    amount=_as_float(row.get("expenditure_amount")),
                    support_oppose=(row.get("support_oppose_indicator") or "O").upper()[:1],
                    candidate_id=candidate_id,
                    purpose=row.get("expenditure_description"),
                )
            )

    result.total = sum(result.supporting.values()) + sum(result.opposing.values())
    result.top_spenders = [
        TopSpender(
            committee_name=name,
            committee_id=committee_id,
            amount=round(entry["amount"], 2),
            supports=entry["supports"],
            opposes=entry["opposes"],
        )
        for (name, committee_id), entry in sorted(
            spender_totals.items(), key=lambda kv: kv[1]["amount"], reverse=True
        )[:MAX_TOP_SPENDERS]
    ]
    result.recent.sort(key=lambda e: e.date, reverse=True)
    result.recent = result.recent[:MAX_RECENT_EXPENDITURES]
    return result


def recent_filings(committee_ids: list[str], warnings: list[str]) -> list[Filing]:
    filings: list[Filing] = []
    for committee_id in committee_ids:
        try:
            payload = _get(
                "/filings/",
                {
                    "committee_id": committee_id,
                    "cycle": FEC_CYCLE,
                    "sort": "-receipt_date",
                    "per_page": MAX_FILINGS,
                },
            )
        except SourceError as exc:
            warnings.append(f"filings for {committee_id} unavailable ({exc})")
            continue
        for row in payload.get("results", []):
            when = _as_date(row.get("receipt_date"))
            if when is None:
                continue
            filings.append(
                Filing(
                    date=when,
                    committee_name=row.get("committee_name") or committee_id,
                    committee_id=committee_id,
                    form_type=row.get("form_type"),
                    report_type=row.get("report_type_full") or row.get("report_type"),
                    coverage_end_date=_as_date(row.get("coverage_end_date")),
                    total_receipts=_as_float(row.get("total_receipts")) or None,
                    url=row.get("pdf_url") or row.get("fec_url"),
                )
            )
    filings.sort(key=lambda f: f.date, reverse=True)
    return filings[:MAX_FILINGS]


def collect() -> FinanceResult:
    warnings: list[str] = []
    result = FinanceResult(warnings=warnings)

    for candidate in CANDIDATES:
        result.candidates[candidate.id] = candidate_finance(
            candidate.id, candidate.name, candidate.fec_candidate_id, warnings
        )

    if USING_DEMO_KEY:
        warnings.append(
            "no FEC_API_KEY set: using the shared demo key, which is rate-limited "
            "too hard for outside spending and filings. Candidate totals only. "
            "A free key from api.data.gov lifts this."
        )
        return result

    fec_ids = {
        cid: record.fec_candidate_id
        for cid, record in result.candidates.items()
        if record.fec_candidate_id
    }
    if fec_ids:
        result.outside_spending = outside_spending(fec_ids, warnings)

    committee_ids = [
        record.committee_id for record in result.candidates.values() if record.committee_id
    ]
    if committee_ids:
        result.filings = recent_filings(committee_ids, warnings)

    return result
