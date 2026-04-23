# Methodology

I am Jeff Marx. I operate the Rollingwood Report, an automated pipeline
that produces structured email briefings after each meeting of
Rollingwood, Texas municipal bodies.

This document explains what the Report is, how the pipeline works, what
accountability structures back it, where my civic participation creates
potential conflicts, and what known limitations readers should weigh.

## What the Report is

The Rollingwood Report is automated coverage of municipal meetings.
After a meeting is posted to the City of Rollingwood's YouTube channel,
the pipeline transcribes it, summarizes it in a structured format, and
emails the result. Each issue is a structured summary with YouTube-
timestamped citations back to the source recording for every
attributed claim. The specific structure — what sections appear, what
they contain, how they're ordered — is defined by the public prompt
at `prompts/summary_prompt.md` and iterates based on operator tuning
and reader feedback. The prompt is versioned in the repo; any issue's
structure is exactly what that version of the prompt produced.

The Report does not editorialize, endorse, predict political outcomes,
or identify "winners" and "losers." It describes what was said and
decided. This is a deliberate constraint encoded in the summarization
prompt.

## How the pipeline works

The pipeline runs daily in GitHub Actions. Each stage is automated:

1. **Check for new meetings.** Watch the Rollingwood YouTube channel for
   newly posted videos matching municipal-meeting keywords.
2. **Download audio.** Use `yt-dlp` to pull an MP3 of any new meeting.
3. **Transcribe.** AssemblyAI's `universal-3-pro` model produces a
   speaker-diarized transcript.
4. **Summarize.** Claude Opus 4.7 generates the structured summary using
   a locked prompt at `prompts/summary_prompt.md` and a roster of
   canonical Rollingwood names.
5. **Deliver.** The summary is archived to Google Drive (markdown +
   PDF), and an email is sent to readers.

There is no human editorial review between transcription and delivery.
I operate the pipeline — I decide which meetings count as in-scope,
when to run it manually for a missed meeting, and what gets changed in
the prompt — but no issue is reviewed by a human before it reaches a
reader's inbox.

Pipeline source is at <https://github.com/jeffm031/rollingwood-report>.
The prompt, roster, and configuration are public.

## Accountability model

I use four structures to reduce the error rate and to make errors
catchable after the fact. Two are operational today; two are commitments
for the Report's first beta edition.

### Operational today

**The tuned prompt.** `prompts/summary_prompt.md` encodes the register
(neutral newsletter voice, third person), the required structure (nine
numbered sections plus an Appendix), and specific rules about citation
accuracy, canonical-name rendering, and what belongs in the "Names to
verify" appendix. The prompt is iteratively tuned against known failure
modes. Prompt tuning is ongoing work; open failure modes are tracked
publicly in `NOTES.md` under "Prompt-tuning followup" in this repo.

**The four-tier name roster.** Speech-to-text misrenders names,
especially for speakers who don't appear often. A roster of canonical
names reduces that. The roster has four tiers: current officials
scraped from the City directory (Tier 1, extended to adjacent bodies
like West Lake Hills via TML city directories), historical public
speakers from the last 24 months of meeting packets (Tier 2), property
owners in Rollingwood from Travis County appraisal data (Tier 3,
likely residents), and names learned from past summaries via reader
correction (Tier 4). The roster is cross-referenced by the pipeline
during summarization; transcript misspellings are resolved to canonical
spellings where a match is found. The roster catches many phonetic
errors but not all — see "Known limitations" below.

### Committed for the Report's first beta edition

**A reader-driven correction pipeline.** Every issue of the Report will
carry a mechanism for readers to submit corrections — an email reply
address, at minimum — and corrections that land will be published in a
subsequent issue. Confirmed names from the "Names to verify" appendix
get promoted into the roster (Tier 4) so the same error doesn't recur.
This pipeline is **not yet operational.** It is a commitment for the
first beta edition.

**Quarterly full-recording audit.** Each quarter I will select one
published issue, watch the source meeting recording end to end, and
publish an audit comparing the recording's content to the issue's
coverage. Discrepancies — factual errors, attribution errors, timestamp
errors, editorial drift — will be documented and published with any
follow-up corrections. Sample size is one issue per quarter; this is
not comprehensive coverage. It is a sampled spot-check, and I'll say so
in each audit. **Not yet operational.** It is a commitment for the first
beta edition.

## Operator commitments

A few commitments I'm making and intend to keep:

- **Correction priority.** When I become aware of an error — from a
  reader, from the quarterly audit, or from my own re-reading — I'll
  publish a correction promptly. Corrections are surfaced in the next
  issue and recorded in the repo.
- **Public tooling.** The pipeline source, prompt, roster, and
  configuration stay in a public repository. The mechanics are open
  for review.
- **Constrained scope.** The Report covers Rollingwood municipal
  meetings. It doesn't speculate about political races, campaign
  dynamics, or regional politics beyond what appeared on the agenda.
- **Disclosure, not recusal.** See the next section.

## Conflicts of interest and disclosures

**Stance.** I participate in Rollingwood civic life. I've applied to
serve on city bodies, and I may in the future hold appointed positions.
I don't believe that participation disqualifies me from operating
civic-journalism tooling about the same community. The alternative —
withdrawing from civic participation in order to report on it — would
hollow out both. I choose transparency instead: the Report discloses my
current applications, appointments, and standing affiliations that
touch municipal matters, and readers can weigh that disclosure when
reading any given issue.

**Current applications and appointments** to Rollingwood bodies are
tracked in `config/disclosures.yml` in this repo. That file is the
single source of truth for dynamic civic-status disclosures; it updates
whenever my status changes, and it carries a `last_reviewed` date that
I refresh on every touch and on a quarterly audit. The file is rendered
into every issue of the Report, so the disclosure is not buried —
readers see it in the same email as the meeting summary.

**Standing disclosures** are stable affiliations that don't change with
my civic status. The following paragraph is rendered into each issue of
the Report alongside the dynamic list from `config/disclosures.yml`:

<!-- STANDING_DISCLOSURE_START -->
I lead RW AI Lab, a local learning community focused on practical
applications of large language models. The Rollingwood Report is itself
produced by a large-language-model pipeline. That creates a recursive
situation: when AI policy or municipal technology comes before a
Rollingwood body, this AI-produced report is covering AI-related civic
matters. Readers should know that and weigh it when reading AI-related
items.
<!-- STANDING_DISCLOSURE_END -->

<!-- Implementation note for render_disclosures() in scripts/run.py
     (or wherever it lives): extract the paragraph content between
     STANDING_DISCLOSURE_START and STANDING_DISCLOSURE_END. Strip the
     HTML comment markers themselves from the extracted text before
     rendering — otherwise they appear as literal <!-- ... --> strings
     in generated issues. Fail-loud if the anchor pair isn't found;
     see config/disclosures.yml for the broader fail-loud contract. -->

## Known limitations

Some specific things the Report does poorly or not at all. I'd rather
name these than gesture vaguely at "AI can make mistakes":

- **Speech-to-text produces phonetic name errors.** AssemblyAI's model
  misrenders names of speakers who don't appear in the roster
  (first-time public commenters) or whose names have unusual
  spellings. The roster resolves many — but not all — of these at
  summarization time. Ambiguous cases are flagged in each issue's
  "Names to verify" appendix.

- **The timestamp-citation rule has known open failure modes.** The
  Report cites YouTube timestamps for every attributed claim, which is
  load-bearing for readers who want to verify in the recording. The
  citation rule doesn't always bind correctly. Current-state specifics
  and in-progress diagnostic work live in `NOTES.md` under
  "Prompt-tuning followup."

- **No human pre-publication review.** Any error — factual,
  attributional, editorial drift — reaches readers before the
  correction pipeline catches it. The correction pipeline is a
  post-hoc mechanism, not a pre-publication safeguard.

- **The quarterly audit is a sample, not comprehensive coverage.** One
  issue per quarter will be compared end to end against the source
  recording. Most issues won't be audited at that depth. If you notice
  something that looks wrong in any issue, please submit a correction
  — don't wait for the next audit.

- **The meeting recording is the authoritative source.** The Report is
  a derivative product, as are the City's official minutes. If an
  issue's coverage conflicts with what the recording shows, the
  recording is what happened. The Report is a convenience for readers
  who don't have two hours per meeting to watch.

## How to contact and submit corrections

Reply to any issue of the Report to submit a correction or question.
Until the reader-driven correction pipeline is operational, I monitor
replies manually. For corrections that identify a name that should be
in the roster, I'll confirm the correct spelling and add it to Tier 4
(learned names) so the same error doesn't recur.

For non-urgent feedback or questions unrelated to a specific issue:
<rollingwoodreport@gmail.com>.
