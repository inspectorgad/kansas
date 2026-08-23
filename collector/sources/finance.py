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
    DonorDetail,
    DonorGroup,
    Filing,
    IndependentExpenditure,
    LargeDonor,
    OutsideSpending,
    SizeBucket,
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


# The named-donor list is the only part of donor detail that needs paging, and it
# is deliberately bounded. FEC aggregate endpoints do the grouping server-side —
# by_employer, by_occupation, by_size — which is both cheaper and more complete
# than anything we could assemble from a truncated row scan.
#
# Rows are requested largest-first with a $1,000 floor, so the budget reaches the
# largest contributions rather than an arbitrary slice. Sixteen pages, because
# eight was not enough: the first live run read 800 of 1,002 such contributions
# for Marshall and 800 of 1,218 for Hamilton, and said so — but a complete
# ranking is worth two more requests. What no budget can fix is a donor who
# arrived at a large total through several smaller gifts, and the payload says so.
LARGE_DONOR_THRESHOLD = 1000.0
LARGE_DONOR_PAGE_BUDGET = 16
MAX_LARGE_DONORS = 25
MAX_DONOR_GROUPS = 10


# Employer and occupation are free text typed by whoever filled in the form, and
# a large share of it is a non-answer. The first live run ranked "NONE" as
# Marshall's top employer at $69,200 and "NULL" as his fourth occupation at
# $60,322 — placeholders presented as findings. They are dropped rather than
# displayed, because a chart whose largest bar is the absence of data is worse
# than a shorter chart.
#
# Kept deliberately: RETIRED, HOMEMAKER, SELF-EMPLOYED, NOT EMPLOYED. Those are
# real answers about how someone spends their time, and for a donor base's
# composition they are among the more informative ones.
NON_ANSWERS = {
    "",
    "NONE",
    "NULL",
    "N/A",
    "NA",
    "NOT APPLICABLE",
    "NOT PROVIDED",
    "REQUESTED",
    "INFORMATION REQUESTED",
    "INFO REQUESTED",
    "BEST EFFORTS",
    "UNKNOWN",
    "UNDISCLOSED",
    "REFUSED",
    "DECLINED",
    "-",
    "--",
    ".",
}


def _is_non_answer(label: str) -> bool:
    """Is this employer or occupation string a blank rather than an answer?"""
    cleaned = " ".join((label or "").split()).upper().strip(" .-")
    return cleaned in NON_ANSWERS or not cleaned


def _individual_name(row: dict) -> str | None:
    """A contributor's name, normalised enough to group their gifts together.

    The FEC's own strings vary in spacing and case between filings, so grouping on
    the raw value splits one donor into several and understates every large one.
    """
    raw = (row.get("contributor_name") or "").strip()
    if not raw:
        return None
    return " ".join(raw.split()).upper()


def _large_donors(committee_id: str, warnings: list[str]) -> tuple[list[LargeDonor], str | None]:
    """Named individuals giving at or above the threshold, summed per person."""
    totals: dict[tuple[str, str | None], dict] = {}
    params: dict = {
        "committee_id": committee_id,
        "two_year_transaction_period": FEC_CYCLE,
        "min_amount": LARGE_DONOR_THRESHOLD,
        "sort": "-contribution_receipt_amount",
        "is_individual": "true",
        "per_page": 100,
    }
    seen: set = set()
    reported: int | None = None
    truncated = False

    for page in range(LARGE_DONOR_PAGE_BUDGET):
        try:
            payload = _get("/schedules/schedule_a/", params)
        except SourceError as exc:
            warnings.append(f"large donors page {page + 1} unavailable ({exc})")
            break

        rows = payload.get("results") or []
        pagination = payload.get("pagination") or {}
        if reported is None:
            reported = pagination.get("count")

        fresh = 0
        for row in rows:
            identity = row.get("sub_id") or (
                row.get("contributor_name"),
                row.get("contribution_receipt_date"),
                row.get("contribution_receipt_amount"),
            )
            if identity in seen:
                continue
            seen.add(identity)
            fresh += 1

            name = _individual_name(row)
            if name is None:
                continue
            key = (name, (row.get("contributor_city") or "").upper() or None)
            entry = totals.setdefault(
                key,
                {
                    "name": (row.get("contributor_name") or "").strip(),
                    "city": row.get("contributor_city"),
                    "state": row.get("contributor_state"),
                    "employer": row.get("contributor_employer"),
                    "occupation": row.get("contributor_occupation"),
                    "amount": 0.0,
                    "gifts": 0,
                },
            )
            entry["amount"] += _as_float(row.get("contribution_receipt_amount"))
            entry["gifts"] += 1

        if not rows or fresh == 0:
            break

        last = pagination.get("last_indexes")
        params = {**params, **last} if isinstance(last, dict) and last else {
            **params,
            "page": page + 2,
        }
        if page == LARGE_DONOR_PAGE_BUDGET - 1 and reported and len(seen) < reported:
            truncated = True

    ranked = sorted(totals.values(), key=lambda e: e["amount"], reverse=True)
    donors = [
        LargeDonor(
            name=entry["name"],
            city=entry["city"],
            state=entry["state"],
            employer=entry["employer"],
            occupation=entry["occupation"],
            amount=round(entry["amount"], 2),
            gifts=entry["gifts"],
        )
        for entry in ranked[:MAX_LARGE_DONORS]
    ]

    coverage = (
        f"Read the {len(seen)} largest of {reported} contributions at or above "
        f"${LARGE_DONOR_THRESHOLD:,.0f}. Donors who reached a large total through "
        "smaller gifts are not ranked here."
        if truncated and reported
        else "Ranked from every contribution at or above "
        f"${LARGE_DONOR_THRESHOLD:,.0f}. A donor who reached a large total through "
        "smaller gifts is not counted."
    )
    return donors, coverage


def _donor_groups(path: str, committee_id: str, label_keys: tuple[str, ...],
                  warnings: list[str], what: str) -> list[DonorGroup]:
    """One of the FEC's server-side groupings of itemized individual money."""
    try:
        payload = _get(path, {"committee_id": committee_id, "cycle": FEC_CYCLE})
    except SourceError as exc:
        warnings.append(f"{what} breakdown unavailable ({exc})")
        return []

    groups: list[DonorGroup] = []
    for row in payload.get("results", []):
        label = next(
            (str(row[key]).strip() for key in label_keys if row.get(key)), None
        )
        amount = _as_float(row.get("total"))
        if not label or amount <= 0 or _is_non_answer(label):
            continue
        groups.append(
            DonorGroup(label=label, amount=round(amount, 2), donors=int(row.get("count") or 0))
        )
    groups.sort(key=lambda g: g.amount, reverse=True)
    return groups[:MAX_DONOR_GROUPS]


def _size_buckets(committee_id: str, warnings: list[str]) -> list[SizeBucket]:
    """Itemized individual money by the FEC's own contribution-size bands."""
    try:
        payload = _get(
            "/schedules/schedule_a/by_size/",
            {"committee_id": committee_id, "cycle": FEC_CYCLE},
        )
    except SourceError as exc:
        warnings.append(f"contribution size breakdown unavailable ({exc})")
        return []

    labels = {
        0: "Under $200",
        200: "$200 to $499",
        500: "$500 to $999",
        1000: "$1,000 to $1,999",
        2000: "$2,000 and above",
    }
    buckets: list[SizeBucket] = []
    for row in payload.get("results", []):
        floor = row.get("size")
        amount = _as_float(row.get("total"))
        if floor is None:
            continue
        buckets.append(
            SizeBucket(
                label=labels.get(int(floor), f"${int(floor):,} and above"),
                amount=round(amount, 2),
                count=int(row.get("count") or 0),
            )
        )
    buckets.sort(key=lambda b: b.label)
    return buckets


def _identical_amount_audit(
    committee_id: str, donors: list[LargeDonor], warnings: list[str]
) -> None:
    """Report the raw rows when several donors share an identical total.

    Five of Marshall's top donors came back at exactly $31,500 over exactly three
    gifts each — five different people in five different states. An identical
    figure repeating across unrelated donors is the shape a double count makes,
    and $10,500 apiece is above the per-election individual limit, so either
    joint-fundraising structure explains it or these rows are being summed when
    they should not be.

    Which of those it is lives in fields no total carries: memo_code marks a
    transaction the FEC considers already counted elsewhere, and earmarked money
    routed through a conduit is reported twice by design. So rather than guessing
    from the pattern, one such donor's rows are fetched and the memo split
    reported. Bounded to a single extra request, and only when the pattern
    actually appears.
    """
    by_amount: dict[float, list[LargeDonor]] = {}
    for donor in donors:
        by_amount.setdefault(round(donor.amount, 2), []).append(donor)

    clusters = {amount: group for amount, group in by_amount.items() if len(group) >= 3}
    if not clusters:
        return

    amount, group = max(clusters.items(), key=lambda kv: len(kv[1]))
    warnings.append(
        f"{len(group)} donors share an identical total of ${amount:,.2f} "
        f"({', '.join(d.name for d in group[:4])}) — auditing the raw rows"
    )

    sample = group[0]
    try:
        payload = _get(
            "/schedules/schedule_a/",
            {
                "committee_id": committee_id,
                "two_year_transaction_period": FEC_CYCLE,
                "contributor_name": sample.name,
                "per_page": 30,
            },
        )
    except SourceError as exc:
        warnings.append(f"identical-total audit could not fetch rows ({exc})")
        return

    rows = payload.get("results") or []
    memo = [r for r in rows if r.get("memo_code")]
    plain = [r for r in rows if not r.get("memo_code")]
    memo_sum = sum(_as_float(r.get("contribution_receipt_amount")) for r in memo)
    plain_sum = sum(_as_float(r.get("contribution_receipt_amount")) for r in plain)
    sub_ids = {r.get("sub_id") for r in rows if r.get("sub_id")}
    types = sorted({str(r.get("receipt_type") or "?") for r in rows})
    lines = sorted({str(r.get("line_number") or "?") for r in rows})

    warnings.append(
        f"audit of {sample.name}: {len(rows)} row(s), {len(sub_ids)} distinct sub_id(s); "
        f"memo-coded {len(memo)} = ${memo_sum:,.2f}, un-memoed {len(plain)} = "
        f"${plain_sum:,.2f}; receipt types {types}; lines {lines}; "
        f"collector summed ${sample.amount:,.2f} over {sample.gifts} gift(s)"
    )


def _donor_detail(committee_id: str, warnings: list[str]) -> DonorDetail:
    """Everything disclosure allows about who funds one campaign."""
    donors, coverage = _large_donors(committee_id, warnings)
    _identical_amount_audit(committee_id, donors, warnings)
    buckets = _size_buckets(committee_id, warnings)
    under_200 = next((b.amount for b in buckets if b.label == "Under $200"), None)
    itemized = sum(b.amount for b in buckets if b.label != "Under $200") or None

    return DonorDetail(
        large_donors=donors,
        large_donor_coverage=coverage,
        top_employers=_donor_groups(
            "/schedules/schedule_a/by_employer/",
            committee_id,
            ("employer", "contributor_employer"),
            warnings,
            "employer",
        ),
        top_occupations=_donor_groups(
            "/schedules/schedule_a/by_occupation/",
            committee_id,
            ("occupation", "contributor_occupation"),
            warnings,
            "occupation",
        ),
        top_cities=_donor_cities(donors),
        size_buckets=buckets,
        itemized_total=round(itemized, 2) if itemized else None,
        unitemized_total=under_200,
    )


def _donor_cities(donors: list[LargeDonor]) -> list[DonorGroup]:
    """Cities ranked by large-donor dollars.

    Built from the named list rather than from a server-side aggregate, because
    openFEC groups geography by state and ZIP and not by city. It therefore
    describes where the large money is, not where all the money is, and the label
    on screen says exactly that.
    """
    totals: dict[str, dict] = {}
    for donor in donors:
        if not donor.city:
            continue
        label = f"{donor.city.title()}, {donor.state}" if donor.state else donor.city.title()
        entry = totals.setdefault(label, {"amount": 0.0, "donors": 0})
        entry["amount"] += donor.amount
        entry["donors"] += 1
    groups = [
        DonorGroup(label=label, amount=round(entry["amount"], 2), donors=entry["donors"])
        for label, entry in totals.items()
    ]
    groups.sort(key=lambda g: g.amount, reverse=True)
    return groups[:MAX_DONOR_GROUPS]


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

        # Donor detail is a deep sweep: several aggregate calls plus a paged scan
        # per candidate. It is skipped on the demo key for the same reason the
        # schedule E and filings sweeps are — the shared key 429s long before it
        # finishes, and a partial donor list is worse than none.
        if not USING_DEMO_KEY:
            record.donors = _donor_detail(record.committee_id, warnings)

    return record


# One page is 100 rows; twenty pages is 2,000 expenditures, comfortably more than
# a Senate race files in a cycle. The budget exists so a pagination change cannot
# spin, and the log says when it was reached rather than quietly truncating.
SCHEDULE_E_PAGE_BUDGET = 20


def _schedule_e_rows(fec_id: str, candidate_id: str, warnings: list[str]) -> list[dict]:
    """Every independent expenditure for or against one candidate this cycle.

    Read row by row rather than from the by_candidate aggregate, because that
    aggregate proved wrong in two different ways on the first live run with a real
    key: it ignored support_oppose_indicator for Marshall, returning the identical
    $214,014.88 as both supporting and opposing him, and it returned nothing at all
    for Hamilton, who had over $1.1M of television placed against him in the same
    data. Each row here carries its own indicator, and those were correct for both
    candidates — the recent list showed S for Marshall's and O for Hamilton's — so
    the split is derived from the rows that demonstrably work.

    Paginated, because totals summed from one page would understate the race.
    """
    rows: list[dict] = []
    seen: set[tuple] = set()
    params: dict = {
        "candidate_id": fec_id,
        "cycle": FEC_CYCLE,
        "sort": "-expenditure_date",
        "per_page": 100,
    }
    reported: int | None = None

    for page in range(SCHEDULE_E_PAGE_BUDGET):
        try:
            payload = _get("/schedules/schedule_e/", params)
        except SourceError as exc:
            warnings.append(
                f"{candidate_id}: schedule E page {page + 1} unavailable ({exc})"
            )
            break

        page_rows = payload.get("results") or []
        pagination = payload.get("pagination") or {}
        if reported is None:
            reported = pagination.get("count")

        fresh = 0
        for row in page_rows:
            fingerprint = _expenditure_fingerprint(row)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rows.append(row)
            fresh += 1

        # A page that repeats itself means the cursor never advanced. Without this
        # the budget is spent refetching page one, and the row count looks healthy.
        if not page_rows or fresh == 0:
            break

        # openFEC hands back the exact query parameters for the next page. Falling
        # back to plain page numbers keeps this working if that changes shape.
        last = pagination.get("last_indexes")
        params = {**params, **last} if isinstance(last, dict) and last else {
            **params,
            "page": page + 2,
        }

    if reported and len(rows) < reported:
        warnings.append(
            f"{candidate_id}: read {len(rows)} of {reported} schedule E rows before the "
            f"{SCHEDULE_E_PAGE_BUDGET}-page budget ran out — outside-spending totals "
            "for this candidate are a floor, not a total"
        )
    return rows


def _expenditure_fingerprint(row: dict) -> tuple:
    """Identity of one expenditure, for paging and de-duplication.

    sub_id is the FEC's own unique row id when present. The fallback matters: the
    live run published two identical $586,399 television placements dated
    2026-08-06, which amendments and re-filings legitimately produce.
    """
    sub_id = row.get("sub_id")
    if sub_id:
        return ("sub_id", str(sub_id))
    return (
        "composite",
        row.get("committee_id"),
        row.get("expenditure_date"),
        round(_as_float(row.get("expenditure_amount")), 2),
        row.get("support_oppose_indicator"),
        row.get("expenditure_description"),
    )


def _committee_names(committee_ids: list[str], warnings: list[str]) -> dict[str, str]:
    """Look up committee names, which the per-expenditure rows do not carry.

    This is why every recent row read "Unidentified committee" while the
    top-spender list beside it had real names: the aggregate response includes the
    name and the row-level response does not. Only the committees actually about
    to be displayed are looked up.
    """
    if not committee_ids:
        return {}
    try:
        payload = _get("/committees/", {"committee_id": committee_ids, "per_page": 100})
    except SourceError as exc:
        warnings.append(f"committee names unavailable ({exc})")
        return {}
    return {
        row["committee_id"]: row["name"]
        for row in payload.get("results", [])
        if row.get("committee_id") and row.get("name")
    }


def outside_spending(fec_ids: dict[str, str], warnings: list[str]) -> OutsideSpending:
    """Independent expenditures for and against each candidate."""
    result = OutsideSpending()
    spenders: dict[str, dict] = {}
    expenditures: list[tuple[str, dict]] = []
    unlabelled = 0

    for candidate_id, fec_id in fec_ids.items():
        for row in _schedule_e_rows(fec_id, candidate_id, warnings):
            indicator = (row.get("support_oppose_indicator") or "").upper()[:1]
            if indicator not in ("S", "O"):
                # Never guess a side. The previous code defaulted to "O", which
                # would file money supporting a candidate as money against them.
                unlabelled += 1
                continue

            amount = _as_float(row.get("expenditure_amount"))
            bucket = result.supporting if indicator == "S" else result.opposing
            bucket[candidate_id] = bucket.get(candidate_id, 0.0) + amount

            committee_id = row.get("committee_id")
            if committee_id:
                entry = spenders.setdefault(
                    committee_id, {"amount": 0.0, "supports": None, "opposes": None}
                )
                entry["amount"] += amount
                entry["supports" if indicator == "S" else "opposes"] = candidate_id

            expenditures.append((candidate_id, row))

    if unlabelled:
        warnings.append(
            f"{unlabelled} schedule E row(s) carried no support/oppose indicator and "
            "were left out rather than assigned a side"
        )

    for bucket in (result.supporting, result.opposing):
        for key, value in list(bucket.items()):
            bucket[key] = round(value, 2)
    result.total = round(sum(result.supporting.values()) + sum(result.opposing.values()), 2)

    ranked = sorted(spenders.items(), key=lambda kv: kv[1]["amount"], reverse=True)
    top = ranked[:MAX_TOP_SPENDERS]
    recent_rows = _deduplicated(expenditures)[:MAX_RECENT_EXPENDITURES]
    wanted = {committee_id for committee_id, _ in top} | {
        row.get("committee_id") for _, row in recent_rows if row.get("committee_id")
    }
    names = _committee_names(sorted(wanted), warnings)

    result.top_spenders = [
        TopSpender(
            committee_name=names.get(committee_id, "Unidentified committee"),
            committee_id=committee_id,
            amount=round(entry["amount"], 2),
            supports=entry["supports"],
            opposes=entry["opposes"],
        )
        for committee_id, entry in top
    ]

    result.recent = [
        IndependentExpenditure(
            date=_as_date(row.get("expenditure_date")),
            committee_id=row.get("committee_id"),
            committee_name=(
                row.get("committee_name")
                or names.get(row.get("committee_id") or "")
                or "Unidentified committee"
            ),
            amount=_as_float(row.get("expenditure_amount")),
            support_oppose=(row.get("support_oppose_indicator") or "").upper()[:1],
            candidate_id=candidate_id,
            purpose=row.get("expenditure_description"),
        )
        for candidate_id, row in recent_rows
    ]
    return result


def _deduplicated(expenditures: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Newest first, with repeated filings of the same expenditure collapsed."""
    dated = [
        (candidate_id, row)
        for candidate_id, row in expenditures
        if _as_date(row.get("expenditure_date")) is not None
    ]
    dated.sort(key=lambda item: _as_date(item[1].get("expenditure_date")), reverse=True)

    seen: set[tuple] = set()
    out: list[tuple[str, dict]] = []
    for candidate_id, row in dated:
        fingerprint = (candidate_id, _expenditure_fingerprint(row))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append((candidate_id, row))
    return out


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


# Fields that decide whether a donor's rows may be summed. memo_code is the one
# that matters most: the FEC marks a transaction "X" when it is informational and
# already counted on another line, and openFEC's own aggregate endpoints exclude
# those. Earmarked money routed through a conduit appears twice by design — once
# as the conduit's contribution and once attributed to the original donor — so
# whether to keep or drop a memo row depends on which of the pair the filer put
# it on, and that cannot be settled without looking.
PROBE_FIELDS = (
    "sub_id",
    "contribution_receipt_date",
    "contribution_receipt_amount",
    "contributor_aggregate_ytd",
    "memo_code",
    "memo_text",
    "receipt_type",
    "receipt_type_desc",
    "line_number",
    "committee_id",
    "contributor_id",
    "is_individual",
    "fec_election_type_desc",
)


def diagnose() -> str:
    """Dump the raw rows behind the largest donors, for a total that looks wrong.

    Marshall's top five donors each came back at exactly $31,500 across exactly
    three gifts — five different people in five different states, an identical
    figure repeating, which is the shape a double count makes. $10,500 apiece is
    above the per-election individual limit, so joint-fundraising or conduit
    structure is the innocent explanation and memo-coded duplicates are the guilty
    one. Both are visible in the raw fields and neither is visible in a total, so
    this prints the rows rather than reasoning about them.
    """
    lines = ["Donor probe", "=" * 72]
    if USING_DEMO_KEY:
        lines.append("No FEC_API_KEY set. This probe needs a real key.")
        return "\n".join(lines)

    warnings: list[str] = []
    for candidate in CANDIDATES:
        lines.append(f"\n[{candidate.name}]")
        fec_id = resolve_candidate_id(candidate.name, candidate.fec_candidate_id)
        if not fec_id:
            lines.append("  candidate id did not resolve")
            continue
        committee_id, committee_name = _principal_committee(fec_id)
        lines.append(f"  {fec_id} -> {committee_id} ({committee_name})")
        if not committee_id:
            continue

        donors, coverage = _large_donors(committee_id, warnings)
        lines.append(f"  coverage: {coverage}")
        if not donors:
            lines.append("  no donors at or above the threshold")
            continue

        for donor in donors[:3]:
            lines.append(f"\n  == {donor.name} — ${donor.amount:,.2f} over {donor.gifts} gift(s)")
            try:
                payload = _get(
                    "/schedules/schedule_a/",
                    {
                        "committee_id": committee_id,
                        "two_year_transaction_period": FEC_CYCLE,
                        "contributor_name": donor.name,
                        "per_page": 30,
                    },
                )
            except SourceError as exc:
                lines.append(f"     lookup failed: {exc}")
                continue

            rows = payload.get("results") or []
            count = (payload.get("pagination") or {}).get("count")
            lines.append(f"     {len(rows)} row(s) returned, api count={count}")
            for row in rows:
                shown = {key: row.get(key) for key in PROBE_FIELDS if row.get(key) is not None}
                lines.append(f"     - {shown}")

            memo = [r for r in rows if r.get("memo_code")]
            plain = [r for r in rows if not r.get("memo_code")]
            lines.append(
                f"     memo-coded: {len(memo)} totalling "
                f"${sum(_as_float(r.get('contribution_receipt_amount')) for r in memo):,.2f}"
            )
            lines.append(
                f"     un-memoed:  {len(plain)} totalling "
                f"${sum(_as_float(r.get('contribution_receipt_amount')) for r in plain):,.2f}"
            )
            sub_ids = [r.get("sub_id") for r in rows]
            lines.append(
                f"     distinct sub_ids: {len({s for s in sub_ids if s})} of {len(sub_ids)}"
            )

    if warnings:
        lines.append("\nwarnings:")
        lines.extend(f"  - {w}" for w in warnings)
    return "\n".join(lines)
