# Canonical-vs-alias mechanism investigation — 2026-04-23

Diagnostic artifact for a future prompt-tuning fix. Captures test
evidence for why the 2026-04-22 evening prompt-tuning pass (commit
`896bbef`) failed to prevent "Tom Farrell" from rendering four times
in the 4/14 regen body despite a maximally strong prompt directive.

No edits to `prompts/summary_prompt.md` are committed by this chunk —
the diagnostic prompt edit in Test B was uncommitted throughout and
reverted before the investigation closed.

## Bug restatement

After `896bbef` tightened `prompts/summary_prompt.md` line 81 to say
"the canonical form, not an alias form, is the only valid rendering
in the summary body" (and added "aliases are for transcript
recognition, not output use"), the 2026-04-22 evening regen of the
4/14 summary still rendered "Tom Farrell" four times in body text.
Tier 1 canonical is "Thom Farrell" with "Tom Farrell" as an alias;
canonical was not used. Captured in NOTES.md as "Prompt-tuning
followup" residual item 2, with the NOTES entry hypothesizing the
mechanism "isn't instruction-solvable at strong-directive level."

Entering hypotheses:

- **H1 (canonical buried).** Roster rendering puts aliases at least
  as prominently as canonical; the LLM picks the more salient
  alternative.
- **H2 (rendering semantic ambiguous).** The `(also: ...)`
  parenthetical in the roster rendering signals "equally valid
  spellings" rather than "recognize in transcript but don't output."
- **H3 (transcript fidelity wins).** The LLM prefers transcript
  spelling when the roster lists it as an alias, because the
  alias-in-roster lowers the cost of "use what the transcript says."

## Test A: roster rendering diagnostic

Verbatim output of `format_for_prompt()` around the Farrell entry:

```
- Sean Downing — Parks Member
- Susan Hinton — BOA Member
- Thom Farrell — CPSF Chair; CRCR Member (also: Tom Farrell)
- Tony Stein — P&Z Member
```

**Analysis.** Canonical "Thom Farrell" is in the visually-dominant
position — first token after the bullet. Role is secondary. Alias is
parenthetical, at the end. Positional hierarchy is correct.

**Refutes H1 (canonical buried).** Canonical is prominent, not
buried.

**Supports H2 (rendering semantic ambiguous).** The `(also: ...)`
framing is linguistically ambiguous. "Also" is a neutral connector;
it reads naturally as "also known as" — i.e., "either spelling is
acceptable." The prompt prose at line 81 spells out the
recognize-only constraint, but the roster rendering does not encode
it — the LLM has to bridge from prose to rendering for the
constraint to hold.

**Supports H3 (transcript fidelity wins).** If the LLM is weighing
"preserve transcript spelling" against "apply roster canonical," the
alias-in-roster lowers the cost of picking transcript fidelity
because the transcript spelling is attested in the prompt.

Thom vs. Tom is a single-character delta (one insertion of "h"). The
smallest possible drift surface. Canonical's prominent position may
not hold against a transcript that consistently pushes "Tom."

## Test B: concrete positive example

Added one sentence to line 81 of the prompt (uncommitted):

> Example: if the transcript says "Tom Farrell" and the roster has
> "Thom Farrell" as canonical with "Tom Farrell" in the aliases
> list, the summary body must say "Thom Farrell" — never "Tom
> Farrell" — even if the transcript consistently uses the alias
> spelling.

Regenerated the 4/14 summary against the 2026-04-14 cached
transcript.

**Count of Farrell renderings in body:**

| Rendering | Count | Locations |
|-----------|-------|-----------|
| "Thom Farrell" (canonical) | **5** | Meeting Details attendees, Public Comments header, a Public Comments body paragraph, Parks/Projects mention, Key Quotes attribution |
| "Tom Farrell" (alias)     | **0** | — |

**Baseline from 2026-04-22 evening regen (before Test B):** 4
alias-in-body occurrences. **Test B result:** 0. Drop of 4 → 0.

Also verified:

- **Transcript notes appendix contains no "Tom Farrell" reference.**
  The LLM didn't route the alias into the editorial section as a
  workaround.
- **Names-to-Verify appendix contains no Farrell entry.** No
  confusion about whether Farrell was resolved.

**Conclusion.** A single concrete positive example completely
eliminated the drift. The mechanism *is* addressable at the prompt
level — the preceding tuning pass's maximally-strong prose directive
wasn't enough on its own, but a concrete example was.

## Test B-prime — skipped

Would have tested whether changing `format_for_prompt()` to render
aliases with unambiguous recognize-only semantics (e.g.,
`(recognize in transcript, never use in output: Tom Farrell)`)
independently reduces the drift. Conditional on Test B failing; Test
B succeeded, so not run. Roster rendering change remains available
as a fallback lever if the concrete-example fix proves unstable
across meetings or speakers.

## Test C — skipped

Would have scoped a post-processing canonicalization pass —
`scripts/canonicalize_summary.py` reading the generated markdown,
applying known alias→canonical substitutions, writing corrected
output. Conditional on both A and B leaving significant alias-in-body
occurrences; Test B reduced them to zero, so not scoped. The
architectural lever remains available if future meetings surface
cases a concrete-example fix can't handle.

## Mechanism diagnosis

**Best-supported hypothesis: H2 + H3 combined, but resolvable at the
prompt level with instruction concreteness.**

The rendering *is* ambiguous (H2), and the LLM *does* appear to
weigh transcript fidelity when the alias is attested (H3). But
neither forces the drift against a sufficiently concrete prompt
instruction. The 2026-04-22 evening pass strengthened the prose
imperative ("only valid rendering," "not a variant to use in
output") without giving the LLM a concrete worked example. Test B's
single sentence — a specific transcript-to-canonical mapping showing
the wrong output alongside the right one — was enough to override
whatever pull the rendering and transcript were exerting.

**The diagnosis refutes the pessimistic NOTES.md framing that
canonical-vs-alias "isn't instruction-solvable at strong-directive
level."** It is instruction-solvable; the strong-directive level
just needs to include worked examples, not just prose. Prose
directives alone leave the LLM reasoning about the rule; a worked
example shows the rule in action, which is a different cognitive
demand.

This pattern is consistent with the 2026-04-22 evening timestamp-
citation fix, which also needed a worked negative example ("an
earlier public-comment speaker's turn-start timestamp is NOT a valid
citation...") to bind the general rule. Prose-plus-example appears
to be the reliable instruction shape for this prompt; prose-only is
not.

## Recommended fix shape for a future chunk

**Primary.** Add a concrete transcript-to-canonical example to line
81 of `prompts/summary_prompt.md`. Keep the existing prose directive
(it carries the general rule). Add one sentence that shows a
specific input/output mapping — the Test B experiment's shape is a
good candidate. Commit. Run a two-regen stability check on 4/14 to
confirm the drift stays at 0 across non-deterministic runs. If
stable, close NOTES.md "Prompt-tuning followup" residual item 2
with a reference to that fix commit and to this investigation.

**Related residuals to investigate during the same fix chunk (don't
bundle unless the evidence justifies it):**

- **Residual item 3 (Fletcher-in-Names-to-Verify drift).** NOTES.md
  hypothesizes this is the same underlying mechanism as item 2. If
  item 2's fix is a concrete example, test whether adding a
  corresponding concrete example to lines 55–60 (the Names-to-Verify
  spec) similarly eliminates the Fletcher drift. If yes, bundle.
  If not, residual 3 is a separate mechanism needing its own
  diagnosis.
- **Residual item 1 (bare-factual-bullet citations).** Probably
  unrelated to this investigation's mechanism — that's a
  citation-anchoring problem, not a canonical-vs-alias rendering
  problem. Fix separately.

**Tertiary lever (available if primary proves unstable).** Change
the roster rendering in `format_for_prompt()` to encode
recognize-only semantics on aliases — e.g., `(recognize in
transcript: Tom Farrell)` or `(variant spellings to recognize, not
output: Tom Farrell)`. Scoped but not executed here; invoke only if
the example-based fix fails a stability check.

**Quaternary lever (available if rendering plus examples still
leak).** Post-processing canonicalization pass —
`scripts/canonicalize_summary.py` reading the generated markdown,
applying known alias→canonical substitutions, writing corrected
output. Would need careful quote-preservation logic (if a transcript
genuinely quotes someone saying "Tom Farrell" in direct speech, the
pass must preserve the quoted spelling). Architectural complexity
reserved for the case where prompt-level fixes can't hold.

## Followup for NOTES.md

The "Prompt-tuning followup" MEDIUM entry in NOTES.md currently
frames canonical-vs-alias as "not instruction-solvable at
strong-directive level" and hypothesizes a transcript-vs-roster
fidelity conflict as the mechanism. This investigation partially
refutes that framing — the mechanism *is* instruction-solvable, just
not at the prose-only strong-directive level. When the fix ships,
update the NOTES entry to reflect the corrected diagnosis and link
back to this investigation file.
