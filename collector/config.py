"""Race-specific configuration: who, where, and which sources to read.

Everything here is data, not logic. Sources that need a key read it from the
environment (set as GitHub Actions secrets) and degrade gracefully when absent,
so a missing key skips one collector instead of failing the whole run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

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
FEC_API_KEY = os.environ.get("FEC_API_KEY", "DEMO_KEY")
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
    Feed(
        "Topeka Capital-Journal",
        "https://www.cjonline.com/arc/outboundfeeds/rss/category/news/",
        paywalled=True,
    ),
    Feed("Kansas City Star", "https://www.kansascity.com/news/politics-government/?widgetName=rssfeed&widgetContentId=712015&getXmlFeed=true", paywalled=True),
    Feed("KSNT", "https://www.ksnt.com/feed/"),
]

# GDELT casts a wider net than the local feeds and needs no key.
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '("Roger Marshall" OR "Adam Hamilton") ("Kansas Senate" OR "U.S. Senate")'

# Headlines must mention the race, not just a common name, to be kept.
NEWS_REQUIRED_TERMS = ("marshall", "hamilton", "kansas senate", "senate race")

# --- Broadcast ads -----------------------------------------------------------
FCC_PUBLIC_FILES_API = "https://publicfiles.fcc.gov"
# Kansas is split across these DMAs; the two that matter are Wichita and KC.
KANSAS_MEDIA_MARKETS = (
    "Wichita-Hutchinson",
    "Kansas City",
    "Topeka",
    "Joplin-Pittsburg",
)

META_AD_LIBRARY_API = "https://graph.facebook.com/v21.0/ads_archive"
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")

# --- Ground game -------------------------------------------------------------
KS_SOS_REGISTRATION = "https://sos.ks.gov/elections/voter-registration-statistics.html"

# Counties that publish their own advance-voting dashboards. These five hold
# roughly half the state's registered voters; the payload says so explicitly.
@dataclass(frozen=True)
class CountyDashboard:
    county: str
    url: str


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
DATA_DIR = os.environ.get("DATA_DIR", "data")
HISTORY_DIR = "history"

# How many points of aggregate/market history to keep inline in the payload.
# Older points stay in data/history/ but are trimmed from the served file so the
# app's cold-start download stays small.
INLINE_HISTORY_POINTS = 180
