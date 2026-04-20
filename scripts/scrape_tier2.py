#!/usr/bin/env python3
"""Scrape Tier 2 historical public speakers from Rollingwood meeting packets.

Strategy:
  - Iterate the /meetings archive over the last 24 months.
  - For each meeting with a Packet PDF, download it (cached under data/packet_cache/).
  - Packets embed the prior meeting(s)' draft minutes as TEXT (no OCR needed).
  - Find each embedded "MEETING MINUTES" section and its meeting date.
  - Extract speaker-name candidates via two patterns:
      A) Name, <street number + street>     — citizen with stated address
      B) Name + speech-verb                  — broader; needs title-stripping.
  - Strip titles, dedupe, and fuzzy-match each candidate against Tier 1 via
    roster.lookup(). If a Tier 1 match is found, add the variant spelling as
    an alias on the Tier 1 entry (--write updates tier1_officials.yml).
  - Remaining candidates become Tier 2.
  - Non-resident context keywords (CTRMA, TxDOT, other-city officials, etc.)
    tag the entry with confidence: non_resident.

Dry-run by default. --write commits to tier1 (alias additions) + tier2.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests
import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
import roster as roster_mod  # noqa: E402

BASE = "https://www.rollingwoodtx.gov"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
ROOT = Path(__file__).parent.parent
ROSTER_DIR = ROOT / "prompts" / "roster"
TIER1_FILE = ROSTER_DIR / "tier1_officials.yml"
TIER2_FILE = ROSTER_DIR / "tier2_historical.yml"
CACHE_DIR = ROOT / "data" / "packet_cache"

# --- Patterns -----------------------------------------------------------------

SPEECH_VERBS = [
    "said", "stated", "asked", "answered", "replied", "responded", "explained",
    "mentioned", "noted", "commented", "expressed", "suggested", "recommended",
    "proposed", "moved", "seconded", "offered", "requested", "urged",
    "encouraged", "advocated", "supported", "opposed", "objected", "argued",
    "presented", "spoke", "addressed", "announced", "confirmed", "inquired",
    "testified", "raised", "clarified", "continued",
]
VERB_ALT = r"(?:" + "|".join(SPEECH_VERBS) + r")"

# Person-name token: capital followed by lowercase, allowing hyphens/apostrophes.
# Requiring a lowercase after the cap filters out all-caps acronyms (GRIP, IV, ACL).
NAME_TOKEN = r"[A-Z][a-z][a-zA-Z'\-]*"
# Also accept short Dutch/Irish prefix tokens (Van, Von, De, La, O', Mc, Mac)
PREFIX_TOKEN = r"(?:Van|Von|De|Del|La|Le|Du|Da|St\.|Mc|Mac|O')"
NAME_PATTERN = (
    rf"{NAME_TOKEN}"
    rf"(?:\s+(?:{PREFIX_TOKEN}\s+)?{NAME_TOKEN}){{1,3}}"
)

NAME_ADDR_RE = re.compile(
    rf"({NAME_PATTERN})\s*,\s*"
    rf"(\d+\s+[A-Z][A-Za-z0-9.\s]+?)"
    rf"(?=\s+(?:and|{VERB_ALT})\b|\s*[,.])",
    re.MULTILINE,
)
NAME_VERB_RE = re.compile(rf"({NAME_PATTERN})\s+{VERB_ALT}\b", re.MULTILINE)

# Titles to peel off the front of a matched name. Sorted longest-first so
# greedy match catches "Mayor Pro Tem" before "Mayor". strip_title() peels
# iteratively to handle stacked titles (e.g. "Mayor Pro Tem Sara Hutson").
TITLES_SORTED = sorted([
    r"Mayor Pro Tem", r"Mayor Pro Tern", r"Mayor Pro Tempore",
    r"Pro Tem", r"Pro Tern", r"Pro Tempore",
    r"Po Tem", r"Tem",  # transcription/PDF fragments of "Mayor Pro Tem"
    r"Event Mayor", r"Rollingwood Mayor",
    r"Mayor", r"Vice Mayor",
    # Council variants
    r"Council Member", r"Councilmember", r"Councilwoman", r"Councilman",
    r"Council",  # bare — strips "Council Brook Brown" etc.
    # Chair variants (include multi-word compounds)
    r"Committee Chair", r"Acting Chair", r"Interim Chair",
    r"Club Chair", r"District Chair", r"Enforcement Chair",
    r"Park Chair", r"Softball Chair", r"Training Chair",
    r"Vice Chair", r"Chair", r"Chairperson", r"Chairman", r"Chairwoman",
    # Commission / body prefixes that sometimes lead a speaker reference
    r"Rollingwood Park Commission", r"Park Commission",
    r"Planning and Zoning Commission", r"Planning and Zoning",
    r"Board of Adjustment", r"Utility Commission",
    r"Comprehensive Plan Strike Force",
    r"Rollingwood Park", r"Rollingwood Community Development Corporation",
    r"Development Corporation",
    # Attorneys, planners, engineers, other professional prefixes
    r"City Attorney", r"City Planner", r"City Engineer",
    r"Corporation President", r"Exchange President",
    # Police roles
    r"Fire Chief", r"Assistant Fire Chief", r"Police Chief",
    r"Chief", r"Sergeant", r"Officer", r"Corporal", r"Lieutenant",
    r"Captain", r"Cadet", r"Reserve Officer",
    # Admin / staff
    r"Acting City Administrator", r"Interim City Administrator",
    r"Acting City Secretary",
    r"City Administrator", r"City Secretary",
    r"Assistant to the City Administrator", r"Administrator",
    r"Development Services Manager", r"Services Manager",
    r"Director of Finance", r"Finance Director",
    r"Public Works Director", r"Public Works Foreman", r"Works Director",
    r"Public Works",
    r"Police Administrative Coordinator", r"Field Operator",
    r"Presiding Judge", r"Judge", r"Court Clerk",
    r"Utility Billing Manager",
    # President / misc
    r"President", r"Vice President", r"Treasurer", r"Secretary",
    r"Ms\.", r"Mr\.", r"Mrs\.", r"Dr\.", r"Rev\.",
    r"Attorney", r"Representative", r"Senator",
    # Stray body words that occasionally prefix a speaker when "of" or other
    # lowercase token breaks the regex's capital-word chain
    r"Adjustment", r"Commissioner", r"Commission", r"Committee", r"Department",
    r"Zoning District",
    # Event-specific
    r"Girls Softball", r"Softball",
], key=len, reverse=True)
# Use a lookahead so the regex also matches when the title is the ENTIRE name
# (e.g. bare "Council Member") — not only when followed by a space.
TITLE_STRIP_RE = re.compile(
    r"^(?:" + "|".join(TITLES_SORTED) + r")(?=\s|$)\s*",
    re.IGNORECASE,
)

# Embedded minutes marker within a packet. Rollingwood draft minutes typically
# begin "CITY COUNCIL MEETING\nMINUTES\n<weekday>, <Month> <day>, <year>".
MINUTES_MARKER_RE = re.compile(
    r"(MEETING\s*\n?\s*MINUTES|MINUTES)\s*\n?\s*"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday),?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),?\s+(\d{4})",
    re.IGNORECASE,
)

# If any of these keywords shows up near a candidate, flag non_resident.
NON_RESIDENT_KEYWORDS = [
    "CTRMA", "CTMA", "TxDOT", "Capital Metro", "CAMPO",
    "City of Austin", "City of Westlake Hills", "Westlake Hills",
    "Travis County", "State Representative", "State Senator",
    "Austin City Council", "SOS Alliance", "Save Our Springs",
    "Westlake Chamber", "Westbank", "Eanes ISD",
    "consultant", "vendor", "attorney for",
    "City Attorney", "City Planner", "City Engineer",
    "Sitio Design", "Lloyd Gosselink", "AlterStudio", "Alter Studio",
]

# People to add explicitly to Tier 2 (or upgrade to these confidence tiers if
# auto-discovered). Role text gets written to the YAML.
FORMER_STAFF: dict = {
    "Ashley Wayman": "former City Administrator",
}
FORMER_COUNCIL: dict = {
    "Wendi Hundley": "former Council Member",
    "Buck Shapiro": "former Council Member",
}

# Within-Tier-2 merges for cases where fuzzy-dedup can't safely connect
# variants automatically (different spellings of the same real person).
T2_MERGE_OVERRIDES: dict = {
    # Glen Harris and Glenn Harris are the same resident at 3012 Hatley Drive
    "Glen Harris": "Glenn Harris",
    # Wendy is the auto-discovered variant; Wendi matches the seeded entry.
    "Wendy Hundley": "Wendi Hundley",
    # Michael / Mike Rhodes — same person; Mike is more common in minutes.
    "Michael Rhodes": "Mike Rhodes",
    # Charlie is a nickname for Charles; Charles is the formal legal name used
    # in City Attorney references.
    "Charlie Zech": "Charles Zech",
}

# Manual Tier 1 alias additions the fuzzy matcher wouldn't catch on its own.
MANUAL_T1_ALIASES: dict = {
    # "Brider" appears in the minutes as a typo of "Brian" (e.g. 2025-10-20)
    "Brian Rider": ["Brider Rider"],
    # "Chris Meakin" is the shortened form; the site spells it "Christpher"
    # (with the missing 'o' preserved per the ground-truth rule).
    "Christpher Meakin": ["Chris Meakin"],
    # BOA Chair: site directory says "Gerald Speitel"; minutes call him "Jerry".
    # Confirmed same person — both listed in 2025-05-28 BOA minutes simultaneously.
    "Gerald Speitel": ["Jerry Speitel"],
}

# Candidates that are obviously not people (common bigrams that accidentally
# look like First-Last capitalized pairs).
# A matched name is rejected if its LAST token is one of these — catches
# building/venue names and street names that happen to sit before an address.
NON_PERSON_LAST_TOKENS = {
    "hall", "center", "centre", "church", "library", "headquarters",
    "boulevard", "blvd", "drive", "dr", "street", "st", "avenue", "ave",
    "lane", "ln", "cove", "court", "ct", "circle", "cir", "road", "rd",
    "way", "parkway", "pkwy", "highway", "hwy",
    "school", "park", "theater", "theatre", "building", "complex",
    "campus", "office", "station", "department", "corporation",
    "association", "commission", "committee", "board", "district",
    "club", "foundation", "county", "city", "town", "village",
    "market", "grill", "cafe", "inn", "hotel", "motel", "lodge",
    "store", "mall", "plaza", "facility", "flagship", "coop", "co-op",
    "hills", "valley", "heights", "terrace", "falls", "creek", "springs",
    "ridge", "grove", "oaks", "river", "woods", "lake", "lakes",
    "valle", "union", "annex", "courthouse", "fire", "station",
    "warehouse", "garage", "code", "ordinance", "section",
    "edition",
}

# Rejects the FIRST token from being one of these common nouns — catches
# "Applications Mayor Gavin Massingill", "Bee Cave Road The", etc., where
# the regex grabbed a common noun plus a real name.
NON_PERSON_FIRST_TOKENS = {
    "Applications", "Application", "Approved", "Approval",
    "Agenda", "Minutes", "Meeting", "Motion",
    "Community", "Family", "Food", "Flagship",
    "Billing", "Acting", "Interim", "International",
    "The", "This", "These", "Those",
    "Bee", "West", "East", "North", "South", "Central",
    "Shoal", "Mueller", "Monterey", "Research", "Carver",
    "Rockwood", "Angelina", "Guadelupe", "Guadalupe",
    "Austin", "Texas", "Travis",
}

# Tokens that should NEVER appear in an accepted Tier 1 alias — catches
# "Dave Benched", "Visit Mary Elizabeth Cofer", etc. (cross-line artifacts).
NOISE_ALIAS_TOKENS = {
    "visit", "visited", "attended", "returned", "arrived", "joined",
    "benched", "motioned", "seconded", "approved", "denied", "noted",
    "addressed", "stated", "said", "asked",
    "the", "and", "but", "for", "with", "by", "of", "from", "about",
    "met", "chaired", "presided",
}

NAME_BLOCKLIST = {
    # City bodies / departments
    "City Council", "City Hall", "City Administrator", "City Secretary",
    "City Attorney", "Rollingwood Park", "Rollingwood Drive", "Public Works",
    "Public Affairs",
    "Police Department", "Fire Department", "Park Commission",
    "Planning Commission", "Utility Commission", "Utility Commissioner",
    "Utility Services", "Planning Zoning", "Zoning Commission",
    "Board Adjustment", "Community Development", "Development Corporation",
    "Development Services", "Strike Force", "Design Group", "Master Plan",
    "Comprehensive Plan", "Code Review", "Residential Code",
    "Citizens Communication", "Public Comment", "Public Hearing",
    # Meeting/process language
    "Open Meetings", "Meetings Act", "Meeting Agenda", "Executive Session",
    "Consent Agenda", "Regular Agenda", "Board Member", "Committee Chair",
    "Council Members", "Commission Members", "Board Members",
    "Council Member", "Pro Tem",
    "Electronic Meters Staff", "Residential Building Height Measurement",
    "Neighborhood Character Neighbors", "Commercial Retail Group",
    "Pavilion Race Route The",
    # Places
    "Rollingwood Texas", "Rollingwood Community", "Austin City", "Texas City",
    "Texas State", "Bee Cave", "Bee Caves", "Lady Bird", "Ladybird Lake",
    "Zilker Park", "Mopac South", "Mopac North", "South Mopac",
    "Barton Creek", "Barton Springs", "Austin High", "High School",
    "Middle School", "Elementary School", "Hill Country", "Western Hills",
    "Loop Hwy", "United States", "North American",
    "PfISD Rock Gym", "Typhoon Texas Waterpark",
    "Western Hills Girls Softball", "Western Hills Little League",
    "Sitio Design", "Sitio Design Austin",
    "Randalls Brodie", "Randalls Steiner Ranch",
    "Silsbee Ford", "Lloyd Gosselink",
    # Orgs / programs that read like names
    "Baptist Church", "Austin Baptist", "Boy Scout", "Eagle Scout",
    "Girl Scout", "Little League",
    # Staff role-words
    "Finance Director", "Police Chief", "Police Officer", "Reserve Officer",
    "Fire Chief", "Judge Chief",
    # Scheduling / docs
    "Fiscal Year", "Quarterly Report", "Annual Report", "November Election",
    "Roberts Rules", "Robert Rules", "Order Roberts", "Master Development",
    # Residual artifacts
    "Approved Approved", "Approved Denied", "United Way",
}

# --- Data types ---------------------------------------------------------------


@dataclass
class Candidate:
    name: str
    sources: list = field(default_factory=list)  # (meeting_date, pattern, context)
    addresses_seen: set = field(default_factory=set)


@dataclass
class MeetingRow:
    date: str
    title: str
    detail_url: str
    packet_url: str | None


# --- Discovery ----------------------------------------------------------------


def fetch(url: str, timeout: int = 60) -> requests.Response:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r


def discover_meetings(start: date, end: date) -> list:
    out: list = []
    page = 0
    while page < 20:
        params = {
            "date_filter[value][year]": start.year,
            "date_filter[value][month]": start.month,
            "date_filter[value][day]": start.day,
            "date_filter_1[value][year]": end.year,
            "date_filter_1[value][month]": end.month,
            "date_filter_1[value][day]": end.day,
            "page": page,
        }
        url = f"{BASE}/meetings?" + urlencode(params)
        soup = BeautifulSoup(fetch(url).text, "html.parser")
        added = 0
        for tr in soup.find_all("tr"):
            ds = tr.find("span", attrs={"content": True})
            if not ds or "T" not in ds.get("content", ""):
                continue
            title_cell = tr.find("td", class_="views-field-title")
            details_a = tr.find("a", title=True, href=re.compile(r"/page/"))
            if not (title_cell and details_a):
                continue
            packet_a = tr.select_one(
                "td.views-field-field-packets-link a[href*='.pdf']"
            )
            out.append(MeetingRow(
                date=ds["content"][:10],
                title=title_cell.get_text(" ", strip=True),
                detail_url=details_a["href"],
                packet_url=packet_a["href"] if packet_a else None,
            ))
            added += 1
        if added == 0:
            break
        page += 1
    return out


# --- Packet text --------------------------------------------------------------


def cached_packet_bytes(packet_url: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(packet_url.encode()).hexdigest()[:16]
    path = CACHE_DIR / f"{key}.pdf"
    if path.exists() and path.stat().st_size > 1000:
        return path.read_bytes()
    tmp = path.with_suffix(".pdf.part")
    with requests.get(packet_url, headers=HEADERS, timeout=300, stream=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    tmp.replace(path)
    return path.read_bytes()


def extract_text(pdf_bytes: bytes) -> str:
    try:
        import io
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        return ""


def find_embedded_minutes(text: str) -> list:
    """Return a list of (minutes_date, start_offset, end_offset) for each
    embedded minutes section found in the packet text."""
    markers = []
    for m in MINUTES_MARKER_RE.finditer(text):
        month, day, year = m.group(2), int(m.group(3)), int(m.group(4))
        try:
            dt = datetime.strptime(f"{month} {day} {year}", "%B %d %Y").date()
        except ValueError:
            continue
        markers.append((m.start(), dt))
    markers.sort()
    out = []
    for i, (start, dt) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        # Cap minutes section at 40KB — anything longer is probably not a
        # single minutes document.
        end = min(end, start + 40000)
        out.append((dt, start, end))
    return out


# --- Extraction ---------------------------------------------------------------


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def strip_title(raw_name: str) -> str:
    name = _normalize_whitespace(raw_name)
    # Peel titles iteratively: "Mayor Pro Tem Sara Hutson" → "Sara Hutson"
    for _ in range(4):
        new = TITLE_STRIP_RE.sub("", name).strip()
        if new == name:
            break
        name = new
    return name


def is_plausible_name(name: str) -> bool:
    if not name:
        return False
    parts = name.split()
    if len(parts) < 2 or len(parts) > 4:
        return False
    if name in NAME_BLOCKLIST:
        return False
    low = name.lower()
    # Filter pairs of common abstract nouns masquerading as names
    if any(w in low.split() for w in {
        "meeting", "agenda", "minutes", "ordinance", "resolution",
        "section", "chapter", "article", "report", "rate", "rates",
        "increase", "increases", "application", "proposal", "project",
        "fund", "budget", "expenditure", "committee",
    }):
        return False
    # Last token should look like a surname (cap + lowercase, not a number/roman)
    if re.fullmatch(r"[IVXLCDM]+", parts[-1]):
        return False
    # Reject if last token is a building/street/body noun (not a surname)
    if parts[-1].lower() in NON_PERSON_LAST_TOKENS:
        return False
    # Reject if first token is a common noun that sometimes gets matched
    # as a "first name" by our capital-word pattern
    if parts[0] in NON_PERSON_FIRST_TOKENS:
        return False
    return True


def extract_from_minutes(text: str, meeting_date: date) -> list:
    hits = []
    for m in NAME_ADDR_RE.finditer(text):
        raw_name = _normalize_whitespace(m.group(1))
        addr = _normalize_whitespace(m.group(2))
        stripped = strip_title(raw_name)
        if not is_plausible_name(stripped):
            continue
        ctx = text[max(0, m.start() - 80):min(len(text), m.end() + 180)]
        hits.append({
            "name": stripped,
            "raw_name": raw_name,
            "address": addr,
            "pattern": "A",
            "context": ctx,
            "date": meeting_date,
        })

    # Pattern B runs on the same text; dedupe by (name, date) at assembly time.
    for m in NAME_VERB_RE.finditer(text):
        raw_name = _normalize_whitespace(m.group(1))
        stripped = strip_title(raw_name)
        if not is_plausible_name(stripped):
            continue
        ctx = text[max(0, m.start() - 80):min(len(text), m.end() + 180)]
        hits.append({
            "name": stripped,
            "raw_name": raw_name,
            "address": None,
            "pattern": "B",
            "context": ctx,
            "date": meeting_date,
        })
    return hits


# --- Assembly -----------------------------------------------------------------


def is_non_resident_context(ctx: str) -> bool:
    low = ctx.lower()
    for kw in NON_RESIDENT_KEYWORDS:
        if kw.lower() in low:
            return True
    return False


def assemble(all_hits: list) -> dict:
    cands: dict = {}
    for h in all_hits:
        key = T2_MERGE_OVERRIDES.get(h["name"], h["name"])
        c = cands.setdefault(key, Candidate(name=key))
        c.sources.append((h["date"], h["pattern"], h["context"]))
        if h["address"]:
            c.addresses_seen.add(h["address"])
    return cands


def split_first_last(name: str) -> tuple:
    parts = name.split()
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (parts[0], "")


# --- Outputs ------------------------------------------------------------------


def _clean_alias(variant: str, canonical: str) -> bool:
    """Guard against cross-line artifacts and verb-tense noise getting aliased."""
    tokens = variant.lower().split()
    canonical_tokens = canonical.lower().split()
    # Reject if any token is on the noise list
    if any(t in NOISE_ALIAS_TOKENS for t in tokens):
        return False
    # Reject if variant has MORE than one extra token vs canonical
    if len(tokens) > len(canonical_tokens) + 1:
        return False
    return True


def _has_tier1_suffix(name: str) -> bool:
    """True if dropping 1..N-2 leading tokens lands on a name that resolves
    to Tier 1. Catches 'Zech Mayor Gavin Massingill', 'Park Commission Laurie
    Mills', etc."""
    tokens = name.split()
    for i in range(1, max(1, len(tokens) - 1)):
        cand = " ".join(tokens[i:])
        if len(cand.split()) >= 2 and roster_mod.lookup(cand) is not None:
            return True
    return False


def classify(cands: dict) -> dict:
    """Return dict with keys:
      tier1_alias_additions: canonical -> [(variant, first_date, count)]
      tier2_entries: list of dicts for YAML
    """
    # Reset lru_cache to pick up fresh file
    roster_mod._load_all.cache_clear()

    # canonical -> list of (variant, first_date, count)
    tier1_alias_add: dict = defaultdict(list)
    tier2_entries: list = []

    # Pre-seed merge aliases so the surviving canonical entry carries the
    # prior-spelling as a variant in its own Tier 2 aliases.
    t2_internal_aliases: dict = defaultdict(set)
    for variant, canonical in T2_MERGE_OVERRIDES.items():
        t2_internal_aliases[canonical].add(variant)

    # Names that should resolve via manual Tier 1 alias and not appear as
    # their own Tier 2 entries.
    manual_alias_to_canonical = {
        v: k for k, vs in MANUAL_T1_ALIASES.items() for v in vs
    }

    for name, c in cands.items():
        # Manual Tier 1 alias takes precedence over fuzzy lookup.
        if name in manual_alias_to_canonical:
            canonical = manual_alias_to_canonical[name]
            first_date = min(str(d) for d, _, _ in c.sources)
            tier1_alias_add[canonical].append((name, first_date, len(c.sources)))
            continue

        hit = roster_mod.lookup(name)
        if hit is not None:
            if hit != name and _clean_alias(name, hit):
                first_date = min(str(d) for d, _, _ in c.sources)
                tier1_alias_add[hit].append((name, first_date, len(c.sources)))
            continue

        # Drop noise whose suffix is a Tier 1 person (e.g., "Zech Mayor Gavin
        # Massingill" or "Park Commission Laurie Mills"). The real person is
        # already captured by cleaner hits elsewhere.
        if _has_tier1_suffix(name):
            continue

        # Tier 2 candidate
        non_res = any(is_non_resident_context(ctx) for _, _, ctx in c.sources)
        first, last = split_first_last(name)
        a_count = sum(1 for _, p, _ in c.sources if p == "A")
        b_count = sum(1 for _, p, _ in c.sources if p == "B")
        source_dates = sorted({str(d) for d, _, _ in c.sources})

        # Confidence precedence: former_staff > former_council > non_resident > confirmed
        if name in FORMER_STAFF:
            confidence = "former_staff"
            role = FORMER_STAFF[name]
        elif name in FORMER_COUNCIL:
            confidence = "former_council"
            role = FORMER_COUNCIL[name]
        elif non_res:
            confidence = "non_resident"
            role = ""
        else:
            confidence = "confirmed"
            role = ""

        tier2_entries.append({
            "canonical_name": name,
            "first": first,
            "last": last,
            "aliases": sorted(t2_internal_aliases.get(name, set())),
            "role": role,
            "source": "tier2",
            "confidence": confidence,
            "_meta": {
                "address_hits": a_count,
                "verb_hits": b_count,
                "appearances": len(c.sources),
                "first_seen": source_dates[0],
                "last_seen": source_dates[-1],
                "addresses_seen": sorted(c.addresses_seen)[:3],
            },
        })

    # Seed former-officials that didn't appear in auto-discovery.
    discovered = {e["canonical_name"] for e in tier2_entries}
    for name, role in FORMER_COUNCIL.items():
        if name not in discovered:
            first, last = split_first_last(name)
            tier2_entries.append({
                "canonical_name": name, "first": first, "last": last,
                "aliases": [], "role": role, "source": "tier2",
                "confidence": "former_council",
                "_meta": {"address_hits": 0, "verb_hits": 0, "appearances": 0,
                          "first_seen": "", "last_seen": "",
                          "addresses_seen": [], "seed_only": True},
            })
    for name, role in FORMER_STAFF.items():
        if name not in discovered:
            first, last = split_first_last(name)
            tier2_entries.append({
                "canonical_name": name, "first": first, "last": last,
                "aliases": [], "role": role, "source": "tier2",
                "confidence": "former_staff",
                "_meta": {"address_hits": 0, "verb_hits": 0, "appearances": 0,
                          "first_seen": "", "last_seen": "",
                          "addresses_seen": [], "seed_only": True},
            })

    # Apply manual Tier 1 alias additions that the fuzzy matcher misses.
    for canonical, variants in MANUAL_T1_ALIASES.items():
        for v in variants:
            tier1_alias_add[canonical].append((v, "manual", 0))

    tier2_entries.sort(key=lambda e: e["canonical_name"].casefold())
    return {
        "tier1_alias_additions": tier1_alias_add,
        "tier2_entries": tier2_entries,
    }


def update_tier1_aliases(additions: dict) -> int:
    if not additions:
        return 0
    data = yaml.safe_load(TIER1_FILE.read_text()) or []
    added = 0
    # additions is canonical -> [(variant, first_date, count), ...]
    variant_sets = {k: {v for v, _, _ in items} for k, items in additions.items()}
    for entry in data:
        canonical = entry.get("canonical_name")
        if canonical in variant_sets:
            current = set(entry.get("aliases") or [])
            new = sorted(current | variant_sets[canonical])
            if new != sorted(current):
                entry["aliases"] = new
                added += len(set(new) - current)
    header = (
        "# Tier 1 — Current Rollingwood officials (Council, commissioners, staff).\n"
        "# Auto-generated by scripts/scrape_tier1.py; aliases may be augmented\n"
        "# by scripts/scrape_tier2.py when historical minutes reveal new variants.\n"
        "# Source: rollingwoodtx.gov.\n\n"
    )
    TIER1_FILE.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    )
    return added


def write_tier2(entries: list) -> None:
    to_write = []
    for e in entries:
        stripped = {k: v for k, v in e.items() if not k.startswith("_")}
        to_write.append(stripped)
    header = (
        "# Tier 2 — Historical public speakers from Rollingwood meeting minutes.\n"
        "# Auto-generated by scripts/scrape_tier2.py.\n"
        "# Source: packet-embedded draft minutes from the last 24 months.\n"
        "# Re-run with --write to refresh.\n\n"
    )
    TIER2_FILE.write_text(
        header + yaml.safe_dump(to_write, sort_keys=False, allow_unicode=True, width=1000)
    )


# --- Main orchestration -------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Write tier2_historical.yml and update tier1_officials.yml.")
    ap.add_argument("--months", type=int, default=24,
                    help="Lookback window in months (default 24).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of packets processed (for dev).")
    args = ap.parse_args()

    end = date.today()
    start = (end - timedelta(days=30 * args.months))

    print(f"🔎 Discovering meetings from {start} to {end}…")
    meetings = discover_meetings(start, end)
    with_packet = [m for m in meetings if m.packet_url]
    print(f"   {len(meetings)} meetings discovered; {len(with_packet)} have packet PDFs.")
    window_start = start

    if args.limit:
        with_packet = with_packet[: args.limit]
        print(f"   --limit {args.limit} → processing {len(with_packet)} packets")

    all_hits = []
    packets_processed = 0
    minutes_sections_found = 0
    for i, m in enumerate(with_packet, 1):
        try:
            data = cached_packet_bytes(m.packet_url)
        except Exception as e:
            print(f"   [{i}/{len(with_packet)}] {m.date} {m.title[:40]} — download failed: {e}")
            continue
        text = extract_text(data)
        if not text:
            continue
        sections = find_embedded_minutes(text)
        if not sections:
            # no embedded minutes in this packet (happens if it's the
            # packet for the first meeting of a body in our window)
            packets_processed += 1
            continue
        for sec_date, s, e in sections:
            # Skip embedded minutes older than the 24-month window
            # (packets sometimes include historical appendices).
            if sec_date < window_start:
                continue
            hits = extract_from_minutes(text[s:e], sec_date)
            all_hits.extend(hits)
            minutes_sections_found += 1
        packets_processed += 1
        if i % 10 == 0 or i == len(with_packet):
            print(f"   [{i}/{len(with_packet)}] processed through {m.date}")

    print(f"\n📄 Packets processed: {packets_processed}/{len(with_packet)}")
    print(f"📑 Embedded minutes sections parsed: {minutes_sections_found}")
    print(f"🔖 Raw speaker hits (pre-dedup): {len(all_hits)}")

    cands = assemble(all_hits)
    print(f"👥 Unique candidate names (pre-classification): {len(cands)}")

    result = classify(cands)
    t1_adds = result["tier1_alias_additions"]
    t2 = result["tier2_entries"]

    n_t1_variants = sum(len(v) for v in t1_adds.values())
    print(f"🔗 Tier 1 variants discovered in minutes: {n_t1_variants} across {len(t1_adds)} Tier 1 entries")
    print(f"🧾 Tier 2 entries (non-Tier-1 speakers): {len(t2)}")
    non_res = [e for e in t2 if e["confidence"] == "non_resident"]
    print(f"   of which non_resident: {len(non_res)}")

    # Show 20 samples — mix Pattern-A and Pattern-B
    a_samples = [e for e in t2 if e["_meta"]["address_hits"] > 0][:12]
    b_samples = [e for e in t2 if e["_meta"]["address_hits"] == 0][:8]
    print("\n--- Sample Tier 2 candidates (pattern A first, then B) ---")
    for e in a_samples + b_samples:
        meta = e["_meta"]
        flag = " [non_resident]" if e["confidence"] == "non_resident" else ""
        addr = f"  addresses: {meta['addresses_seen']}" if meta["addresses_seen"] else ""
        print(f"  {e['canonical_name']:30} "
              f"A={meta['address_hits']:2d} B={meta['verb_hits']:3d} "
              f"seen {meta['first_seen']} → {meta['last_seen']}{flag}")
        if addr:
            print(f"     {addr}")

    if t1_adds:
        print("\n--- Variants to add to Tier 1 aliases (canonical ← variant) ---")
        for canonical in sorted(t1_adds):
            for variant, first_date, count in sorted(t1_adds[canonical]):
                src = f"first seen {first_date}, {count} mention{'s' if count != 1 else ''}"
                if first_date == "manual":
                    src = "manual override (scripts/scrape_tier2.py MANUAL_T1_ALIASES)"
                print(f"  {canonical:22} ← {variant:22}  ({src})")

    if args.write:
        added = update_tier1_aliases(t1_adds)
        write_tier2(t2)
        print(f"\n✅ Wrote {TIER2_FILE}")
        print(f"✅ Updated {TIER1_FILE} — {added} alias additions")
    else:
        print("\n(dry-run; pass --write to commit to tier1 + tier2 YAML)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
