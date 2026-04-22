# Timestamp-citation audit — 2026-04-14 summary

Evidence base for a future prompt-tuning session on
`prompts/summary_prompt.md`. This audit documents a
citation-misalignment bug discovered when the first real-send preview
email (Chunk C, 2026-04-22) landed in Jeff's inbox and he cross-
checked the cited timestamps against the raw transcript.

Source summary reviewed: the 2026-04-14 Special City Council summary at
`~/Special City Council Meeting 4-14-2026 [ecUUdeLa5_A].mp3.summary.md`.

## 1. Bug discovered

The email rendering revealed that YouTube timestamp citations in the
summary don't consistently point at the moment each cited claim was
made. The pattern: real timestamps from the transcript are being
reused as "section anchors" across multiple distinct claims — some
of which were made by different speakers at different moments in the
meeting. The citations are not fabricated; they are misapplied. A
reader clicking a citation link lands somewhere real in the video,
but often minutes away from the claim they were trying to verify.

## 2. Concrete examples with ground truth

### Example 1 — Bill Bunch paragraph citing 1:20:22

**Claimed:** "Bill Bunch of the Save Our Springs Alliance urged the
Council to postpone any vote, to support Travis County's and the City
of Austin's calls for a full EIS, and announced a public town hall on
the project scheduled for April 22 at Austin High School
[(1:20:22)]."

**Ground truth** (verified against raw transcript): Bunch begins
speaking at approximately **1:25:20** ("My name is Bill Bunch and I'm
with the Save Our Springs Alliance"). The "please postpone any vote"
statement comes later in his comment, around **1:26–1:28**. The
timestamp 1:20:22 falls in the middle of Thom Farrell's public
comment, not Bunch's.

**Correct citation:** approximately 1:26–1:28 for "postpone any vote,"
not 1:20:22.

**Why the LLM got it wrong:** 1:20:22 appears to be acting as a
cluster anchor for "the public-comments section as a whole." Bunch's
content is being anchored to a moment that's inside the prior
speaker's block.

### Example 2 — Paige Ellis resolution citing 1:20:22

**Claimed:** "Austin City Council: Council Member Paige Ellis is
expected to add a resolution as an addendum for consideration
Thursday, April 23, which would reaffirm a call for a full EIS
[(1:20:22)]."

**Ground truth:** This reference comes from Bill Bunch's comment,
where he mentions Paige Ellis in the context of Austin City Council
action. The specific moment is somewhere in the ~1:26–1:35 range
(within Bunch's comment block), not 1:20:22.

**Correct citation:** Within Bunch's comment block, at the specific
moment he introduces the Ellis resolution.

**Why the LLM got it wrong:** same pattern — using the public-
comments-cluster anchor instead of the specific claim moment.

### Example 3 — Town hall announcement citing 1:20:22

**Claimed:** "Community town hall on MOPAC South: Wednesday, April 22
(Earth Day), 6:00–8:00 p.m., Austin High School cafeteria, announced
by Save Our Springs Alliance [(1:20:22)]."

**Ground truth:** Bunch announces the town hall; this is inside his
comment block, ~1:25–1:35.

**Correct citation:** the specific moment in Bunch's comment where he
invites attendees to the town hall.

**Why the LLM got it wrong:** same failure mode.

### Example 4 — "No formal action was taken" citing 0:55:14

**Claimed:** "No formal action was taken on a Rollingwood position or
comment letter; the matter was reposted for further Council discussion
the following evening [(0:55:14)]."

**Ground truth:** *verify against transcript.* Possibly accurate for
when the reposting decision was discussed; possibly a statement made
at a different point. Included as a "check this" item because the
other three examples establish that 1:20:22-style reuse is happening;
0:55:14 could be a similarly-reused anchor for the "outcome" framing
of the discussion, or it could be a genuine single-moment citation.
Worth one eyeball-check when the prompt-tuning session starts.

## 3. Failure-mode diagnosis

The LLM appears to be applying a **section-anchor citation strategy**
rather than a **claim-anchor citation strategy**. When a block of
summary content is "about" a speaker or a topic, it inherits that
section's anchor timestamp — often the moment the broader topic was
introduced, or the moment the primary speaker in the block began
speaking. That anchor then gets applied across multiple distinct
claims within the block, including claims made by *other* speakers
and at *different* moments.

The outputs are real timestamps (the LLM isn't hallucinating) but
misaligned to their specific claims. This is a consistent pattern,
not random drift — the same anchor (1:20:22) recurs across at least
three distinct claims in the Upcoming & How to Participate bullets,
none of which were made at 1:20:22.

## 4. What the fix must preserve

The current prompt is doing several things well that shouldn't regress
in the tuning pass:

- **Date-error self-correction.** The 4/14 summary correctly reconciles
  a transcript date error (August 14 in transcript vs. April 14 actual)
  in its Transcript Notes appendix.
- **Roster-based name canonicalization.** Vaughan / Massingill /
  Pattillo all render canonically, with the roster resolution
  documented in Transcript Notes.
- **Transcript-vs-extrapolation distinction.** The Transcript Notes
  appendix distinguishes clearly between what's verbatim in the
  transcript vs. what the model extrapolated. That honesty is
  load-bearing for the accountability model.

These are independently valuable and shouldn't be disturbed.

## 5. Fix shape (not fix text)

The structural instruction the prompt needs:

> Cite the specific moment each claim was made, not the moment the
> broader topic was introduced. Every direct quote gets the quote's
> own timestamp. Every attributed claim gets the attributing speaker's
> timestamp for that specific sentence, not for their comment's
> opening. Cluster anchors ("this whole block is from speaker X at
> time Y") are forbidden for factual claims — each claim stands on
> its own citation.

Not drafting the actual prompt text here — that's tomorrow's session.
This audit is the requirements doc for that work.

## 6. Severity and priority

**Beta-launch blocker.** The Rollingwood Report's accountability
model depends on timestamps being verifiable. A reader who clicks a
link and lands at the wrong moment in the video loses trust
immediately and irrecoverably for that issue. The "hyperlinked
verifiable citations" value proposition collapses if the citations
don't consistently resolve to their claims.

The **"Prompt-tuning pass overdue for summary_prompt.md"** entry in
NOTES.md — previously medium priority — is upgraded to **high
priority, beta-launch blocker** by this audit. See that entry for
the broader tuning scope (which also covers the Names-to-Verify
semantic drift and canonical-vs-alias handling observed earlier in
the 2026-04-21 session).

## 7. Out of scope for this audit

- **Names-to-Verify semantic drift.** Separate issue already logged in
  NOTES.md. Both are prompt-tuning work, but they're independent
  failure modes that should be reasoned about separately.
- **Specific prompt text.** The tuning session drafts that from the
  fix-shape requirement here. Don't conflate evidence with
  intervention.
- **Fixing the existing 4/14 summary on disk.** No point — any
  published beta issue will regenerate from a new prompt against
  the same cached transcript.
- **Fetching the raw transcript into the repo** for inspection
  tooling. Out of scope today; may become useful if we want the
  prompt-tuning session's ground-truth verification to be
  scriptable rather than manual.
