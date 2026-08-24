# Data sources

Every source the collector reads, what it provides, and its honest limits. Rate
limits and licences are respected; requests carry a descriptive User-Agent and a
per-host delay.

## Collecting now

| Source | Provides | Access | Cadence | Notes |
|---|---|---|---|---|
| **Wikipedia** — [2026 Kansas Senate election](https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Kansas) | Every public general-election poll | MediaWiki API, no key | On change | CC BY-SA 4.0, attributed in-app. Hand-maintained markup, so the parser is defensive and reports rows it cannot read. **No free polling API exists** — this is the most complete free structured source. |
| **Kalshi** | Win probability | Public REST, no auth | Continuous | CFTC-regulated exchange. |
| **Polymarket** | Win probability | Gamma API, no auth | Continuous | Returns some list fields as JSON-encoded strings. |
| **FEC (openFEC)** | Receipts, disbursements, cash on hand, in-state share, independent expenditures, filings | `api.data.gov` key (free) | Per filing | Public domain. Candidate ids are resolved at runtime, never trusted from config. The for/against split is summed from each expenditure's own `support_oppose_indicator`, not from `schedule_e/by_candidate` — see below. |
| **Kansas newsrooms** — Kansas Reflector, KCUR, KWCH, KSNT | Headlines | RSS | Continuous | Headline, outlet and link only; paywalled outlets get no summary. Topeka Capital-Journal, Lawrence Journal-World, Kansas Public Radio and the KC Star widget URL were dropped after each answered 404 or timed out on live runs. `--probe-news` reports, per feed, how many entries it served and how many the relevance filter kept — which is what separates a dead feed from a feed with no race coverage from a filter that is too strict. |
| **GDELT 2.0** | Wider news sweep | Doc API, no key | Continuous | Catches coverage the local feeds miss. |
| **Cook Political Report, Sabato's Crystal Ball, Inside Elections** | Race ratings | Page scrape | Rare | **Disabled.** All three answer 403 Forbidden to this collector — a block, not a moved page — so no parser change reaches them. A rating change would be among the more newsworthy events in the race, which is why the probe stays. |

## Collecting, format unverified

These three are written as **probes** rather than single parsers: each tries the
plausible shapes, reports which matched, and prints what was actually served when
none did. `--probe-ads`, `--probe-ground` and `--probe-results` turn that into a
diagnosis run. None of these endpoints was reachable from the environment the
collector was written in.

| Source | Provides | Access | Status |
|---|---|---|---|
| **FCC Online Public Inspection File** | Broadcast ad buys by station, market and flight | Public API, no key | Collecting. Broadcast only — cable, streaming, digital and mail do not appear, so totals are a floor. Attribution is inference: a filing naming no candidate is reported unattributed, never assigned on a hunch. |
| **Meta Ad Library** | Digital ad spend | Requires an approved app and identity verification | Setup friction is real; the payload reports `available: false` with the reason, and the app shows it. Meta reports spend as a range, so figures are range midpoints and are estimates. |
| **Kansas Secretary of State** | Voter registration by county and party | Published statistics | Collecting, monthly cadence. Statistics are sometimes published as PDF or XLSX, which the table parser cannot read; `--probe-ground` says which. |
| **County election offices** — Johnson, Sedgwick, Shawnee, Wyandotte, Douglas | Advance ballots sent, returned, in-person | Public dashboards | Collecting. **Partial coverage by design.** Kansas publishes no statewide daily feed. These five counties hold roughly half the state's registered voters and lean urban; the payload says so and the app labels it. A dashboard that cannot be read is reported as *uncovered*, never as zero. |
| **Kansas SoS election night reporting** (`ent.sos.ks.gov`) | Live returns, statewide and by county | Goes live 5pm CT, Nov 3 | Handles a JSON feed, embedded JSON, or an HTML table. Collection switches on automatically three days out. **Probe it against the August 2026 primary archive before election day** — see [ELECTION_NIGHT.md](ELECTION_NIGHT.md). Paid AP Elections API is the named fallback. |

## Deliberately out of scope

| Source | Why |
|---|---|
| **X / Twitter candidate feeds** | The API is paid. Bluesky is free and would be used instead if either candidate is active there. |
| **Marshall's Senate voting record** (Congress.gov API, Senate.gov roll-call XML) | Free and straightforward; deferred to a later phase. The incumbent has a record and the challenger does not, so it is a one-sided tracker. |
| **Google Trends** | Only an unofficial endpoint exists. Fragile, and search interest is a weak signal. |
| **AdImpact, Cook's rating API, other paid feeds** | Paid. The project runs at zero cost. |

## Keys and secrets

No key ever ships inside the APK. The collector runs in GitHub Actions and reads
keys from repository secrets; the app only ever fetches static JSON.

| Secret | Needed for | Without it |
|---|---|---|
| `FEC_API_KEY` | Campaign finance | Falls back to `DEMO_KEY`, which is rate-limited hard and will fail on a full run |
| `META_ACCESS_TOKEN` | Digital ad spend | Digital ads report as unavailable, with the reason shown |

Every other source needs no authentication.

## Why outside spending is read row by row

The obvious way to get money-for and money-against is openFEC's
`/schedules/schedule_e/by_candidate/` aggregate with a `support_oppose_indicator`
filter. That is what this collector did, and on the first live run with a real API
key it was wrong in two different ways at once.

For Marshall it returned identical rows for both values of the filter: the same
$214,014.88 appeared as money supporting him and money opposing him, the published
total was exactly twice the real figure, and every committee — Senate
Conservatives Fund included — was labelled as both supporting and opposing the
same candidate.

For Hamilton it returned nothing at all, so he was absent from the breakdown
entirely, while the row-level endpoint in the very same run showed more than $1.1M
of television placed against him.

The split is now summed from `/schedules/schedule_e/`, where each expenditure
carries its own indicator. Those were correct for both candidates in the same run
that produced the bad aggregate, which is the whole reason for trusting them. Two
consequences worth knowing when reading `finance.json`:

- Totals are paginated over a twenty-page budget. If a candidate has more rows
  than that, the run warns that the figure is a floor rather than a total. It will
  never silently understate the money in the race.
- Committee names come from a separate `/committees/` lookup, because the
  row-level response omits them. Only the committees about to be displayed are
  looked up.

## Donor detail, and what it cannot tell you

Named donors come from FEC Schedule A, which is public record: federal law
requires committees to itemize a contributor's name, city, state, employer and
occupation once that contributor passes $200 in aggregate for the cycle.

The threshold is the whole caveat. Everything below $200 is reported as a single
unnamed total, so a named-donor list is not a sample of a campaign's supporters —
it is a census of its larger ones, and it under-represents a small-dollar campaign
far more than a big-cheque one. In this race that asymmetry has a direction:
Hamilton raises roughly 70% of his money in state on a small-dollar profile, so
his named donors account for a smaller share of his total than Marshall's do of
his. Showing the two lists side by side without saying that would invite exactly
the wrong comparison, which is why the caveat is the card's subtitle in the app
and a field in the payload rather than a comment in the code.

How each part is built:

| Part | Source | Limit worth knowing |
|---|---|---|
| Top employers, occupations | `schedule_a/by_employer/`, `by_occupation/` | Aggregated by the FEC over all itemized individual money. Self-reported, so "retired" and "self-employed" dominate. |
| Size bands, small-dollar share | `schedule_a/by_size/` | The FEC's own bands. This is where the under-$200 total comes from. |
| Largest donors | `schedule_a/`, `min_amount=1000`, largest first, plus a second pass for negatives | Ranked from contributions of $1,000 or more, **net of refunds and reattributions**. A donor who reached a large total through several smaller gifts is **not** ranked, and the payload says so. |
| Cities | Derived from the named list | The FEC groups geography by state and ZIP, never by city, so this ranks *large-donor* dollars only and is labelled that way on screen. |
| In-state share | `schedule_a/by_state/` | Itemized individual money only — the same threshold applies. |

Two further points. Contributions are grouped per donor on a normalised name plus
city, because the FEC's own strings vary in spacing and case between filings and
grouping on the raw value splits one donor into several and understates every
large one. And the FEC's sale-or-use restriction forbids using contributor
information to solicit contributions or for any commercial purpose; the app states
this on the card rather than leaving a reader to assume it is a mailing list.

### Refunds are why the largest-donor list needs two queries

An audit of one of Marshall's donors returned four rows: a single un-memoed
contribution of $14,000, and three memo-coded rows summing to **minus $7,000**.
Refunds and reattributions are filed as negative amounts, and the `min_amount`
floor that finds large contributions excludes every negative row by definition.
So the first version of this list published gross giving — a donor whose money had
been refunded stayed on it at full value.

The collector now runs a second query for negative rows and nets them against the
running totals, which is also why a donor can disappear from the list between
runs: below the threshold once netted, they were never a large donor. The coverage
note states the netting and counts the corrections applied, so a reader never has
to guess whether it happened.

One further caution about these rows, visible in the same audit. That $14,000
single contribution exceeds what an individual may give a candidate committee for
a whole cycle, which means some rows on this endpoint are not simple individual
contributions — joint fundraising allocations and conduit transfers appear here
too. Contrast Hamilton's list, where sixteen donors sit at exactly $7,000: that is
$3,500 for the primary plus $3,500 for the general, the individual maximum, and
those rows audit clean with no memo entries at all. Treat a total well above
$7,000 as a sign the money arrived through a structure rather than as one
person's cheque.

## Two sources that are off, and why that is a decision rather than a gap

`FCC_ENABLED` and `RATINGS_ENABLED` are both False, and each is a considered
answer to a live probe rather than unfinished work.

**Broadcast ads.** Four documented FCC facility-search paths, all 404 against the
live API. The endpoint shape needs discovering from a browser session; the paths
in this repo are guesses that have now been ruled out.

**Race ratings.** Cook, Sabato's Crystal Ball and Inside Elections all answer 403
Forbidden. That is a deliberate block on automated requests, so no amount of
parser work reaches them. The realistic routes are a licensed feed or entering
ratings by hand, and a rating change is newsworthy enough that a manual path may
be worth it.

Both stay off for the same reason, which matters more than either source. A
disabled source costs nothing and says why. An enabled-but-failing source spends
requests to fail and files the same warning every twenty minutes — and a log that
always carries the same complaint is a log nobody reads. That is not
hypothetical here: it is how `[OK] hamilton: 3,075 (100.0%)` survived a full day
as a *reported success* in the election-night probe. Keeping the warning list
short enough to read is a correctness measure, not tidiness.

## Entering a rating by hand

Since no handicapper will serve this collector, `collector/manual/ratings.json`
is how a rating reaches the app. It ships empty — nothing in it was invented to
fill the screen.

To add one: read the rating off the handicapper's own page, add an entry, set
`as_of` to the date **they** published it rather than today, set `url` to the page
you read, and commit. Put the old label in `previous` when a rating moves; that is
what the change detection compares. The git history is the audit trail for who
changed a rating and when, which is the main reason this lives in the repo rather
than in a database.

Two things the route does that matter more than the mechanics.

**Every entry is labelled.** The payload carries `entered_by_hand`, and the app
shows "Entered by hand · published 20 Aug" beneath the ratings line. A typed
figure and a scraped one carry different guarantees and must not look alike. The
label is not decoration and should not be removed to tidy the screen.

**Stale entries are reported, not dropped.** A hand-copied label goes stale in
total silence — a rating typed in August still reads as current in November unless
something says otherwise. Past 45 days the collector warns, naming the source and
the age, and still publishes: an old rating with its date visible is more useful
than none, and the warning is what prompts a re-check.

A malformed file is never silently empty, and one bad entry does not take the
others with it — it is skipped and named in the warnings.
