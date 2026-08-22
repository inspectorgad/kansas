"""The published JSON contract for the Kansas Senate 2026 tracker.

One model per published file. `FILES` maps each output filename to its model,
and is what the publisher and the contract-check CI job both iterate over.
"""

from . import ads, common, finance, ground, markets, news, polls, race, results  # noqa: F401
from .ads import AdsPayload
from .common import (
    CANDIDATE_IDS,
    ELECTION_DATE,
    HAMILTON,
    MARSHALL,
    SCHEMA_VERSION,
    Attribution,
    Candidate,
    CandidatePair,
    Party,
    Payload,
    Rating,
    Strict,
)
from .finance import FinancePayload
from .ground import GroundPayload
from .markets import MarketsPayload
from .news import NewsPayload
from .polls import PollsPayload
from .race import RacePayload
from .results import ResultsPayload

FILES: dict[str, type[Payload]] = {
    "race.json": RacePayload,
    "polls.json": PollsPayload,
    "markets.json": MarketsPayload,
    "finance.json": FinancePayload,
    "news.json": NewsPayload,
    "ads.json": AdsPayload,
    "ground.json": GroundPayload,
    "results.json": ResultsPayload,
}

__all__ = [
    "ads",
    "common",
    "finance",
    "ground",
    "markets",
    "news",
    "polls",
    "race",
    "results",
    "FILES",
    "SCHEMA_VERSION",
    "CANDIDATE_IDS",
    "ELECTION_DATE",
    "MARSHALL",
    "HAMILTON",
    "Attribution",
    "Candidate",
    "CandidatePair",
    "Party",
    "Payload",
    "Rating",
    "Strict",
    "AdsPayload",
    "FinancePayload",
    "GroundPayload",
    "MarketsPayload",
    "NewsPayload",
    "PollsPayload",
    "RacePayload",
    "ResultsPayload",
]
