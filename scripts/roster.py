"""Name roster with tiered sources and fuzzy lookup.

Tier 1 (officials) and Tier 2 (historical speakers) are authoritative.
Tier 3 (TCAD parcel owners) is broad but less authoritative.
Tier 4 (learned) accumulates from approved past summaries.

Public API:
    lookup(name) -> canonical name or None
    format_for_prompt() -> text block for injection into the summary prompt
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from metaphone import doublemetaphone
from rapidfuzz import fuzz, process

ROSTER_DIR = Path(__file__).parent.parent / "prompts" / "roster"
TIER_FILES = [
    ("tier1", "tier1_officials.yml"),
    ("tier2", "tier2_historical.yml"),
    ("tier3", "tier3_tcad.yml"),
    ("tier4", "tier4_learned.yml"),
]
FUZZY_THRESHOLD = 85


@dataclass
class RosterEntry:
    canonical_name: str
    first: str = ""
    last: str = ""
    aliases: list = field(default_factory=list)
    role: str = ""
    source: str = ""
    confidence: str = ""

    def search_keys(self) -> list:
        keys = [self.canonical_name] + list(self.aliases)
        if self.last:
            keys.append(self.last)
        return [k for k in keys if k]


def _load_file(path: Path, default_source: str) -> list:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or []
    entries = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        name = (raw.get("canonical_name") or "").strip()
        if not name:
            continue
        entries.append(
            RosterEntry(
                canonical_name=name,
                first=(raw.get("first") or "").strip(),
                last=(raw.get("last") or "").strip(),
                aliases=[a for a in (raw.get("aliases") or []) if a],
                role=(raw.get("role") or "").strip(),
                source=(raw.get("source") or default_source).strip(),
                confidence=(raw.get("confidence") or "").strip(),
            )
        )
    return entries


@lru_cache(maxsize=1)
def _load_all() -> tuple:
    entries = []
    for tier, filename in TIER_FILES:
        entries.extend(_load_file(ROSTER_DIR / filename, tier))
    return tuple(entries)


def _metaphone_codes(s: str) -> frozenset:
    """Return the non-empty Double Metaphone codes (primary + secondary) for s."""
    if not s:
        return frozenset()
    primary, secondary = doublemetaphone(s)
    return frozenset(c for c in (primary, secondary) if c)


def lookup(name_from_transcript: str) -> Optional[str]:
    """Resolve a transcript name to a canonical roster name.

    Strategy:
      1. Case-insensitive exact match on canonical_name, aliases, or last.
      2. Phonetic match: Double Metaphone codes overlap (primary OR secondary).
      3. Fuzzy match via rapidfuzz.fuzz.ratio (>= FUZZY_THRESHOLD).
    Returns the canonical_name on match, or None.
    """
    if not name_from_transcript or not name_from_transcript.strip():
        return None
    entries = _load_all()
    if not entries:
        return None

    query = name_from_transcript.strip()
    query_lc = query.casefold()

    # Build (search_key, entry) pool once.
    pool = [(key, e) for e in entries for key in e.search_keys()]

    # 1. Exact (case-insensitive)
    for key, e in pool:
        if key.casefold() == query_lc:
            return e.canonical_name

    # 2. Phonetic — overlap on primary or secondary Double Metaphone code
    query_codes = _metaphone_codes(query)
    if query_codes:
        for key, e in pool:
            if _metaphone_codes(key) & query_codes:
                return e.canonical_name

    # 3. Fuzzy
    choices = [key for key, _ in pool]
    best = process.extractOne(
        query, choices, scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD
    )
    if best is not None:
        _, _, idx = best
        return pool[idx][1].canonical_name

    return None


def format_for_prompt() -> str:
    """Render the full roster as a text block for the summary prompt."""
    entries = _load_all()
    if not entries:
        return "# Rollingwood roster\n(Roster is empty — no entries loaded.)"

    tier_labels = {
        "tier1": "## Tier 1 — Current officials (confirmed)",
        "tier2": "## Tier 2 — Historical public speakers (confirmed)",
        "tier3": "## Tier 3 — TCAD-listed parcel owners (likely residents)",
        "tier4": "## Tier 4 — Learned from past summaries",
    }

    buckets = {k: [] for k in tier_labels}
    for e in entries:
        buckets.setdefault(e.source, []).append(e)

    lines = ["# Rollingwood roster — canonical names for cross-reference"]
    for tier, label in tier_labels.items():
        bucket = buckets.get(tier) or []
        if not bucket:
            continue
        lines.append("")
        lines.append(label)
        for e in sorted(bucket, key=lambda x: x.canonical_name.casefold()):
            suffix = f" — {e.role}" if e.role else ""
            alias_str = (
                f" (also: {', '.join(e.aliases)})" if e.aliases else ""
            )
            lines.append(f"- {e.canonical_name}{suffix}{alias_str}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Smoke test — runnable as: python scripts/roster.py
    print(f"Entries loaded: {len(_load_all())}")
    print()
    print("Lookup tests (expect None while roster is empty;")
    print("after Tier 1 populates Gavin Massengill, Massingill/Massingale should resolve.")
    print("Maske is a known AssemblyAI garble and will only resolve if added as an alias.)")
    for n in ["Maske", "Massingale", "Massingill"]:
        print(f"  lookup({n!r:14}) -> {lookup(n)!r}")
    print()
    print(format_for_prompt())
