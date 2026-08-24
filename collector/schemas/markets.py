"""markets.json — prediction-market implied probabilities.

This is the app's only genuinely minute-to-minute number. It is a probability
of winning, never a vote share, and the app must never label it as one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .common import Attribution, Payload, Strict


class Market(Strict):
    platform: str = Field(description="kalshi | polymarket")
    market_id: str
    title: str | None = None
    url: str | None = None
    marshall: float = Field(ge=0.0, le=1.0)
    hamilton: float = Field(ge=0.0, le=1.0)
    volume_usd: float | None = None
    open_interest: float | None = None
    last_trade_at: datetime | None = None
    fetched_at: datetime


class MarketPoint(Strict):
    t: datetime
    marshall: float
    hamilton: float


class Consensus(Strict):
    """Volume-weighted blend across platforms."""

    as_of: datetime
    marshall: float
    hamilton: float
    platforms: list[str]
    change_1h: float | None = None
    change_24h: float | None = None
    change_7d: float | None = None
    history: list[MarketPoint] = []


class MarginBucket(Strict):
    """One band of the implied winning margin, and its probability."""

    label: str = Field(description="Human-readable band, e.g. 'Marshall by 5-7'.")
    candidate_id: str | None = Field(
        default=None, description="Who wins in this band; null if it spans both."
    )
    low: float | None = Field(default=None, description="Lower margin bound, points.")
    high: float | None = Field(
        default=None, description="Upper bound; null for the open-ended top band."
    )
    probability: float = Field(ge=0.0, le=1.0)


class MarginDistribution(Strict):
    """The winning margin implied by Kalshi's margin-threshold ladder.

    Each rung prices "will the margin be at least N points", so the ladder is a
    survival curve and the difference between adjacent rungs is the probability
    of landing in that band. That is subtraction on a monotone curve, not a model.

    Two properties are worth stating because they are what makes this publishable.
    The bands sum to one, and they do so using a win probability derived from an
    entirely separate market — the governor-by-senate combination grid — so the
    ladder and the grid cross-check each other. And the resolution is asymmetric:
    the exchange lists margin rungs for one party only, so the other side is a
    single band with no detail inside it.
    """

    median_margin: float | None = Field(
        default=None,
        description="Margin where the survival curve crosses 0.5, interpolated.",
    )
    leader: str | None = Field(default=None, description="Candidate the median favours.")
    buckets: list[MarginBucket] = []
    rungs: int = Field(default=0, description="Threshold markets the ladder was built from.")
    detailed_side: str | None = Field(
        default=None,
        description="Candidate whose margins are itemised; the other is one band.",
    )
    note: str = Field(
        default=(
            "Bands come from market prices for 'will the margin be at least N "
            "points'. The exchange lists those rungs for one candidate only, so the "
            "other side appears as a single band."
        ),
        description="Shown on screen wherever the distribution appears.",
    )


class MarketsPayload(Payload):
    markets: list[Market] = []
    consensus: Consensus | None = None
    margin: MarginDistribution | None = None
    attribution: list[Attribution] = []
    disclaimer: str = (
        "Prediction-market prices are an implied probability of winning, "
        "not a projected vote share."
    )
