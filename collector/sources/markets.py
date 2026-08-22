"""Prediction-market probabilities from Kalshi and Polymarket.

This is the app's only genuinely minute-to-minute number, and the one most
easily misread, so two rules are enforced here rather than left to the UI:

  * Prices are normalised to a probability pair that sums to 1, so a stale or
    one-sided book cannot render as "72% vs 41%".
  * The payload carries an explicit disclaimer that this is a probability of
    winning and not a projected vote share.

Both platforms expose public read endpoints needing no authentication. Either
one being down degrades to the other rather than failing the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from config import KALSHI_API, POLYMARKET_GAMMA_API
from fetch import SourceError, get_json
from schemas import Attribution
from schemas.markets import Consensus, Market, MarketPoint

KALSHI_ATTRIBUTION = Attribution(
    name="Kalshi", url="https://kalshi.com", note="CFTC-regulated event exchange."
)
POLYMARKET_ATTRIBUTION = Attribution(
    name="Polymarket", url="https://polymarket.com", note="Public Gamma API."
)

# Matched against market titles to find this race.
RACE_TERMS = ("kansas",)
SENATE_TERMS = ("senate",)
MARSHALL_TERMS = ("marshall",)
HAMILTON_TERMS = ("hamilton",)


@dataclass
class MarketsResult:
    markets: list[Market]
    consensus: Consensus | None = None
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _matches_race(title: str) -> bool:
    text = (title or "").lower()
    if not any(term in text for term in RACE_TERMS):
        return False
    if any(term in text for term in SENATE_TERMS):
        return True
    # Some titles name the candidates instead of the office.
    return any(t in text for t in MARSHALL_TERMS) and any(t in text for t in HAMILTON_TERMS)


def normalise(marshall: float | None, hamilton: float | None) -> tuple[float, float] | None:
    """Turn raw prices into a probability pair summing to 1.

    A binary market quotes one side; the other is its complement. When both
    sides are quoted they rarely sum to exactly 1 (the spread), so we scale.
    """
    if marshall is None and hamilton is None:
        return None
    if marshall is None:
        marshall = 1.0 - float(hamilton)
    if hamilton is None:
        hamilton = 1.0 - float(marshall)
    total = float(marshall) + float(hamilton)
    if total <= 0:
        return None
    return float(marshall) / total, float(hamilton) / total


def _kalshi_markets(payload: dict) -> list[Market]:
    now = datetime.now(timezone.utc)
    out: list[Market] = []
    for market in payload.get("markets", []):
        title = market.get("title") or market.get("subtitle") or ""
        ticker = market.get("ticker") or ""
        if not _matches_race(f"{title} {ticker}"):
            continue

        # Kalshi quotes cents on the "yes" side of one named outcome.
        yes = market.get("last_price")
        if yes is None:
            yes = market.get("yes_bid")
        if yes is None:
            continue
        probability = float(yes) / 100.0

        subject = f"{title} {market.get('yes_sub_title', '')} {ticker}".lower()
        if any(t in subject for t in MARSHALL_TERMS):
            pair = normalise(probability, None)
        elif any(t in subject for t in HAMILTON_TERMS):
            pair = normalise(None, probability)
        else:
            continue  # a market on this race we cannot attribute to a candidate
        if pair is None:
            continue

        out.append(
            Market(
                platform="kalshi",
                market_id=ticker or str(market.get("id", "")),
                title=title or None,
                url=f"https://kalshi.com/markets/{ticker}" if ticker else None,
                marshall=round(pair[0], 4),
                hamilton=round(pair[1], 4),
                volume_usd=_as_float(market.get("volume")),
                open_interest=_as_float(market.get("open_interest")),
                fetched_at=now,
            )
        )
    return out


def _polymarket_markets(payload: list | dict) -> list[Market]:
    now = datetime.now(timezone.utc)
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    out: list[Market] = []
    for market in rows:
        question = market.get("question") or market.get("title") or ""
        if not _matches_race(question):
            continue

        outcomes = _parse_maybe_json(market.get("outcomes")) or []
        prices = _parse_maybe_json(market.get("outcomePrices")) or []
        if len(outcomes) != len(prices):
            continue

        marshall = hamilton = None
        for outcome, price in zip(outcomes, prices):
            label = str(outcome).lower()
            value = _as_float(price)
            if value is None:
                continue
            if any(t in label for t in MARSHALL_TERMS):
                marshall = value
            elif any(t in label for t in HAMILTON_TERMS):
                hamilton = value
            elif label in ("yes", "no"):
                # A "will X win" market: Yes belongs to whoever the question names.
                subject = question.lower()
                target = "marshall" if any(t in subject for t in MARSHALL_TERMS) else (
                    "hamilton" if any(t in subject for t in HAMILTON_TERMS) else None
                )
                if target is None:
                    continue
                if (label == "yes") == (target == "marshall"):
                    marshall = value
                else:
                    hamilton = value

        pair = normalise(marshall, hamilton)
        if pair is None:
            continue

        slug = market.get("slug")
        out.append(
            Market(
                platform="polymarket",
                market_id=str(market.get("id") or slug or ""),
                title=question or None,
                url=f"https://polymarket.com/event/{slug}" if slug else None,
                marshall=round(pair[0], 4),
                hamilton=round(pair[1], 4),
                volume_usd=_as_float(market.get("volumeNum") or market.get("volume")),
                open_interest=_as_float(market.get("liquidityNum") or market.get("liquidity")),
                fetched_at=now,
            )
        )
    return out


def _parse_maybe_json(value):
    """Polymarket returns some list fields as JSON-encoded strings."""
    import json

    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else None
        except json.JSONDecodeError:
            return None
    return None


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_consensus(
    markets: list[Market], history: list[MarketPoint] | None = None
) -> Consensus | None:
    """Volume-weighted blend across platforms, plus movement over 1h/24h/7d."""
    if not markets:
        return None

    weights = [(m.volume_usd or 0.0) + 1.0 for m in markets]  # +1 so a zero-volume book still counts
    total = sum(weights)
    marshall = sum(m.marshall * w for m, w in zip(markets, weights)) / total
    hamilton = sum(m.hamilton * w for m, w in zip(markets, weights)) / total

    now = datetime.now(timezone.utc)
    series = sorted(history or [], key=lambda p: p.t)

    def change_since(delta: timedelta) -> float | None:
        cutoff = now - delta
        past = [p for p in series if p.t <= cutoff]
        if not past:
            return None
        return round(marshall - past[-1].marshall, 4)

    return Consensus(
        as_of=now,
        marshall=round(marshall, 4),
        hamilton=round(hamilton, 4),
        platforms=sorted({m.platform for m in markets}),
        change_1h=change_since(timedelta(hours=1)),
        change_24h=change_since(timedelta(days=1)),
        change_7d=change_since(timedelta(days=7)),
        history=series + [MarketPoint(t=now, marshall=round(marshall, 4), hamilton=round(hamilton, 4))],
    )


def collect(history: list[MarketPoint] | None = None) -> MarketsResult:
    markets: list[Market] = []
    warnings: list[str] = []
    attribution: list[Attribution] = []

    try:
        payload = get_json(f"{KALSHI_API}/markets", {"status": "open", "limit": 200})
        found = _kalshi_markets(payload)
        markets.extend(found)
        if found:
            attribution.append(KALSHI_ATTRIBUTION)
    except SourceError as exc:
        warnings.append(f"kalshi unavailable: {exc}")

    try:
        payload = get_json(
            f"{POLYMARKET_GAMMA_API}/markets",
            {"closed": "false", "limit": 200, "order": "volumeNum", "ascending": "false"},
        )
        found = _polymarket_markets(payload)
        markets.extend(found)
        if found:
            attribution.append(POLYMARKET_ATTRIBUTION)
    except SourceError as exc:
        warnings.append(f"polymarket unavailable: {exc}")

    if not markets:
        # Leaving the previous markets.json in place and failing loudly beats
        # publishing an empty file: a slightly stale probability is recoverable,
        # a silently missing headline number is not.
        if warnings:
            raise SourceError("; ".join(warnings))
        raise SourceError(
            "both platforms responded but no market matched this race — "
            "market titles have probably changed"
        )

    return MarketsResult(
        markets=markets,
        consensus=build_consensus(markets, history),
        attribution=attribution,
        warnings=warnings,
    )
