# Rollingwood Report — Notes

Working notes for deferred work and open design questions. Not a spec; a backlog.

## Backlog

### Fix Mayor Vaughan spelling

The 2026-04-14 Special City Council summary rendered the Mayor of West Lake
Hills as "James Vaughn" six times in the body. Authoritative spelling is
**James Vaughan** (7 letters: V-a-u-g-h-a-n), verified against the TML city
directory, the Westlake Chamber of Commerce, and the City of West Lake Hills'
own chamber listing. The AssemblyAI transcript rendered the name variably
("Vaughn" and "Fong"); the model adopted "Vaughn" as canonical because no
roster entry existed to override it.

- **Immediate fix:** add James Vaughan to Tier 1 as a one-off entry, with
  aliases covering the transcription variants we've seen ("Vaughn", "Fong",
  and any others).
- **Real fix:** see the "Tier 1 scope" design question below. The one-off
  entry buys correctness for the next meeting; the design change is what
  prevents this failure class from recurring with every adjacent-body
  official who speaks at a Rollingwood meeting.

### Thom Farrell canonical — RESOLVED 2026-04-20

Originally flagged as a Tier 2 misspelling. On 2026-04-21 review,
discovered the fix already landed: Tier 1's `scrape_tier1.py` `ALIAS_MAP`
was updated to canonicalize "Thom Farrell" with "Tom Farrell" as an
alias (commit `38a3d54`). Tier 2's `tier2_historical.yml` currently has
no Farrell entry at all — fuzzy lookup against Tier 1 dedupes any
future historical-speaker hits. No further action on the roster.

One related prompt-level observation that remains open: the LLM sometimes
renders "Tom" in summary body text despite the roster listing "Thom" as
canonical with "Tom" as alias. Seen in the 2026-04-21 Tier 2 migration
regen. Prompt tuning issue (`prompts/summary_prompt.md`), not a roster
issue. Low priority — log here if it recurs in published reports.

### Tier 2 per-entry packet URLs (low priority)

After the 2026-04-21 schema migration, all Tier 2 entries carry
`source_url: https://www.rollingwoodtx.gov/meetings` — a general
reference, not the specific packet a speaker was discovered in. The
scraper already tracks the meeting date per hit (see `_meta.first_seen`
/ `_meta.last_seen`) but doesn't stash the packet URL itself. Next time
`scripts/scrape_tier2.py` runs in full, update it to write the specific
packet URL (or the most recent packet URL, if a speaker appears in
multiple) as `source_url` instead of the general reference. Low
priority — the general reference is adequate for the
source-provenance use case today.

### Drop redundant YOUTUBE URL field from run.py user_content now that VIDEO ID is explicit

### Memory hygiene audit

Three places had stale "2026 Council candidate" framing propagated across
Claude Code's persistent memory (`user_role.md`,
`feedback_no_claude_coauthor_trailer.md` "why" paragraph, `MEMORY.md` index).
All caught and corrected 2026-04-20. Periodic audit of
`~/.claude/projects/.../memory/` against current project reality
recommended, especially for any assertions about Jeff's civic status,
scope of project, or settled decisions. Stale memory is worse than no
memory because it sounds authoritative.

### Prompt-level jurisdiction surfacing — blocks clean Tier 1 resolution on ambiguous roles

The 2026-04-20 4/14 re-run after the TCAD fix demonstrated that when two
jurisdictions both have an official with the same role (Rollingwood's
Alun Thomas vs. West Lake Hills' Trey Fletcher, both "City Administrator"),
the LLM flags one of them as unresolved rather than resolving to the
canonical spelling.

**Root cause.** `scripts/roster.py`'s `format_for_prompt()` renders each
entry as `- {canonical_name} — {role} (also: {aliases})` with no
jurisdiction. So the prompt sees two "City Administrator" entries with
no city context, and the LLM does the honest thing and flags one as
needing verification.

Flagged in `design/tier1_expansion.md` as "Decision 4:
jurisdiction-surfacing deferred." No longer deferrable in practice.

**Fix.** Update `format_for_prompt()` to include jurisdiction in the
rendered line, e.g., `- Trey Fletcher — City Administrator of West Lake
Hills (adjacent body)`. Medium effort; should land before any further
Tier 1 adjacent-body scrapers (otherwise the problem compounds across
jurisdictions as Travis County, CTRMA, and Austin D8 come online).

**Priority: high.** Blocks correctness of every summary that mentions
a role shared across Rollingwood and an adjacent body.

### Fix tier3 TCAD ingester — name parsing bugs

`scripts/ingest_tcad.py` produces malformed entries in `prompts/roster/tier3_tcad.yml`.
Observed on 2026-04-20 pre-commit review of 780 entries.

**Symptoms.**

- Trust/entity tokens interleaved into person names, e.g.
  `Richard T 2020 Qualified Personal Anderson` (should be `Richard T Anderson`
  with the trust owner filtered out), `Carolyn Revocable Living Kavanagh`,
  `Nora Revocable Saldivar`, `Revocable Schoolfield`.
- Entity-only rows that weren't filtered out at all: `Living Trust`,
  `Management Trust`, `Revocable Trust`, `Alan & Gay Erwin Trust`,
  `Personal Residence Trust Etal`, `Residence Trust & Mo Anderson 2020 Qualified`.
- Apparent truncation of real surnames, e.g. `Melissa Greenwoo Morrow`
  (likely "Greenwood" truncated).

**Hypothesis.** The ingester likely isn't handling TCAD's multi-token owner
field correctly — the CSV packs trust name, trustee, and co-owner into one
field with inconsistent delimiters, and the parser appears to split on
whitespace and stuff tokens into `first`/`last` without detecting the
entity-vs-individual boundary. The `Greenwoo` truncation suggests a
fixed-width or off-by-one slice somewhere in the parse path.

**Scope of impact.** Tier 3 is only consulted when a transcript name fails
to match Tiers 1 and 2. So this affects correctness for **first-time
resident speakers** who aren't officials and haven't spoken in the last 24
months — a long tail, but it's exactly the cohort Tier 3 exists to cover.
The mangled entries also pollute the phonetic/fuzzy lookup space and can
cause false positives against other names.

**Fix plan.**

1. Audit `scripts/ingest_tcad.py` parsing logic against the raw
   `~/Developer/tcad-property-roll/rollingwood_parcels.csv`.
2. Identify which parsing branches produce bad output — specifically the
   entity-filter predicate and the first/last split.
3. Fix and regenerate `prompts/roster/tier3_tcad.yml`.
4. Re-run `scripts/test_local.py` on the 2026-04-14 meeting to confirm
   no regression in name resolution.

**Priority.** Lower than Tier 1 expansion (Mayor Vaughan / adjacent-body
officials), but should be fixed **before a wider subscriber launch** —
Tier 3 will matter more once reports go to residents who expect to see
their neighbors' names rendered correctly.

### Centralize SURNAME_OVERRIDES across scrapers

`SURNAME_OVERRIDES` — the manual first/last override map for names where
the last-word-is-surname heuristic fails — is currently duplicated in
`scripts/scrape_tier1.py` and `scripts/scrape_tml.py`. Same problem affects
every scraper, since they all confront the same class of multi-word-surname
edge case (Van Bavel, De Los Santos, O'Brien, etc.).

Not urgent. Premature abstraction is worse than mild duplication, and we
have only two scrapers today. Extract to a shared `scripts/name_utils.py`
when the third scraper is added (Travis County, CTRMA, or Austin). The
warning-log instrumentation in `scrape_tml.py` (`name_split_looks_suspicious`)
should move into the shared module at that point. Same thinking applies to
`read_roster`/`write_roster`, which are also duplicated.

### Per-source error isolation in multi-source scraper runs

When the scheduled refresh workflow is added, wrap each source fetch +
parse + upsert in try/except so an individual source failure (404,
timeout, malformed HTML) doesn't abort the whole run. Log failures as
warnings and continue with remaining sources. The PR-opening action
should surface the failures in the PR description so they're visible in
review without the operator having to read the workflow logs.

Today only one adjacent-body source is active (`West Lake Hills (TML)`),
so this doesn't matter yet — a failure there is the whole run anyway.

### scrape_tml.py dry-run output should surface the credentials field

The scraper's dry-run NEW-entries block prints `canonical_name`, `role`,
and `jurisdiction` but not `credentials`. When `credentials` is non-empty
(e.g., Trey Fletcher → `"AICP, ICMA-CM"`, Jennifer Bills → `"AICP, LEED AP"`),
the operator has no way to eyeball what would land in YAML without
separately calling `build_entry` on the parsed `ScrapedPerson`. The
2026-04-20 West Lake Hills dry-run required exactly this workaround.

Low priority. Fix by appending `credentials={p.credentials!r}` to the
NEW-entry log line in `upsert()` when non-empty, or by printing the full
`build_entry` dict in a `--verbose` mode.

### Council Data Project schema reference (generalization phase)

When generalizing for other towns (phase 8+), review Council Data Project's
ingestion model at https://councildataproject.org/cdp-backend/ingestion_models.html
for schema inspiration. Their Event / Session / Body / Matter / Person /
Seat / Role / Vote modeling is well-designed and battle-tested on ~10 cities.

**Do not adopt their stack.** CDP is GCP-heavy, last released June 2023,
and org signals point to unmaintained instances getting archived.
Product shape is also wrong for us — CDP is a searchable meeting database;
the Rollingwood Report is an automated prose newsletter. The data *model*
is the part worth borrowing; the infrastructure and product are not.

### citymeetings.nyc — contact for cross-city expansion

Vikram Oberoi runs citymeetings.nyc — the closest existing product to this
project. One-person operation, AI + human oversight, ~10k monthly visitors,
NYC-scale. He has publicly offered collaboration for cross-city deployment:
*"If you live elsewhere and would like to bring citymeetings.nyc-like
coverage to your area, email me."*

Worth reaching out once the Rollingwood Report is in beta and we have
something concrete to show. Not urgent — premature contact with nothing
to demo is worse than no contact.

## Observations

### Transcription is non-deterministic across runs

On the same audio (4/14/2026 Special City Council, video `ecUUdeLa5_A`),
AssemblyAI's `universal-3-pro` produced materially different name
renderings on consecutive days:

- 2026-04-18 spike: "Fong" (for Vaughan), "Masko" (for Massingill)
- 2026-04-20 re-run: "Vaughn" (for Vaughan), "Mascow" (for Massingill)

**Implication for roster design.** We can't rely on having seen a
specific phonetic error before in order to catch it. The roster has to
be comprehensive enough in canonical names that whatever the
transcriber happens to produce on a given run, the canonical spelling
is available for the phonetic/fuzzy match to land on. This reinforces
the breadth-first rationale for Tier 1 adjacent-body expansion: it's
not about enumerating known transcriber errors, it's about covering
everyone who might be named.

## Open design questions

### Tier 1 scope — expand to adjacent-body officials

**Diagnosis.** `scripts/scrape_tier1.py` pulls from rollingwoodtx.gov only
(`/directory` plus the seven `/bc-*` commission pages). By design, it cannot
include officials from neighboring or overlapping bodies — West Lake Hills,
Eanes ISD, Travis County, CTRMA, state legislators whose districts include
Rollingwood. Mayor Vaughan was the first instance of this blind spot to
surface in a published report; the same class of error is waiting to happen
with Trey Fletcher (WLH city administrator), James Bass (CTRMA executive
director), Ann Howard (Travis County commissioner), Paige Ellis (Austin CM),
and others who appeared at the 2026-04-14 meeting alone.

**Likely scope.** Roughly 40–80 names across curated sources:

- TML city directory (West Lake Hills officials)
- Eanes ISD board page
- Travis County Commissioners Court
- CTRMA board
- State reps whose districts include Rollingwood

**Selection rule: positional, not geographic.** Include officials whose
roles mean they might plausibly appear at (or be substantively discussed
at) a Rollingwood meeting. This is the MOPAC South / joint-meeting /
regional-policy set, not "everyone in the Austin metro."

**Open questions when we pick this up.**

- Where does this go — a new tier (Tier 1-adjacent?), or an expansion of
  Tier 1 with a `jurisdiction` field?
- How is it kept current? The city directory pages aren't standardized
  across adjacent bodies the way rollingwoodtx.gov's pages are. Likely a
  per-source scraper plus a manually curated seed list.
- How does confidence flow? These aren't Rollingwood officials; should
  they carry a different confidence tier so the prompt can treat them
  as "confirmed spelling, non-Rollingwood affiliation"?

### Prompt-level uncertainty escalation (lower priority)

When the LLM sees phonetic ambiguity in a name (as it did with
"Vaughn"/"Fong" on 2026-04-14) and cannot match the roster, the current
prompt has it commit to one spelling in the report body and note the
variant in the Appendix → Transcript notes. It should instead flag the
name as unverified in the body itself — marking it as ambiguous to the
reader at the point the name appears, rather than burying the flag in an
editor-facing appendix.

This is prompt tuning, not architecture. Should come **after** the Tier 1
expansion — otherwise we'd be tuning the uncertainty behavior while the
inputs are still missing canonical data for half the people being named.
