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

Polls and our own polling average · prediction-market win probability ·
campaign money and outside spending from the FEC · news from Kansas newsrooms ·
race ratings · broadcast ad buys · voter registration and advance ballots ·
live returns on election night.

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
