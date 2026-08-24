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

## What the probe found on 2026-08-24

Run against the archived August 4 primary, nineteen days after it was held. The
answer is worse than "the format is unknown".

**The official ENR host refuses us outright.** Every path under
`ent.sos.ks.gov` — four JSON candidates and the page itself — returned
**403 Forbidden**, not 404. That is a block, not an absence. It may behave
differently on election night, when the host is actually serving results, but it
cannot be relied on and there is no way to find out before November 3.

**The fallback page parsed, and what it produced was nonsense:**

```
[OK  ] html-table: https://www.kssos.org/ent/kssos_ent.html
  hamilton: 3,075 (100.0%)
  counties: 0 of 105
  precincts reporting: 100.0%
```

One candidate. Three thousand votes in a state that casts over a million. Every
precinct reporting. Zero counties. And the probe called it a success, because the
only test was whether a parse returned something non-empty.

That is the most dangerous failure this project has had — worse than the margin
ladder, worse than the double-counted outside spending — because it would have
fired on election night, on the one screen that matters, and published a called
race. Nothing downstream could have caught it: the payload would have validated,
the app would have rendered it, and a reader would have had no reason to doubt it.

A plausibility gate now stands between a parse and a publish, and a failing parse
is recorded as a rejection with its reason rather than as a match:

- **Both candidates must appear**, at any stage of the count. An ENR feed
  enumerates a contest's candidates from the first precinct, so a candidate with
  no votes shows a zero rather than being absent. A lone row is always an
  artefact. (The first version of this check only applied above 5% reporting,
  which let a single candidate through early in the evening — precisely when
  nobody is watching closely.)
- **A finished count cannot be in the thousands.** Above 99% reporting the total
  must exceed 300,000; Kansas cast about 1.35M Senate votes in 2020 and just over
  a million in the 2022 midterm.
- **Full reporting with no counties contradicts itself.** 100% of precincts in and
  not one county row parsed cannot both be true.

None of these are judgements about the politics. They are arithmetic and
structure.

### What still has to happen before November 3

The gate makes a wrong number impossible to publish. It does **not** make the
right number possible to collect — that is still unsolved, and it is now the
open question rather than a suspicion:

1. Find out whether `ent.sos.ks.gov` serves anything on election night, or
   whether the 403 is permanent. If it is permanent, the AP Elections API (paid)
   is the named fallback and needs arranging with weeks to spare, not hours.
2. Work out what the `kssos.org` fallback page actually contains. The 3,075-vote
   table is *something* — quite possibly a single county or a down-ballot contest —
   and identifying it is how a real parser gets written.
3. Rehearse against a full archived general election, not a primary.
