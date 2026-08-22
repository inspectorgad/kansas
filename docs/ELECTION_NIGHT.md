# Election night runbook

**Election day: Tuesday, November 3, 2026. Kansas polls close at 7pm CT; the
Secretary of State's election night reporting page goes live at 5pm CT.**

This is the one night the app has to work, and the one source that has never been
observed. `ent.sos.ks.gov` serves live data for a few hours a year and was
unreachable from the environment the collector was written in, so its format is
**unverified**. Everything below exists to close that gap before it matters
rather than during it.

## Do this well before November 3

Run the probe against the archived primary. The August 4, 2026 primary results
are still served, and whatever shape they are in is almost certainly the shape
November's will be in.

```sh
python collector/run.py --probe-results
```

The probe tries three shapes in order and tells you which matched:

1. **A JSON feed** at one of the paths in `JSON_CANDIDATE_PATHS`.
2. **JSON embedded in the page** — a `var results = {…}` bootstrap.
3. **An HTML table**, matched on county names rather than column position.

A successful run prints the parsed statewide totals, how many of the 105 counties
it read, and the precinct-reporting percentage. **That output is the go/no-go
signal.** If it prints `NO SHAPE MATCHED`, it also prints the first 600
characters of what was actually served — enough to add the missing parser in
`collector/sources/results.py` in one sitting.

### Rehearse the rest of the path offline

Knowing the page's shape is only half of it. The other half — parse, reconcile,
publish, render — can be rehearsed today, with no network at all:

```sh
python collector/rehearse.py                     # all three stages
python collector/rehearse.py --stage mid
python collector/rehearse.py --data-dir /tmp/enr  # keep the files to inspect
```

It replays recorded pages at three points in the night, prints what the app's
Race tab would show at each, and reconciles the county rows against the statewide
totals. It runs on every push in CI. A passing rehearsal means everything
downstream of the parser is sound; it says nothing about whether the real page
matches, which is what `--probe-results` is for.

The fixtures deliberately reproduce the misreading described below — the early
count leads one way and the final count the other. If that ever stops holding,
the fixtures have lost the case they exist for.

Then confirm the app end to end:

```sh
python collector/run.py --only results --data-dir /tmp/enr-test
# inspect /tmp/enr-test/results.json, then point a debug build at it
```

## Two failure modes worth knowing about in advance

**Kansas has a Marshall County and a Hamilton County.** A naive surname match
reads those county rows as candidate totals and roughly doubles the statewide
count. Candidate matching therefore requires corroboration — a first name, an
honorific, or a party tag — and `test_results_source.py` pins this. If you touch
`_candidate_id`, run those tests.

**The counties that report first are not representative.** Johnson and Sedgwick
are large and relatively quick; the western rural counties are small and slow.
An early Democratic lead from urban counties is expected and does not mean what
it looks like. The app shows percent-reporting next to every figure for exactly
this reason, and it never calls a race on its own.

## On the night

Collection switches on automatically three days out — `default_targets()` adds
`results` inside `RESULTS_WINDOW_DAYS`. Nothing needs to be enabled by hand.

Cadence: the GitHub Actions cron runs every 20 minutes, which is too slow for a
count in progress. The app compensates: `RaceViewModel.startResultsPolling()`
refreshes `results.json` every 60 seconds while returns are live, so the phone
polls the published file faster than the collector rewrites it. If you want
fresher data than 20 minutes, trigger the workflow manually — repeatedly, or
temporarily lower the cron.

Watch for:

- `status` moving `pending` → `live`. The app raises a one-time notification
  when it does.
- The county count climbing toward 105. A count that stalls well short of it
  means the parser is reading some rows and missing others — worse than reading
  none, because it looks like data.
- Statewide totals that do not match the sum of the counties. The HTML parser
  derives statewide from the county rows when the page gives no explicit total,
  so a mismatch means both were found and they disagree.

## After the night

Returns are **unofficial**. The official canvass follows in the weeks after
election day and does move numbers. When the count is finished, set `status` to
`final`; leaving it `live` keeps the app polling every 60 seconds forever.

## If the scrape cannot be made to work

The documented fallback is the **AP Elections API**, which is paid. It is the
reason the results collector is isolated behind a single `collect()` function:
swapping the source means replacing one module, not touching the app. Decide this
in October, not on election night.
