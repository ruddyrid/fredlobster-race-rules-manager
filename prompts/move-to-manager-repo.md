# Fred Lobster Race Rules 2027 — Move the tooling to its own repo prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It moves the management tooling out of the race-rulebook repo into its own new repo, re-points the running backend service at the new location, and removes the backend from race-rulebook. The live site stays at v1.0 — this move does not publish anything.

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). The rulebook content (docs/, mkdocs.yml) stays here and stays the single source of truth for the rules.
- New repo: **https://github.com/ruddyrid/fredlobster-race-rules-manager** (owner decision 2026-11-11). The management tooling lives here from now on: the backend, the `fred` CLI, the admin GUI, the operator notes, and the prompts runbook.
- What moves (from the working copy into the new repo):
  - `backend/` — the FastAPI service, including `app.py`, `README.md`, and `static/` (the admin GUI).
  - `fred/` — the terminal client (`fred.py`, launcher, README.md).
  - `OPERATOR-NOTES.md` — the one-page operator notes.
  - `prompts/` — all phase prompts, the inventory, and the runbook README.
- What does NOT move: `docs/`, `mkdocs.yml`, `requirements.txt`, `site/` — the rulebook stays in race-rulebook.
- The backend is currently committed in race-rulebook (commit d97c70e) AND the backend service is running from the working copy. So this is a move, not a copy: the new repo must be verified complete before anything is removed from race-rulebook, and the running service must be re-pointed at the new location before the old code is deleted.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` and the new `~/fredlobster-race-rules-manager` directory — **yes**.
   2. Read files outside those folders (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Run local servers on localhost and restart the `fredlobster-backend` systemd user service — **yes**.
   4. Edit the `fredlobster-backend` systemd user service file to re-point it at the new code location — **yes**.
   5. Fetch from the internet (git clone/push, pip installs only if a genuine need appears) — **yes**.
   6. Push to GitHub — **yes, these two repos only**: `fredlobster-race-rules-manager` (initial commit) and `race-rulebook` (the backend-removal commit, `main` branch only).
   7. Publish (GitHub Pages) — **no**. This move does not deploy anything.
   8. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   9. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Verify the new repo exists and is empty

1. Check whether https://github.com/ruddyrid/fredlobster-race-rules-manager exists and is empty (no commits). Use `git ls-remote https://github.com/ruddyrid/fredlobster-race-rules-manager.git` — an empty repo answers with no refs.
2. If the repo does not exist, STOP and tell the owner to create it on GitHub (empty — no README, no .gitignore, no license) and then re-run this prompt. Do not create the repo yourself, do not guess at its visibility — the owner picks public or private when creating it.
3. If the repo exists but is NOT empty, STOP and report what is in it — do not push into it.

## Step 2 — Read how the backend service runs today

1. Read the `fredlobster-backend` systemd user service file (`~/.config/systemd/user/fredlobster-backend.service`) and note exactly how it launches the backend: the working directory, the command, the port, and any environment (`FL_HOST` and friends).
2. Read `backend/README.md` and note what paths it documents (code location, rulebook working-copy location, how the service is reached).
3. Note the current head commit SHA of the race-rulebook working copy. Report what you found before moving anything.

## Step 3 — Assemble the new repo and push it

1. Clone the empty repo: `git clone https://github.com/ruddyrid/fredlobster-race-rules-manager.git ~/fredlobster-race-rules-manager`.
2. Copy into it, from `~/fredlobster-race-rules-2027`: `backend/`, `fred/`, `OPERATOR-NOTES.md`, `prompts/`. Copy the full directories, including hidden files if any of them has them.
3. Write a top-level `README.md` in the new repo: what this repo is (the management tooling for the Fred Lobster race rules), what lives here (backend, `fred` CLI, admin GUI, operator notes, prompts runbook), where the rulebook content lives (https://github.com/ruddyrid/race-rulebook — the rules themselves are NOT in this repo), and how the pieces fit (backend is the single writer; `fred` and the admin GUI talk only to the backend API; admin access is tailnet-only).
4. Fix stale paths in the copied files: `OPERATOR-NOTES.md` ("where things live") and `backend/README.md` must describe the NEW layout — backend code in `~/fredlobster-race-rules-manager/backend/`, rulebook working copy still in `~/fredlobster-race-rules-2027`. Update only the paths that changed; do not rewrite anything else. Do not reintroduce the retired misspelling anywhere.
5. Commit everything in the new repo as one commit:
   `Initial commit: Fred Lobster race rules manager (backend, fred CLI, admin GUI, operator notes, prompts)`
   Push to `origin main` and verify on GitHub that every file is there (list the repo contents and compare with the copy). Report the commit SHA.
6. If the push fails, report the exact error and stop — do not force-push, do not retry with different credentials. Do NOT proceed to Step 4 or 5 until the new repo is verified complete on GitHub.

## Step 4 — Re-point the running backend service at the new location

1. Update the `fredlobster-backend` service file so it runs the backend from `~/fredlobster-race-rules-manager/backend/` (same port, same environment, same `FL_HOST` — change only the code path). The backend still works on the rulebook working copy `~/fredlobster-race-rules-2027` for the rule files — that path does not change.
2. Run `systemctl --user daemon-reload`, restart the service, and verify it is healthy: `fred status` returns correctly, the admin GUI loads over the tailnet and its status panel reads the published version, and the live site returns `200` with the footer stamp still v1.0.
3. Do NOT publish, do NOT draft or change any rule, do NOT roll back — this step only proves the service runs from its new home. If the service does not come up healthy, stop and report the exact error (and the old working-copy code is still there to fall back on — do not delete anything).

## Step 5 — Remove the backend from race-rulebook

1. Only after Step 3 is verified on GitHub AND Step 4 is verified healthy: in `~/fredlobster-race-rules-2027`, remove `backend/` — `git rm -r backend/` for the tracked files, then plain `rm -rf` for anything untracked left under it (e.g. `backend/static/` if it was never committed). Then `git status --short` to confirm the only change is the `backend/` removal.
2. Commit with this message:
   `Remove backend (moved to fredlobster-race-rules-manager)`
   Push to `origin main` on race-rulebook and verify on GitHub that `backend/` is gone from `main`. Report the commit SHA.
3. If the push fails, report the exact error and stop — do not force-push.

## Step 6 — Save the prompt and report back

1. Save this prompt as `prompts/move-to-manager-repo.md` in the NEW repo (`~/fredlobster-race-rules-manager/prompts/`), and update that repo's `prompts/README.md` to list it. Do NOT commit it separately — if the new repo's initial commit already went out, note the prompt file as uncommitted in the new repo and let the owner decide; do not make a second commit on your own.
2. Report: the new repo URL and initial commit SHA; the service verification (running from the new location, `fred` and admin GUI both working); the race-rulebook removal commit SHA and confirmation `backend/` is gone from `main`; the final `git status` of the rulebook working copy (what is still uncommitted — `site/` churn and anything else); and the live-site check. Then stop.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy and the new repo directory only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelling anywhere — directory, file, or page.
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
