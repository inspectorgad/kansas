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
from schemas import HAMILTON, MARSHALL, Attribution
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
# Both boundaries are required, and the reason is embarrassing: "arkansas" ends
# with the letters "kansas", so a substring test made every Arkansas contest a
# Kansas one. A live run pulled "Will Democratics win the Senate race in
# Arkansas?" into this race's market set. Same class of fault as the AKSEN ticker
# below — a state name matched inside another state's name.
STATE_NAME = re.compile(r"(?:^|[^a-z])kansas(?:[^a-z]|$)", re.IGNORECASE)
SENATE_TERMS = ("senate", "senator")
MARSHALL_TERMS = ("marshall",)
HAMILTON_TERMS = ("hamilton",)

# Kalshi quotes this race by *party*, not by candidate: the live listing offers
# "Will Kansas Senate winner be Republican party" rather than a market named for
# Marshall. Since each is their party's nominee, the party market is the race, and
# mapping it across is sound — but the payload says so rather than implying the
# market names the candidate.
PARTY_TO_CANDIDATE = {"republican": MARSHALL, "democratic": HAMILTON, "democrat": HAMILTON}

# Markets covering two offices at once ("Governor winner AND Senate winner") are
# not a Senate probability on their own. But Kalshi lists all four outcomes of the
# governor-by-senate grid, and four mutually exclusive, exhaustive outcomes can be
# marginalised exactly: P(Senate R) = P(gov D, sen R) + P(gov R, sen R). That is
# arithmetic on a complete partition, not a model.
#
# As it turns out this is the only route available. A live scan of 2,400 Kalshi
# events and 1,200 Polymarket markets found no standalone 2026 Kansas Senate
# contract on either platform — only these combos, plus a 2028 Kansas race.
COMBO_MARKERS = ("GOVCOMBO", "COMBO", "SWEEP")

# The trailing segment encodes governor then senate, three letters each.
COMBO_OUTCOME = re.compile(r"-(DEM|REP)(DEM|REP)(?:-|$)")

# This race is November 2026. Kalshi also lists a 2028 Kansas Senate market
# (SENATEKS-28-D), which would otherwise match every rule here.
CYCLE_MARKERS = ("26NOV", "-26-", "26AUG", "2026")
WRONG_CYCLE = re.compile(r"-(2[0-9])-|-(2[0-9])[A-Z]{3}")

# "KS" as a standalone word, for prose like "Senate KS 2026". Both boundaries are
# required: a right boundary alone would match "Blackhawks", and Kalshi lists
# plenty of NHL *Senators* markets — "Senators beat the Blackhawks" would then
# satisfy both halves of the test and be collected as this race.
STATE_WORD = re.compile(r"(?:^|[^a-z])ks(?:[^a-z]|$)", re.IGNORECASE)

# Exchange tickers concatenate, so no token boundary appears around the state
# code. A live run showed why "contains SEN and KS" is not good enough: Kalshi
# spells the Alaska Senate race KXAKSENGOVCOMBO, and "AKSEN" contains "KS" as a
# substring, so every Alaska contest matched as Kansas.
#
# That same run revealed the real shape — KX + state + SEN + qualifier — so
# Kansas reads KXKSSEN..., with the state code immediately before the office.
# KSSEN is therefore the primary pattern; SEN...KS covers the reverse ordering
# some series use, anchored to the end of the alpha run so AKSEN cannot satisfy
# it either.
TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
KANSAS_SENATE_TICKER = re.compile(r"KSSEN|SEN[A-Z]*KS(?![A-Z])")


@dataclass
class MarketsResult:
    markets: list[Market]
    consensus: Consensus | None = None
    attribution: list[Attribution] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _ticker_identifies_race(raw: str) -> bool:
    """A ticker naming both Kansas and the Senate settles the test at once.

    Checked before the state and office rules because one token carries both.
    The pattern is deliberately narrow: a looser "contains SEN and KS" collected
    the whole Alaska Senate slate, whose tickers read KXAKSEN... — the "KS" there
    is the tail of "AK" plus the head of "SEN", meaning nothing.
    """
    return any(KANSAS_SENATE_TICKER.search(token) for token in TICKER_TOKEN.findall(raw))


def _mentions_state(text: str) -> bool:
    """Does this text name Kansas, spelled out or abbreviated as a word?

    Both forms are word-bounded. Neither "arkansas" nor "Blackhawks" names this
    state, and both matched before.
    """
    return bool(STATE_NAME.search(text)) or bool(STATE_WORD.search(text))


def _is_combo(ticker: str) -> bool:
    upper = (ticker or "").upper()
    return any(marker in upper for marker in COMBO_MARKERS)


def _is_this_cycle(ticker: str) -> bool:
    """Reject other cycles. Absent a year marker, assume the current one."""
    upper = (ticker or "").upper()
    if any(marker in upper for marker in CYCLE_MARKERS):
        return True
    match = WRONG_CYCLE.search(upper)
    if match:
        year = match.group(1) or match.group(2)
        return year == "26"
    return True


def _party_candidate(text: str) -> str | None:
    lowered = (text or "").lower()
    for party, candidate in PARTY_TO_CANDIDATE.items():
        if party in lowered:
            return candidate
    return None


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


ALL_OUTCOMES = (("DEM", "DEM"), ("DEM", "REP"), ("REP", "DEM"), ("REP", "REP"))


def combo_grid(rows: list[dict], kansas_only: bool = True) -> dict[str, dict[tuple[str, str], float]]:
    """Group combination outcomes by series ticker: {series: {(gov, sen): price}}.

    Grouping is the whole point. Keyed on the outcome pair alone, as this was, a
    scan that reached two states' grids pooled them — Arkansas's DEMDEM
    overwriting Kansas's — and the result still held four entries, so it read as
    a complete partition while being assembled from two different races. That is
    the worst failure available here: real prices, wrong contest, a number that
    looks entirely normal on screen.

    Series must also positively identify Kansas and the Senate. Excluding other
    states by name is not enough when the ticker is all that distinguishes them.
    """
    grids: dict[str, dict[tuple[str, str], float]] = {}

    for market in rows:
        ticker = str(market.get("ticker", "")).upper()
        if not _is_combo(ticker) or not _is_this_cycle(ticker):
            continue
        if kansas_only and not _ticker_identifies_race(ticker):
            continue
        match = COMBO_OUTCOME.search(ticker)
        if not match:
            continue
        price = market.get("last_price")
        if price is None:
            price = market.get("yes_bid")
        if price is None:
            continue
        series = ticker[: match.start()]
        grids.setdefault(series, {})[(match.group(1), match.group(2))] = float(price) / 100.0

    return grids


def describe_grid(rows: list[dict]) -> str:
    """Name every combination series found and which of its four cells are priced.

    The generic "no market listed" warning could not distinguish a race nobody
    quotes from a grid one cell short, and inferring which from a truncated
    sample cost two rounds of guessing. This says it outright.
    """
    grids = combo_grid(rows, kansas_only=False)
    if not grids:
        return "no combination series found"

    parts = []
    for series, outcomes in sorted(grids.items()):
        have = ",".join(f"{gov}{sen}" for gov, sen in ALL_OUTCOMES if (gov, sen) in outcomes)
        missing = ",".join(f"{gov}{sen}" for gov, sen in ALL_OUTCOMES if (gov, sen) not in outcomes)
        mine = "kansas" if _ticker_identifies_race(series) else "other-state"
        parts.append(f"{series} [{mine}] priced={have or 'none'} missing={missing or 'none'}")
    return "; ".join(parts)


def marginalise_combos(rows: list[dict]) -> tuple[float, float] | None:
    """Derive the Senate probability from a complete governor-by-senate grid.

    All four outcomes of one Kansas series must be present. With fewer, the
    missing mass is unknown and renormalising the rest would invent a number
    rather than derive one — so a partial grid yields nothing instead of a
    plausible guess.
    """
    grids = combo_grid(rows)
    if not grids:
        return None

    # One series covers this race. If several appear, the fullest is the live one.
    _series, outcomes = max(grids.items(), key=lambda item: len(item[1]))
    if len(outcomes) != 4:
        return None

    total = sum(outcomes.values())
    if total <= 0:
        return None

    # The second element of each key is the Senate outcome.
    senate_r = sum(v for (_gov, sen), v in outcomes.items() if sen == "REP")
    senate_d = sum(v for (_gov, sen), v in outcomes.items() if sen == "DEM")
    return normalise(senate_r / total, senate_d / total)


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

        if _is_combo(ticker) or not _is_this_cycle(ticker):
            continue

        subject = f"{title} {market.get('yes_sub_title', '')} {ticker}".lower()
        if any(t in subject for t in MARSHALL_TERMS):
            pair = normalise(probability, None)
        elif any(t in subject for t in HAMILTON_TERMS):
            pair = normalise(None, probability)
        else:
            # No candidate named, so fall back to the party the contract is on.
            party = _party_candidate(market.get("yes_sub_title") or "")
            if party == MARSHALL:
                pair = normalise(probability, None)
            elif party == HAMILTON:
                pair = normalise(None, probability)
            else:
                continue  # a market on this race we cannot attribute
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


CURSOR_KEYS = ("cursor", "next_cursor", "nextCursor")


def _extract_cursor(payload: dict) -> str | None:
    """Find the continuation token wherever the response puts it.

    A live run scanned 2,400 events and found 118 distinct — the cursor was being
    read from a key that was not there, so page one came back twelve times.
    """
    for key in CURSOR_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    nested = payload.get("pagination")
    if isinstance(nested, dict):
        for key in CURSOR_KEYS:
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return None


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
    seen_events: set[str] = set()

    for _ in range(MAX_PAGES):
        params: dict[str, object] = {"status": "open", "limit": KALSHI_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI_API}/events", params)
        events = payload.get("events") or []
        scanned += len(events)

        # Stop the moment a page repeats itself. Without this a cursor that never
        # advances quietly refetches page one until the page budget runs out, and
        # the resulting large "scanned" count reads as a thorough search.
        tickers = {str(e.get("event_ticker", "")) for e in events if e.get("event_ticker")}
        if tickers and tickers <= seen_events:
            break
        seen_events |= tickers

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

        cursor = _extract_cursor(payload)
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
        cursor = _extract_cursor(payload)
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

    `scanned` must count the same things `titles` holds, or the stall check
    compares apples to oranges. It did exactly that for one run: `scanned`
    counted Kalshi *events* while `titles` held the *markets* pulled from the few
    matching ones, so 2,400 events yielding 40 markets was reported as
    "PAGINATION STALLED" when pagination was working perfectly.

    `containers_scanned` carries the event count separately, as context rather
    than as a denominator.
    """

    platform: str
    scanned: int = 0
    titles: list[str] = field(default_factory=list)
    containers_scanned: int = 0

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
        if self.containers_scanned:
            parts.insert(1, f"events={self.containers_scanned}")
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
        rows, kalshi.containers_scanned = _kalshi_pages()
        # scanned must count what titles holds — markets, not the events walked
        # to reach them — or the stall check compares unlike things.
        kalshi.scanned = len(rows)
        kalshi.titles = [
            f"{r.get('title', '')} {r.get('yes_sub_title', '')} [{r.get('ticker', '')}]"
            for r in rows
        ]
        found = _kalshi_markets({"markets": rows})
        if not found:
            # No standalone contract; derive it from the combination grid.
            derived = marginalise_combos(rows)
            if derived is not None:
                found = [
                    Market(
                        platform="kalshi",
                        market_id="KXKSSENGOVCOMBO-derived",
                        title="Kansas Senate 2026 (derived from governor/Senate combinations)",
                        marshall=round(derived[0], 4),
                        hamilton=round(derived[1], 4),
                        fetched_at=datetime.now(UTC),
                    )
                ]
                warnings.append(
                    "no standalone Kansas Senate contract exists; the probability is "
                    "marginalised from Kalshi's four governor-by-senate outcomes"
                )
            else:
                # Say which cells are priced. "Nothing matched" and "the grid is
                # one cell short" need entirely different fixes, and a capped
                # title sample cannot tell them apart.
                warnings.append(f"combination grid unusable: {describe_grid(rows)}")
        markets.extend(found)
        if found:
            attribution.append(KALSHI_ATTRIBUTION)
    except SourceError as exc:
        warnings.append(f"kalshi unavailable: {exc}")
    reports.append(kalshi)

    poly = ScanReport("polymarket")
    try:
        rows, poly.scanned = _polymarket_pages()  # markets are the unit here
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
        detail = " || ".join(r.describe() for r in reports)
        healthy = all(not r.pagination_stalled and r.scanned > 0 for r in reports)

        # A platform that errored, or pagination that stalled, means we did not
        # really look — that is breakage, and the last good file should stay.
        if not healthy:
            raise SourceError(f"market scan unhealthy: {detail}")

        # Both platforms answered and neither lists this race. That is a fact
        # about the world rather than a fault, and failing forever on it would
        # keep the collector permanently red over something no fix can change.
        # The app already renders a null consensus as "no market is quoting this
        # race", which is the honest thing to show.
        warnings.append(f"no market for this race is listed on either platform. {detail}")
        return MarketsResult(
            markets=[], consensus=None, attribution=[], warnings=warnings
        )

    if any(m.platform == "kalshi" for m in markets):
        warnings.append(
            "Kalshi quotes this race by party rather than by candidate; the "
            "Republican contract is read as Marshall and the Democratic one as "
            "Hamilton, each being their party's nominee."
        )

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
