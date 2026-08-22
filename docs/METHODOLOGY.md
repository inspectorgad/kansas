# Methodology

Everything the app displays is either a number someone else published, or a
number we computed from numbers someone else published. This document covers the
second kind. If you only read one section, read [What this app does not
know](#what-this-app-does-not-know).

## The polling average

We compute our own average rather than republishing RealClearPolitics', Cook's,
or PollingSource's. That keeps the licensing clean, but the real reason is that
a borrowed average is a black box — this one is auditable, and its
implementation of record is [`collector/aggregate/polls.py`](../collector/aggregate/polls.py).

Each poll receives a weight that is the product of three factors.

**Recency.** Exponential decay on the poll's *end* date with a 14-day half-life.
A poll two weeks old counts half as much as one released today; a poll from six
weeks ago counts about an eighth. We use the end date, not the publication date,
because a poll describes the electorate when it was in the field.

**Sample size.** `sqrt(n / 600)`, capped at 1.5×. Precision scales with the
square root of the sample, so a 2,400-person poll is worth twice a 600-person
poll, not four times. The cap stops one very large survey from dominating. A
poll that does not report its sample size gets 0.75 — an unreported sample is
itself a quality signal.

**Independence.** Campaign- and party-sponsored polls are weighted at 0.45. They
are not excluded. Internal polls carry real information and excluding them would
throw away signal, particularly early in a race when they may be the only polls
that exist. But they are released selectively — a campaign publishes the poll it
likes — so they earn less than half the weight of an independent survey.

A poll is treated as partisan if its sponsor names a campaign, party or PAC, or
if its pollster appears in the list in [`collector/config.py`](../collector/config.py).
The app labels every such poll in the list view; you can always see which polls
are carrying the average.

### House-effect correction

Some pollsters lean consistently in one direction. For any pollster with **two or
more** polls in the window, we measure the average gap between its margins and
the naive weighted average, then subtract a shrunk estimate of that gap:

    correction = mean_residual × n / (n + 2)

The shrinkage matters. With two polls a pollster's apparent lean is mostly noise,
so we apply half of it; with ten polls we apply most of it. A pollster with a
single poll receives no correction at all, because one poll cannot distinguish a
house effect from ordinary sampling error.

The correction is split between the two candidates — half subtracted from one,
half added to the other — so the reported shares stay near the polls' own scale
rather than drifting.

### The uncertainty band

The band is not a margin of error. It combines two sources of uncertainty:

    band = sqrt(sampling² + disagreement²)

where `sampling` is the 95% sampling error implied by the weighted effective
sample, and `disagreement` is the weighted standard deviation of the margins in
the window. The second term is the important one. When pollsters disagree, that
disagreement is real uncertainty about the state of the race, and an average
that reported only its own sampling error would look far more confident than the
evidence supports. The band is floored at one point.

### The window

We use polls from the last 45 days. If that leaves fewer than three polls, the
window widens until it holds three, so the average degrades to "stale but
present" rather than vanishing during a quiet stretch.

### The trendline

The trend chart is **recomputed as-of each day**, using only the polls that had
finished by that date. A point dated three weeks ago shows what the average
would actually have read three weeks ago. It is not a smoothing of today's data
projected backwards, which would show the past as though today's polls had
already existed.

`trend_7d` is today's margin minus the margin computed as of seven days ago.

## The prediction-market number

Kalshi and Polymarket quote in different shapes: one side of a binary market, or
a pair of outcome prices that include the spread. We normalise every quote to a
probability pair summing to exactly 1, so nothing can render as two numbers that
do not add up. The consensus across platforms is weighted by trading volume,
since a deep book carries more information than a thin one.

**This is a probability of winning, not a projected vote share.** A candidate at
72% is not expected to receive 72% of the vote. The app never labels it as a
share, and the payload carries a disclaimer to that effect. It also reflects what
bettors believe, which is not the same as what voters intend — prediction markets
have been confidently wrong before, and they move on news faster than they move
on evidence.

## Money

Figures come from FEC filings, so they are as current as the last report — which
can be months old. The app always shows the coverage end date next to the totals.
Between quarterly reports, only 24- and 48-hour independent-expenditure notices
appear, so outside spending updates faster than candidate fundraising does.

Burn rate is total cycle disbursements divided by months elapsed since the cycle
began: a cycle-long average, not a current monthly rate.

In-state share is computed from **itemized** individual contributions only.
Donors giving under $200 are not itemized, so this figure describes larger
donors and will differ from a true count of all donors.

## What this app does not know

- **There is no live vote share before election night.** Polls arrive a few per
  week. The only number that updates continuously before November 3 is the
  prediction-market probability, and that is a probability, not a share.
- **Polling averages are not forecasts.** This average describes the polls. It
  does not model turnout, undecided-voter behaviour, or the systematic polling
  error that has shown up in recent cycles. A one-point lead inside a four-point
  band is a race with no clear leader.
- **Advance-ballot coverage is partial.** Kansas publishes no statewide daily
  early-vote feed, so the app covers only the counties running their own public
  dashboards. Those counties lean more urban than the state as a whole; the
  totals are not a state sample.
- **Ad spending is a floor, not a total.** The FCC political file covers
  broadcast. Cable, streaming, digital and mail largely do not appear.
- **Every number is as of a timestamp.** The app shows it on every screen. When
  a source breaks, the collector fails loudly and the app keeps showing the last
  good value with its real age, rather than a fresh-looking wrong one.
