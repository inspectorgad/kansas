"""Holds the pydantic schemas and the Kotlin DTOs in step.

Several modules on both sides carry a comment saying "a CI check keeps these in
sync". This is that check. Without it the two definitions drift the first time
someone adds a field on one side only, and the symptom is a field that silently
reads as null in the app rather than an error anyone notices.

The Kotlin side is parsed with regexes rather than compiled, because the Android
toolchain is not available where the collector's tests run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import schemas

ANDROID = Path(__file__).resolve().parents[2] / "android" / "app" / "src" / "main" / "java" / "org" / "ksrace" / "senate2026"
PAYLOADS_KT = ANDROID / "data" / "model" / "Payloads.kt"
DATAFILE_KT = ANDROID / "data" / "DataFile.kt"

# Kotlin data class -> pydantic model. Only the shapes that cross the wire.
CLASS_TO_MODEL = {
    "RacePayload": schemas.RacePayload,
    "PollsPayload": schemas.PollsPayload,
    "MarketsPayload": schemas.MarketsPayload,
    "FinancePayload": schemas.FinancePayload,
    "NewsPayload": schemas.NewsPayload,
    "ResultsPayload": schemas.ResultsPayload,
    "AdsPayload": schemas.AdsPayload,
    "GroundPayload": schemas.GroundPayload,
    "AdFiling": schemas.ads.AdFiling,
    "WeeklySpend": schemas.ads.WeeklySpend,
    "MarketSpend": schemas.ads.MarketSpend,
    "BroadcastAds": schemas.ads.BroadcastAds,
    "DigitalAds": schemas.ads.DigitalAds,
    "CountyRegistration": schemas.ground.CountyRegistration,
    "Registration": schemas.ground.Registration,
    "CountyAdvance": schemas.ground.CountyAdvance,
    "AdvanceBallots": schemas.ground.AdvanceBallots,
    "Poll": schemas.polls.Poll,
    "Aggregate": schemas.polls.Aggregate,
    "AggregatePoint": schemas.polls.AggregatePoint,
    "Market": schemas.markets.Market,
    "MarketPoint": schemas.markets.MarketPoint,
    "Consensus": schemas.markets.Consensus,
    "MarginDistribution": schemas.markets.MarginDistribution,
    "MarginBucket": schemas.markets.MarginBucket,
    "CandidateFinance": schemas.finance.CandidateFinance,
    "DonorDetail": schemas.finance.DonorDetail,
    "DonorGroup": schemas.finance.DonorGroup,
    "SizeBucket": schemas.finance.SizeBucket,
    "LargeDonor": schemas.finance.LargeDonor,
    "CommitteeDonor": schemas.finance.CommitteeDonor,
    "AffiliatedCommittee": schemas.finance.AffiliatedCommittee,
    "IndependentExpenditure": schemas.finance.IndependentExpenditure,
    "TopSpender": schemas.finance.TopSpender,
    "OutsideSpending": schemas.finance.OutsideSpending,
    "Filing": schemas.finance.Filing,
    "NewsItem": schemas.news.NewsItem,
    "CandidateResult": schemas.results.CandidateResult,
    "CountyResult": schemas.results.CountyResult,
    "Candidate": schemas.common.Candidate,
    "Rating": schemas.common.Rating,
    "Attribution": schemas.common.Attribution,
    "CandidatePair": schemas.common.CandidatePair,
}

# Fields the app deliberately does not model, with the reason.
KOTLIN_MAY_OMIT = {
    # Purely informational on the wire; the app writes its own caption instead.
    ("MarketsPayload", "disclaimer"),
}


def kotlin_classes() -> dict[str, set[str]]:
    """Map each Kotlin data class to the wire field names it declares."""
    source = PAYLOADS_KT.read_text()
    classes: dict[str, set[str]] = {}

    # Each `data class Name(` ... `)` block, up to the closing paren at column 0.
    for match in re.finditer(
        r"data class (\w+)\(\s*(.*?)^\)", source, re.DOTALL | re.MULTILINE
    ):
        name, body = match.group(1), match.group(2)
        fields: set[str] = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("*"):
                continue
            serial = re.search(r'@SerialName\("([^"]+)"\)', line)
            if serial:
                fields.add(serial.group(1))
                continue
            prop = re.search(r"\bval\s+(\w+)\s*:", line)
            if prop:
                fields.add(prop.group(1))
        classes[name] = fields
    return classes


@pytest.fixture(scope="module")
def kotlin() -> dict[str, set[str]]:
    assert PAYLOADS_KT.is_file(), f"missing {PAYLOADS_KT}"
    parsed = kotlin_classes()
    assert parsed, "parsed no data classes out of Payloads.kt — the regex needs updating"
    return parsed


def test_every_mapped_class_exists_in_kotlin(kotlin):
    missing = sorted(set(CLASS_TO_MODEL) - set(kotlin))
    assert not missing, f"Kotlin is missing data classes: {missing}"


@pytest.mark.parametrize("class_name", sorted(CLASS_TO_MODEL))
def test_kotlin_covers_every_published_field(class_name, kotlin):
    """Every field the collector can publish must be readable by the app."""
    model = CLASS_TO_MODEL[class_name]
    published = {
        (field.alias or name)
        for name, field in model.model_fields.items()
    }
    known = kotlin[class_name]
    allowed = {f for (cls, f) in KOTLIN_MAY_OMIT if cls == class_name}

    missing = sorted(published - known - allowed)
    assert not missing, (
        f"{class_name} in Payloads.kt does not read these published fields: {missing}. "
        "Add them to the Kotlin DTO, or list them in KOTLIN_MAY_OMIT with a reason."
    )


@pytest.mark.parametrize("class_name", sorted(CLASS_TO_MODEL))
def test_kotlin_declares_no_field_the_collector_never_sends(class_name, kotlin):
    """A field the app reads but nothing publishes is dead code at best."""
    model = CLASS_TO_MODEL[class_name]
    published = {
        (field.alias or name)
        for name, field in model.model_fields.items()
    }
    # Computed Kotlin-side conveniences are properties, not constructor fields,
    # so anything the regex found really is expected on the wire.
    extra = sorted(kotlin[class_name] - published)
    assert not extra, (
        f"{class_name} in Payloads.kt reads fields the collector never publishes: {extra}"
    )


def test_datafile_enum_matches_the_published_file_list():
    source = DATAFILE_KT.read_text()
    declared = set(re.findall(r'\w+\("([^"]+\.json)"\)', source))
    assert declared == set(schemas.FILES), (
        "DataFile.kt and collector FILES disagree: "
        f"only in Kotlin {sorted(declared - set(schemas.FILES))}, "
        f"only in Python {sorted(set(schemas.FILES) - declared)}"
    )
