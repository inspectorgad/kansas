"""Shared primitives for the Kansas Senate 2026 data contract.

Every JSON file the collector publishes is defined by a model in this package.
The Kotlin @Serializable DTOs in the Android app mirror these one-for-one; the
`contract-check` CI job fails the build if the two drift apart.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

# The two candidates on the November ballot. Used as stable JSON keys
# everywhere, so these strings are part of the public contract.
MARSHALL = "marshall"
HAMILTON = "hamilton"
CANDIDATE_IDS = (MARSHALL, HAMILTON)

ELECTION_DATE = date(2026, 11, 3)


class Party(StrEnum):
    REPUBLICAN = "R"
    DEMOCRAT = "D"
    LIBERTARIAN = "L"
    INDEPENDENT = "I"
    UNAFFILIATED = "U"


class Strict(BaseModel):
    """Base model: reject unknown fields so upstream shape changes fail loudly."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Payload(Strict):
    """Base for every top-level published file."""

    schema_version: int = SCHEMA_VERSION
    generated_at: datetime


class Attribution(Strict):
    """Credit and licensing for a data source, surfaced in the app's Settings."""

    name: str
    url: str
    license: str | None = None
    note: str | None = None


class CandidatePair(Strict):
    """A value for each candidate. The workhorse shape of this contract."""

    marshall: float
    hamilton: float

    def margin(self) -> float:
        """Positive means Marshall leads."""
        return self.marshall - self.hamilton

    def leader(self) -> str:
        return MARSHALL if self.marshall >= self.hamilton else HAMILTON


class Candidate(Strict):
    id: str
    name: str
    party: Party
    incumbent: bool = False
    fec_candidate_id: str | None = None
    committee_id: str | None = None
    website: str | None = None


class Rating(Strict):
    """A handicapper's race rating, e.g. Cook's "Likely R"."""

    source: str
    rating: str
    lean: Party | None = None
    as_of: date | None = None
    url: str | None = None
    previous: str | None = Field(
        default=None, description="Prior rating, set when the source moves the race."
    )
    entered_by_hand: bool = Field(
        default=False,
        description=(
            "True when a person typed this rather than a scraper reading it. The "
            "app labels these, because a hand-copied figure and a live one carry "
            "different guarantees and must not look alike."
        ),
    )
