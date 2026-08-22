"""ads.json — broadcast ad buys from the FCC political file, plus digital spend."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .common import Attribution, Payload, Strict


class AdFiling(Strict):
    id: str
    station: str
    market: str | None = None
    advertiser: str
    side: str | None = Field(
        default=None,
        description="candidate_id the buy supports, or null when unattributed.",
    )
    is_outside_group: bool = False
    amount: float | None = None
    flight_start: date | None = None
    flight_end: date | None = None
    filed_at: datetime | None = None
    url: str | None = None


class WeeklySpend(Strict):
    week_start: date
    marshall: float = 0.0
    hamilton: float = 0.0
    outside: float = 0.0


class MarketSpend(Strict):
    market: str
    marshall: float = 0.0
    hamilton: float = 0.0
    outside: float = 0.0


class BroadcastAds(Strict):
    total_by_side: dict[str, float] = {}
    by_week: list[WeeklySpend] = []
    by_market: list[MarketSpend] = []
    filings: list[AdFiling] = []


class DigitalAds(Strict):
    available: bool = False
    unavailable_reason: str | None = None
    total_by_side: dict[str, float] = {}
    by_page: list[dict] = []


class AdsPayload(Payload):
    broadcast: BroadcastAds = BroadcastAds()
    digital: DigitalAds = DigitalAds()
    attribution: list[Attribution] = []
