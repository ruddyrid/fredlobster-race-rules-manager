# Phase 0 inventory — Fred Lobster Race Rules 2027

Source: fresh clone of `https://github.com/ruddyrid/race-rulebook`, head commit
`d2e317a90f3d8894360bc6ee73feceab6894b0e3` ("Clarify bumper beam and flank rules").
Working copy: `~/fredlobster-race-rules-2027`.

## What the book covers

A complete club-level rulebook for a 4-cylinder enduro race (the FRed Lobster 100):

- **Home** (`docs/index.md`) — intro, printable-full-book button, start-here links,
  rule-section table, RACEceiver gear links, then a "Full Rules" section intended to
  inline every rule file.
- **Quick Reference** (`docs/quick-reference.md`) — one-page condensed rules: vehicle
  requirements, team requirements, safety highlights, claims, recommended gear.
- **Rules** (`docs/rules/`) — **5 rule pages** plus an overview page:
  1. `safety.md` — required equipment, red/black flags, mandatory pit stops, pit-area
     rules, recommendations, conduct.
  2. `classes.md` — 8 numbered eligibility items (4-cylinder, 2WD, tires, helmet, brake
     light, extinguisher, mud flaps, bumpers).
  3. `technical.md` — bumper rules (stock preference, one-beam fabrication limit, main
     supports, flank supports, no chassis reinforcement), radiator protectors,
     transponders, Friday testing; includes two diagrams under `docs/images/`.
  4. `procedures.md` — 11 numbered team/driver/registration items, RACEceiver, driver
     changes.
  5. `penalties.md` — 8 numbered claim items ($1,500, 50th-lap deadline, claim board).
- **Appendices** (`docs/appendices/`) — `index.md` (a near-duplicate of the home page) and
  `glossary.md` (glossary table of 13 terms).
- **Changelog** (`docs/changelog.md`) — 2026 season entries, most recent October 6, 2026.

Total markdown pages: 12 (435 lines).

## Site configuration

- MkDocs 1.6.1 + **Material for MkDocs 9.6.14** (theme already Material — light/dark
  palette, custom colors, tabs/sections navigation).
- `search` plugin present with suggest + highlight features.
- `print-site` plugin present (builds a combined `/print_page/`).
- Print styles already exist in `docs/css/custom.css` for the combined print page.
- Deploy: `.github/workflows/deploy.yml` runs on push to `main` (plus manual dispatch) and
  runs `mkdocs build` then `mkdocs gh-deploy --force`. Pages source is the `gh-pages`
  branch (legacy build), live at `https://ruddyrid.github.io/race-rulebook/`.
- A second workflow, `changelog-check.yml`, guards changelog updates.

## Unfinished / broken items found (not fixed in Phase 0)

1. **The combined "Full Rules" sections do not render.** `docs/index.md` uses
   `{% include "rules/safety.md" %}` and `docs/rules/index.md` and
   `docs/appendices/index.md` use `![[safety.md]]` (Obsidian embed syntax). None of these
   are processed by the enabled extensions — the built HTML contains the literal
   `{% include … %}` / `![[…]]` strings and **none of the rule text**. The
   `markdown_include` extension that is enabled expects `{!file!}` syntax. This is the
   single biggest content defect: the home page's "Full Rules" block is empty placeholder
   text, and `rules/index.md` likewise shows raw syntax instead of the rules.
   Blocked on a decision: the intended single-source-of-truth pattern (include vs. the
   print-site plugin's combined page) needs to be picked before the includes are rewired.
2. **Placeholder in safety rules.** `docs/rules/safety.md:17` — red-flag penalty text ends
   with "(TBD)": "Repeat offenders can expect severe punishment and public embarrassment
   (TBD)."
3. **`docs/appendices/index.md` duplicates the home page** but is titled and navigated as
   "Diagrams & Forms" — it contains no diagrams or forms.
4. **Naming inconsistency.** Site name is `FRed Lobster 100 Rulebook` (odd capitalization)
   and pages refer to "FRed Lobster 100", while the project display title is
   **Fred Lobster Race Rules 2027**. Left untouched in Phase 0 (no rule-content edits).
5. **Stale absolute link.** The "Download / Print Full Rulebook" button in
   `docs/index.md` and `docs/appendices/index.md` is hard-coded to
   `https://ruddyrid.github.io/race-rulebook/print_page/` rather than a relative path, so it
   will break if the site URL ever changes.
6. **No version/date stamp in the footer**, and no per-page print styling for the
   quick reference (the existing print CSS targets the combined print page).

## Build and preview status

- `.venv` created with system Python 3.14.8; `pip install -r requirements.txt` clean.
- `mkdocs build` exits clean (0.3 s).
- `mkdocs serve --dev-addr 127.0.0.1:8000` running on localhost only.
- `curl` checks: `/` 200, `/rules/` 200, `/rules/safety/` 200, `/quick-reference/` 200,
  `/search/search_index.json` 200.
