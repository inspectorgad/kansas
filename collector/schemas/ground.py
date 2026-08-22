"""ground.json — voter registration and advance-ballot returns.

Coverage is deliberately honest: Kansas publishes no statewide daily
advance-vote feed, so ballot returns cover only the counties that run their
own public dashboards. The app labels this rather than implying a full picture.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .common import Attribution, Payload, Strict


class CountyRegistration(Strict):
    county: str
    republican: int = 0
    democrat: int = 0
    unaffiliated: int = 0
    libertarian: int = 0
    total: int = 0


class Registration(Strict):
    as_of: date | None = None
    statewide: CountyRegistration | None = None
    by_county: list[CountyRegistration] = []
    source_url: str | None = None


class CountyAdvance(Strict):
    county: str
    mail_ballots_sent: int | None = None
    mail_ballots_returned: int | None = None
    in_person_votes: int | None = None
    total_advance: int | None = None
    party_breakdown: dict[str, int] | None = None
    as_of: datetime | None = None
    source_url: str | None = None


class AdvanceBallots(Strict):
    coverage_note: str = (
        "Kansas publishes no statewide daily advance-vote feed. These figures "
        "cover only counties that operate a public dashboard."
    )
    counties_covered: list[str] = []
    counties: list[CountyAdvance] = []


class GroundPayload(Payload):
    registration: Registration = Registration()
    advance_ballots: AdvanceBallots = AdvanceBallots()
    attribution: list[Attribution] = []
