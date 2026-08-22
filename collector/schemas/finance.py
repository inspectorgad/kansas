"""finance.json — campaign money from the FEC, including outside spending.

In a race expected to draw ~$50M, outside spending is often the larger half,
so it gets equal billing with the candidates' own committees.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .common import Attribution, Payload, Strict


class CandidateFinance(Strict):
    candidate_id: str
    fec_candidate_id: str | None = None
    committee_id: str | None = None
    committee_name: str | None = None
    coverage_start_date: date | None = None
    coverage_end_date: date | None = Field(
        default=None, description="End of the most recent reporting period."
    )
    total_receipts: float = 0.0
    total_disbursements: float = 0.0
    cash_on_hand: float = 0.0
    debts_owed: float = 0.0
    individual_contributions: float = 0.0
    small_dollar_contributions: float | None = Field(
        default=None, description="Unitemized, i.e. donors under $200."
    )
    pac_contributions: float = 0.0
    in_state_amount: float | None = None
    in_state_pct: float | None = None
    burn_rate_monthly: float | None = Field(
        default=None, description="Mean monthly disbursements this cycle."
    )


class IndependentExpenditure(Strict):
    date: date
    committee_id: str | None = None
    committee_name: str
    amount: float
    support_oppose: str = Field(description="S (supports) or O (opposes).")
    candidate_id: str
    purpose: str | None = None
    url: str | None = None


class TopSpender(Strict):
    committee_name: str
    committee_id: str | None = None
    amount: float
    supports: str | None = None
    opposes: str | None = None


class OutsideSpending(Strict):
    supporting: dict[str, float] = Field(
        default_factory=dict, description="candidate_id -> dollars spent supporting."
    )
    opposing: dict[str, float] = Field(
        default_factory=dict, description="candidate_id -> dollars spent opposing."
    )
    total: float = 0.0
    top_spenders: list[TopSpender] = []
    recent: list[IndependentExpenditure] = []


class Filing(Strict):
    date: date
    committee_name: str
    committee_id: str | None = None
    form_type: str | None = None
    report_type: str | None = None
    coverage_end_date: date | None = None
    total_receipts: float | None = None
    url: str | None = None


class FinancePayload(Payload):
    cycle: int = 2026
    candidates: dict[str, CandidateFinance] = {}
    outside_spending: OutsideSpending = OutsideSpending()
    filings: list[Filing] = []
    attribution: list[Attribution] = []
