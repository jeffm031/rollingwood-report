# Tier 1 Expansion — Adjacent-Body Officials

Status: design, 2026-04-20
Supersedes the "Tier 1 scope" open design question in NOTES.md.

## Motivation

`scripts/scrape_tier1.py` pulls only from rollingwoodtx.gov. Adjacent-body
officials who appear at Rollingwood meetings (West Lake Hills mayor, Travis
County commissioners, CTRMA staff, Austin councilmembers) have no canonical
spellings in the roster, so transcripts like "Vaughn" / "Fong" for Mayor
James Vaughan resolve to nothing and ship as-garbled. Same failure class
looms for Trey Fletcher, James Bass, Ann Howard, Paige Ellis, etc.

See NOTES.md "Transcription is non-deterministic across runs" — we cannot
enumerate known garbles; we have to cover the canonical names.

## Decisions

### 1. Tier structure — extend Tier 1, don't split

Single file: `prompts/roster/tier1_officials.yml`. Add four fields to every
entry:

| Field         | Values                                                        |
|---------------|---------------------------------------------------------------|
| `jurisdiction`| Free-form string. "Rollingwood" for existing entries; e.g.    |
|               | "West Lake Hills", "Travis County", "CTRMA", "Austin".        |
| `confidence`  | `rollingwood_official` \| `adjacent_official` \|              |
|               | `historical_speaker` \| `resident` \| `learned`               |
| `source_url`  | The page the entry was scraped from.                          |
| `scraped_at`  | ISO date (`YYYY-MM-DD`) of the scrape that produced the row.  |

**`scraped_at` semantics.** The field means "when did this row's data come
from a source," not "when did we add the field." Existing Rollingwood
entries get `scraped_at: 2026-04-17` (the file's mtime — the last actual
rollingwoodtx.gov scrape), not today's date. Today we are doing a schema
migration, not a re-scrape. Future maintainers: preserve this distinction.

**`source_url` derivation for existing Rollingwood entries.** The 2026-04-20
schema migration assigns `source_url` to existing entries by reading their
`role` field and applying this rule:

- If the entry's `role` contains any `/directory`-sourced content — Council
  members, Mayor, or city staff (anything that isn't a commission-page
  role) — `source_url = https://www.rollingwoodtx.gov/directory`.
- Otherwise, `source_url =` the URL of the first-listed commission page in
  the role string (Parks → `/bc-pc`, P&Z → `/bc-pz`, RCDC → `/bc-corp`,
  BOA → `/bc-boa`, Utility Commission → `/bc-uc`, CPSF → `/bc-cpsf`,
  CRCR → `/bc-crcr`).

Rationale: multi-body entries (e.g., Brook Brown's `Council Member; CPSF
member (...)`) need a single primary source. `/directory` wins over
commission pages because the directory is the canonical roster of current
officials; commission pages are secondary views.

**Rationale for single file.** Lookup in `scripts/roster.py` is flat and
phonetic — splitting Tier 1 would require changing roster code to iterate
additional files with no functional benefit. Jurisdiction is metadata; the
phonetic matcher doesn't care which city someone is from.

### 2. Config-driven sources from day one

`config/adjacent_bodies.yml` lists sources. Each entry:

```yaml
- name: "West Lake Hills (TML)"
  scraper: tml
  url: "https://directory.tml.org/profile/city/607"
  jurisdiction: "West Lake Hills"
  notes: "Mayor + 5 council members."
```

Scrapers read this config. Other Texas towns forking this repo can edit
config only — no code changes.

### 3. Refresh cadence — monthly via PR (future session)

A scheduled GitHub Actions workflow will run the scrapers monthly and open
a PR with roster diffs. Jeff reviews before changes land. The workflow
itself is not being built this session; today's work is: build the scraper,
run it manually once, commit.

### 4. Confidence flow

Downstream `scripts/roster.py` does not yet branch on `confidence`. For
Tier 1 expansion alone the existing phonetic lookup is sufficient — the
goal is making the canonical spelling *available* to match against.

Jurisdiction surfacing in the summary prompt is **deferred** — tracked in
Open items for later sessions. For this session's scope, getting the
canonical spellings into the roster is the entire goal; rendering them
with jurisdictional context is a separate downstream prompt-tuning task.

### 5. Upsert key — `(canonical_name, source_url)` composite

Idempotency key for scraper runs is the pair `(canonical_name, source_url)`.
Rationale:

- One human can legitimately appear under multiple sources (e.g., Gavin
  Massingill could appear as Mayor on rollingwoodtx.gov and as a board
  member on a chamber-of-commerce site). Single-URL keying would force one
  row to overwrite the other; composite keying preserves both.
- Depends on `canonical_name` being stable across scrapes of the same
  source — which holds, since TML and similar directories don't re-spell
  people between scrapes.
- **Intentional corollary:** if a source changes its published spelling
  ("James Vaughan" → "Jim Vaughan"), the scraper creates a new row rather
  than updating the old one. That's desirable: a spelling change on a
  canonical source is signal the operator should see in a diff, not noise
  to silently absorb.

### 6. Election-cycle staleness

Roster entries for elected positions have predictable staleness windows
around elections. Austin's November 2026 cycle may change the District 8
council member if the incumbent does not successfully petition for a third
term; Travis County precinct boundaries may shift after census cycles;
adjacent-city council compositions change on their own cadences. The
monthly refresh PR catches these post-hoc, but operators in other cities
forking this repo should match their refresh cadence to their local
election cadence. Not a blocker for today's work — noted so it's not a
surprise when a refresh PR lands with half a city council replaced.

## Per-tier migration plan

The `confidence` field is being repurposed. Previously it held `confirmed`
across all tiers; the new enum encodes provenance category. This session
migrates only Tier 1 — which means during the transition `confidence`
means different things in different tier files. That's a known, bounded
transitional state, not a hidden one. Explicit end state:

| Tier   | Current `confidence`     | Target `confidence`                           | Migration trigger                                  |
|--------|--------------------------|-----------------------------------------------|----------------------------------------------------|
| Tier 1 | `confirmed` (today)      | `rollingwood_official` \| `adjacent_official` | This session.                                      |
| Tier 2 | `confirmed`              | `historical_speaker`                          | The Thom Farrell / Tier 2 regeneration session.    |
| Tier 3 | `likely_resident`        | `resident`                                    | The TCAD ingester fix session (don't migrate until the known parsing bugs are fixed; otherwise we'd lock the new schema onto about-to-be-regenerated data). |
| Tier 4 | `confirmed` \| `learned` | `learned`                                     | Alongside Tier 2 or Tier 3, whichever lands first. |

## Scraper architecture

```
config/adjacent_bodies.yml
       │
       ▼
scripts/scrape_tml.py        (one module per source format)
scripts/scrape_<other>.py    (TBD — county, CTRMA, Austin)
       │
       ▼
prompts/roster/tier1_officials.yml
```

**Why one module per source format.** TML profiles are HTML tables; CTRMA,
county, and Austin surfaces are likely a mix of PDFs, structured HTML, and
possibly APIs. Parameterizing a single scraper across all of them would be
strictly worse than one module per format — the parse code is where the
format-specific complexity lives, and trying to hide it behind a unified
interface would push the complexity into config.

**Per-scraper contract.**

- Reads `config/adjacent_bodies.yml`, filters to entries where `scraper`
  matches this module.
- Supports `--source NAME` to run a single config entry; default is all
  matching entries.
- Default mode is `--dry-run`; `--write` is required to modify roster
  files. The scheduled refresh workflow invokes scrapers with `--write`
  explicitly; interactive runs stay in dry-run unless the operator opts in.
- Idempotent upsert on `(canonical_name, source_url)`. If present, update
  `scraped_at`; else append. Existing Rollingwood entries (which have no
  `source_url` from an adjacent-body page) are never touched.
- Output YAML stays sorted alphabetically by `canonical_name` (matches
  existing file layout).

## Initial curated source list

For this session, only the first is populated and tested. The rest are
recorded as pending entries in the config file so scope is self-documenting.

**Active now**

1. **West Lake Hills — TML directory**
   `https://directory.tml.org/profile/city/607`
   ~6 entries: Mayor + 5 Council. Parseable TML profile format.

**Pending (URLs to verify before activation)**

2. **Travis County Commissioners Court** — County Judge + Precinct 3
   commissioner (whose precinct includes Rollingwood). URL TBD —
   traviscountytx.gov has individual commissioner pages; need to confirm
   Pct 3 is correct for Rollingwood.
3. **CTRMA Board of Directors** — mobilityauthority.com lists the board;
   exact page TBD.
4. **Austin City Council, District 8** — the district covering Rollingwood.
   Confirmed 2026-04-20: Paige Ellis is the current D8 CM; her individual
   member page is on austintexas.gov (exact URL TBD). She is reaching
   Austin's two-term limit and must petition for a third term to run in
   November 2026 per the city charter — see Decision 6 on election-cycle
   staleness.

**Deferred to future sessions**

- State representatives whose districts include Rollingwood (TX House +
  Senate). Not included today per session scope.

## Explicitly out of scope

**Eanes ISD is not a source.** The Rollingwood Report covers municipal
meetings — the Eanes school district is a separate governmental body that
doesn't appear at Rollingwood council meetings in a substantive sense. No
Eanes ISD references in code, config, or docs.

## Open items for later sessions

- Scheduled refresh workflow (GHA cron + PR-opening action).
- Migrating Tier 2/3/4 entries to the new `confidence` enum (see table).
- Additional scrapers for county / CTRMA / Austin once URLs are verified.
- Surfacing `jurisdiction` in the summary prompt so adjacent-body names
  are disambiguated in the body.
