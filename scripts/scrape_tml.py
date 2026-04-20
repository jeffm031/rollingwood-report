#!/usr/bin/env python3
"""Scrape a TML city directory profile and upsert into the Tier 1 roster.

Reads config/adjacent_bodies.yml to find sources with `scraper: tml`, fetches
each source's URL, parses the `Government Officials` section, and upserts
canonical-name entries into prompts/roster/tier1_officials.yml.

Scope policy: TML directories include both elected and appointed officials.
This scraper includes every entry listed under "Government Officials" on a
city's TML profile. The same policy applies to operators deploying this in
other cities — if you fork this repo, expect staff as well as council.

Idempotent upsert keyed on (canonical_name, source_url):
  - If a matching entry exists, update its scraped_at.
  - Otherwise, append a new entry.
Existing Rollingwood entries (whose source_url is on rollingwoodtx.gov) are
never touched because their (canonical_name, source_url) can never match a
TML source.

Defaults to dry-run. Pass --write to actually modify the roster.
Run with --self-test to exercise parsing assertions without network access.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "adjacent_bodies.yml"
ROSTER_PATH = PROJECT_ROOT / "prompts" / "roster" / "tier1_officials.yml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}

# Name-suffix whitelist. Tokens immediately following a comma that are part
# of the person's name, not professional credentials.
NAME_SUFFIXES: frozenset[str] = frozenset({
    "Jr.", "Jr", "Sr.", "Sr", "II", "III", "IV", "V",
})

# Manual first/last overrides for names where the last-word-is-surname
# heuristic fails (Dutch/German/Irish prefix surnames, etc.). Parallel to
# scrape_tier1.py's SURNAME_OVERRIDES — see NOTES.md for the planned
# extraction into a shared scripts/name_utils.py once a third scraper
# appears and the pattern is proven.
SURNAME_OVERRIDES: dict[str, tuple[str, str]] = {}

# Heuristic tokens that commonly participate in multi-word surnames. When a
# name contains one, the scraper logs a warning so the operator can eyeball
# the split and add a SURNAME_OVERRIDES entry if wrong. The warning does
# not change the split. Match is case-sensitive against title-cased tokens;
# a future source that publishes lowercased names would miss some of these
# — handle if/when that happens.
SUSPICIOUS_TOKENS: frozenset[str] = frozenset({
    "Van", "van", "Von", "von", "De", "de", "Di", "di", "Da", "da",
    "Del", "del", "La", "la", "Le", "le", "Saint", "St.",
    "Bin", "bin", "Ibn", "ibn",
})


@dataclass
class ScrapedPerson:
    canonical_name: str
    first: str
    last: str
    role: str
    credentials: str = ""


# --- name parsing --------------------------------------------------------

def split_name_and_credentials(raw: str) -> tuple[str, str]:
    """Split a TML name cell into (name, credentials).

    Rule: split on the first comma. If the token immediately after that
    comma is a known name suffix (Jr., III, etc.), peel only the suffix
    into the name; whatever remains after that is credentials.
    Otherwise the whole tail is credentials.

    Examples:
      "Trey Fletcher, AICP, ICMA-CM" -> ("Trey Fletcher", "AICP, ICMA-CM")
      "John Smith, Jr."              -> ("John Smith, Jr.", "")
      "John Smith, Jr., AICP"        -> ("John Smith, Jr.", "AICP")
      "Jane Doe"                     -> ("Jane Doe", "")

    Note: \\s+ collapses ASCII + Unicode whitespace (incl. NBSP) in Python 3,
    so non-breaking spaces between tokens don't break the split.
    """
    s = re.sub(r"\s+", " ", raw).strip()
    if "," not in s:
        return s, ""
    head, tail = s.split(",", 1)
    head = head.strip()
    tail = tail.strip()
    first_tail_token = tail.split(",", 1)[0].split()[0] if tail else ""
    if first_tail_token in NAME_SUFFIXES:
        # Peel only the suffix onto the name; the remainder is credentials.
        rest_of_tail = tail[len(first_tail_token):].lstrip(", ").strip()
        return f"{head}, {first_tail_token}", rest_of_tail
    return head, tail


def split_first_last(name: str) -> tuple[str, str]:
    """Last-word-is-surname heuristic, with SURNAME_OVERRIDES escape hatch."""
    if name in SURNAME_OVERRIDES:
        return SURNAME_OVERRIDES[name]
    parts = name.split()
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


def name_split_looks_suspicious(name: str) -> bool:
    """True if the name shape is one that commonly breaks last-word split.

    Case-sensitive against title-cased input — sufficient for TML, which
    publishes names in title case. Does not change the split; only flags
    for operator eyeball.
    """
    tokens = name.split()
    if len(tokens) > 3:
        return True
    for t in tokens:
        if (t in SUSPICIOUS_TOKENS
                or t.startswith("O'")
                or t.startswith("Mc")
                or t.startswith("Mac")):
            return True
    return False


# --- role normalization --------------------------------------------------

def normalize_role(role: str) -> str:
    """Normalize TML role strings to match Rollingwood Tier 1 style.

    TML publishes both 'City Councilmember Place N' and 'City Council Member
    Place N' — inconsistent at the source. Rollingwood Tier 1 uses 'Council
    Member' (two words, no 'City' prefix; the city is implicit in the
    jurisdiction field). Normalize council-member variants only; other
    roles ('City Administrator', 'City Secretary', etc.) are proper titles
    and pass through verbatim.
    """
    s = re.sub(r"\s+", " ", role).strip()
    m = re.match(r"^City Council\s*[Mm]ember\s+(Place\s+\d+)\s*$", s)
    if m:
        return f"Council Member {m.group(1)}"
    return s


# --- TML parsing ---------------------------------------------------------

def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_tml(html: str) -> list[ScrapedPerson]:
    """Extract all Government Officials from a TML city profile."""
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("div.individuals")
    if container is None:
        return []
    people: list[ScrapedPerson] = []
    for div in container.select("div.individual"):
        name_el = div.select_one("div.name")
        pos_el = div.select_one("div.position")
        if not name_el:
            continue
        raw_name = name_el.get_text(" ", strip=True)
        raw_role = pos_el.get_text(" ", strip=True) if pos_el else ""
        if not raw_name:
            continue
        canonical, credentials = split_name_and_credentials(raw_name)
        role = normalize_role(raw_role)
        first, last = split_first_last(canonical)
        people.append(ScrapedPerson(
            canonical_name=canonical,
            first=first,
            last=last,
            role=role,
            credentials=credentials,
        ))
    return people


# --- config + roster I/O -------------------------------------------------

def load_tml_sources() -> list[dict]:
    data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    sources = data.get("sources") or []
    return [s for s in sources if s.get("scraper") == "tml"]


def read_roster() -> tuple[str, list[dict]]:
    """Return (header_text, entries_list).

    Splits the leading comment header from the YAML body at the first
    entry marker (`- canonical_name`). The header is preserved verbatim
    on write; the entries list is the parsed YAML data.
    """
    text = ROSTER_PATH.read_text()
    lines = text.splitlines(keepends=True)
    split_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("- canonical_name"):
            split_idx = i
            break
    if split_idx is None:
        return text, []
    header = "".join(lines[:split_idx])
    body = "".join(lines[split_idx:])
    entries = yaml.safe_load(body) or []
    return header, entries


def write_roster(header: str, entries: list[dict]) -> None:
    entries_sorted = sorted(
        entries, key=lambda e: e["canonical_name"].casefold()
    )
    body = yaml.safe_dump(
        entries_sorted, sort_keys=False, allow_unicode=True, width=1000
    )
    ROSTER_PATH.write_text(header + body)


# --- upsert --------------------------------------------------------------

def build_entry(person: ScrapedPerson, source: dict, today: str) -> dict:
    entry: dict = {
        "canonical_name": person.canonical_name,
        "first": person.first,
        "last": person.last,
        "aliases": [],
        "role": person.role,
        "source": "tier1",
        "confidence": "adjacent_official",
        "jurisdiction": source["jurisdiction"],
        "source_url": source["url"],
        "scraped_at": today,
    }
    if person.credentials:
        entry["credentials"] = person.credentials
    return entry


def upsert(
    entries: list[dict],
    scraped: list[ScrapedPerson],
    source: dict,
    today: str,
) -> list[tuple[str, str]]:
    """Upsert scraped people into entries in place. Returns a change log
    of (action, description) tuples where action is 'new' or 'update'."""
    log: list[tuple[str, str]] = []
    by_key = {
        (e["canonical_name"], e.get("source_url", "")): i
        for i, e in enumerate(entries)
    }
    for p in scraped:
        new_entry = build_entry(p, source, today)
        key = (new_entry["canonical_name"], new_entry["source_url"])
        if key in by_key:
            existing = entries[by_key[key]]
            old_scraped = existing.get("scraped_at", "(none)")
            existing["scraped_at"] = today
            log.append((
                "update",
                f"{p.canonical_name} ({p.role}) — "
                f"scraped_at {old_scraped} -> {today}",
            ))
        else:
            entries.append(new_entry)
            log.append((
                "new",
                f"{p.canonical_name} ({p.role}) — "
                f"jurisdiction={source['jurisdiction']}",
            ))
    return log


# --- self-test -----------------------------------------------------------

def _self_test() -> int:
    """Exercise parsing invariants without network access.

    Invoked via `python scripts/scrape_tml.py --self-test`. Returns 0 on
    success, 1 on any failure. Asserts catch the kind of subtle bug that
    would otherwise land silently (e.g., the Jr.+credentials composition
    case in split_name_and_credentials).
    """
    name_cred_cases = [
        ("Trey Fletcher, AICP, ICMA-CM", ("Trey Fletcher", "AICP, ICMA-CM")),
        ("John Smith, Jr.",              ("John Smith, Jr.", "")),
        ("John Smith, Jr., AICP",        ("John Smith, Jr.", "AICP")),
        ("Jane Doe",                     ("Jane Doe", "")),
    ]
    for raw, expected in name_cred_cases:
        got = split_name_and_credentials(raw)
        assert got == expected, (
            f"split_name_and_credentials({raw!r}) = {got!r}, expected {expected!r}"
        )
    print(f"split_name_and_credentials: {len(name_cred_cases)} cases OK")

    role_cases = [
        ("City Councilmember Place 1",      "Council Member Place 1"),
        ("City Council Member Place 4",     "Council Member Place 4"),
        ("City Administrator",              "City Administrator"),
        ("Mayor",                           "Mayor"),
        ("Chief of Police",                 "Chief of Police"),
    ]
    for raw, expected in role_cases:
        got = normalize_role(raw)
        assert got == expected, (
            f"normalize_role({raw!r}) = {got!r}, expected {expected!r}"
        )
    print(f"normalize_role: {len(role_cases)} cases OK")
    return 0


# --- CLI -----------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    today = date.today().isoformat()
    tml_sources = load_tml_sources()
    if args.source:
        tml_sources = [s for s in tml_sources if s.get("name") == args.source]
        if not tml_sources:
            print(
                f"No tml source with name={args.source!r} in {CONFIG_PATH.name}",
                file=sys.stderr,
            )
            return 2
    if not tml_sources:
        print("No tml sources configured.", file=sys.stderr)
        return 1

    header, entries = read_roster()
    total_log: list[tuple[str, str, str]] = []
    warnings: list[str] = []

    for source in tml_sources:
        url = source.get("url")
        if not url:
            warnings.append(f"Skipping source {source.get('name')!r}: no url")
            continue
        print(f"Fetching {source['name']}: {url}")
        html = fetch_html(url)
        scraped = parse_tml(html)
        print(f"  {len(scraped)} individuals parsed.")

        for p in scraped:
            if name_split_looks_suspicious(p.canonical_name):
                warnings.append(
                    f"[name-split] {p.canonical_name!r} split as "
                    f"first={p.first!r} last={p.last!r} — may need a "
                    f"SURNAME_OVERRIDES entry"
                )

        log = upsert(entries, scraped, source, today)
        for action, desc in log:
            total_log.append((source["name"], action, desc))

    news = [(src, d) for src, a, d in total_log if a == "new"]
    updates = [(src, d) for src, a, d in total_log if a == "update"]
    print()
    print(f"=== Summary: {len(news)} new, {len(updates)} updated ===")
    if news:
        print()
        print("NEW entries:")
        for src, desc in news:
            print(f"  [{src}] {desc}")
    if updates:
        print()
        print("UPDATED entries (scraped_at only):")
        for src, desc in updates:
            print(f"  [{src}] {desc}")
    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(f"  {w}")

    if args.write:
        write_roster(header, entries)
        print()
        print(f"Wrote {ROSTER_PATH.relative_to(PROJECT_ROOT)}")
    else:
        print()
        print("(dry-run; pass --write to modify the roster)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Scrape a TML city directory profile into the Tier 1 roster."
    )
    ap.add_argument(
        "--source", metavar="NAME",
        help="Only scrape the config entry with this `name` field.",
    )
    ap.add_argument(
        "--write", action="store_true",
        help=f"Write changes to {ROSTER_PATH.relative_to(PROJECT_ROOT)}. "
             "Default is dry-run.",
    )
    ap.add_argument(
        "--self-test", action="store_true",
        help="Run parsing assertions and exit (no network, no writes).",
    )
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
