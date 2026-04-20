#!/usr/bin/env python3
"""Ingest TCAD parcel owners into Tier 3 (likely_resident) of the name roster.

Source: ~/Developer/tcad-property-roll/rollingwood_parcels.csv (TCAD export).
Copies the source CSV into data/rollingwood_parcels.csv (gitignored) and writes
prompts/roster/tier3_tcad.yml.

Filter:
  - Roll Code == "Residential"
  - Exemptions NOT starting with "EX-" (excludes tax-exempt parcels like
    churches and city-owned property)

Row classification (new 2026-04-20):
  - If `is_entity(owner_name)` is True → entity, skip.
  - If `is_entity(owner_name + " " + ofn)` is True:
      - If owner_name contains trust-adjacent tokens (REVOCABLE, LIVING,
        QUALIFIED, PERSONAL, RESIDENCE, MANAGEMENT, FAMILY, CHARITABLE,
        INSURANCE, IRREVOCABLE, ETAL, HOLDING), full-row skip.
      - Else parse owner_name only (treat OFN as entity tail, not spouse).
  - Else → normal parse with OFN as spouse source.

Parse:
  - "LASTNAME, FIRST MIDDLE" and "LASTNAME FIRST MIDDLE" both handled.
  - Joint owners split on " & " or " AND ". For each joint owner, if the
    last token is ≥4 letters (and not a suffix), treat it as a distinct
    surname; otherwise share the primary surname (1-3 letter tokens are
    middle initials).
  - OFN handling:
      * Leading "& " is stripped (TCAD continuation marker).
      * If OFN parses to a clean "First [Middle] Last" shape, it either
        replaces an Owner-Name-derived person (when OFN's first-tokens
        prefix-match) or appends as a new person.
      * Single-token OFN completes truncated joint first names
        ("SHAN" + OFN "SHANTHERI" → "Shantheri Jayakumar").
  - Within-row strict-prefix dedup catches TCAD field-width truncations
    like "Melissa Greenwoo" vs "Melissa Greenwood" (same row).
  - Suffixes (JR, SR, II, III, IV, V, VI) are moved to the end of the
    canonical name.
  - Hyphenated surnames and middle initials are preserved.

Privacy rule: addresses are NOT included in the YAML output.

CLI:
  --write    Commit tier3_tcad.yml + tcad_unresolved_trusts.yml.
  --test     Run regression test against tests/tcad_test_sample.yml (no
             network, no writes); exits 0 on pass, 1 on fail.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
SRC_CSV = Path.home() / "Developer" / "tcad-property-roll" / "rollingwood_parcels.csv"
DATA_DIR = ROOT / "data"
LOCAL_CSV = DATA_DIR / "rollingwood_parcels.csv"
ROSTER_DIR = ROOT / "prompts" / "roster"
TIER3_FILE = ROSTER_DIR / "tier3_tcad.yml"
TRUSTS_FILE = ROSTER_DIR / "tcad_unresolved_trusts.yml"
TEST_FIXTURE = ROOT / "tests" / "tcad_test_sample.yml"

# --- Entity detection --------------------------------------------------------

ENTITY_TOKENS = frozenset({
    "TRUST", "TRUSTEE", "TRUSTEES", "TRST",
    "LLC", "LP", "LLP", "LTD", "INC", "CORP", "CORPORATION",
    "PC", "PLLC", "COMPANY", "HOLDINGS", "HOLDING", "PROPERTIES",
    "FOUNDATION", "ASSN", "ASSOCIATION", "ASSOCIATES", "PARTNERS",
    "PARTNERSHIP", "PTRS", "INVESTMENTS",
    "ESTATE", "CHURCH", "MINISTRIES", "TEMPLE", "SYNAGOGUE",
    "ISD", "HOA", "UNIVERSITY", "COLLEGE", "SCHOOL",
    "TCAD",
})

ENTITY_PHRASES = (
    "CITY OF ", "COUNTY OF ", "STATE OF ", "ESTATE OF ",
    "LIVING TRUST", "FAMILY TRUST", "REVOCABLE TRUST",
    "IRREVOCABLE TRUST", "CHARITABLE TRUST", "INSURANCE TRUST",
    "MANAGEMENT TRUST", "QUALIFIED PERSONAL RESIDENCE",
    "PERSONAL RESIDENCE TRUST",
    "TRUSTEE OF", "TRUSTEES OF",
    "L.L.C.", "L.P.", "P.L.L.C.",
)

TRUST_ADJACENT = frozenset({
    "REVOCABLE", "IRREVOCABLE", "LIVING", "QUALIFIED", "PERSONAL",
    "RESIDENCE", "MANAGEMENT", "FAMILY", "CHARITABLE", "INSURANCE",
    "ETAL", "HOLDING", "EXEMPT", "QPRT",
})

SUFFIXES = frozenset({"JR", "SR", "II", "III", "IV", "V", "VI"})


def _token_set(s: str) -> frozenset:
    return frozenset(re.findall(r"\b[A-Z][A-Z'&.]*\b", (s or "").upper()))


def _is_entity_text(text: str) -> bool:
    if not text:
        return False
    upper = text.upper()
    for phrase in ENTITY_PHRASES:
        if phrase in upper:
            return True
    return bool(_token_set(text) & ENTITY_TOKENS)


def classify_row(owner_name: str, ofn: str) -> str:
    """Return 'entity', 'person-only', or 'normal'.

    - 'entity': full-row skip.
    - 'person-only': parse owner_name, ignore OFN (OFN is an entity tail).
    - 'normal': parse owner_name with OFN as spouse source.
    """
    if not owner_name:
        return "entity"
    if _is_entity_text(owner_name):
        return "entity"
    concat = f"{owner_name} {ofn or ''}".strip()
    if not _is_entity_text(concat):
        return "normal"
    # OFN introduces entity tokens. Check owner_name for trust-adjacent
    # tokens — if present, the person data in owner_name is also polluted.
    if _token_set(owner_name) & TRUST_ADJACENT:
        return "entity"
    return "person-only"


# --- Name parsing ------------------------------------------------------------

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


def _pull_suffix(tokens: list) -> tuple:
    if tokens and tokens[-1].upper() in SUFFIXES:
        raw = tokens[-1].upper()
        formatted = raw if raw in {"II", "III", "IV", "V", "VI"} else raw.title()
        return tokens[:-1], formatted
    return tokens, ""


def _split_joint_owner(tokens: list, primary_last: str) -> tuple:
    """For a joint owner's token list, decide first name and surname.

    Rule: if the last token is ≥4 letters (and not a suffix), treat it as
    a distinct surname. Otherwise (1-3 letter token or suffix) the shared
    primary surname applies; the token is a middle initial.
    """
    tokens, suffix = _pull_suffix(tokens)
    if not tokens:
        return "", primary_last, suffix
    if len(tokens) >= 2 and len(tokens[-1]) >= 4:
        last = tokens[-1]
        first = " ".join(tokens[:-1])
    else:
        last = primary_last
        first = " ".join(tokens)
    return first, last, suffix


def _strict_prefix_match(shorter: str, longer: str) -> bool:
    """True if `shorter` is a strict character prefix of `longer` (len < len)."""
    return len(shorter) < len(longer) and longer.startswith(shorter)


def parse_owner(owner_name: str, owner_first_name: str = "", kind: str = "normal") -> list:
    """Parse a TCAD row's Owner Name + OFN into a list of Person records.

    `kind`:
      - "normal": parse OFN as spouse/joint data directly.
      - "person-only": strip entity tail from OFN first, then parse any
        person data that remains (recovers persons like Gay Erwin from
        'ALAN & GAY ERWIN TRUST' or Scott Campbell from '... FAMILY TRST').
    """
    if not owner_name:
        return []
    name = re.sub(r"\s+", " ", owner_name.strip()).rstrip("&").rstrip().strip()

    if "," in name:
        last_raw, rest = (x.strip() for x in name.split(",", 1))
    else:
        parts = name.split(None, 1)
        last_raw = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    primary_last_raw = last_raw.strip()
    primary_last = _title_case(primary_last_raw)

    joint_parts = [p.strip() for p in re.split(r"\s+(?:&|AND)\s+", rest) if p.strip()]

    people: list = []

    if joint_parts:
        first_tokens = joint_parts[0].split()
        first_tokens, suffix = _pull_suffix(first_tokens)
        if first_tokens:
            people.append(Person(
                first=_title_case(" ".join(first_tokens)),
                last=primary_last,
                suffix=suffix,
            ))

    for jp in joint_parts[1:]:
        tokens = jp.split()
        first, last, suffix = _split_joint_owner(tokens, primary_last_raw)
        if not first and not last:
            continue
        people.append(Person(
            first=_title_case(first),
            last=_title_case(last),
            suffix=suffix,
        ))

    # --- OFN handling -------------------------------------------------------
    ofn = (owner_first_name or "").strip()
    if kind == "person-only":
        ofn = _strip_entity_tail(ofn)

    # Single-token OFN as a truncation completion for a joint owner.
    ofn_for_completion = ofn
    if ofn_for_completion.startswith("& "):
        ofn_for_completion = ofn_for_completion[2:].strip()
    ofc_tokens = ofn_for_completion.split()
    if len(ofc_tokens) == 1:
        completion = ofc_tokens[0].upper()
        for i, p in enumerate(people):
            first_tokens = p.first.split()
            if (len(first_tokens) == 1
                    and completion.startswith(first_tokens[0].upper())
                    and completion != first_tokens[0].upper()):
                people[i] = Person(
                    first=_title_case(ofc_tokens[0]),
                    last=p.last,
                    suffix=p.suffix,
                )
                break
        return _dedupe_within_row(people)

    # Multi-token OFN: parse as zero-or-more persons.
    ofn_people = _parse_ofn_persons(ofn, primary_last_raw)
    for op in ofn_people:
        op_first_tokens = op.first.split()
        action = "append"
        replace_idx = -1
        for i, p in enumerate(people):
            p_first_tokens = p.first.split()
            if _tokens_prefix(op_first_tokens, p_first_tokens):
                # op first is a strict prefix of p first.
                if op.last == p.last:
                    # Same surname: op is the less-complete version. Skip it.
                    action = "drop"
                else:
                    # Different surname: OFN corrects a joint-owner's
                    # surname truncation (Nicastro/Baer, Springer/Serfass).
                    action = "replace"
                    replace_idx = i
                break
            if _tokens_prefix(p_first_tokens, op_first_tokens):
                # p first is a strict prefix of op first: OFN is the more-
                # complete version of an existing person.
                action = "replace"
                replace_idx = i
                break
        if action == "drop":
            continue
        if action == "replace":
            people[replace_idx] = op
        else:
            if not any(p.canonical_name == op.canonical_name for p in people):
                people.append(op)

    return _dedupe_within_row(people)


def _tokens_prefix(short: list, long: list) -> bool:
    """True if `short` token list is a prefix of `long` (elementwise, case-insensitive),
    and `long` is strictly longer. Used for OFN → Owner-Name replacement."""
    if len(short) == 0 or len(short) >= len(long):
        return False
    return all(s.upper() == l.upper() for s, l in zip(short, long))


def _strip_entity_tail(ofn: str) -> str:
    """Strip OFN tokens from the first entity/trust-adjacent token onward.

    Used in 'person-only' rows where OFN contains extractable person data
    before an entity tail (e.g., 'ALAN & GAY ERWIN TRUST' → 'ALAN & GAY ERWIN',
    'SCOTT EUGENE CAMPBELL FAMILY TRST' → 'SCOTT EUGENE CAMPBELL').
    Returns '' if OFN is nothing but entity/trust-adjacent tokens.
    """
    if not ofn:
        return ""
    tokens = ofn.split()
    for i, t in enumerate(tokens):
        if t.upper() in ENTITY_TOKENS or t.upper() in TRUST_ADJACENT:
            return " ".join(tokens[:i]).strip().rstrip("&").strip()
    return ofn


def _parse_ofn_persons(ofn: str, primary_last_raw: str) -> list:
    """Parse OFN into zero or more Person records.

    Handles both single-person ('First [Middle] Last') and joint-owner
    ('A & B' or 'A & B LAST') forms. Strips leading '& ' continuation markers.
    Returns [] when OFN is empty or yields no extractable persons.
    """
    if not ofn:
        return []
    if ofn.startswith("& "):
        ofn = ofn[2:].strip()
    if not ofn:
        return []
    parts = [p.strip() for p in re.split(r"\s+(?:&|AND)\s+", ofn) if p.strip()]
    if len(parts) >= 2:
        people = []
        for part in parts:
            tokens = part.split()
            first, last, suffix = _split_joint_owner(tokens, primary_last_raw)
            if not first and not last:
                continue
            people.append(Person(
                first=_title_case(first),
                last=_title_case(last),
                suffix=suffix,
            ))
        return people
    tokens = ofn.split()
    tokens, suffix = _pull_suffix(tokens)
    if len(tokens) < 2:
        return []
    last = tokens[-1]
    first = " ".join(tokens[:-1])
    return [Person(first=_title_case(first), last=_title_case(last), suffix=suffix)]


def _dedupe_within_row(people: list) -> list:
    """Remove persons whose canonical_name is a strict character prefix of
    another person's canonical_name in the same row. Catches TCAD field-
    width truncations like 'Melissa Greenwoo Morrow' vs 'Melissa Greenwood
    Morrow' appearing in the same row."""
    if len(people) < 2:
        return people
    to_drop = set()
    for i, p in enumerate(people):
        if i in to_drop:
            continue
        for j, q in enumerate(people):
            if i == j or j in to_drop:
                continue
            if _strict_prefix_match(p.canonical_name, q.canonical_name):
                to_drop.add(i)
                break
    return [p for i, p in enumerate(people) if i not in to_drop]


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
    data = sorted(entity_owners, key=lambda x: x["owner_name"].casefold())
    header = (
        "# Tier 3 unresolved entities — TCAD owner strings that are trusts, LLCs,\n"
        "# corporations, churches, or other non-individual owners. Not written\n"
        "# into the main roster; listed here for manual resolution later.\n"
        "# Auto-generated by scripts/ingest_tcad.py.\n\n"
    )
    TRUSTS_FILE.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    )


# --- Ingest ------------------------------------------------------------------

def ingest(rows: list) -> tuple:
    """Run the full ingest pipeline. Returns (individuals_dict, entity_list)."""
    individuals = {}
    entity_list = []
    entity_owner_seen = set()

    for r in rows:
        owner_name = (r.get("Owner Name") or "").strip()
        ofn = (r.get("Owner First Name") or "").strip()
        prop_id = (r.get("Property ID") or "").strip()

        if not owner_name:
            continue

        kind = classify_row(owner_name, ofn)
        if kind == "entity":
            if owner_name not in entity_owner_seen:
                entity_owner_seen.add(owner_name)
                entity_list.append({
                    "owner_name": owner_name, "property_id": prop_id,
                })
            continue

        persons = parse_owner(owner_name, ofn, kind=kind)
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

    return individuals, entity_list


def is_residential(r: dict) -> bool:
    roll = (r.get("Roll Code") or "").strip().lower()
    if roll != "residential":
        return False
    exem = (r.get("Exemptions") or "").strip().upper()
    if exem.startswith("EX-"):
        return False
    return True


# --- Regression test ---------------------------------------------------------

def run_tests() -> int:
    """Run the fixture-based regression test. Returns 0 on pass, 1 on fail."""
    if not TEST_FIXTURE.exists():
        print(f"Fixture not found: {TEST_FIXTURE}", file=sys.stderr)
        return 1
    cases = yaml.safe_load(TEST_FIXTURE.read_text()) or []
    passed = 0
    failed = []
    for c in cases:
        pid = c["property_id"]
        on = c["owner_name"]
        ofn = c.get("owner_first_name", "") or ""
        expected = c["expected"]

        kind = classify_row(on, ofn)
        if expected["kind"] == "entity":
            if kind == "entity":
                passed += 1
            else:
                failed.append((pid, on, ofn, "expected entity", f"got kind={kind}"))
            continue

        # Expected individuals
        if kind == "entity":
            failed.append((pid, on, ofn, f"expected individuals {expected['persons']}",
                           "got kind=entity (full-row skip)"))
            continue

        persons = parse_owner(on, ofn, kind=kind)
        got = [p.canonical_name for p in persons]
        want = list(expected["persons"])
        if sorted(got, key=str.casefold) == sorted(want, key=str.casefold):
            passed += 1
        else:
            failed.append((pid, on, ofn, f"expected {want}", f"got {got}"))

    total = len(cases)
    print(f"TCAD parser regression: {passed}/{total} passed")
    if failed:
        print(f"\nFailures ({len(failed)}):")
        for pid, on, ofn, want, got in failed:
            print(f"  [{pid}] ON={on!r} OFN={ofn!r}")
            print(f"         {want}")
            print(f"         {got}")
        return 1
    return 0


# --- Main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="Commit tier3_tcad.yml + tcad_unresolved_trusts.yml.")
    ap.add_argument("--test", action="store_true",
                    help="Run fixture regression test (no network, no writes).")
    args = ap.parse_args()

    if args.test:
        return run_tests()

    if not SRC_CSV.exists():
        print(f"Source CSV not found: {SRC_CSV}", file=sys.stderr)
        return 1

    DATA_DIR.mkdir(exist_ok=True)
    shutil.copy2(SRC_CSV, LOCAL_CSV)
    print(f"Copied source to {LOCAL_CSV} ({LOCAL_CSV.stat().st_size // 1024} KB)")

    with LOCAL_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)

    residential = [r for r in rows if is_residential(r)]
    individuals, entity_list = ingest(residential)

    print(f"\nStatistics")
    print(f"   Total CSV rows: {total}")
    print(f"   Residential rows kept: {len(residential)}")
    print(f"   Entity owner strings skipped (unique): {len(entity_list)}")
    print(f"   Unique individuals parsed: {len(individuals)}")

    # Spot-check: any individual with an entity token in their source owner_name?
    suspicious = []
    for cname, entry in individuals.items():
        src = entry.get("_source_owner_name", "").upper()
        toks = _token_set(src)
        leaked = toks & ENTITY_TOKENS
        if leaked or any(ph in src for ph in ENTITY_PHRASES):
            suspicious.append((cname, entry["_source_owner_name"], sorted(leaked)))

    print(f"   Trust-skip-leak violations: {len(suspicious)}")
    if suspicious:
        print("   Samples:")
        for cname, src, leaked in suspicious[:10]:
            print(f"     {cname!r} ← {src!r}  (leaked={leaked})")

    if args.write:
        ROSTER_DIR.mkdir(parents=True, exist_ok=True)
        clean = [{k: v for k, v in d.items() if not k.startswith("_")}
                 for d in individuals.values()]
        write_tier3(clean)
        write_trusts(entity_list)
        print(f"\nWrote {TIER3_FILE}")
        print(f"Wrote {TRUSTS_FILE} ({len(entity_list)} entities)")
    else:
        print("\n(dry-run; pass --write to commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
