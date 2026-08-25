"""Race-specific configuration: who, where, and which sources to read.

Everything here is data, not logic. Sources that need a key read it from the
environment (set as GitHub Actions secrets) and degrade gracefully when absent,
so a missing key skips one collector instead of failing the whole run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from schemas import HAMILTON, MARSHALL, Candidate, Party

# --- Candidates ---------------------------------------------------------------
# FEC candidate ids are hints only. The finance collector resolves them from the
# FEC candidate-search endpoint at runtime and prefers what the API returns, so a
# stale or wrong id here degrades to a lookup rather than to bad numbers.
CANDIDATES: list[Candidate] = [
    Candidate(
        id=MARSHALL,
        name="Roger Marshall",
        party=Party.REPUBLICAN,
        incumbent=True,
        fec_candidate_id="S0KS00232",
    ),
    Candidate(
        id=HAMILTON,
        name="Adam Hamilton",
        party=Party.DEMOCRAT,
        incumbent=False,
    ),
]

# Surname -> candidate id, for matching poll tables, headlines and ad buys.
SURNAMES: dict[str, str] = {"marshall": MARSHALL, "hamilton": HAMILTON}

# --- Polls --------------------------------------------------------------------
# No free polling API exists, so the Wikipedia race article is the primary
# structured source. CC BY-SA, attributed in the app's Settings screen.
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_ARTICLE = "2026 United States Senate election in Kansas"

# Pollsters known to poll for a campaign or an aligned group. A poll is also
# flagged partisan whenever its sponsor field names a campaign, regardless of
# whether the pollster appears here.
PARTISAN_POLLSTERS: dict[str, str] = {
    "gbao": "D",
    "public policy polling": "D",
    "global strategy group": "D",
    "impact research": "D",
    "cygnal": "R",
    "trafalgar": "R",
    "co/efficient": "R",
    "wpa intelligence": "R",
    "remington research": "R",
    "fabrizio": "R",
}

# --- Prediction markets -------------------------------------------------------
KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
MARKET_SEARCH_TERMS = ("kansas senate", "kansas s enate 2026", "ks senate")

# --- Campaign finance --------------------------------------------------------
FEC_API = "https://api.open.fec.gov/v1"
# api.data.gov issues a free key. "DEMO_KEY" works but is rate-limited hard.
#
# `or` rather than a get() default: an unset secret in GitHub Actions arrives as
# an empty string, not as absent, and a get() default would have sent
# `api_key=` and taken a 403 — which is exactly what the first live run did.
FEC_API_KEY = os.environ.get("FEC_API_KEY") or "DEMO_KEY"
FEC_CYCLE = 2026
FEC_STATE = "KS"
FEC_OFFICE = "S"

# --- News --------------------------------------------------------------------
@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    paywalled: bool = False


NEWS_FEEDS: list[Feed] = [
    Feed("Kansas Reflector", "https://kansasreflector.com/feed/"),
    Feed("KCUR", "https://www.kcur.org/politics-elections-and-government.rss"),
    Feed("KWCH", "https://www.kwch.com/arc/outboundfeeds/rss/category/news/"),
    Feed("KSNT", "https://www.ksnt.com/feed/"),
    Feed("KSNT politics", "https://www.ksnt.com/news/politics/feed/"),
    # A search feed, not an outlet. It answered with 100 entries spanning four
    # months, 67 of them about this race — an order of magnitude more than the
    # four local feeds produce between them, and it reaches the Kansas City Star,
    # the Topeka Capital-Journal, Religion News Service and Cook, none of which we
    # can fetch directly. Items arriving this way are re-attributed to the outlet
    # that wrote them; see sources/news.py.
    Feed("Google News",
         "https://news.google.com/rss/search?q=%22Kansas+Senate%22+OR+"
         "%22Roger+Marshall%22+OR+%22Adam+Hamilton%22&hl=en-US&gl=US&ceid=US:en"),
    # Dropped after live runs, each verified 404 or timeout: Topeka
    # Capital-Journal, Lawrence Journal-World, Kansas Public Radio, and the
    # Kansas City Star widget URL. Only feeds that actually answered are kept —
    # a 404 per outlet per run is noise that buries real failures.
    #
    # Probed 2026-08-24 and rejected, so they are not retried: KSNT Capitol
    # Bureau and KWCH politics both serve valid but empty channels (846 and 746
    # bytes, zero entries); cjonline's politics path 404s; the Wichita Eagle and
    # Kansas City Star widget URLs both time out; kansaspublicradio.org/feed/
    # 404s; and Salina Post's search URL serves an HTML page, not a feed.
]

# Feeds not yet adopted, tested only by `--probe-news`. Nothing here is fetched
# on a scheduled run.
#
# The four adopted feeds answered every request of the 2026-08-24 probe and were
# still wrong: KWCH and KSNT serve general-news firehoses (crime, weather, K-State
# volleyball) rather than politics, KCUR's politics feed is only ten items deep,
# and Kansas Reflector was carrying the entire tracker by itself. None of these
# candidates is reachable from the environment the collector is written in, and
# guessing four FCC paths blind already cost four 404s a run, so they are probed
# before any is adopted.
CANDIDATE_NEWS_FEEDS: list[Feed] = [
    # Answered 429, which is throttling rather than a wrong URL, so it is worth
    # another look later. Everything else from the 2026-08-24 round is recorded as
    # rejected in the NEWS_FEEDS comment above.
    Feed("KAKE", "https://www.kake.com/rss/news/"),
]

# GDELT casts a wider net than the local feeds and needs no key — in theory. In
# practice it answered HTTP 429 to every attempt of every run for the collector's
# entire life, contributing exactly zero items, and it still 429s with the longer
# throttle backoff, so the cause is the shared runner IP rather than our schedule.
# Off, on the same terms as the FCC endpoint: three requests and 15s of backoff
# per run for nothing. `--probe-news` still tries it, so a recovery would show.
# The Google News search feed does this job and does it far better.
GDELT_ENABLED = False

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '("Roger Marshall" OR "Adam Hamilton") ("Kansas Senate" OR "U.S. Senate")'

# Relevance filtering lives in sources/news.py:is_relevant, not here. A flat term
# list used to sit at this spot and was never imported by anything — it read like
# the live rule and was not, which is worse than no constant at all.

# --- Broadcast ads -----------------------------------------------------------
FCC_PUBLIC_FILES_API = "https://publicfiles.fcc.gov"

# Broadcast ad collection is off until a working facility-search path is found.
# Four documented shapes were tried against the live API and all four 404'd, so
# every run was spending four requests to fail. `--probe-ads` still tries them
# all on demand; flip this to True once one answers.
FCC_ENABLED = False
# Kansas is split across these DMAs; the two that matter are Wichita and KC.
KANSAS_MEDIA_MARKETS = (
    "Wichita-Hutchinson",
    "Kansas City",
    "Topeka",
    "Joplin-Pittsburg",
)

META_AD_LIBRARY_API = "https://graph.facebook.com/v21.0/ads_archive"
# Same reasoning as FEC_API_KEY: an unset secret is "" and must read as absent.
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN") or None

# Industry classification of donors has no source. OpenSecrets was the only
# organisation publishing the employer-to-industry mapping and discontinued its
# API in 2026; FollowTheMoney was absorbed into OpenSecrets years earlier, and
# Stanford's DIME is a post-cycle academic release, so neither covers a race that
# is still running. The FEC records a self-reported employer string and nothing
# else, so top_employers is as far as this can honestly go.

# --- Ground game -------------------------------------------------------------
KS_SOS_REGISTRATION = "https://sos.ks.gov/elections/voter-registration-statistics.html"

# Counties that publish their own advance-voting dashboards. These five hold
# roughly half the state's registered voters; the payload says so explicitly.
@dataclass(frozen=True)
class CountyDashboard:
    county: str
    url: str


# Advance voting for the general election opens 20 days out. Before this date a
# county dashboard still shows *primary* figures, and the first live run duly
# matched numbers on two of them in August. Publishing those as general-election
# early vote would be worse than publishing nothing.
from datetime import UTC, datetime  # noqa: E402
from datetime import date as _date  # noqa: E402

# Market history recorded before this instant was produced by a derivation now
# known to be wrong, and is discarded on read rather than carried forward.
#
# The run at 17:28 on 2026-08-22 published Marshall .3727 / Hamilton .6273 from
# eleven rungs of the KXMIDTERMMOV margin-of-victory ladder — prices for "will
# the Republican margin be at least N points", volume-weighted as if each were a
# win probability. Since the series is read back from the previous markets.json
# each run, that single point would otherwise ride forward for as long as the
# inline window holds it, showing a phantom forty-point swing on the sparkline
# and poisoning every 1h and 24h delta for a day.
#
# Points are dropped rather than corrected because they cannot be corrected: the
# prices behind them answered a different question. Raise this whenever the
# derivation changes in a way that makes earlier points incomparable.
MARKET_HISTORY_EPOCH = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)

ADVANCE_VOTING_OPENS = _date(2026, 10, 14)

ADVANCE_DASHBOARDS: list[CountyDashboard] = [
    CountyDashboard("Johnson", "https://www.jocoelection.org/"),
    CountyDashboard("Sedgwick", "https://www.sedgwickcounty.org/elections/"),
    CountyDashboard("Shawnee", "https://www.snco.gov/election/"),
    CountyDashboard("Wyandotte", "https://www.wycokck.org/Departments/Election-Office"),
    CountyDashboard("Douglas", "https://www.douglascountyks.org/depts/clerk/elections"),
]

# --- Election night ----------------------------------------------------------
# Goes live at 5pm CT on election day. The exact response format is unverified;
# collector/sources/results.py probes JSON first and falls back to HTML.
KS_ENR_BASE = "https://ent.sos.ks.gov"
KS_ENR_FALLBACK = "https://www.kssos.org/ent/kssos_ent.html"

# --- Race ratings ------------------------------------------------------------
# Race-rating collection is off because all three handicappers refuse the
# request. A live probe on 2026-08-24 got 403 Forbidden from every one — Cook,
# Sabato's Crystal Ball and Inside Elections — not 404, so this is a deliberate
# block rather than a moved page, and no amount of parser work changes it.
#
# Three requests per run were being spent to fail, and the resulting warning fired
# every twenty minutes about something unfixable. That is worse than silence: a
# log that always carries the same complaint is a log nobody reads, which is how
# the election-night parser reporting "3,075 votes, 100% reporting" as a success
# went unnoticed for a day.
#
# `--probe-ratings` still tries all three on demand and reports exactly what came
# back. Flip this to True if one of them starts answering, or if a licensed feed
# gets arranged.
RATINGS_ENABLED = False

# Ratings entered by hand, since scraping them is not an option. Version
# controlled on purpose: every edit is a commit, so the git history is the audit
# trail for who changed a rating and when.
MANUAL_RATINGS_PATH = Path(__file__).resolve().parent / "manual" / "ratings.json"

# A hand-entered rating goes stale silently, which is the whole risk of the
# manual route. Past this many days the collector says so rather than letting a
# months-old label sit on the home screen looking current.
MANUAL_RATING_STALE_DAYS = 45

RATING_SOURCES = {
    "Cook Political Report": "https://www.cookpolitical.com/senate/race/488581",
    "Sabato's Crystal Ball": "https://centerforpolitics.org/crystalball/2026-senate/",
    "Inside Elections": "https://insideelections.com/ratings/senate",
}

# --- Run behaviour -----------------------------------------------------------
USER_AGENT = (
    "ks-senate-2026-tracker/1.0 (+https://github.com/inspectorgad/kansas) "
    "open-source election tracker"
)
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3

# A 429 means we tripped a rate limit, so the wait has to outlast the window we
# tripped. The plain 2**attempt schedule sleeps 1s then 2s, and GDELT — whose free
# doc API throttles on the order of seconds — answered 429 on all three attempts
# of every run since collection started. Those retries were spent inside the
# window they were waiting out, so they could not have succeeded. A Retry-After
# header from the server wins over both of these.
THROTTLE_BACKOFF_BASE = 5.0
THROTTLE_BACKOFF_CAP = 30.0
DATA_DIR = os.environ.get("DATA_DIR", "data")
HISTORY_DIR = "history"

# How many points of aggregate/market history to keep inline in the payload.
# Older points stay in data/history/ but are trimmed from the served file so the
# app's cold-start download stays small.
INLINE_HISTORY_POINTS = 180
