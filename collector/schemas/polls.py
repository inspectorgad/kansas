"""polls.json — individual public polls plus the aggregate we compute ourselves.

We do not republish anyone else's polling average. Ours is defined in
docs/METHODOLOGY.md and computed in collector/aggregate/polls.py.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .common import Attribution, CandidatePair, Party, Payload, Strict


class Poll(Strict):
    id: str = Field(description="Stable hash of pollster + field dates, for dedup.")
    pollster: str
    sponsor: str | None = None
    partisan: Party | None = Field(
        default=None,
        description="Set when the poll was sponsored by a campaign or aligned group. "
        "Surfaced as a label in the app and down-weighted in the aggregate.",
    )
    start_date: date
    end_date: date
    sample_size: int | None = None
    population: str | None = Field(
        default=None, description="LV, RV, or A (adults)."
    )
    margin_of_error: float | None = None
    results: CandidatePair
    other: float | None = None
    undecided: float | None = None
    url: str | None = None
    added_at: datetime | None = Field(
        default=None, description="When the collector first saw this poll."
    )


class AggregatePoint(Strict):
    """One day of the aggregate time series, for the trend chart."""

    date: date
    marshall: float
    hamilton: float
    margin: float
    n_polls: int


class Aggregate(Strict):
    as_of: datetime
    method: str
    marshall: float
    hamilton: float
    margin: float = Field(description="Positive means Marshall leads.")
    leader: str
    band: float = Field(
        description="Half-width of the uncertainty band, in points."
    )
    n_polls_used: int
    trend_7d: float | None = Field(
        default=None, description="Change in margin over the last 7 days."
    )
    history: list[AggregatePoint] = []


class PollsPayload(Payload):
    polls: list[Poll]
    aggregate: Aggregate | None = None
    attribution: list[Attribution] = []
