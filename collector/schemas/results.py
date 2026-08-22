"""results.json — election-night returns.

Dormant with status "pending" until the Kansas Secretary of State's election
night reporting site goes live at 5pm on November 3, 2026.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from .common import Attribution, Payload, Strict


class ResultsStatus(str, Enum):
    PENDING = "pending"
    LIVE = "live"
    FINAL = "final"


class CandidateResult(Strict):
    candidate_id: str
    votes: int = 0
    pct: float = 0.0


class CountyResult(Strict):
    county: str
    marshall_votes: int = 0
    hamilton_votes: int = 0
    other_votes: int = 0
    total_votes: int = 0
    precincts_reporting: int | None = None
    precincts_total: int | None = None
    pct_reporting: float | None = None


class ResultsPayload(Payload):
    status: ResultsStatus = ResultsStatus.PENDING
    statewide: list[CandidateResult] = []
    total_votes: int = 0
    precincts_reporting: int | None = None
    precincts_total: int | None = None
    pct_reporting: float | None = None
    counties: list[CountyResult] = []
    called: bool = False
    called_for: str | None = None
    last_updated: datetime | None = None
    source_url: str | None = None
    attribution: list[Attribution] = []
