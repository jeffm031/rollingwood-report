#!/usr/bin/env python3
"""Scrape Tier 1 officials (current Rollingwood government) from rollingwoodtx.gov.

Dry-run by default — prints the full extracted roster for review. Use --write to
commit the result to prompts/roster/tier1_officials.yml.

Sources:
  - /directory                    (Council + all city staff, grouped by dept)
  - /bc-pc, /bc-pz, /bc-corp, /bc-boa, /bc-uc, /bc-cpsf, /bc-crcr
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

BASE = "https://www.rollingwoodtx.gov"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
OUTPUT = (
    Path(__file__).parent.parent / "prompts" / "roster" / "tier1_officials.yml"
)

# Alias overrides — canonical_name -> list of variants to add. Captures
# transcript garbles we've seen plus obvious spelling variants.
ALIAS_MAP: dict[str, list[str]] = {
    "Gavin Massingill": ["Gavin Massengill", "Massengill", "Massingale", "Maske"],
    "Brook Brown": ["Brooke Brown", "Brooke"],
    "Kevin Glasheen": ["Kevin Glashen", "Glashen"],
    "Sara Hutson": ["Sarah Hutson", "Sara Hudson", "Sarah Hudson", "Hudson"],
    "Phil McDuffee": ["Phil McDuffie", "McDuffie"],
    "Amy Pattillo": ["Amy Petillo", "Amy Pitillo", "Amy Patillo",
                     "Petillo", "Pitillo", "Patillo"],
    "Thom Farrell": ["Tom Farrell"],
    "Brian Rider": ["Brian Ryder", "Ryder"],
    "Bobby Hempfling": ["Bobby Hempling", "Hempling"],
    "Alun Thomas": ["Alan Thomas", "Alan"],
    "Kristal Muñoz": ["Crystal Munoz", "Crystal Muñoz", "Kristal Munoz", "Munoz"],
    "Christpher Meakin": ["Christopher Meakin"],
    "Ismael Parra": ["Izzy Parra", "Izzy"],
}

# Short abbreviation prepended to roles on commission pages so combined roles
# read cleanly (Dave Bench → "P&Z Chair; CRCR Chair").
BODY_ABBREV: dict[str, str] = {
    "Parks Commission": "Parks",
    "Planning & Zoning Commission": "P&Z",
    "RCDC": "RCDC",
    "Board of Adjustment": "BOA",
    "Utility Commission": "Utility Commission",
    "Comprehensive Plan Strike Force": "CPSF",
    "CRCR": "CRCR",
}

# Manual first/last overrides for names where the last-word-is-surname
# heuristic fails (Dutch/German/Irish prefix surnames, etc.).
SURNAME_OVERRIDES: dict[str, tuple[str, str]] = {
    "Jay Van Bavel": ("Jay", "Van Bavel"),
}

# Canonical names to drop from Tier 1 entirely (no longer serving, site stale).
# These may still appear in Tier 2 when we scrape historical minutes.
DROP_NAMES: frozenset = frozenset({
    "David Smith",  # removed from RCDC in early 2026; CPSF listing stale
})

COMMISSION_PAGES: list[tuple[str, str]] = [
    ("/bc-pc", "Parks Commission"),
    ("/bc-pz", "Planning & Zoning Commission"),
    ("/bc-corp", "RCDC"),
    ("/bc-boa", "Board of Adjustment"),
    ("/bc-uc", "Utility Commission"),
    ("/bc-cpsf", "Comprehensive Plan Strike Force"),
    ("/bc-crcr", "CRCR"),
]


@dataclass
class RawHit:
    name: str
    role_on_body: str
    body: str
    snippet: str


@dataclass
class Person:
    canonical_name: str
    first: str
    last: str
    roles: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    snippets: list[tuple[str, str]] = field(default_factory=list)  # (body, snippet)


def fetch(path: str) -> str:
    url = BASE + path if path.startswith("/") else path
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def _clean_name(raw: str) -> str:
    # Strip quoted middle names ("Izzy"), collapse whitespace.
    cleaned = re.sub(r'\s*"[^"]+"\s*', " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_name(name: str) -> tuple[str, str]:
    if name in SURNAME_OVERRIDES:
        return SURNAME_OVERRIDES[name]
    parts = name.split()
    if len(parts) == 1:
        return (parts[0], "")
    return (" ".join(parts[:-1]), parts[-1])


def _normalize_cpsf_role(raw_role: str) -> str:
    """Turn the city's long CPSF role descriptors into short clean labels."""
    r = raw_role.strip()
    low = r.lower()
    if low == "committee chair":
        return "CPSF Chair"
    m = re.match(r"^Council Member\s+(.+?)\s+Appointee\s*$", r, re.IGNORECASE)
    if m:
        appointer_surname = m.group(1).split()[-1]
        return f"CPSF member (appointed by {appointer_surname})"
    commission_map = [
        ("park commission", "Parks delegate"),
        ("planning and zoning commission", "P&Z delegate"),
        ("utility commission", "Utility delegate"),
        ("board of adjustment", "BOA delegate"),
        ("rollingwood community development corporation", "RCDC delegate"),
    ]
    for prefix, label in commission_map:
        if low.startswith(prefix):
            return f"CPSF member ({label})"
    m = re.match(r"^(.+?),\s*at\s*large\s*member\s*$", r, re.IGNORECASE)
    if m:
        affil = m.group(1).strip()
        paren = re.search(r"\(([^)]+)\)", affil)
        if paren:
            affil = paren.group(1)
        return f"CPSF at-large member ({affil})"
    return f"CPSF {r}"


def parse_directory(html: str) -> list[RawHit]:
    soup = BeautifulSoup(html, "html.parser")
    hits: list[RawHit] = []
    for h3 in soup.find_all("h3"):
        dept = h3.get_text(strip=True)
        if not dept:
            continue
        ul = h3.find_next_sibling("ul")
        if ul is None:
            # sometimes wrapped in a parent <div class="responsive">
            parent = h3.find_parent()
            if parent:
                ul = parent.find("ul")
        if ul is None:
            continue
        for li in ul.find_all("li"):
            classes = " ".join(li.get("class") or [])
            if "views-row" not in classes:
                continue
            name_el = li.select_one(".views-field-title .field-content")
            pos_el = li.select_one(".views-field-field-position .field-content")
            if not name_el:
                continue
            name = _clean_name(name_el.get_text(" ", strip=True))
            if not name or name.lower().startswith("vacant"):
                continue
            role = pos_el.get_text(" ", strip=True) if pos_el else ""
            hits.append(RawHit(
                name=name, role_on_body=role, body=dept, snippet=str(li)
            ))
    return hits


def _li_is_linklike(li) -> bool:
    """True if the li's content is primarily a single document-link anchor."""
    anchors = li.find_all("a")
    txt = li.get_text(" ", strip=True)
    if not anchors:
        return False
    # One anchor whose text matches nearly the whole li text = link-only item.
    if len(anchors) == 1 and anchors[0].get_text(" ", strip=True) == txt:
        return True
    return False


def parse_commission(html: str, body_name: str) -> list[RawHit]:
    """Parse a /bc-* page. Tries each h2/h3 whose text mentions 'member' (except
    'Membership' alone) and returns hits from the first header whose list
    actually contains people (not document links)."""
    soup = BeautifulSoup(html, "html.parser")
    abbrev = BODY_ABBREV.get(body_name, body_name)

    candidates = []
    for h in soup.find_all(["h2", "h3"]):
        text = (h.get_text(" ") or "").strip().lower()
        if "member" not in text:
            continue
        if text == "membership":  # too generic — often document section
            continue
        candidates.append(h)

    for header in candidates:
        ul = header.find_next("ul")
        if ul is None:
            continue
        hits: list[RawHit] = []
        for li in ul.find_all("li", recursive=False):
            if _li_is_linklike(li):
                continue
            txt = li.get_text(" ", strip=True)
            if not txt or len(txt) > 200:
                continue
            if "," in txt:
                head, tail = txt.split(",", 1)
                name = _clean_name(head)
                role_label = tail.strip()
            else:
                name = _clean_name(txt)
                role_label = "Member"
            if not name or name.lower().startswith("vacant"):
                continue
            combined_role = f"{abbrev} {role_label}".strip()
            hits.append(RawHit(
                name=name, role_on_body=combined_role,
                body=body_name, snippet=str(li),
            ))
        if hits:
            return hits
    return []


def parse_cpsf(html: str) -> list[RawHit]:
    """CPSF uses a <p> with <br>-separated 'Position N: Name, Role' lines."""
    soup = BeautifulSoup(html, "html.parser")
    header = None
    for h in soup.find_all(["h2", "h3"]):
        text = (h.get_text(" ") or "").strip().lower()
        if "strike force members" in text:
            header = h
            break
    if header is None:
        return []
    para = header.find_next("p")
    if para is None:
        return []
    # Normalize <br> to newlines, then split.
    for br in para.find_all("br"):
        br.replace_with("\n")
    raw_text = para.get_text("\n")
    hits: list[RawHit] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^Position\s+\d+:\s*(.+)$", line)
        if not m:
            continue
        remainder = m.group(1).strip()
        if not remainder or remainder.lower().startswith("vacant"):
            continue
        if "," in remainder:
            head, tail = remainder.split(",", 1)
            name = _clean_name(head)
            role_label = tail.strip()
        else:
            name = _clean_name(remainder)
            role_label = "Member"
        if not name:
            continue
        hits.append(RawHit(
            name=name,
            role_on_body=_normalize_cpsf_role(role_label),
            body="Comprehensive Plan Strike Force",
            snippet=f"<p fragment>Position …: {remainder}</p>",
        ))
    return hits


def assemble(hits: list[RawHit]) -> dict[str, Person]:
    people: dict[str, Person] = {}
    for h in hits:
        key = h.name
        if key in DROP_NAMES:
            continue
        if key not in people:
            first, last = _split_name(h.name)
            people[key] = Person(canonical_name=h.name, first=first, last=last)
        p = people[key]
        if h.role_on_body and h.role_on_body not in p.roles:
            p.roles.append(h.role_on_body)
        p.snippets.append((h.body, h.snippet))
    for canonical, person in people.items():
        person.aliases = ALIAS_MAP.get(canonical, [])
    return people


def collect_all() -> dict[str, Person]:
    all_hits: list[RawHit] = []
    all_hits.extend(parse_directory(fetch("/directory")))
    for path, body in COMMISSION_PAGES:
        html = fetch(path)
        if body == "Comprehensive Plan Strike Force":
            all_hits.extend(parse_cpsf(html))
        else:
            all_hits.extend(parse_commission(html, body))
    return assemble(all_hits)


def render_review(people: dict[str, Person]) -> str:
    lines: list[str] = []
    lines.append(f"# {len(people)} unique Tier 1 officials extracted\n")
    for canonical in sorted(people.keys(), key=str.casefold):
        p = people[canonical]
        lines.append(f"--- {p.canonical_name} ---")
        lines.append(f"  role:    {'; '.join(p.roles) if p.roles else '(none)'}")
        lines.append(f"  aliases: {p.aliases if p.aliases else '[]'}")
        lines.append(f"  first/last: {p.first!r} / {p.last!r}")
        for body, snippet in p.snippets:
            snip = re.sub(r"\s+", " ", snippet).strip()
            if len(snip) > 400:
                snip = snip[:400] + "…"
            lines.append(f"  [{body}] {snip}")
        lines.append("")
    return "\n".join(lines)


def to_yaml(people: dict[str, Person]) -> str:
    data = []
    for canonical in sorted(people.keys(), key=str.casefold):
        p = people[canonical]
        data.append({
            "canonical_name": p.canonical_name,
            "first": p.first,
            "last": p.last,
            "aliases": p.aliases,
            "role": "; ".join(p.roles),
            "source": "tier1",
            "confidence": "confirmed",
        })
    header = (
        "# Tier 1 — Current Rollingwood officials (Council, commissioners, staff).\n"
        "# Auto-generated by scripts/scrape_tier1.py.\n"
        "# Source: rollingwoodtx.gov. Ground truth; name spellings authoritative.\n"
        "# Re-run the scraper with --write to refresh.\n\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help=f"Write YAML to {OUTPUT.relative_to(Path.cwd())}.")
    args = ap.parse_args()

    people = collect_all()
    print(render_review(people))

    if args.write:
        OUTPUT.write_text(to_yaml(people))
        print(f"\n✅ Wrote {OUTPUT}")
    else:
        print("(dry-run; pass --write to commit to tier1_officials.yml)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
