"""Our polling average.

We compute this ourselves rather than republish RCP's or Cook's, which keeps the
licensing clean and, more importantly, means the methodology is written down and
auditable. It is documented for readers in docs/METHODOLOGY.md; this module is
the implementation of record.

Each poll gets a weight that is the product of three factors:

  recency      exponential decay on the poll's *end* date, 14-day half-life
  sample size  sqrt(n) normalised to a 600-respondent poll, capped at 1.5x
  independence a 0.45 multiplier for campaign- or party-sponsored polls

House effects are then removed: for any pollster with at least two polls in the
window we measure how far its margins sit from the naive average and subtract a
shrunk estimate of that bias, so a single outlier house cannot drag the average.

The reported band is the sampling error implied by the weighted effective sample
combined with the spread between pollsters, floored at one point. Pollster
disagreement is real uncertainty and belongs in the band.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from config import PARTISAN_POLLSTERS
from schemas import HAMILTON, MARSHALL
from schemas.polls import Aggregate, AggregatePoint, Poll

HALF_LIFE_DAYS = 14.0
REFERENCE_SAMPLE = 600.0
MAX_SAMPLE_BOOST = 1.5
PARTISAN_WEIGHT = 0.45
LOOKBACK_DAYS = 45
MIN_POLLS = 3
HOUSE_EFFECT_SHRINKAGE = 2.0
MIN_BAND = 1.0

METHOD = (
    "Weighted average of public polls: 14-day recency half-life, sqrt(sample) "
    "weighting normalised to n=600, 0.45x weight for campaign-sponsored polls, "
    "and shrunk house-effect correction for pollsters with 2+ polls in the "
    "45-day window."
)


def is_partisan(poll: Poll) -> bool:
    """A poll counts as partisan if its sponsor is a campaign or its pollster is aligned."""
    if poll.partisan is not None:
        return True
    if poll.sponsor:
        sponsor = poll.sponsor.lower()
        if any(term in sponsor for term in ("campaign", "for senate", "committee", "pac", "party")):
            return True
        if any(name in sponsor for name in ("marshall", "hamilton")):
            return True
    return poll.pollster.strip().lower() in PARTISAN_POLLSTERS


def poll_weight(poll: Poll, as_of: date) -> float:
    """Weight for a single poll, as of a given date. Zero for future-dated polls."""
    age_days = (as_of - poll.end_date).days
    if age_days < 0:
        return 0.0

    recency = 0.5 ** (age_days / HALF_LIFE_DAYS)

    if poll.sample_size and poll.sample_size > 0:
        sample = min(math.sqrt(poll.sample_size / REFERENCE_SAMPLE), MAX_SAMPLE_BOOST)
    else:
        sample = 0.75  # an unreported sample size is itself a quality signal

    independence = PARTISAN_WEIGHT if is_partisan(poll) else 1.0

    return recency * sample * independence


def _eligible(polls: list[Poll], as_of: date) -> list[Poll]:
    """Polls inside the lookback window, widened if that leaves too few."""
    past = sorted(
        (p for p in polls if p.end_date <= as_of),
        key=lambda p: p.end_date,
        reverse=True,
    )
    cutoff = as_of - timedelta(days=LOOKBACK_DAYS)
    inside = [p for p in past if p.end_date >= cutoff]
    if len(inside) >= MIN_POLLS:
        return inside
    return past[:MIN_POLLS]


def _house_effects(polls: list[Poll], weights: list[float], naive_margin: float) -> dict[str, float]:
    """Per-pollster bias vs. the naive average, shrunk toward zero by sample count."""
    residuals: dict[str, list[float]] = {}
    for poll, weight in zip(polls, weights):
        if weight <= 0:
            continue
        margin = poll.results.marshall - poll.results.hamilton
        residuals.setdefault(poll.pollster.strip().lower(), []).append(margin - naive_margin)

    effects: dict[str, float] = {}
    for pollster, values in residuals.items():
        if len(values) < 2:
            continue  # one poll cannot distinguish house effect from noise
        mean = sum(values) / len(values)
        shrink = len(values) / (len(values) + HOUSE_EFFECT_SHRINKAGE)
        effects[pollster] = mean * shrink
    return effects


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(v * w for v, w in zip(values, weights)) / total


def _point(polls: list[Poll], as_of: date) -> tuple[float, float, float, int, float] | None:
    """Return (marshall, hamilton, margin, n_polls, band) as of a date, or None."""
    eligible = _eligible(polls, as_of)
    if not eligible:
        return None

    weights = [poll_weight(p, as_of) for p in eligible]
    if sum(weights) <= 0:
        return None

    marshall_raw = [p.results.marshall for p in eligible]
    hamilton_raw = [p.results.hamilton for p in eligible]
    margins = [m - h for m, h in zip(marshall_raw, hamilton_raw)]

    # Two passes: naive average, then remove shrunk house effects.
    naive_margin = _weighted_mean(margins, weights)
    effects = _house_effects(eligible, weights, naive_margin)

    adjusted_marshall, adjusted_hamilton = [], []
    for poll, marshall, hamilton in zip(eligible, marshall_raw, hamilton_raw):
        bias = effects.get(poll.pollster.strip().lower(), 0.0)
        # Split the correction between the two candidates so shares stay sensible.
        adjusted_marshall.append(marshall - bias / 2.0)
        adjusted_hamilton.append(hamilton + bias / 2.0)

    marshall = _weighted_mean(adjusted_marshall, weights)
    hamilton = _weighted_mean(adjusted_hamilton, weights)
    margin = marshall - hamilton

    # Band: sampling error at the weighted effective sample, combined with the
    # observed spread between pollsters.
    effective_n = sum(
        w * (p.sample_size or REFERENCE_SAMPLE) for p, w in zip(eligible, weights)
    )
    sampling = 1.96 * math.sqrt(0.25 / effective_n) * 100.0 if effective_n > 0 else MIN_BAND

    adjusted_margins = [m - h for m, h in zip(adjusted_marshall, adjusted_hamilton)]
    mean_margin = _weighted_mean(adjusted_margins, weights)
    variance = _weighted_mean([(m - mean_margin) ** 2 for m in adjusted_margins], weights)
    spread = math.sqrt(variance)

    band = max(math.sqrt(sampling**2 + spread**2), MIN_BAND)

    return marshall, hamilton, margin, len(eligible), band


def aggregate_polls(
    polls: list[Poll], as_of: date, history_days: int = 120
) -> Aggregate | None:
    """Compute the current average plus a daily back-series for the trend chart.

    The history is recomputed as-of each day using only polls that had finished
    by then, so the trendline shows what the average actually would have read at
    the time rather than a smoothing of today's data.
    """
    current = _point(polls, as_of)
    if current is None:
        return None
    marshall, hamilton, margin, n_polls, band = current

    history: list[AggregatePoint] = []
    for days_back in range(history_days, -1, -1):
        day = as_of - timedelta(days=days_back)
        point = _point(polls, day)
        if point is None:
            continue
        history.append(
            AggregatePoint(
                date=day,
                marshall=round(point[0], 2),
                hamilton=round(point[1], 2),
                margin=round(point[2], 2),
                n_polls=point[3],
            )
        )

    trend_7d = None
    week_ago = _point(polls, as_of - timedelta(days=7))
    if week_ago is not None:
        trend_7d = round(margin - week_ago[2], 2)

    from datetime import datetime, timezone

    return Aggregate(
        as_of=datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
        method=METHOD,
        marshall=round(marshall, 2),
        hamilton=round(hamilton, 2),
        margin=round(margin, 2),
        leader=MARSHALL if margin >= 0 else HAMILTON,
        band=round(band, 2),
        n_polls_used=n_polls,
        trend_7d=trend_7d,
        history=history,
    )
