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

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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

# Matched against market titles, subtitles and tickers to find this race.
#
# "kansas" alone was too strict: a live run scanned 2,500 open markets and matched
# none, because exchange tickers spell the state "KS" (KXSENATEKS-26) and the
# readable state name often sits on the parent event rather than the market row.
# So a bare "ks" token counts too — a token, not a substring, or anything
# containing "ks" (Knicks, KSS) would qualify.
RACE_TERMS = ("kansas",)
SENATE_TERMS = ("senate", "senator")
MARSHALL_TERMS = ("marshall",)
HAMILTON_TERMS = ("hamilton",)

# "KS" as a standalone word, for prose like "Senate KS 2026". Both boundaries are
# required: a right boundary alone would match "Blackhawks", and Kalshi lists
# plenty of NHL *Senators* markets — "Senators beat the Blackhawks" would then
# satisfy both halves of the test and be collected as this race.
STATE_WORD = re.compile(r"(?:^|[^a-z])ks(?:[^a-z]|$)", re.IGNORECASE)

# Exchange tickers concatenate, so KXSENATEKS-26 never yields a token boundary
# around its "KS". Matching an all-caps token that contains both SEN and KS picks
# those up without loosening the prose rule.
TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")


@dataclass
class MarketsResult:
    markets: list[Market]
    consensus: Consensus | None = None
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ticker_identifies_race(raw: str) -> bool:
    """An all-caps token holding both SEN and KS names the office and the state.

    KXSENATEKS-26 says "Senate" and "Kansas" in one word, so it settles both
    halves of the test at once — which is why this is checked before the state
    and office rules rather than feeding into them.
    """
    return any("SEN" in token and "KS" in token for token in TICKER_TOKEN.findall(raw))


def _mentions_state(text: str) -> bool:
    """Does this text name Kansas, spelled out or abbreviated as a word?"""
    return any(term in text for term in RACE_TERMS) or bool(STATE_WORD.search(text))


def _matches_race(title: str) -> bool:
    """True when this text identifies the Kansas Senate race.

    Requires the state *and* either the office or both candidates. Dropping
    either half is how this goes wrong: state-only would match the Kansas
    governor's race, office-only would match the other 33 Senate contests.
    """
    raw = title or ""
    text = raw.lower()
    if _ticker_identifies_race(raw):
        return True
    if not _mentions_state(text):
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
    now = datetime.now(UTC)
    out: list[Market] = []
    for market in payload.get("markets", []):
        title = market.get("title") or market.get("subtitle") or ""
        ticker = market.get("ticker") or ""
        # The state can sit on any of these: a market row often carries only the
        # candidate name while its parent event holds "Kansas Senate".
        haystack = " ".join(
            str(market.get(key, ""))
            for key in (
                "title", "subtitle", "yes_sub_title", "no_sub_title",
                "ticker", "event_ticker", "series_ticker", "category",
            )
        )
        if not _matches_race(haystack):
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
    now = datetime.now(UTC)
    rows = payload if isinstance(payload, list) else payload.get("data", [])
    out: list[Market] = []
    for market in rows:
        question = market.get("question") or market.get("title") or ""
        haystack = " ".join(
            str(market.get(key, ""))
            for key in ("question", "title", "slug", "groupItemTitle")
        )
        if not _matches_race(haystack):
            continue

        outcomes = _parse_maybe_json(market.get("outcomes")) or []
        prices = _parse_maybe_json(market.get("outcomePrices")) or []
        if len(outcomes) != len(prices):
            continue

        marshall = hamilton = None
        for outcome, price in zip(outcomes, prices, strict=True):
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
    marshall = sum(m.marshall * w for m, w in zip(markets, weights, strict=True)) / total
    hamilton = sum(m.hamilton * w for m, w in zip(markets, weights, strict=True)) / total

    now = datetime.now(UTC)
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


# Gamma caps `limit` at 100 and silently returns 100 for a larger ask. The first
# paginated run requested 200, got 100, and its "short page means last page"
# check ended the loop after page one — so 100 markets were mistaken for the
# whole exchange.
POLYMARKET_PAGE_SIZE = 100
KALSHI_PAGE_SIZE = 200
MAX_PAGES = 12

# Kalshi's open-market list is dominated by sports parlay shards — a live scan of
# 2,400 rows returned nothing but Real Madrid, MLB over/unders and WNBA props.
# Elections are far past any page budget worth spending, so the race is found
# through /events (hundreds of entries, human-readable titles) instead, and these
# combinatorial shards are dropped so a diagnostic sample stays readable.
PARLAY_MARKERS = ("CROSSCATEGORY", "-SHARD", "MULTIVENTURE", "KXMVE")


def _is_parlay(ticker: str) -> bool:
    upper = (ticker or "").upper()
    return any(marker in upper for marker in PARLAY_MARKERS)


def _kalshi_event_markets() -> tuple[list[dict], int]:
    """Find this race through Kalshi's event list rather than its market list.

    Events group markets and number in the hundreds rather than the hundreds of
    thousands, and their titles carry the readable contest name. Scanning markets
    directly cannot work: the open-market list is mostly sports parlays and the
    election contests sit well beyond any sane page budget.
    """
    rows: list[dict] = []
    scanned = 0
    cursor: str | None = None

    for _ in range(MAX_PAGES):
        params: dict[str, object] = {"status": "open", "limit": KALSHI_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI_API}/events", params)
        events = payload.get("events") or []
        scanned += len(events)

        for event in events:
            haystack = " ".join(
                str(event.get(key, ""))
                for key in ("title", "sub_title", "event_ticker", "series_ticker", "category")
            )
            if not _matches_race(haystack):
                continue
            # The event names the race; its markets name the candidates.
            ticker = event.get("event_ticker")
            if not ticker:
                continue
            try:
                detail = get_json(
                    f"{KALSHI_API}/markets", {"event_ticker": ticker, "limit": 100}
                )
            except SourceError:
                continue
            for market in detail.get("markets") or []:
                # Carry the event's title down so candidate rows inherit the race.
                market.setdefault("title", event.get("title", ""))
                rows.append(market)

        cursor = payload.get("cursor") or None
        if not cursor or not events:
            break

    return rows, scanned


def _kalshi_pages() -> tuple[list[dict], int]:
    """Event-first discovery, falling back to a bounded market scan.

    The fallback exists only so a change to /events does not take the source down
    entirely; it is not expected to find anything on its own, for the reason
    above.
    """
    rows, scanned = _kalshi_event_markets()
    if rows:
        return rows, scanned

    fallback: list[dict] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, object] = {"status": "open", "limit": KALSHI_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI_API}/markets", params)
        page = payload.get("markets") or []
        scanned += len(page)
        fallback.extend(m for m in page if not _is_parlay(str(m.get("ticker", ""))))
        cursor = payload.get("cursor") or None
        if not cursor or not page:
            break

    return fallback, scanned


def _polymarket_pages() -> tuple[list[dict], int]:
    """Walk Polymarket's Gamma listing by offset.

    The page size must match Gamma's cap of 100: asking for more returns 100
    anyway, and any "a short page is the last page" rule then fires immediately.
    """
    rows: list[dict] = []
    scanned = 0

    for page in range(MAX_PAGES):
        payload = get_json(
            f"{POLYMARKET_GAMMA_API}/markets",
            {
                "closed": "false",
                "limit": POLYMARKET_PAGE_SIZE,
                "offset": page * POLYMARKET_PAGE_SIZE,
                "order": "volumeNum",
                "ascending": "false",
            },
        )
        batch = payload if isinstance(payload, list) else payload.get("data", [])
        if not batch:
            break
        scanned += len(batch)
        rows.extend(batch)
        if len(batch) < POLYMARKET_PAGE_SIZE:
            break

    return rows, scanned


@dataclass
class ScanReport:
    """What one platform's listing actually contained.

    `distinct` is the load-bearing field. When it is far below `scanned`, the
    pagination is not advancing and we fetched the same page repeatedly — which
    looks identical to "we searched thoroughly and found nothing" in a plain
    count, and is the reason this is measured rather than assumed.
    """

    platform: str
    scanned: int = 0
    titles: list[str] = field(default_factory=list)

    @property
    def distinct(self) -> int:
        return len({t.strip() for t in self.titles if t.strip()})

    @property
    def pagination_stalled(self) -> bool:
        return self.scanned > 0 and self.distinct * 2 <= self.scanned

    def office_mentions(self, limit: int = 5) -> list[str]:
        found = sorted({t.strip() for t in self.titles if "senate" in t.lower() and t.strip()})
        return found[:limit]

    def sample(self, limit: int = 5) -> list[str]:
        seen: list[str] = []
        for title in self.titles:
            cleaned = title.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
            if len(seen) >= limit:
                break
        return seen

    def describe(self) -> str:
        parts = [f"{self.platform}: scanned={self.scanned} distinct={self.distinct}"]
        if self.pagination_stalled:
            parts.append("PAGINATION STALLED (same page refetched)")
        office = self.office_mentions()
        parts.append(
            f"office mentions={office}" if office else f"no office mentions; sample={self.sample(3)}"
        )
        return " | ".join(parts)


def collect(history: list[MarketPoint] | None = None) -> MarketsResult:
    markets: list[Market] = []
    warnings: list[str] = []
    attribution: list[Attribution] = []
    reports: list[ScanReport] = []

    kalshi = ScanReport("kalshi")
    try:
        rows, kalshi.scanned = _kalshi_pages()
        kalshi.titles = [
            f"{r.get('title', '')} {r.get('yes_sub_title', '')} [{r.get('ticker', '')}]"
            for r in rows
        ]
        found = _kalshi_markets({"markets": rows})
        markets.extend(found)
        if found:
            attribution.append(KALSHI_ATTRIBUTION)
    except SourceError as exc:
        warnings.append(f"kalshi unavailable: {exc}")
    reports.append(kalshi)

    poly = ScanReport("polymarket")
    try:
        rows, poly.scanned = _polymarket_pages()
        poly.titles = [str(r.get("question") or r.get("title") or "") for r in rows]
        found = _polymarket_markets(rows)
        markets.extend(found)
        if found:
            attribution.append(POLYMARKET_ATTRIBUTION)
    except SourceError as exc:
        warnings.append(f"polymarket unavailable: {exc}")
    reports.append(poly)

    for report in reports:
        if report.pagination_stalled:
            warnings.append(f"{report.platform} pagination stalled: {report.describe()}")

    if not markets:
        # Leaving the previous markets.json in place and failing loudly beats
        # publishing an empty file: a slightly stale probability is recoverable,
        # a silently missing headline number is not.
        #
        # The message carries the evidence rather than pointing at another
        # command, because "nothing matched" alone cannot distinguish a renamed
        # market from pagination that never advanced.
        detail = " || ".join(r.describe() for r in reports)
        if warnings:
            raise SourceError(f"{'; '.join(warnings)} || {detail}")
        raise SourceError(f"no market matched this race. {detail}")

    return MarketsResult(
        markets=markets,
        consensus=build_consensus(markets, history),
        attribution=attribution,
        warnings=warnings,
    )


def diagnose() -> str:
    """List what the platforms actually offer, so matching can be tuned.

    The failure this exists for is silent: both APIs answer, nothing matches, and
    the reason could be pagination, a renamed market, or a title that never says
    "Kansas". Printing the near-misses distinguishes them in one run.
    """
    lines = ["Prediction market probe", "=" * 40]

    for label, loader, title_of in (
        ("kalshi", _kalshi_pages, lambda r: f"{r.get('title', '')} {r.get('yes_sub_title', '')} [{r.get('ticker', '')}]"),
        ("polymarket", _polymarket_pages, lambda r: r.get("question") or r.get("title") or ""),
    ):
        lines.append(f"\n[{label}]")
        try:
            rows, scanned = loader()
        except SourceError as exc:
            lines.append(f"  FAILED: {exc}")
            continue

        lines.append(f"  scanned {scanned} open markets")
        senate = [title_of(r) for r in rows if "senate" in title_of(r).lower()]
        kansas = [t for t in senate if "kansas" in t.lower() or " ks" in t.lower()]

        lines.append(f"  mentioning 'senate': {len(senate)}")
        for title in senate[:12]:
            marker = "  <-- matches Kansas" if title in kansas else ""
            lines.append(f"    · {title.strip()}{marker}")
        if not senate:
            lines.append("    (none — either pagination is short or titles differ)")

    return "\n".join(lines)
