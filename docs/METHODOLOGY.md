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

**What counts as a poll.** Only surveys. The Wikipedia article lists forecast
models and averages — Silver Bulletin, Race to the White House, and others —
in among the pollsters, and for several runs this collector read them as polls
and averaged them. That made our "own" average partly an average of other
people's averages, double-counting every poll underneath them and contradicting
the paragraph above. Named forecasters and anything whose name contains
*average*, *aggregate*, *forecast*, *projection* or *model* are now excluded, and
each exclusion is named in the collector log.

A structural rule was tried first and abandoned: a row with neither a sample size
nor a margin of error describes no survey, but it also describes real polls that
Wikipedia lists without either, and with only a handful of polls in this race
losing genuine ones costs more than catching an unnamed model. So such rows are
kept and reported in the run warnings instead. That report is how the next
unlisted forecaster is meant to be found — by appearing in a log, rather than by
a rule written in advance for a row nobody has seen.

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

### Where the number comes from

Neither platform lists a standalone 2026 Kansas Senate contract. A scan of 2,400
Kalshi events and 1,200 Polymarket markets found only a 2028 Kansas race and
Kalshi's four *governor-by-Senate* combination outcomes.

Those four are mutually exclusive and exhaustive, so the Senate probability is
recovered exactly by marginalising over the governor:

    P(Senate R) = P(gov D, Senate R) + P(gov R, Senate R)

That is arithmetic on a complete partition, not a model — but it is a derivation
rather than a quoted price, so the app labels it as such. All four outcomes must
be present: with three, the missing mass is unknown, and renormalising the rest
would invent a number instead of deriving one.

If no market of any kind is listed, the app says so rather than showing a stale
figure, and the headline falls back to the polling average.

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

## The implied margin

The market screen answers who is favoured. This answers by how much, which is the
more useful question in a race whose poll average and market probability disagree
as sharply as this one's do.

Kalshi lists a ladder of margin thresholds — `KXMIDTERMMOV-KSSENR-P3` through
`-P23` — each pricing "will the Republican margin be at least N points". A ladder
of thresholds is a survival curve, so the gap between adjacent rungs is the
probability of landing between them. Subtraction on a monotone curve, not a model.

Two things make it publishable rather than suggestive:

**The bands close.** The ladder cannot see the narrow-win band — the space between
"wins at all" and "wins by at least three" — so that comes from the win
probability derived from the governor-by-senate combination grid, an entirely
separate set of contracts. When the observed ladder is combined with the observed
grid, the thirteen bands sum to 100.00%. Two unrelated markets agreeing to the
cent is a much stronger claim than either alone, and it is also the check that
would catch a misread price on either side.

**It refuses rather than guesses.** Prices are not probabilities; a thin book can
quote a bigger win above a smaller one, which would make a band negative. Any
inversion withholds the whole distribution instead of clamping it to zero. So does
a ladder whose lowest rung exceeds the probability of winning at all, because one
of those two numbers is then wrong and nothing here can say which.

Two limits worth knowing when reading the chart. The exchange lists rungs for one
candidate only, so that side has a dozen bands and the other has one — an
asymmetry in the source, not in the race. And the top band is open-ended: "by 23
or more" has no upper bound, so the distribution has no defined mean, which is why
the headline figure is the median.

These same rungs are deliberately excluded from the win probability itself.
Averaging them as if each were a chance of winning once published Marshall at
.3727 when the real figure was .7732 — the single worst number this project has
shipped.
