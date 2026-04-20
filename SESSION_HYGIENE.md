# Session Hygiene — Rollingwood Report

Standing collaboration norms for Claude Code sessions. Kept separate from
`NOTES.md` (work backlog) because these are procedural — they apply to
every session regardless of what's in flight.

## Operating mode

**Default: proceed.** This project prioritizes time efficiency over
perfection on local work. Nothing ships publicly without an explicit
push, so the asymmetry of "minute-per-approval × many approvals" versus
"occasional reversible local error" favors speed.

### Execute without asking

- Running scripts, tests, Python invocations.
- Reading / grep / find / diff inside the project directory.
- Creating or modifying files inside `scripts/`, `config/`, `prompts/`,
  `design/`, `tests/`, and `NOTES.md`.
- Copying files to `/tmp` for scratch or before/after comparisons.
- `git add` and `git commit`, provided the files being added are
  (a) inside this project directory and (b) not in `.gitignore`. Draft
  commit messages inline as part of the work; no `Co-Authored-By: Claude`
  trailer (per `CLAUDE.md` — Jeff is the sole named operator).
- Approving prefilter prompts inline for any of the above.

### Gates (always stop and ask)

1. **`git push`.** The boundary between local and public. Always show
   the commit SHA, the commit message, and the remote before asking.
   No always-allow on this one, ever.
2. **Modifications to `methodology.md`, `editorial-policy.md`, or
   `README.md`.** Public accountability documents. Draft diffs inline,
   show, wait for approval before writing.
3. **Email, subscriber list, or the subscribers repo.** Any action that
   sends mail, modifies subscribers, or touches the subscribers repo.

### Strategic questions bubble up

If the next action requires a project-direction call — "should we do A
or B," "does this invalidate the phase plan," "is this still the right
reinvention" — stop, frame the decision in one paragraph, ask. Don't
guess.

## Session summaries at natural stopping points

At every natural stopping point (end of a scraper, end of a tier, end
of a fix), post a 2–3 sentence "what shipped, any surprises, recommended
next." Don't wait to be asked.

## Background

This regime replaced a tighter gate discipline tried earlier on
2026-04-20, under which every file write and local commit was
show-first. That regime produced four retroactive-approval cycles in a
single session (file write, Python heredoc re-run, `cp` snapshot,
commit) where the approval message arrived after the mechanical action
had already completed — because the actions were reversible and the
prefilter prompts were out-of-band. All four were flagged in real
time; the push gate held. The takeaway: on a project where nothing
ships publicly without an explicit push, tight gates on mechanical
work cost more than they save. Push stays tight; everything local
loosens.
