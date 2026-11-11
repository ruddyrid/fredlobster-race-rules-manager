# Fred Lobster Race Rules 2027 — Phase 5 hardening & handoff prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. This is the last phase: prove the whole system is sound, write the operator notes, and hand it over. Phases 0–4 are done (public site live at v1.0, backend committed, `fred` CLI and admin GUI both proven end-to-end with test publish + rollback). This phase makes no changes to the live site and commits nothing.

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). All work happens here. The pristine clone at `~/race-rulebook` stays untouched.
- Phase 5 is hardening & handoff (~1 session). Done when: every publish is confirmed pushed to GitHub, a full restore from a fresh clone is proven, the one-page operator notes exist, and the owner has a clean list of what is still uncommitted and why.
- The plan (owner's Muse space, "Fred Lobster Race Rules Management Plan"): Markdown in git stays the single source of truth; all interfaces talk to the backend, never to each other; the public site stays read-only; admin/backend stay tailnet-only.
- Decisions settled: (1) GitHub Pages; (2) build the small custom admin GUI; (3) single admin for 2027; (4) one working copy per season, archived read-only at season's end.
- The live site stays at v1.0 through this phase. Do not publish, do not roll back, do not re-run Phase 2, 3, or 4.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` — **yes** (operator notes only — see Step 4).
   2. Read files outside that folder (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Create and delete ONE temp directory `~/fredlobster-restore-test` for the restore test, and nothing else outside the working copy — **yes**.
   4. Run local servers on localhost — **yes**.
   5. Fetch from the internet (pip installs into the temp dir's venv only) — **yes**.
   6. Install packages (pip, temp-dir venv only) — **yes**.
   7. Push to GitHub — **no**. This phase makes no commits and no pushes. If something looks like it needs committing, report it and stop that part.
   8. Publish (GitHub Pages) — **no**.
   9. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   10. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Preflight: read what is there and smoke-test each interface

1. Read `backend/` (main service file, README, `static/`), `fred/README.md`, `prompts/README.md` and the prompt files, and the admin GUI as served. Note the backend's port, service name, and `FL_HOST` setting (it should bind the tailnet IP `100.108.5.126` after Phase 4).
2. Smoke-test each interface read-only:
   - `fred status` and `fred sections` return correctly against the live backend.
   - The admin GUI loads over the tailnet and its status panel reads the published version.
   - The live site returns `200` and the footer stamp reads v1.0.
3. Report anything that does not respond before moving on. If an interface is down, diagnose it (service status, logs) and report the fix — do not rebuild anything.

## Step 2 — Verify every publish is pushed to GitHub

1. List the publish commits on `main` (the Phase 2, 3, and 4 test publishes and their reverts) and confirm each one is on `origin/main` — run `git log --oneline` and `git status` and compare with GitHub.
2. Confirm the live GitHub Pages site matches the committed state: footer stamp v1.0, rule text renders, no literal include syntax, all key routes `200`.
3. If any publish is missing from GitHub, or the live site disagrees with the repo, report exactly what is out of sync and stop — do not push or publish to fix it.

## Step 3 — Prove a full restore from a fresh clone

1. Clone the repo fresh into `~/fredlobster-restore-test` (do not touch `~/race-rulebook`). Create a venv there, install `requirements.txt`, run `mkdocs build`, serve it on localhost, and check the home, rules, safety, quick-reference, and search pages return `200`, the footer stamp reads v1.0, and the rule text renders with no literal include syntax.
2. Verify the committed backend is complete: list `backend/` in the fresh clone and compare it with the working copy — report any file the running service needs that is NOT in the repo (if the service depends on an uncommitted file, that is a finding, not something to fix by committing).
3. Delete `~/fredlobster-restore-test` when done and confirm it is gone. Report the restore result: what was rebuilt, what matched the live site, and anything missing.

## Step 4 — Write the one-page operator notes

1. Write `OPERATOR-NOTES.md` at the working-copy root — one page, plain language, no jargon the owner has not seen before. It covers:
   - Where things live: the working copy, the repo, the backend service, `fred`, the admin GUI, the prompts runbook.
   - How to publish a rule change: draft → diff → publish (via `fred` or the admin GUI), and what a publish does (commit, version bump, build, deploy, changelog).
   - How to roll back, and what to check after (live footer version, `git status`).
   - How to reach the admin GUI (tailnet only, `FL_HOST=100.108.5.126`; flip it back to localhost-only if ever needed) and that there is no login beyond the tailnet.
   - The off-season freeze (Decision 4): at season's end the working copy is archived read-only and the next season starts from a fresh copy — the procedure, not the freeze itself. Do NOT freeze or archive anything now; the 2027 season has not happened yet.
2. Do not commit the notes — they stay uncommitted with the rest of the working-copy changes for the owner's review.

## Step 5 — Save the prompt and report back

1. Save this prompt as `prompts/phase-5-hardening-handoff.md` in the working copy, and update `prompts/README.md` to list it.
2. Report: the preflight results (each interface up or down); the publish audit (every publish on GitHub or not, live site match); the restore test result (what rebuilt, what matched, anything missing, temp dir deleted); the operator notes file; and the full still-uncommitted list, item by item — `fred/`, `prompts/` (including `phase-2-backend.md`), `backend/static/` and the `backend/app.py` + `README.md` changes from Phase 4, the operator notes, and the `site/` build churn — so the owner can decide on each. Then stop. The system is handed over.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelled variant of the project name anywhere — directory, file, or page. (This line is reworded from the original so the forbidden spelling is not itself written into a file.)
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
