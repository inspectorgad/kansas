"""Broadcast ad buys from the FCC political file, and digital spend from Meta.

Two honest caveats are built into the output rather than left to a footnote.

First, broadcast totals are a **floor, not a total**. The FCC political file
covers licensed broadcast stations. Cable, streaming, digital, radio networks and
mail largely do not appear, and in a modern Senate race those carry a large share
of the spend.

Second, attributing a buy to a candidate is inference. Station filings name the
*advertiser* — often a super PAC with a name like "Sunflower Values Fund" that
says nothing about who it helps. We attribute only what we can justify: a filing
naming a candidate or their authorised committee. Everything else is reported as
unattributed rather than guessed into one column.

The FCC endpoint shape could not be verified where this was written, so
`probe()` reports what the API actually returns and the live-check CI job is the
arbiter.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from config import (
    FCC_ENABLED,
    FCC_PUBLIC_FILES_API,
    KANSAS_MEDIA_MARKETS,
    META_ACCESS_TOKEN,
    META_AD_LIBRARY_API,
    SURNAMES,
)
from fetch import SourceError, get_json
from schemas import HAMILTON, MARSHALL, Attribution
from schemas.ads import AdFiling, BroadcastAds, DigitalAds, MarketSpend, WeeklySpend

FCC_ATTRIBUTION = Attribution(
    name="FCC Online Public Inspection File",
    url="https://publicfiles.fcc.gov/",
    license="U.S. Government work, public domain",
    note="Licensed broadcast stations only. Cable, streaming, digital and mail are not covered.",
)
META_ATTRIBUTION = Attribution(
    name="Meta Ad Library",
    url="https://www.facebook.com/ads/library/",
)

# Committee names that identify an authorised campaign buy rather than an
# outside group. Anything else naming a candidate is treated as outside money.
AUTHORISED_MARKERS = ("for kansas", "for senate", "for us senate", "committee to elect")

MONEY = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")

# The OPIF API's paths are not something to guess at once and give up on: the
# first live run took a 404 on a single assumed path. These are tried in order
# and the probe reports which, if any, answers.
FACILITY_SEARCH_PATHS = (
    "/api/service/facility/search/state/{state}.json",
    "/api/manager/search/facilities.json?state={state}",
    "/api/service/facility/search/state/{state}",
    "/api/facility/search/state/{state}.json",
)

POLITICAL_FILE_PATHS = (
    "/api/service/{service}/facility/{facility_id}/politicalfiles.json",
    "/api/service/{service}/facility/{facility_id}/political-files.json",
    "/api/service/{service}/facility/{facility_id}/folder/politicalfiles.json",
)


@dataclass
class AdsResult:
    broadcast: BroadcastAds = field(default_factory=BroadcastAds)
    digital: DigitalAds = field(default_factory=DigitalAds)
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def filing_id(station: str, advertiser: str, when: date | None, amount: float | None) -> str:
    key = f"{station}|{advertiser}|{when}|{amount}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def parse_money(text: str | None) -> float | None:
    """Read a dollar figure out of free text. Returns None rather than zero.

    Zero and "unknown" mean different things here: a $0 buy is a real filing
    (often a correction), while an unparseable amount must not be counted as one.
    """
    if not text:
        return None
    match = MONEY.search(str(text))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def attribute(advertiser: str) -> tuple[str | None, bool]:
    """Work out which candidate a buy helps, and whether it is an outside group.

    Returns (candidate_id, is_outside_group). A name we cannot justify attributing
    yields (None, True) and is reported as unattributed — never folded into a
    candidate's column on a hunch.
    """
    lowered = (advertiser or "").lower()
    named = [cid for surname, cid in SURNAMES.items() if surname in lowered]

    if len(named) != 1:
        # Nobody named, or an attack ad naming both. Either way we cannot say
        # who it helps from the advertiser field alone.
        return None, True

    candidate_id = named[0]
    authorised = any(marker in lowered for marker in AUTHORISED_MARKERS)
    return candidate_id, not authorised


def week_start(day: date) -> date:
    """Monday of the week containing `day`, so buys bucket consistently."""
    return day - timedelta(days=day.weekday())


def aggregate(filings: list[AdFiling]) -> BroadcastAds:
    """Roll filings up by side, week and media market."""
    by_side: dict[str, float] = {}
    weekly: dict[date, dict[str, float]] = {}
    markets: dict[str, dict[str, float]] = {}

    for filing in filings:
        amount = filing.amount
        if amount is None:
            continue

        # An outside buy is tracked separately from the campaign's own money.
        bucket = "outside" if filing.is_outside_group else (filing.side or "unattributed")
        by_side[bucket] = by_side.get(bucket, 0.0) + amount

        # The candidate columns of the weekly and market breakdowns follow the
        # side the money helps, with outside money in its own column.
        column = "outside" if filing.is_outside_group else filing.side
        if column in (MARSHALL, HAMILTON, "outside"):
            if filing.flight_start:
                week = week_start(filing.flight_start)
                weekly.setdefault(week, {})[column] = weekly.setdefault(week, {}).get(column, 0.0) + amount
            if filing.market:
                markets.setdefault(filing.market, {})[column] = (
                    markets.setdefault(filing.market, {}).get(column, 0.0) + amount
                )

    return BroadcastAds(
        total_by_side={k: round(v, 2) for k, v in sorted(by_side.items())},
        by_week=[
            WeeklySpend(
                week_start=week,
                marshall=round(columns.get(MARSHALL, 0.0), 2),
                hamilton=round(columns.get(HAMILTON, 0.0), 2),
                outside=round(columns.get("outside", 0.0), 2),
            )
            for week, columns in sorted(weekly.items())
        ],
        by_market=[
            MarketSpend(
                market=market,
                marshall=round(columns.get(MARSHALL, 0.0), 2),
                hamilton=round(columns.get(HAMILTON, 0.0), 2),
                outside=round(columns.get("outside", 0.0), 2),
            )
            for market, columns in sorted(markets.items())
        ],
        filings=sorted(filings, key=lambda f: (f.filed_at or datetime.min.replace(tzinfo=UTC)), reverse=True)[:200],
    )


def _as_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _facility_search(state: str) -> tuple[dict | None, str | None]:
    """Try each known facility-search path; return the first that answers."""
    for template in FACILITY_SEARCH_PATHS:
        path = template.format(state=state)
        try:
            payload = get_json(f"{FCC_PUBLIC_FILES_API}{path}")
        except SourceError:
            continue
        if isinstance(payload, dict):
            return payload, path
    return None, None


def _political_file(service: str, facility_id: object) -> dict | None:
    for template in POLITICAL_FILE_PATHS:
        path = template.format(service=service, facility_id=facility_id)
        try:
            payload = get_json(f"{FCC_PUBLIC_FILES_API}{path}")
        except SourceError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def fetch_broadcast(warnings: list[str]) -> list[AdFiling]:
    """Pull political-file entries for Kansas broadcast stations.

    The OPIF API's exact response shape is unverified here, so this reads
    defensively: any field it cannot find is left null rather than defaulted, and
    a station that cannot be read is a warning rather than a failed run.
    """
    filings: list[AdFiling] = []

    facilities, used_path = _facility_search("KS")
    if facilities is None:
        raise SourceError(
            "no FCC facility-search path answered for Kansas "
            f"(tried {len(FACILITY_SEARCH_PATHS)}); run --probe-ads"
        )

    rows = facilities.get("results") or facilities.get("facilities") or []
    if not rows:
        raise SourceError(
            f"FCC facility search at {used_path} returned no Kansas stations — "
            "the response shape has probably changed; run --probe-ads"
        )

    for facility in rows[:60]:  # bounded: a full sweep is hundreds of requests
        facility_id = facility.get("id") or facility.get("facilityId")
        call_sign = facility.get("callSign") or facility.get("call_sign") or str(facility_id)
        service = (facility.get("service") or "tv").lower()
        market = facility.get("market") or facility.get("dma")
        if market and market not in KANSAS_MEDIA_MARKETS:
            market = market  # keep whatever the API says; the list is a hint only
        if not facility_id:
            continue

        documents = _political_file(service, facility_id)
        if documents is None:
            warnings.append(f"{call_sign}: no political-file path answered")
            continue

        for entry in documents.get("results") or documents.get("documents") or []:
            advertiser = (
                entry.get("advertiser")
                or entry.get("candidateName")
                or entry.get("name")
                or ""
            )
            if not advertiser:
                continue
            side, is_outside = attribute(advertiser)
            if side is None and not _mentions_race(advertiser, entry):
                continue  # a political file entry about some other contest

            amount = parse_money(
                entry.get("grossAmount") or entry.get("amount") or entry.get("total")
            )
            flight_start = _as_date(entry.get("flightStartDate") or entry.get("startDate"))
            filed_at = None
            raw_filed = entry.get("lastUpdate") or entry.get("createTs")
            if raw_filed:
                try:
                    filed_at = datetime.fromisoformat(str(raw_filed).replace("Z", "+00:00"))
                except ValueError:
                    filed_at = None

            filings.append(
                AdFiling(
                    id=filing_id(call_sign, advertiser, flight_start, amount),
                    station=call_sign,
                    market=market,
                    advertiser=advertiser,
                    side=side,
                    is_outside_group=is_outside,
                    amount=amount,
                    flight_start=flight_start,
                    flight_end=_as_date(entry.get("flightEndDate") or entry.get("endDate")),
                    filed_at=filed_at,
                    url=entry.get("href") or entry.get("url"),
                )
            )

    return filings


def _mentions_race(advertiser: str, entry: dict) -> bool:
    text = f"{advertiser} {entry.get('office', '')} {entry.get('race', '')}".lower()
    return "senate" in text or any(surname in text for surname in SURNAMES)


def fetch_digital(warnings: list[str]) -> DigitalAds:
    """Meta ad spend, when a token exists.

    The Ad Library API needs an approved app and a verified identity, which is
    real friction. Rather than fail, the payload says it is unavailable and why,
    so the app can show that honestly instead of an empty chart.
    """
    if not META_ACCESS_TOKEN:
        return DigitalAds(
            available=False,
            unavailable_reason=(
                "Meta Ad Library access requires an approved app and identity "
                "verification; no token is configured."
            ),
        )

    totals: dict[str, float] = {}
    try:
        payload = get_json(
            META_AD_LIBRARY_API,
            {
                "access_token": META_ACCESS_TOKEN,
                "search_terms": "Marshall Hamilton Kansas Senate",
                "ad_reached_countries": "['US']",
                "ad_type": "POLITICAL_AND_ISSUE_ADS",
                "fields": "page_name,spend,impressions,ad_delivery_start_time",
                "limit": 200,
            },
        )
    except SourceError as exc:
        warnings.append(f"Meta Ad Library unavailable: {exc}")
        return DigitalAds(available=False, unavailable_reason=str(exc))

    pages: list[dict] = []
    for ad in payload.get("data", []):
        page = ad.get("page_name") or "unknown"
        spend = ad.get("spend") or {}
        # Meta reports spend as a range, not a figure. Its midpoint is an
        # estimate and the payload should not imply otherwise.
        low = parse_money(spend.get("lower_bound")) or 0.0
        high = parse_money(spend.get("upper_bound")) or low
        midpoint = (low + high) / 2

        side, _ = attribute(page)
        if side:
            totals[side] = totals.get(side, 0.0) + midpoint
        pages.append({"page": page, "estimated_spend": round(midpoint, 2), "side": side})

    return DigitalAds(
        available=True,
        total_by_side={k: round(v, 2) for k, v in totals.items()},
        by_page=pages[:100],
    )


def collect() -> AdsResult:
    warnings: list[str] = []
    result = AdsResult(warnings=warnings)

    if not FCC_ENABLED:
        warnings.append(
            "broadcast ads disabled: no working FCC facility-search path is known "
            "(run --probe-ads to retry the documented shapes)"
        )
    else:
        try:
            filings = fetch_broadcast(warnings)
            result.broadcast = aggregate(filings)
            if filings:
                result.attribution.append(FCC_ATTRIBUTION)
        except SourceError as exc:
            warnings.append(f"broadcast ads unavailable: {exc}")

    result.digital = fetch_digital(warnings)
    if result.digital.available:
        result.attribution.append(META_ATTRIBUTION)

    return result


def diagnose() -> str:
    """Report which FCC paths answer, and what shape they return."""
    lines = ["FCC political file probe", "=" * 40]

    answered: dict | None = None
    used: str | None = None
    for template in FACILITY_SEARCH_PATHS:
        path = template.format(state="KS")
        try:
            payload = get_json(f"{FCC_PUBLIC_FILES_API}{path}")
        except SourceError as exc:
            lines.append(f"  [MISS] {path}: {exc}")
            continue
        lines.append(f"  [OK  ] {path}")
        if answered is None and isinstance(payload, dict):
            answered, used = payload, path

    if answered is None:
        lines.append("\nNo facility-search path answered. Broadcast ads are not")
        lines.append("collectable until one is found; the payload reports this rather")
        lines.append("than showing an empty chart as though there were no spending.")
        return "\n".join(lines)

    rows = answered.get("results") or answered.get("facilities") or []
    lines.append(f"\nusing {used}")
    lines.append(f"  top-level keys: {sorted(answered)[:10]}")
    lines.append(f"  Kansas stations: {len(rows)}")
    if rows:
        lines.append(f"  first facility keys: {sorted(rows[0])[:15]}")
        facility_id = rows[0].get("id") or rows[0].get("facilityId")
        service = (rows[0].get("service") or "tv").lower()
        lines.append(f"\n  political file for facility {facility_id}:")
        for template in POLITICAL_FILE_PATHS:
            path = template.format(service=service, facility_id=facility_id)
            try:
                get_json(f"{FCC_PUBLIC_FILES_API}{path}")
                lines.append(f"    [OK  ] {path}")
            except SourceError as exc:
                lines.append(f"    [MISS] {path}: {exc}")
    return "\n".join(lines)
