# Fred Lobster Race Rules 2027 — include fix prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It fixes the broken "Full Rules" blocks: the combined pages currently show literal include syntax instead of the rule text. Run this BEFORE the Phase 2 backend prompt — the backend will serve these same files.

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). All work happens here. The pristine clone at `~/race-rulebook` stays untouched.
- Live site: https://ruddyrid.github.io/race-rulebook/ (GitHub Pages, `gh-pages` branch, deployed by `mkdocs gh-deploy`).
- The defect, confirmed on the live home page: the "Full Rules" section shows literal text — `{% include "rules/safety.md" %}`, `{% include "rules/classes.md" %}`, `{% include "rules/technical.md" %}`, `{% include "rules/procedures.md" %}`, `{% include "rules/penalties.md" %}` — and no rule text. The same problem exists on the rules and appendices combined pages, which use Obsidian-style `![[...]]` embeds. Neither pattern is processed by the extensions currently enabled in `mkdocs.yml`.
- Owner decision (2026-11-11): **convert the includes to a pattern MkDocs understands** — one pattern for both styles, keeping the pages combined. Do not inline the rule text into the combined pages.
- The MkDocs venv from Phase 0 is at `~/fredlobster-race-rules-2027/.venv` — activate it first: `source .venv/bin/activate`.

## Step 1 — Inspect first

Find every include/embeds in the working copy: `grep -rn "{% include" docs/` and `grep -rn "!\[\[" docs/`. Read `mkdocs.yml` (extensions, plugins, `extra_css`) and `requirements.txt`. Report what you found — every file that uses an include pattern, and which extensions are currently enabled — before changing anything.

## Step 2 — Pick one supported pattern and convert

1. Choose ONE MkDocs-supported include mechanism that fits what is already installed, with the least change — for example `pymdownx.snippets` (the `--8<-- "file"` syntax, part of pymdown-extensions) or the `mkdocs-include-markdown-plugin` (`{% include-markdown "file" %}`). If the chosen mechanism needs a package that is not installed, add it to `requirements.txt` and install it in the venv, and enable it in `mkdocs.yml`.
2. Convert ALL of the includes to that one pattern: the five `{% include "rules/*.md" %}` tags in `docs/index.md`, and every `![[...]]` embed in `docs/rules/index.md` and `docs/appendices/index.md`. After the conversion, no `{% include` and no `![[` syntax may remain anywhere under `docs/`.
3. Do not change any rule text. Do not change `site_name` — it stays "FRed Lobster 100 Rulebook" until the owner decides otherwise. Do not restyle anything. Do not touch the footer stamp or the print CSS from Phase 1.

## Step 3 — Leave these alone and report them

- The `(TBD)` in `docs/rules/safety.md:17` — leave it exactly as-is. It needs the owner's content; do not invent any.
- `docs/appendices/index.md` duplicating the home page with no diagrams/forms — leave the structure as-is except for the embed conversion. Report it as still open.
- The site name — leave it. Report it as still open.

## Step 4 — Build, check locally, deploy

1. `mkdocs build` — it must exit clean. Fix nothing silently; if the build fails, report the exact error and stop.
2. Verify the built output, not just the build exit code: `grep` the built HTML under `site/` for the rule text (for example a sentence from `rules/safety.md`) and confirm NO literal `{% include` or `![[` remains in any built page. Then serve locally (`mkdocs serve --dev-addr 127.0.0.1:8000`) and check the home page, the rules page, and the appendices page return `200` with the rule text actually visible.
3. Deploy to GitHub Pages with `mkdocs gh-deploy` (the repo's existing mechanism). The deploy target is the **race-rulebook repo only**. Do not create a new repo. Verify the live link with `curl` and expect `200`, then confirm on the live pages that the Full Rules sections show the rule text. GitHub Pages can take a minute or two after a deploy; wait and re-check if it is not up yet.
4. Save this prompt as `prompts/phase-1b-include-fix.md` in the working copy, and update `prompts/README.md` to list it. Do not commit anything — all changes stay uncommitted in the working copy, except the deploy push itself.

## Step 5 — Report back and stop

Report: which include pattern was chosen and why, every file changed, the build and local-check results, the live link with confirmation the rule text renders, and the still-open items (the safety.md TBD, the appendices duplication, the site name). Then stop. The owner will review the live book before Phase 2.

## Authorizations (answer these first, before any sensitive action)

The owner has pre-approved the following for THIS job only:

1. Write/edit files in `~/fredlobster-race-rules-2027` — **yes**.
2. Read files outside that folder (the `~/race-rulebook` clone, the repo contents) — **yes**.
3. Run a local preview server on localhost — **yes**.
4. Fetch from the internet (pip installs, if a plugin is needed) — **yes**.
5. Install packages (pip, only what the MkDocs build needs) — **yes**.
6. Push to GitHub — **yes, race-rulebook repo only** (the `gh-pages` branch, as the deploy requires).
7. Publish (GitHub Pages, this repo) — **yes**.
8. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
9. Read, print, log, or store any secret (password, API key, token) — **no**.

If any step needs something outside these approvals, stop and ask the owner first.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelled variant of the project name anywhere — directory, file, or page. (This line is the only wording deviating from the original prompt, because word-for-word it would write that spelling into a file, which the rule itself forbids.)
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
