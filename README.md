# Kansas Senate 2026 Tracker

An Android app tracking the U.S. Senate race in Kansas between **Roger Marshall**
(R, incumbent) and **Adam Hamilton** (D) — election day **November 3, 2026**.

Not affiliated with either campaign, any election authority, or any news
organization. Every figure carries its source and its timestamp.

## How it works

Two halves, no server, no recurring cost:

```
GitHub Actions cron (every 20 min)         Android app (Kotlin / Compose)
  collector/  (Python)                       reads the static JSON over HTTPS
    fetch → parse → aggregate → validate     Room cache, full offline read
    write only when content changed          WorkManager refresh + local alerts
         │                                                  ▲
         └────────►  data branch (raw JSON + history/) ──────┘
```

Polling data has no free API, so aggregation happens once in CI rather than on
every phone. That keeps API keys out of the APK, gives every device identical
numbers, and preserves the time series the trend charts need.

## What it tracks

| Screen | Tracks |
|---|---|
| **Race** | Market win probability, poll average and margin, money and news at a glance. Becomes live returns on election night. |
| **Polls** | Every public poll with its methodology, a partisan-sponsor label, and the aggregate's trendline. |
| **Money** | Receipts, cash on hand, burn rate, in-state share, and outside spending for and against each side. |
| **News** | Headlines from Kansas newsrooms, linking out to the publisher. |
| **Advertising** | Broadcast buys by week and media market; digital spend where available. |
| **Registration and early voting** | Party registration statewide and by county; advance ballots for the counties that publish them. |
| **Election night** | County-by-county returns, sortable, refreshing every minute. |

Full inventory, with limits, in [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
How the average is computed, and what the app does not know, in
[docs/METHODOLOGY.md](docs/METHODOLOGY.md).

## Running the collector

```sh
python -m venv .venv && .venv/bin/pip install -r collector/requirements-dev.txt

.venv/bin/python collector/run.py                    # collect everything
.venv/bin/python collector/run.py --only polls        # one source
.venv/bin/python collector/run.py --dry-run           # collect, write nothing
.venv/bin/python collector/run.py --live-check        # verify live endpoints
```

Three sources scrape endpoints whose format could not be verified while this was
written. Each ships as a probe that reports what it actually found:

```sh
.venv/bin/python collector/run.py --probe-results    # Kansas election-night page
.venv/bin/python collector/run.py --probe-ads        # FCC political file
.venv/bin/python collector/run.py --probe-ground     # registration + county dashboards
```

**Before November 3, run `--probe-results` against the archived August primary.**
That is the go/no-go check for election night — see
[docs/ELECTION_NIGHT.md](docs/ELECTION_NIGHT.md).

Set `FEC_API_KEY` (free from [api.data.gov](https://api.data.gov/signup/)) for
campaign finance. Everything else needs no key.

### Tests

```sh
cd collector && ../.venv/bin/pytest
```

Tests replay recorded fixtures rather than hitting the network, so the parsers
are testable offline. `KS_FIXTURES=1` puts the collector itself in replay mode.

## Building the app

CI compiles the APK on every push and uploads it as an artifact — see the
**Android build** job. Locally:

```sh
cd android && ./gradlew assembleDebug
```

## Failure policy

A source that breaks fails loudly: the collector exits non-zero, CI goes red,
and the previous good file stays published. The app then shows the last known
value with its real age. A stale number labelled stale is recoverable; a wrong
number that looks fresh is not.

The same rule runs through the data model. A county dashboard that cannot be read
is reported as *uncovered*, never as zero returned ballots. An ad buy that cannot
be attributed to a side is reported as *unattributed*, never assigned to a
candidate on a hunch. A filing with no dollar figure stays null rather than
becoming a $0 buy. In each case the two readings are opposite facts, and merging
them would produce something that looks like data and is not.

## What this app does not claim

Not affiliated with either campaign, any election authority, or any news
organisation. It does not forecast, and it does not call races. The prediction
market number is a probability of winning, never a projected vote share. There is
no live vote share at all before election night. The limits of every source are
listed in [docs/METHODOLOGY.md](docs/METHODOLOGY.md) and surfaced in the app's own
Settings screen.
