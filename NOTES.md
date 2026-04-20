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
