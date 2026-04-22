# Rollingwood Report — Agent notes

> **Fresh-session startup — read `SESSION_HYGIENE.md` first.** At the
> start of any new Claude Code session in this repo, read
> `SESSION_HYGIENE.md` in full before taking any action. It encodes the
> operating-mode rules: what executes without asking, what requires an
> explicit gate, how commits and pushes are handled. Skipping this step
> has a documented failure-mode track record — 2026-04-21 produced four
> cases where Claude Code routed git commits through Jeff for approval
> despite the rule (in `SESSION_HYGIENE.md`) saying commits in this
> project directory auto-approve. This callout lives in `CLAUDE.md`
> rather than in `SESSION_HYGIENE.md` itself because `CLAUDE.md` is
> auto-loaded at session start; the pointer has to be in the
> auto-loaded file or it can't do its job.

## Standing rules

### Ground truth for names (Tier 1 roster)

The city directory at **https://www.rollingwoodtx.gov/directory** is authoritative
for all current Rollingwood officials — mayor, council, city staff, and (via the
`/bc-*` commission pages linked from the home page) commission members.

- When building or updating Tier 1 of the name roster, fetch from the directory
  (and the `/bc-*` pages for commissions) and use the spellings there **verbatim**
  as canonical.
- Departmental filters narrow the directory to one department. Known filter:
  - Mayor & Council: `/directory?field_department_tid=601`
- Never ask the user to confirm canonical spellings that can be resolved from the
  directory. Fetch and use what the city publishes.
- Flag only genuine ambiguities — e.g., the directory doesn't list someone the
  minutes mention, or the directory entry itself has an obvious typo (site typos
  are preserved as canonical; the correct-spelling variant is added as an alias).

### Tier sources

- **Tier 1 (confirmed):** current officials scraped from rollingwoodtx.gov
  (`scripts/scrape_tier1.py`). Ground truth for canonical spellings.
- **Tier 2 (confirmed / former_staff / former_council / non_resident):** historical
  public speakers from packet-embedded minutes, last 24 months
  (`scripts/scrape_tier2.py`). Cross-references Tier 1 and appends discovered
  variants to the matching Tier 1 entry's `aliases`.
- **Tier 3 (likely_resident):** TCAD parcel owners from
  `~/Developer/tcad-property-roll/rollingwood_parcels.csv` — build via
  `scripts/ingest_tcad.py`.
- **Tier 4 (learned):** accumulated from reviewed past summaries.
  See "Names to Verify" rule below.

### Names to Verify → Tier 4 feedback loop

Every published report ends with an Appendix subsection titled "Names to verify,"
listing people whose names appeared in the transcript but did not resolve to
any roster entry. After the user reviews that report against the source video
and confirms a name's correct spelling, the confirmed entry should be added to
`prompts/roster/tier4_learned.yml` with:
- `source: tier4`
- `confidence: learned`
- `jurisdiction: Rollingwood`
- `aliases: [<transcript variants that should resolve here>]`
- `role:` a short phrase noting context (e.g., "President, Western Hills Little League")

This is how Tier 4 grows — from human-confirmed feedback on past reports, not
automated scraping. Future sessions should understand that the Appendix is not
just an editorial aid; it is the feedback mechanism for improving name
resolution on the next run.

### Git conventions

- **No `Co-Authored-By: Claude` trailers on commits.** Jeff is the
  operator; Claude is the tool. This applies to every commit in this
  repo without exception. Rationale: the project's public
  accountability story depends on Jeff being the single named human
  responsible for what ships. Attributing co-authorship to Claude
  muddies that claim.

### Roster module

- `scripts/roster.py` exposes `lookup(name)` and `format_for_prompt()`.
- Lookup is exact → Double Metaphone (primary OR secondary overlap) → rapidfuzz ≥85%.
- `metaphone` (pip: `metaphone>=0.6`) provides `doublemetaphone` — jellyfish does not.

## Project conventions

- `.env` is gitignored; never commit secrets. OAuth client secrets under
  `client_secret*.json` and tokens under `token*.json` are gitignored.
- `data/packet_cache/` (Tier 2 packet downloads) is gitignored.
- `prompts/summary_prompt.md` is the neutral-newsletter audience prompt
  (not Jeff-as-candidate).
