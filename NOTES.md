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

### Tier 4 certainty-vs-provenance deferred (low priority)

The 2026-04-21 Tier 4 migration collapsed `confidence: confirmed | learned`
(a within-tier data-quality signal) into `confidence: learned` (a
provenance category per the design-doc enum). Both existing Tier 4 entries
were `confirmed` at migration time; no information was lost because the
signal was inert in downstream code — `scripts/roster.py` doesn't branch
on Tier 4 confidence, and nothing else reads it.

When the feedback-loop pipeline is built (depends on Gmail send pipeline
existing first — the loop is "published report → operator confirms name
→ entry lands in Tier 4"), revisit whether auto-added-by-correction
entries need a lower-certainty flag distinct from their `learned`
provenance.

Options considered and deferred:
- Add a `certainty: confirmed | learned` field to Tier 4 entries
  (preserves the signal; adds schema that only Tier 4 uses).
- Expand the design-doc enum with a `confirmed` value (breaks the
  one-value-per-tier pattern).

Pick the right shape once the feedback loop's actual requirements are
visible. Deciding today would commit the schema before the requirements
are clear.

### Move OAuth consent screen from Testing to Production before beta launch (medium priority)

**Discovered 2026-04-21** during the first `scripts/send_preview.py --send`
attempt (Chunk C). The Gmail API refresh call returned `invalid_grant:
Token has been expired or revoked` four days after `token_newsletter.json`
was bootstrapped (2026-04-17 → 2026-04-21). Bootstrap had to be re-run
to complete the send test.

**Root cause.** The newsletter GCP project's OAuth consent screen is in
**Testing** mode. Testing-mode refresh tokens are invalidated after
~7 days of issuance (in practice sometimes sooner, as observed here at
day 4). This is fine for early development but will bite the production
pipeline — the GHA cron runs on an hourly-ish schedule; an expired
refresh token means the job silently fails to send summaries until
someone re-bootstraps the token locally.

**Structural fix.** In Google Cloud Console → APIs & Services → OAuth
consent screen, move the newsletter project's consent screen from
**Testing** to **In production**. This requires completing the App
verification step for the scopes in use. For reference, current scopes
(from `scripts/bootstrap_google_auth_newsletter.py`):

- `gmail.send` — restricted scope (not sensitive per Google's
  classification); verification usually light-touch
- `gmail.readonly` — restricted scope, same
- `gmail.labels`, `gmail.modify` — restricted
- `drive.file` — app-created files only, non-sensitive
- `spreadsheets.readonly` — non-sensitive

Restricted scopes may need a brief security assessment; the usual
turnaround is a few days to a couple of weeks.

**Blocker relationship.** Must land **before beta launch.** A production
pipeline that silently dies on a 7-day refresh-token expiry is not a
production pipeline. Token refresh has to "just work" indefinitely once
the GHA cron is the only thing hitting the API.

**Priority: medium.** Doesn't block the feedback-loop or prompt-tuning
work Claude Code can do locally, but is a hard prerequisite for the
beta-cron actually running. Should land in the same phase as the Gmail
feedback-loop wiring.

### Prompt-tuning followup (medium priority)

The 2026-04-22 evening prompt-tuning pass (commit `896bbef`) landed
the primary beta-blocker fix and identified three residual items.
The 2026-04-23 followup resolved one measurably, likely-resolved
another as defensive hardening, and surfaced a regression on the
third that pushes it back to open with diagnostic evidence.

**Fixed by `896bbef`.** The section-anchor citation pattern (a single
timestamp reused across multiple distinct claims from a single
discussion segment) is resolved. Three of four audited citation
errors corrected: Bunch's postpone request, Paige Ellis resolution,
April 22 town hall all cite Bunch's turn start at 1:25:48. Preserve-
list items held: date-error self-correction, roster canonicalization,
Transcript-vs-extrapolation distinction.

**Residual item 2 (canonical-vs-alias) — RESOLVED by `2d97e76`
(2026-04-23).** Added a concrete categorical example at line 81
showing the transcript-to-canonical mapping ("if transcript says
'Tom Farrell' ... body must say 'Thom Farrell' — never 'Tom
Farrell'"). Reduced "Tom Farrell" body occurrences from 4 to 0
across three regens (yesterday's investigation Test B, today's
Fix 1 regen, today's Fix 2 regen). Pattern generalizes safely —
categorical mapping shape.

**Residual item 3 (Fletcher-in-Names-to-Verify drift) — likely
resolved by `3f901f3` (2026-04-23), unverified.** Added a categorical
example at lines 55–60 showing the boundary (Fletcher resolves under
a jurisdiction subsection; MUST NOT appear in Names-to-Verify).
Committed as defensive hardening rather than a measured fix:
Fletcher was already absent from Names-to-Verify in today's post-Fix-1
regen, so no before/after signal was available to measure. Example
shape is categorical (same class as item 2's fix), so the fix is
expected safe — but uncertainty is slightly elevated now that item
1's attempt shows some example shapes induce new failure modes
(see meta-observation below). Justification remains pattern-
consistency with item 2's proven mechanism plus defensive hardening
against non-deterministic regressions. Worth confirming with a
second-meeting stability check when one runs.

**Residual item 1 (bare-factual-bullet citations) — STILL OPEN.**
Attempted a fix on 2026-04-23 (uncommitted, reverted). The edit
added a concrete specific-coordinate example to line 75's citation
rule — showing that a bare declarative sentence like "Council will
reconvene the following evening" must cite the announcer's turn
(0:55:20, Massingill) not an adjacent turn (0:55:14, Vaughan). Primary
target hit (Example 4 citation moved 0:55:14 → 0:55:20) but
**regressed previously-correct Bunch citations**. Six Bunch-derived
claims that had been correctly cited at 1:25:48 (Bunch's single turn
start) regenerated with fabricated sub-turn timestamps: 1:28:00,
1:30:00, 1:35:00, 1:38:00, 1:40:00, 1:41:00. Direct transcript
verification: none of these exist as markers (`grep -c "^(1:28:00)"`
etc. returns 0 for all six). The LLM fabricated sub-turn precision
that the transcript doesn't encode, violating the prompt's own
"read verbatim from the `(H:MM:SS)` marker" rule.

Future fix needs diagnostic work on what example shape binds the
bare-factual-bullet rule without teaching wrong-level precision.
Don't re-attempt in the same session that discovered the regression —
fresh context, diagnostic approach.

**Meta-observation: example shape matters.** Yesterday's investigation
(`sessions/2026-04-23_canonical_vs_alias_investigation.md`) found
that concrete examples bind abstract rules where prose-only drifts.
Today's Fix 3 regression refines that finding with a caveat:

- **Categorical mapping examples** ("if transcript says X, output Y"
  — Fix 1 and Fix 2's shape) generalize safely. They teach a pattern
  that the LLM applies across cases without over-generalizing the
  example's surface features.
- **Specific-coordinate examples** ("cite 0:55:20 not 0:55:14" —
  Fix 3's shape) risk teaching the wrong level of precision. The LLM
  sees seconds-level discrimination modeled and infers that seconds-
  level discrimination is always expected, even where the transcript
  doesn't support it.

Sample is small: two fixes using the categorical shape (Fix 1
measured safe with 4 → 0 replication across three regens; Fix 2
inferred safe, not measured) and one attempt using the specific-
coordinate shape (Fix 3 measured unsafe). Future prompt-tuning should
treat this as a working hypothesis to confirm with further evidence,
not a settled rule.

Future prompt-tuning work should start from this refined understanding:
*concrete* does not mean "literal coordinates from the problem case" —
*concrete* means "specific enough to show the pattern without
overfitting to surface features of the example."

**Priority: medium.** Downgrade from HIGH (pre-`896bbef`) remains
justified — beta-blocker citation bug fixed, item 2 fully resolved,
item 3 hardened-pending-verification, item 1's residual narrower
than any originally-bundled observation. Subscriber-visibility of
item 1 (one wrong citation timestamp on one declarative bullet) is
lower than item 2's was (visibly misspelled name in body text).

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

### Project-knowledge hygiene (low priority)

Sibling failure mode to the Memory hygiene audit above, on a different
automated-context surface.

**Discovered 2026-04-23** when a chunk briefed Claude Code to rewrite
`methodology.md` and `editorial-policy.md`. The chunk's premise
described specific stale content in those files (candidate-for-Council
framing, "human review before every send" commitment, November 2026
election timeline); the files did not exist in the repo and never had
been committed. Investigation traced the mismatch to stale
`methodology.md` and `editorial-policy.md` drafts sitting in the
Claude Project's knowledge — silently loading into every new Claude
conversation's context — carrying framing that predated the
2026-04-18 project pivot (from candidate-for-Council to
applicant-for-RCDC-and-Parks-Commission).

**Action taken 2026-04-23.** Both stale drafts deleted from Project
knowledge. Fresh Claude contexts no longer inherit the outdated
current-state claims.

**Standing practice going forward.** Review Project knowledge for
staleness when the project takes substantial direction changes
(shifts in Jeff's civic role, scope changes, product direction shifts),
or roughly quarterly when no such event has occurred. Current-state
docs (methodology, editorial policy, status/roadmap) are higher-risk
for silent staleness because they make claims a reader would treat as
authoritative; architectural and historical docs are lower-risk
because they don't claim to describe present state. When a new
foundational doc is written to the repo and added to Project knowledge,
any older version must be replaced or removed, not supplemented —
otherwise the context window carries both, and the LLM has no reliable
way to know which is current.

**Priority: low.** Pattern note, not a blocker. Today's instance was
caught early (before content got drafted against the stale premise).
The recurring risk is a new Claude Code context acting on false
project-state assumptions without catching them.

### Prompt-level jurisdiction surfacing — RESOLVED 2026-04-21

Originally flagged as HIGH / beta-blocker during the 2026-04-20 4/14
re-run that showed Alun Thomas and Trey Fletcher both rendering as
"City Administrator" without city context, causing the LLM to flag
Fletcher as unresolved. Fix shipped the following morning: commit
`a942e03` ("Surface jurisdiction in roster prompt; Tier 1 subsections")
updated `scripts/roster.py`'s `format_for_prompt()` to group Tier 1
entries into per-jurisdiction subsections (Rollingwood first, adjacent
bodies tagged `(adjacent body)`). Verified on the 4/14 regen: Fletcher
renders as "City Administrator of Westlake Hills" in body text.
Closes Decision 4 in `design/tier1_expansion.md`.

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
