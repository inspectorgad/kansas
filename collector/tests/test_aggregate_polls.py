"""Tests for the polling average.

These are property tests on the weighting rules, not golden numbers pinned to a
particular arithmetic result, so the methodology can be tuned without rewriting
the suite. The one exception is test_matches_hand_computed_average, which pins
the arithmetic for a simple two-poll case.
"""

from datetime import date, timedelta

from conftest import make_poll

from aggregate.polls import (
    HALF_LIFE_DAYS,
    PARTISAN_WEIGHT,
    aggregate_polls,
    is_partisan,
    poll_weight,
)

AS_OF = date(2026, 8, 22)


def test_returns_none_without_polls():
    assert aggregate_polls([], AS_OF) is None


def test_single_poll_reproduces_that_poll(poll_factory):
    polls = [poll_factory("Nonpartisan Research", 46.0, 45.0, AS_OF)]
    agg = aggregate_polls(polls, AS_OF, history_days=0)
    assert agg is not None
    assert agg.marshall == 46.0
    assert agg.hamilton == 45.0
    assert agg.margin == 1.0
    assert agg.leader == "marshall"
    assert agg.n_polls_used == 1


def test_leader_flips_with_the_margin(poll_factory):
    agg = aggregate_polls([poll_factory("A", 44.0, 48.0, AS_OF)], AS_OF, history_days=0)
    assert agg.leader == "hamilton"
    assert agg.margin < 0


def test_recency_decay_halves_weight_at_the_half_life(poll_factory):
    fresh = poll_factory("A", 46.0, 45.0, AS_OF)
    stale = poll_factory("B", 46.0, 45.0, AS_OF - timedelta(days=int(HALF_LIFE_DAYS)))
    assert poll_weight(stale, AS_OF) == poll_weight(fresh, AS_OF) * 0.5


def test_newer_poll_pulls_the_average_toward_itself(poll_factory):
    old = poll_factory("Old Pollster", 52.0, 40.0, AS_OF - timedelta(days=30))
    new = poll_factory("New Pollster", 44.0, 47.0, AS_OF)
    agg = aggregate_polls([old, new], AS_OF, history_days=0)
    # The fresh poll dominates, so the average must sit closer to it.
    assert abs(agg.margin - (-3.0)) < abs(agg.margin - 12.0)


def test_partisan_polls_are_down_weighted(poll_factory):
    neutral = poll_factory("Neutral Research", 46.0, 45.0, AS_OF)
    partisan = poll_factory("GBAO", 44.0, 48.0, AS_OF)
    assert is_partisan(partisan)
    assert poll_weight(partisan, AS_OF) == poll_weight(neutral, AS_OF) * PARTISAN_WEIGHT

    agg = aggregate_polls([neutral, partisan], AS_OF, history_days=0)
    # Down-weighting is not exclusion: the partisan poll still moves the average,
    # but less than it would under a plain mean of the two margins.
    unweighted = (1.0 + -4.0) / 2
    assert agg.margin > unweighted
    assert agg.margin < 1.0


def test_campaign_sponsorship_marks_a_poll_partisan(poll_factory):
    poll = poll_factory(
        "Unknown Polling", 44.0, 48.0, AS_OF, sponsor="Hamilton for Senate campaign"
    )
    assert is_partisan(poll)


def test_larger_samples_carry_more_weight(poll_factory):
    small = poll_factory("A", 46.0, 45.0, AS_OF, sample=300)
    large = poll_factory("B", 46.0, 45.0, AS_OF, sample=1200)
    assert poll_weight(large, AS_OF) > poll_weight(small, AS_OF)


def test_sample_boost_is_capped(poll_factory):
    huge = poll_factory("A", 46.0, 45.0, AS_OF, sample=100_000)
    reference = poll_factory("B", 46.0, 45.0, AS_OF, sample=600)
    assert poll_weight(huge, AS_OF) <= poll_weight(reference, AS_OF) * 1.5 + 1e-9


def test_missing_sample_size_is_penalised(poll_factory):
    unknown = poll_factory("A", 46.0, 45.0, AS_OF, sample=None)
    known = poll_factory("B", 46.0, 45.0, AS_OF, sample=600)
    assert poll_weight(unknown, AS_OF) < poll_weight(known, AS_OF)


def test_future_dated_polls_are_ignored(poll_factory):
    future = poll_factory("A", 46.0, 45.0, AS_OF + timedelta(days=5))
    assert poll_weight(future, AS_OF) == 0.0


def test_house_effect_pulls_a_repeat_outlier_toward_the_field(poll_factory):
    # One house consistently 10 points more Republican than everyone else.
    polls = [
        poll_factory("Outlier Data", 54.0, 40.0, AS_OF - timedelta(days=2)),
        poll_factory("Outlier Data", 55.0, 41.0, AS_OF - timedelta(days=9)),
        poll_factory("Field A", 46.0, 45.0, AS_OF - timedelta(days=3)),
        poll_factory("Field B", 45.0, 46.0, AS_OF - timedelta(days=4)),
        poll_factory("Field C", 46.0, 44.0, AS_OF - timedelta(days=5)),
    ]
    corrected = aggregate_polls(polls, AS_OF, history_days=0)

    # Same polls, but the outlier's two entries attributed to different houses,
    # so no house effect is identifiable and no correction is applied.
    polls[1] = poll_factory("Outlier Data Two", 55.0, 41.0, AS_OF - timedelta(days=9))
    uncorrected = aggregate_polls(polls, AS_OF, history_days=0)

    assert corrected.margin < uncorrected.margin


def test_single_poll_pollster_gets_no_house_correction(poll_factory):
    polls = [
        poll_factory("Lonely Poll", 54.0, 40.0, AS_OF),
        poll_factory("Field A", 46.0, 45.0, AS_OF),
    ]
    agg = aggregate_polls(polls, AS_OF, history_days=0)
    naive = (14.0 + 1.0) / 2
    assert abs(agg.margin - naive) < 0.01


def test_band_is_positive_and_widens_with_disagreement(poll_factory):
    agreeing = [
        poll_factory("A", 46.0, 45.0, AS_OF),
        poll_factory("B", 46.0, 45.0, AS_OF - timedelta(days=1)),
        poll_factory("C", 46.0, 45.0, AS_OF - timedelta(days=2)),
    ]
    disagreeing = [
        poll_factory("A", 52.0, 39.0, AS_OF),
        poll_factory("B", 43.0, 48.0, AS_OF - timedelta(days=1)),
        poll_factory("C", 46.0, 45.0, AS_OF - timedelta(days=2)),
    ]
    tight = aggregate_polls(agreeing, AS_OF, history_days=0)
    wide = aggregate_polls(disagreeing, AS_OF, history_days=0)
    assert tight.band >= 1.0
    assert wide.band > tight.band


def test_trend_reports_movement_over_the_last_week(poll_factory):
    polls = [
        poll_factory("A", 50.0, 42.0, AS_OF - timedelta(days=20)),
        poll_factory("B", 44.0, 47.0, AS_OF - timedelta(days=1)),
    ]
    agg = aggregate_polls(polls, AS_OF, history_days=0)
    # The race moved toward Hamilton over the past week.
    assert agg.trend_7d is not None and agg.trend_7d < 0


def test_history_is_chronological_and_as_of_dated(poll_factory):
    polls = [
        poll_factory("A", 50.0, 42.0, AS_OF - timedelta(days=40)),
        poll_factory("B", 46.0, 45.0, AS_OF - timedelta(days=10)),
        poll_factory("C", 44.0, 47.0, AS_OF - timedelta(days=1)),
    ]
    agg = aggregate_polls(polls, AS_OF, history_days=60)
    dates = [point.date for point in agg.history]
    assert dates == sorted(dates)
    assert dates[-1] == AS_OF
    # A point dated before the second poll cannot reflect it.
    early = next(p for p in agg.history if p.date == AS_OF - timedelta(days=30))
    assert early.n_polls == 1


def test_lookback_window_widens_when_polls_are_sparse(poll_factory):
    # Only stale polls exist; the average must still report rather than vanish.
    polls = [
        poll_factory("A", 48.0, 44.0, AS_OF - timedelta(days=120)),
        poll_factory("B", 47.0, 45.0, AS_OF - timedelta(days=150)),
    ]
    agg = aggregate_polls(polls, AS_OF, history_days=0)
    assert agg is not None and agg.n_polls_used == 2


def test_matches_hand_computed_average(poll_factory):
    """Pins the arithmetic for two equal-weight, same-day, nonpartisan polls."""
    polls = [
        poll_factory("Alpha Research", 46.0, 45.0, AS_OF),
        poll_factory("Beta Analytics", 48.0, 43.0, AS_OF),
    ]
    agg = aggregate_polls(polls, AS_OF, history_days=0)
    assert agg.marshall == 47.0
    assert agg.hamilton == 44.0
    assert agg.margin == 3.0
