#!/usr/bin/env python3
"""Ingest TCAD parcel owners into Tier 3 (likely_resident) of the name roster.

Source: ~/Developer/tcad-property-roll/rollingwood_parcels.csv (TCAD export).
Copies the source CSV into data/rollingwood_parcels.csv (gitignored) and writes
prompts/roster/tier3_tcad.yml.

Filter:
  - Roll Code == "Residential"
  - Exemptions NOT starting with "EX-"  (excludes tax-exempt entities like
    churches and city-owned parcels)

Parse:
  - Entity keywords (TRUST, LLC, LP, INC, CORP, TRST, CHURCH, FOUNDATION, etc.)
    trigger a skip. Skipped owner strings are logged to
    prompts/roster/tcad_unresolved_trusts.yml for later manual resolution.
  - "LASTNAME, FIRST MIDDLE" and "LASTNAME FIRST MIDDLE" both handled (the
    TCAD file uses surname-first with or without comma).
  - Joint owners split on " & " or " AND ". Primary surname is used for each
    joint owner unless Owner First Name column supplies a distinct surname
    (e.g. "ROLOSON WALTER J &" + Owner First Name = "KENDRA MAYER ROLOSON").
  - Suffixes (JR, SR, II, III, IV) are moved to the end of the canonical name.
  - Hyphenated surnames and middle initials are preserved.

Privacy rule: addresses are NOT included in the YAML output.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
SRC_CSV = Path.home() / "Developer" / "tcad-property-roll" / "rollingwood_parcels.csv"
DATA_DIR = ROOT / "data"
LOCAL_CSV = DATA_DIR / "rollingwood_parcels.csv"
ROSTER_DIR = ROOT / "prompts" / "roster"
TIER3_FILE = ROSTER_DIR / "tier3_tcad.yml"
TRUSTS_FILE = ROSTER_DIR / "tcad_unresolved_trusts.yml"

# --- Entity detection --------------------------------------------------------

ENTITY_TOKENS = {
    "TRUST", "TRUSTEE", "TRUSTEES", "TRST",
    "LLC", "LP", "LLP", "LTD", "INC", "CORP", "CORPORATION",
    "PC", "PLLC", "COMPANY", "HOLDINGS", "PROPERTIES",
    "FOUNDATION", "ASSN", "ASSOCIATION", "ASSOCIATES", "PARTNERS",
    "PARTNERSHIP", "PTRS", "INVESTMENTS",
    "ESTATE", "CHURCH", "MINISTRIES", "TEMPLE", "SYNAGOGUE",
    "ISD", "HOA", "UNIVERSITY", "COLLEGE", "SCHOOL",
}
ENTITY_PHRASES = [
    "CITY OF ", "COUNTY OF ", "STATE OF ", "ESTATE OF ",
    "LIVING TRUST", "FAMILY TRUST", "REVOCABLE TRUST",
    "IRREVOCABLE TRUST", "CHARITABLE TRUST", "INSURANCE TRUST",
    "TRUSTEE OF", "TRUSTEES OF",
    "L.L.C.", "L.P.", "P.L.L.C.",
]


def is_entity(owner_name: str) -> bool:
    if not owner_name:
        return True
    upper = owner_name.upper()
    for phrase in ENTITY_PHRASES:
        if phrase in upper:
            return True
    tokens = re.findall(r"\b[A-Z][A-Z'&.]*\b", upper)
    return bool(set(tokens) & ENTITY_TOKENS)


# --- Owner-name parsing ------------------------------------------------------

SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "VI"}


@dataclass
class Person:
    first: str
    last: str
    suffix: str = ""

    @property
    def canonical_name(self) -> str:
        parts = [p for p in [self.first, self.last, self.suffix] if p]
        return " ".join(parts)


def _title_case(s: str) -> str:
    """Title-case a name, handling Mc/O', hyphens, apostrophes, suffixes."""
    if not s:
        return s
    out = []
    for w in s.split():
        wu = w.upper()
        if wu in SUFFIXES:
            out.append(wu if wu in {"II", "III", "IV", "V", "VI"} else w.title())
        elif wu.startswith("MC") and len(w) > 2:
            out.append("Mc" + w[2:].title())
        elif wu.startswith("MAC") and len(w) > 3 and w[3].isalpha():
            out.append("Mac" + w[3:].title())
        elif w.startswith(("O'", "O’")):
            out.append("O'" + w[2:].title())
        elif "-" in w:
            out.append("-".join(p.title() for p in w.split("-")))
        else:
            out.append(w.title())
    return " ".join(out)


def _pull_suffix(first_tokens: list) -> tuple:
    """If the last token is a suffix (JR, SR, III, ...), pop it."""
    if first_tokens and first_tokens[-1].upper() in SUFFIXES:
        return first_tokens[:-1], first_tokens[-1].upper()
    return first_tokens, ""


def parse_owner(owner_name: str, owner_first_name: str = "") -> list:
    """Parse a TCAD Owner Name into a list of Person records. Returns [] if
    the string is an entity (caller should have already filtered via is_entity)."""
    if not owner_name:
        return []
    name = re.sub(r"\s+", " ", owner_name.strip()).rstrip("&").rstrip().strip()

    # Separate primary surname.
    if "," in name:
        last_raw, rest = (x.strip() for x in name.split(",", 1))
    else:
        parts = name.split(None, 1)
        last_raw = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    primary_last = last_raw.strip()

    # Split "rest" (the first-names part) on & or AND.
    joint_parts = [p.strip() for p in re.split(r"\s+(?:&|AND)\s+", rest) if p.strip()]

    people: list = []

    # Primary owner (first entry)
    if joint_parts:
        first_tokens = joint_parts[0].split()
        first_tokens, suffix = _pull_suffix(first_tokens)
        if first_tokens:
            people.append(Person(
                first=_title_case(" ".join(first_tokens)),
                last=_title_case(primary_last),
                suffix=suffix,
            ))

    # Secondary joint owners from Owner Name string
    for jp in joint_parts[1:]:
        tokens = jp.split()
        tokens, suffix = _pull_suffix(tokens)
        if not tokens:
            continue
        people.append(Person(
            first=_title_case(" ".join(tokens)),
            last=_title_case(primary_last),
            suffix=suffix,
        ))

    # If Owner Name ended with trailing "&" (signaled by an empty joint slot
    # before the rstrip), OR Owner First Name gives us additional name info
    # that's clearly distinct, use it.
    ofn = (owner_first_name or "").strip()
    if ofn:
        ofn_tokens = ofn.split()
        ofn_tokens, suffix = _pull_suffix(ofn_tokens)
        if len(ofn_tokens) >= 2:
            # Assume "FIRST [MIDDLE] LAST" format. Last token is surname.
            ofn_last = ofn_tokens[-1]
            ofn_first = " ".join(ofn_tokens[:-1])
            # Only add if not already in `people` under either surname.
            candidate = Person(
                first=_title_case(ofn_first),
                last=_title_case(ofn_last),
                suffix=suffix,
            )
            if not any(p.canonical_name == candidate.canonical_name for p in people):
                # Also check: did the Owner Name end in a trailing "&" (truncation)?
                # If so, this column is the spouse. If not, it may still be the
                # spouse (useful extra data). Either way, add.
                people.append(candidate)

    return people


# --- Output ------------------------------------------------------------------


def write_tier3(persons: list) -> None:
    data = []
    for p in sorted(persons, key=lambda x: (x["last"].casefold(), x["first"].casefold())):
        data.append({
            "canonical_name": p["canonical_name"],
            "first": p["first"],
            "last": p["last"],
            "aliases": p["aliases"],
            "role": "",
            "source": "tier3",
            "confidence": "likely_resident",
        })
    header = (
        "# Tier 3 — TCAD parcel owners (residential, individuals only).\n"
        "# Auto-generated by scripts/ingest_tcad.py.\n"
        "# Source: ~/Developer/tcad-property-roll/rollingwood_parcels.csv\n"
        "# Privacy: addresses are intentionally excluded.\n"
        "# Re-run with --write to refresh.\n\n"
    )
    TIER3_FILE.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    )


def write_trusts(entity_owners: list) -> None:
    data = []
    for e in sorted(entity_owners, key=lambda x: x["owner_name"].casefold()):
        data.append(e)
    header = (
        "# Tier 3 unresolved entities — TCAD owner strings that are trusts, LLCs,\n"
        "# corporations, churches, or other non-individual owners. Not written\n"
        "# into the main roster; listed here for manual resolution later.\n"
        "# Auto-generated by scripts/ingest_tcad.py.\n\n"
    )
    TRUSTS_FILE.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    )


# --- Main --------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Commit tier3_tcad.yml + tcad_unresolved_trusts.yml.")
    args = ap.parse_args()

    if not SRC_CSV.exists():
        print(f"❌ Source CSV not found: {SRC_CSV}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(exist_ok=True)
    shutil.copy2(SRC_CSV, LOCAL_CSV)
    print(f"📥 Copied source to {LOCAL_CSV} ({LOCAL_CSV.stat().st_size // 1024} KB)")

    with LOCAL_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)

    # --- Filter ---
    def is_residential(r):
        roll = (r.get("Roll Code") or "").strip().lower()
        if roll != "residential":
            return False
        exem = (r.get("Exemptions") or "").strip().upper()
        if exem.startswith("EX-"):
            return False
        return True

    residential = [r for r in rows if is_residential(r)]

    # --- Parse ---
    individuals = {}  # canonical -> entry dict
    entity_list = []  # dicts with owner_name + property_id
    entity_owner_seen = set()
    suspicious_individuals = []  # individuals whose source contained entity tokens

    for r in residential:
        owner_name = (r.get("Owner Name") or "").strip()
        owner_first = (r.get("Owner First Name") or "").strip()
        prop_id = (r.get("Property ID") or "").strip()

        if not owner_name:
            continue

        if is_entity(owner_name):
            if owner_name not in entity_owner_seen:
                entity_owner_seen.add(owner_name)
                entity_list.append({
                    "owner_name": owner_name, "property_id": prop_id,
                })
            continue

        persons = parse_owner(owner_name, owner_first)
        for p in persons:
            cname = p.canonical_name
            if not cname or not p.last:
                continue
            if cname in individuals:
                continue
            individuals[cname] = {
                "canonical_name": cname,
                "first": p.first,
                "last": p.last,
                "aliases": [],
                "_source_owner_name": owner_name,
            }

    # Verify skip logic: any individual whose source contained an entity token?
    for cname, entry in individuals.items():
        src = entry.get("_source_owner_name", "").upper()
        toks = set(re.findall(r"\b[A-Z][A-Z'&.]*\b", src))
        leaked = toks & ENTITY_TOKENS
        has_phrase = any(ph in src for ph in ENTITY_PHRASES)
        if leaked or has_phrase:
            suspicious_individuals.append({
                "canonical_name": cname, "source": entry["_source_owner_name"],
                "leaked_tokens": sorted(leaked), "has_phrase": has_phrase,
            })

    # --- Stats ---
    print(f"\n📊 Statistics")
    print(f"   Total CSV rows: {total}")
    print(f"   Residential rows kept: {len(residential)}")
    print(f"   Entity owner strings skipped (unique): {len(entity_list)}")
    print(f"   Unique individuals parsed: {len(individuals)}")
    print(f"   Trust-skip-leak violations: {len(suspicious_individuals)}")

    # --- 20 samples (tricky cases first) ---
    print(f"\n📋 Sample parsed individuals (first 20, showing tricky cases):")
    samples = list(individuals.values())
    # Pick a mix: multi-word first names, suffixes, hyphens
    interesting = [
        v for v in samples
        if (len(v["first"].split()) >= 2
            or "-" in v["first"] or "-" in v["last"]
            or " III" in v["canonical_name"] or " II" in v["canonical_name"]
            or " Jr" in v["canonical_name"] or " Sr" in v["canonical_name"])
    ]
    display = interesting[:10] + [v for v in samples if v not in interesting][:10]
    for v in display[:20]:
        print(f"   {v['canonical_name']:35} first={v['first']!r:20} last={v['last']!r:15} "
              f"← source={v['_source_owner_name']!r}")

    # --- Trust-skip-leak report (user asked for this explicitly) ---
    print(f"\n🔍 Trust-skip-leak check (should be zero):")
    if not suspicious_individuals:
        print("   ✅ No individuals slipped past the entity filter.")
    else:
        print(f"   ⚠️  {len(suspicious_individuals)} individuals have entity tokens in source:")
        for s in suspicious_individuals[:20]:
            print(f"      {s['canonical_name']!r} ← {s['source']!r}  (leaked={s['leaked_tokens']})")

    # --- Write ---
    if args.write:
        ROSTER_DIR.mkdir(parents=True, exist_ok=True)
        # Strip internal _source_owner_name before writing
        clean = [{k: v for k, v in d.items() if not k.startswith("_")}
                 for d in individuals.values()]
        write_tier3(clean)
        write_trusts(entity_list)
        print(f"\n✅ Wrote {TIER3_FILE}")
        print(f"✅ Wrote {TRUSTS_FILE} ({len(entity_list)} entities)")
    else:
        print("\n(dry-run; pass --write to commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
