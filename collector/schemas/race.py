"""race.json — who is running, when, and how handicappers see it."""

from __future__ import annotations

from datetime import date

from .common import Candidate, Payload, Rating


class RacePayload(Payload):
    election_date: date
    days_until_election: int
    state: str = "KS"
    office: str = "U.S. Senate"
    candidates: list[Candidate]
    ratings: list[Rating] = []
