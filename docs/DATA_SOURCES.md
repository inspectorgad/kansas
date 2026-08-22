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
| **FEC (openFEC)** | Receipts, disbursements, cash on hand, in-state share, independent expenditures, filings | `api.data.gov` key (free) | Per filing | Public domain. Candidate ids are resolved at runtime, never trusted from config. |
| **Kansas newsrooms** — Kansas Reflector, KCUR, KWCH, KSNT, Topeka Capital-Journal, KC Star | Headlines | RSS | Continuous | Headline, outlet and link only; paywalled outlets get no summary. |
| **GDELT 2.0** | Wider news sweep | Doc API, no key | Continuous | Catches coverage the local feeds miss. |
| **Cook Political Report, Sabato's Crystal Ball, Inside Elections** | Race ratings | Page scrape | Rare | A rating change is among the more newsworthy events in a race. |

## Built, awaiting data

| Source | Provides | Access | Status |
|---|---|---|---|
| **FCC Online Public Inspection File** | Broadcast ad buys by station, market and flight | Public API, no key | Schema defined; collector is Phase 3. Broadcast only — cable, streaming, digital and mail do not appear, so totals are a floor. |
| **Meta Ad Library** | Digital ad spend | Requires an approved app and identity verification | Setup friction is real; the payload reports `available: false` with a reason until a token exists. |
| **Kansas Secretary of State** | Voter registration by county and party | Published statistics | Monthly cadence. |
| **County election offices** — Johnson, Sedgwick, Shawnee, Wyandotte, Douglas | Advance ballots sent, returned, in-person | Public dashboards | **Partial coverage by design.** Kansas publishes no statewide daily feed. These five counties hold roughly half the state's registered voters and lean urban; the payload says so and the app labels it. |
| **Kansas SoS election night reporting** (`ent.sos.ks.gov`) | Live returns, statewide and by county | Goes live 5pm CT, Nov 3 | **Format unverified** — the site was unreachable from the environment this was written in. Must be probed against the August 2026 primary archive well before election day. Paid AP Elections API is the named fallback. |

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
