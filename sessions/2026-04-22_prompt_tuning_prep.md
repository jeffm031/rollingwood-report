# Prompt-tuning prep — `prompts/summary_prompt.md`

Analysis-only prep for the prompt-tuning session that tomorrow will
open and execute from. Zero edits to `summary_prompt.md` in this
chunk. Paired with `sessions/2026-04-22_timestamp_audit.md` (the
requirements doc with ground-truthed examples).

## 1. Current prompt structure

`prompts/summary_prompt.md` is 88 lines, one document, four parts:

- **Lines 1–4. Voice and register.** Third-person, neutral, civic-
  newsletter register.
- **Lines 5–62. Output format.** Nine numbered sections (Executive
  Summary → Public Comments → Key Quotes) plus a two-subheading
  Appendix (Transcript notes, Names to verify). Each section has
  its own spec of what it contains.
- **Lines 64–75. Rules.** Ten bullet-style rules. Neutrality,
  balanced attribution, accuracy-over-completeness, speaker labels,
  no preamble, **and the single timestamp-citation instruction at
  line 75.**
- **Lines 77–87. Roster cross-reference rules.** How to use the
  four-tier roster appended at runtime; canonical-spelling authority
  (line 81); non-resident signal handling (line 87); how to handle
  unresolved names (line 86 → Appendix "Names to verify").

**The entire timestamp-citation policy lives in one paragraph at
line 75.** Every citation-related decision the LLM makes routes
through that one block.

## 2. Citation instruction gap analysis

The current instruction, verbatim (line 75):

> **Timestamp citation via YouTube links.** When the user message
> includes a `VIDEO ID:` field, every attribution, decision, vote,
> quote, and discussion item must cite a timestamped link back to
> the source so the reader can verify. Use the format
> `[(H:MM:SS)](https://www.youtube.com/watch?v=VIDEO_ID&t=NNNs)`
> where `VIDEO_ID` is the value of the `VIDEO ID:` field and `NNN`
> is the integer-second start time of the speaker turn that supports
> the claim, computed from the `(H:MM:SS)` marker at the start of
> each transcript line. Link to the speaker turn itself, not a
> nearby moment. If multiple turns support a claim, link the
> earliest. If no `VIDEO ID:` is provided, omit the citation rather
> than fabricate a URL.

**Diagnosis.** This instruction *does* address citation location
("Link to the speaker turn itself, not a nearby moment"), so the
observed bug is not instruction-absence — it's instruction-
underspecification interacting with two specific weaknesses:

1. **Turn granularity mismatched with the transcript shape.** The
   cached transcript is produced by AssemblyAI with
   `speaker_labels=True`, which chunks to one line per utterance
   (speaker turn). Long turns stay on one line with one timestamp
   — Bill Bunch's full 5-minute public comment sits on a single
   line at **(1:25:48)**. So "the speaker turn that supports the
   claim" gives the LLM only a turn-opener timestamp even when the
   specific claim was made three minutes into that turn. This is
   the ceiling of what the transcript permits; the fix has to
   accept per-turn precision but enforce *the right turn*.

2. **"If multiple turns support a claim, link the earliest" is
   bug-prone.** When the LLM is reasoning about a cluster of
   related claims (e.g., all the bullets in "Upcoming & How to
   Participate" that trace back to Bunch's comment), it can
   plausibly interpret "multiple turns support → earliest" as
   licensing it to pick a single cluster anchor. Observed behavior
   suggests the anchor it picks isn't even the earliest of the
   *attributed speaker's* turns — it picks the earliest turn in
   the **section** (e.g., the public-comment segment's opening
   at 1:20:22, which is Farrell's brief "I don't know. Listen, I
   recognize that."). Section-anchor behavior that the instruction
   didn't intend but didn't forbid either.

**Ground-truth from sampling the raw transcript:**

- Bunch's attributed claims (postpone vote, EIS call, town hall
  announcement, Paige Ellis resolution) are all in his single
  turn at **(1:25:48)**. The summary cited **(1:20:22)** — a
  different speaker entirely (Farrell).
- Example 4's "no formal action this evening" claim was made by
  Mayor Massingill at **(0:55:20)**. The summary cited **(0:55:14)**
  — six seconds off, adjacent turn, but attributed to Vaughan
  ("thank you for hosting. It's always fun."). Not a section anchor
  — a speaker-attribution error on adjacent turns.

So Examples 1–3 are section-anchor errors; Example 4 is a
nearest-adjacent-turn speaker-attribution error. Two distinct
failure modes, both fixable by the same underlying principle:
**every citation must come from a turn BY the speaker making the
attributed claim.**

## 3. Proposed fix shape, mapped to specific locations

**Location: line 75 (the citation paragraph). Substitutive.**

The existing paragraph needs to be replaced, not merely augmented.
The current text has instructions that actively mislead ("link the
earliest" as a multi-turn rule) and needs to be rewritten around a
stricter principle.

Fix-shape requirements for tomorrow's replacement paragraph (not
drafting the text):

a. **Preserve.** Every attribution / decision / vote / quote /
   discussion item must carry a citation. Format unchanged. Speaker-
   turn granularity unchanged (can't do better; transcript is
   turn-level). "Omit citation if no VIDEO ID" unchanged.

b. **Strengthen: speaker accuracy.** The cited turn's speaker must
   be the speaker to whom the summary attributes the claim. A
   citation pointing to Speaker X's turn for a claim attributed to
   Speaker Y is forbidden even if the timestamps are close.

c. **Strengthen: per-claim citation.** Each distinct claim gets its
   own citation, evaluated on its own merits. Section-anchors are
   forbidden for factual claims. "Multiple turns support a claim"
   is narrow to literal cases where the same speaker made the same
   claim across separate turns; it does not apply across speakers
   or across the boundary of a speaker's long continuous turn.

d. **Remove or rework: "If multiple turns support, link the
   earliest."** This sentence is load-bearing in the wrong
   direction. Tomorrow's draft replaces it with something that
   clarifies the single-speaker-only reading.

e. **Add: explicit negative example.** A one-sentence example of
   what's wrong is cheap and high-signal. Shape: "Do NOT cite an
   earlier public-comment speaker's turn as the anchor for a later
   speaker's claims."

## 4. Bundled observations from NOTES.md

The HIGH-priority NOTES.md entry bundles two secondary observations
alongside the timestamp-citation primary. Both are independent from
the primary fix; neither conflicts with it; both belong in tomorrow's
pass because they're already instruction-present but under-enforced.

**Names-to-Verify semantic drift.** Fix location: **lines 55–60**
(the Appendix "Names to verify" spec). Current instruction says
"Every person named in sections 1–9 whose name did NOT resolve to
an entry in the Rollingwood roster." The drift: the LLM lists
roster-matched names too, with annotations like "(matches Tier 1
Westlake Hills roster)." Fix shape: tighten "did NOT resolve" to a
hard exclusion of anything that resolved, even if the match felt
approximate — the roster is authoritative for "resolved" status,
not the LLM's confidence. Substitutive, not additive.

**Canonical-vs-alias soft handling.** Fix location: **line 81**
(roster authority rule). Current instruction says "try to resolve"
and "use the canonical spelling." The drift: the LLM sometimes uses
alias spellings in body text (e.g., "Tom Farrell" when canonical is
"Thom Farrell"). Fix shape: replace "try to resolve" with an
unconditional directive; add an explicit forbidden pattern ("an
alias spelling never appears in the summary body"). Additive on
the forbidden-pattern line; substitutive on the "try" softening.

**Interaction check.** None of the three fixes share a prompt
location. Citation fix lives at line 75, Names-to-Verify at 55–60,
canonical-vs-alias at 81. Changes to any one don't touch the others.
No conflict expected.

## 5. Test plan

**Regeneration workflow.** `scripts/test_local.py` reuses the cached
transcript next to the MP3 and only re-runs the Claude summarize
step on a cache hit. Each iteration is ~2–3 min of Claude API time.
Command for each iteration:

```
.venv/bin/python scripts/test_local.py \
  "/Users/jeffmarx/Special City Council Meeting 4-14-2026 [ecUUdeLa5_A].mp3"
```

**Primary test meeting: 4/14 Special City Council.** Only meeting
with a cached transcript. Re-transcribing a second meeting would
cost AssemblyAI credits; not worth it for this pass. Overfit risk
noted in § 6.

**The four audited citations and their correct targets:**

| # | Claim                                       | Summary cited | Correct target | Reason                                   |
|---|---------------------------------------------|---------------|----------------|------------------------------------------|
| 1 | Bunch urged postponement (Exec Summary)     | 1:20:22       | 1:25:48        | Bunch's turn start (line 227 of transcript) |
| 2 | Paige Ellis resolution (Upcoming)           | 1:20:22       | 1:25:48        | Inside Bunch's single turn               |
| 3 | April 22 town hall (Upcoming)               | 1:20:22       | 1:25:48        | Inside Bunch's single turn               |
| 4 | "No formal action this evening" (Exec Summary) | 0:55:14    | 0:55:20        | Massingill, not Vaughan (0:55:14)        |

**"Fixed" criterion.** All four cite the correct speaker's turn.
Acceptable for turn-granularity: if a specific moment within a turn
isn't available from the transcript, the turn-opener for the
attributed speaker is the correct answer (Bunch's 1:25:48 for all
of his claims is correct even though individual claims come later
in the turn).

**"Regressed" criterion — any of these is a blocker:**

- Date-error self-correction lost (e.g., August-14/April-14
  reconciliation no longer appears in Transcript notes)
- Roster canonicalization weakened (e.g., Vaughn not canonicalized
  to Vaughan)
- Transcript-vs-extrapolation honesty lost (Transcript notes
  disappears or becomes generic)
- Any previously-resolved name (Vaughan, Fletcher, Massingill, etc.)
  flipped to unresolved

**"Fixed but new failure mode" criterion — watch for:**

- Citations going missing (LLM becomes over-cautious)
- Citations marked `[uncertain]` or wrapped in hedges
- Summary structure disrupted (section headers lost, bullet
  reorganization)
- Speaker attribution becoming excessively granular to the point of
  reader noise ("per Speaker A at 1:20:22, per Speaker A at 1:20:25,
  per Speaker A at 1:20:28")

**Non-determinism check.** LLM output varies run-to-run on identical
inputs. After the fix lands, do two regenerations and confirm both
pass the four-citation check. If one passes and one fails, the fix
isn't stable and needs iteration.

## 6. Known unknowns and risks

- **LLM non-determinism.** Same prompt → different outputs. See
  two-run check in § 5. If non-determinism swamps the fix, the
  remedy is usually adding a concrete example (positive or negative)
  that's hard for the model to ignore — but don't lead with that;
  try the principle-based fix first.
- **Prompt interaction effects.** Changing line 75 theoretically
  shouldn't affect lines 55–60 or 81. But roster-resolution and
  citation both feed the Appendix. If the citation fix changes how
  the LLM identifies "the attributed speaker," that could cascade
  into Names-to-Verify. Watch for cross-section regressions.
- **Overfit to the 4/14 meeting.** The audit and test plan both
  lean on one meeting. Meetings with different speaker density,
  different public-comment length, or different Council-vs-Public
  ratios might reveal failure modes not visible at 4/14. Cheapest
  mitigation: review the next production-pipeline-generated summary
  with the same four-citation-style check as a follow-up, not as
  part of tomorrow.
- **Transcript chunking dependency.** The fix assumes AssemblyAI
  continues to produce turn-level lines. If the upstream chunking
  changes (e.g., a model update produces sentence-level chunks),
  the "speaker turn that supports the claim" instruction becomes
  friendlier and the citation fix may over-constrain. Not an
  immediate risk; note for future prompt-tuning if transcript
  format shifts.
- **Model-update drift.** If the `CLAUDE_MODEL` constant in
  `scripts/test_local.py` changes between today's test and
  tomorrow's tuning, behavior shifts for reasons unrelated to the
  prompt. Pin the model for the tuning pass; flag any accidental
  change.

## 7. Session scope

**Primary (load-bearing):** citation strategy fix at line 75.
Claim-anchor semantics, speaker-accuracy enforcement, negative
example. Evidence base: § 3 of this doc plus
`sessions/2026-04-22_timestamp_audit.md`.

**Secondary (should land in the same session):**

- Names-to-Verify semantic clarification at lines 55–60
- Canonical-vs-alias tightening at line 81

**Not in scope tomorrow:**

- Any other NOTES.md item (OAuth consent-screen move, Tier 2
  per-entry packet URLs, Tier 4 certainty revisit, summary_prompt
  stale "Vaughn" example on line 23, etc.)
- Regenerating a second meeting to cross-check
- Fixing the deployed 4/14 `.summary.md` (no point; any beta-bound
  summary regenerates from the updated prompt)
- Drafting prompt text in this prep (already discipline)
- Any work that would require more than ~5 Claude-API iterations
  on the 4/14 transcript

**Definition of done.** Line 75 rewritten; lines 55–60 and 81
tightened; two consecutive regenerations of the 4/14 summary pass
all four audit-item citations and don't regress any of the
preserve-this items. Audit items verified against Jeff's ground-
truth targets (§ 5 table). Commit and push in one logical unit.
