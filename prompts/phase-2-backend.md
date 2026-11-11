# Fred Lobster Race Rules 2027 — Phase 2 prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It builds the backend core: a small FastAPI service on the OptiPlex that is the single writer for the rule files, with the publish pipeline as one operation. Phase 1 is done (the 2027 rulebook is live on GitHub Pages, searchable, with the version stamp and one-page quick-reference print). Decision 1 is settled: **GitHub Pages**. Decisions 2–4 are still open but Phase 2 does not need them — it assumes the plan's recommendations (single admin, custom backend, one working copy per season).

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). All work happens here. The pristine clone at `~/race-rulebook` stays untouched.
- Phase 2 is "Backend core" (~2–3 sessions). Done when: a publish can be triggered end-to-end via raw API calls and lands as a clean commit + live site update, and rollback restores the prior version.
- The plan: Markdown in git stays the single source of truth. The backend is a thin service that reads and writes the rule files; all three interfaces talk to the backend, never to each other. **No database** — the rule files and git are the storage.
- The MkDocs venv from Phase 0 is at `~/fredlobster-race-rules-2027/.venv` — activate it first for any `mkdocs` or `pip` command: `source .venv/bin/activate`.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the nine authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` — **yes**.
   2. Read files outside that folder (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Run a local preview server on localhost — **yes**.
   4. Fetch from the internet (pip installs, only what the backend needs) — **yes**.
   5. Install packages (pip, only FastAPI + its runner and what the MkDocs build needs) — **yes**.
   6. Push to GitHub — **yes, race-rulebook repo only** (the branches the publish pipeline needs: `main` and/or `gh-pages`).
   7. Publish (GitHub Pages, this repo) — **yes**.
   8. Enable/start a user systemd service for the backend — **yes, `fredlobster-backend` only, bound to localhost / the Tailscale IP only, never a public address**.
   9. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   10. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Inspect what is already there

1. Read `mkdocs.yml` in full and note: the theme, the version-stamp footer mechanism Phase 1 used (footer override? theme config?), the current version string and where it lives, and the nav order.
2. Read `.github/workflows/` (if any) and note how Phase 1 deployed — GitHub Actions workflow, or `mkdocs gh-deploy` to the `gh-pages` branch. The publish pipeline must reuse that same mechanism; do not invent a second one.
3. Note the current published version, the head commit SHA, and the Python version in the venv. Report what you found before writing any code.

## Step 2 — Build the backend

1. **Where the code lives.** Create the service under `~/fredlobster-race-rules-2027/backend/` (FastAPI, Python — one language with the MkDocs toolchain; keep it small, single-file-friendly). Do NOT commit the backend code yet — it stays uncommitted in the working copy until the owner decides whether it lives in this repo or a separate one. Say so in the report-back.
2. **The API — exactly these endpoints, nothing extra:**
   - `GET /api/status` — version, draft state, sync state (clean vs uncommitted, in sync with GitHub or not).
   - `GET /api/sections` — section list + file contents (read from `docs/`, nav order from `mkdocs.yml`).
   - `PUT /api/draft/:section` — save a draft edit. Drafts are held by the backend only (e.g. under `backend/drafts/`, never committed, never in `docs/`) — the public site never sees a half-finished rule.
   - `GET /api/diff` — draft vs published, line by line.
   - `POST /api/publish` — the pipeline in Step 3, as one operation.
   - `POST /api/rollback` — restore a previous published version (git), then rebuild and redeploy.
3. **Access control.** The service listens on localhost / the Tailscale IP only (e.g. `127.0.0.1:8100` if that port is free — confirm it is free first). Never `0.0.0.0`, no Tailscale Funnel, no router port forwarding. The public site is a separate static output and contains no part of the backend.
4. **Data model — just files.** `docs/rules/` (index, classes, penalties, procedures, safety, technical — one Markdown file per section), `docs/quick-reference.md`, `docs/changelog.md` (appended by the backend at every publish, never hand-edited), `mkdocs.yml` (nav order — the backend reads nav from here so new sections appear everywhere at once). Front matter per section: section id, title, last-published version; everything else is the rule text.

## Step 3 — The publish pipeline (one operation)

`POST /api/publish` does these in order, and stops with a plain-language reason at the first failure — a failed check blocks the publish, nothing half-publishes:

1. **Validate.** Every nav section exists, no empty pages, no broken internal links, `mkdocs build` exits clean.
2. **Commit.** Write the drafts into the real files as one git commit, with the new version in the commit message.
3. **Version bump.** Bump the version (v1.0 → v1.1 style, continuing whatever Phase 1 used) and stamp the version + date into the site footer on every page, using the same mechanism Phase 1 used.
4. **Build.** Run the MkDocs build.
5. **Deploy.** Push the built site using the mechanism found in Step 1 (existing workflow or `mkdocs gh-deploy`). The deploy target is the **race-rulebook repo only**.
6. **Changelog.** Append the entry to `docs/changelog.md` from the publish (what changed, when, the version it landed in) and include it in the same commit when the flow allows — if the deploy mechanism commits separately, say so plainly in the report-back instead of forcing it.

## Step 4 — Run it as a service

1. Install the service as a **user** systemd service (`~/.config/systemd/user/fredlobster-backend.service`, `systemctl --user enable --now fredlobster-backend`), so it runs alongside herdr and survives reboots the same way the other OptiPlex user services do.
2. Verify it is up after starting: `curl` the status endpoint and confirm the version, draft state, and sync state read correctly.
3. Do NOT reboot the machine to test survival — the owner confirms reboot behavior himself. Say so in the report-back.

## Step 5 — Prove it end to end (raw API calls only)

1. `GET /api/status` — record the published version and sync state.
2. Draft a small, reversible test change with `PUT /api/draft/:section` (for example a version-date stamp refresh — no rule-text changes), then `GET /api/diff` and confirm the diff shows exactly that change and nothing else.
3. `POST /api/publish` — confirm it lands as one clean commit, the live GitHub Pages site updates (curl, expect `200`, footer stamp shows the new version), and the changelog gained the entry.
4. `POST /api/rollback` — restore the pre-test version, confirm the live site is back to exactly what it was before the test publish, and confirm the rollback itself is a clean commit.
5. If any step fails, report the exact error and stop — do not retry the publish, do not hand-edit files to cover it.

## Step 6 — Report back and stop

Report: what Phase 1 had already put in place vs what you added (endpoints, draft storage, service file, port), the publish-pipeline test result (commit SHA, live link, before/after versions), the rollback test result, and the open question of where the backend code should live (same repo vs separate repo — uncommitted for now). Then stop. The owner reviews the backend before Phase 3 (the `fred` terminal GUI).

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelled variant of the project name anywhere — directory, file, or page. (This line is reworded so the forbidden spelling is not itself written into a file; it is the only change from the original prompt.)
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
