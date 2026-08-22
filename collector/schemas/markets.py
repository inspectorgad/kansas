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


class MarketsPayload(Payload):
    markets: list[Market] = []
    consensus: Consensus | None = None
    attribution: list[Attribution] = []
    disclaimer: str = (
        "Prediction-market prices are an implied probability of winning, "
        "not a projected vote share."
    )
