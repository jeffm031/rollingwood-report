# Name triage — unresolved names from 2026-04-14 re-run

Context: after the Tier 1 adjacent-body expansion added West Lake Hills (TML),
the 2026-04-14 Special City Council summary's Names-to-Verify appendix still
listed 8 unresolved names. Triaging each by which tier gap would resolve it.

## Method

- Local `data/rollingwood_parcels.csv` grep for all 8 surnames (TCAD parcel
  ownership → Tier 3 check). Plus variants: "Cockelman" for Cockleman,
  "Erwin" for Irwin.
- `prompts/roster/tier2_historical.yml` grep for the same surnames
  (historical-speaker spot-check).
- Context clues from the 2026-04-14 summary body (each name has an explicit
  role attribution nearby).

## Per-name classification

1. **Ann Howard** — Tier 1 gap (Travis County scraper). Summary body
   identifies her as a current Travis County Commissioner; parcel CSV
   shows only "Jack D Howard" and a "Washburn John Howard Jr" (different
   people), not Ann. Tier 2 has a "Jay Howard" entry (also unrelated).

2. **James Bass** — Tier 1 gap (CTRMA scraper). Summary body identifies
   him as Executive Director of CTRMA. No Bass matches in parcels or Tier 2.

3. **Trammell Cooper** — Out-of-town / unknown. Summary body: advocacy chair
   of the Westlake Chamber of Commerce. Parcel matches for "Cooper" are
   subdivision names ("Nina Cooper Subd"), not a person. Chamber of Commerce
   is not on the Tier 1 source list and isn't on the planned pending list.

4. **Kara Cockleman** — Out-of-town / unknown. Summary body explicitly
   identifies her as a West Lake Hills resident, not a Rollingwood resident.
   No parcel match. Chamber/advocacy context; not an official.

5. **Paige Ellis** — Tier 1 gap (Austin D8 scraper). Summary body: Austin
   City Council member sponsoring a resolution. Parcel matches on "Ellis"
   are unrelated individuals (Philip Ellis / Brian Ellis Winstanley); no
   Paige Ellis as a Rollingwood parcel owner.

6. **Norm Marshall** — Out-of-town / unknown. External transportation
   consultant retained by Save Our Springs Alliance. No parcel match
   (the only "Marshall" hit is a subdivision name). Not in any planned source.

7. **Gerald Doherty** — Out-of-town / unknown. Summary body: *former* Travis
   County commissioner who previously supported the project. A current-
   officials Travis County scraper would not resolve a former commissioner;
   Tier 2 (historical Rollingwood speakers) also won't — he's historical
   to Travis County, not to Rollingwood.

8. **Gay Irwin** — Tier 3 gap (TCAD ingester fix). Parcels CSV line 494:
   `ERWIN ALAN RUSSELL & / ALAN & GAY ERWIN TRUST` at 3 Jeffery Cv. "Gay
   Irwin" is the transcript's rendering of "Gay Erwin." Maps exactly to
   one of the known ingester bugs listed in NOTES.md (entity-only trust
   rows not extracted as persons; trust-owner string concatenated rather
   than parsed).

## Tally

| Bucket                  | Count | Names                                              |
|-------------------------|-------|----------------------------------------------------|
| Tier 1 gap (adjacent)   | 3     | Ann Howard (Travis County), James Bass (CTRMA), Paige Ellis (Austin D8) |
| Tier 2 gap (historical) | 0     | —                                                  |
| Tier 3 gap (resident)   | 1     | Gay Irwin → Gay Erwin                              |
| Out-of-town / unknown   | 4     | Trammell Cooper, Kara Cockleman, Norm Marshall, Gerald Doherty |

## Decision framing

The tally doesn't produce a single clear "most names resolved" winner for
the next move — every candidate fix resolves **exactly one** name from this
batch:

- Thom Farrell Tier 2 fix: 0 of 8 (doesn't touch this batch; fixes a different named bug)
- TCAD ingester fix: 1 of 8 (Gay Irwin)
- Travis County scraper: 1 of 8 (Ann Howard)
- CTRMA scraper: 1 of 8 (James Bass)
- Austin D8 scraper: 1 of 8 (Paige Ellis)

**Implication.** The 4/14 meeting is unusually weighted toward MOPAC South
regional-policy context, which means adjacent-body officials dominate the
unresolved list. A different meeting (budget, P&Z, Parks) would almost
certainly shift the tally toward Tier 3 (resident speakers) — making the
TCAD ingester fix higher-leverage across meetings, even though it ties
with individual Tier 1 scrapers on this meeting alone.

Secondary consideration: the 4 "out-of-town / unknown" names will remain
in Names-to-Verify regardless of which fix we pick. That's expected
behavior — the Tier 4 feedback loop (see CLAUDE.md) is the mechanism
for absorbing these once Jeff confirms spellings against the video.
