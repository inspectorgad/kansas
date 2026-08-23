"""finance.json — campaign money from the FEC, including outside spending.

In a race expected to draw ~$50M, outside spending is often the larger half,
so it gets equal billing with the candidates' own committees.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from .common import Attribution, Payload, Strict


# The itemization threshold is the single most important thing to know when
# reading any of this. Federal law only requires a committee to name a donor once
# that donor passes $200 in aggregate for the cycle; everything under it is
# reported as one unitemized lump with no names attached. So a named-donor list is
# not a sample of a campaign's supporters — it is a census of its larger ones, and
# it under-represents a small-dollar campaign far more than a big-cheque one.
#
# For this race that asymmetry is not hypothetical: Hamilton raises about 70% of
# his money in-state on a small-dollar profile. Any screen showing these fields
# has to say so, which is what `itemized_note` is for — it travels with the data
# rather than living only in a design comment.
class DonorGroup(Strict):
    """Itemized individual money grouped by employer, occupation, or city."""

    label: str
    amount: float
    donors: int = Field(default=0, description="Distinct contributors in the group.")


class SizeBucket(Strict):
    """Itemized individual money by contribution size, from the FEC's own bands."""

    label: str
    amount: float
    count: int = 0


class LargeDonor(Strict):
    """One named individual, summed over their large itemized contributions.

    Named individuals are public record under federal disclosure, but the FEC's
    sale-or-use restriction forbids using contributor information to solicit
    contributions or for commercial purposes. That restriction rides along in the
    payload's attribution rather than being left to whoever reads the file.
    """

    name: str
    city: str | None = None
    state: str | None = None
    employer: str | None = None
    occupation: str | None = None
    amount: float
    gifts: int = Field(default=1, description="Contributions of $1,000 or more.")


class DonorDetail(Strict):
    """Who is funding one candidate, in as much detail as disclosure allows."""

    threshold: float = Field(
        default=1000.0, description="Minimum single contribution in `large_donors`."
    )
    itemized_note: str = Field(
        default=(
            "Federal law itemizes donors only above $200 for the cycle. Smaller "
            "contributions are reported as one unnamed total, so these lists show "
            "a campaign's larger donors and not its typical one."
        ),
        description="Shown on screen wherever donor detail appears.",
    )
    large_donors: list[LargeDonor] = []
    top_employers: list[DonorGroup] = []
    top_occupations: list[DonorGroup] = []
    top_cities: list[DonorGroup] = []
    size_buckets: list[SizeBucket] = []
    itemized_total: float | None = Field(
        default=None, description="Itemized individual contributions this cycle."
    )
    unitemized_total: float | None = Field(
        default=None, description="Contributions under the $200 itemization floor."
    )
    large_donor_coverage: str | None = Field(
        default=None,
        description="How complete `large_donors` is, when it had to be truncated.",
    )


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
    donors: DonorDetail | None = None


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
