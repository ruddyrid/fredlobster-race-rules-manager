# Fred Lobster Race Rules 2027 — Tidy-up after the move prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It cleans up the three leftovers from the move to the manager repo: the duplicate copies in the rulebook working copy, the stale `.gitignore` lines, and the manager repo's runbook table. The live site stays at v1.0 — no publish, no rule changes.

## Context

- Rulebook working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). Head is 8a32a67 ("Remove backend (moved to fredlobster-race-rules-manager)").
- Manager repo: `~/fredlobster-race-rules-manager` (a copy of https://github.com/ruddyrid/fredlobster-race-rules-manager). Head is 052f8db (initial commit, 22 files).
- The move is done and verified: the backend runs from the manager repo, the admin GUI and `fred` are healthy, the live site is at v1.0.
- Three tidy-ups, all owner-approved:
  1. Delete the untracked duplicates still sitting in the rulebook working copy: `OPERATOR-NOTES.md`, `fred/`, `prompts/`. They are copies of what is now in the manager repo.
  2. Remove the stale `backend/` lines from race-rulebook's `.gitignore`.
  3. Fix the manager repo's `prompts/README.md` table (it omits `phase-2-backend.md` and its "prompts still to be added" list is stale) and commit the still-uncommitted runbook files there.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` and `~/fredlobster-race-rules-manager` — **yes**.
   2. Read files outside those folders (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Delete files — **yes, only the three duplicates in Step 1, and only after the diff check in that step passes**.
   4. Push to GitHub — **yes, these two repos only**: `race-rulebook` (`main` only, the `.gitignore` fix) and `fredlobster-race-rules-manager` (`main` only, the runbook fix).
   5. Publish (GitHub Pages) — **no**. The `.gitignore` push will re-run the Pages deploy workflow (it triggers on any push to `main`) — that is a rebuild, not a publish, and the site must still read v1.0 afterward.
   6. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   7. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Verify the duplicates, then delete them from the rulebook working copy

1. For each of the three items in `~/fredlobster-race-rules-2027` — `OPERATOR-NOTES.md`, `fred/`, `prompts/` — compare it with the same path in `~/fredlobster-race-rules-manager` (use `diff -r`, ignoring nothing). The manager repo copy is the authority.
2. If every file matches exactly, delete the three duplicates from the rulebook working copy (`rm -rf` on each path). If ANY file differs, or any of the three is missing from the manager repo, STOP and report exactly what differs — do not delete anything.
3. After deletion, run `git status --short` in the rulebook working copy and confirm the only remaining uncommitted items are the `site/` build churn (and the `.gitignore` change from Step 2, if you have already made it).

## Step 2 — Fix race-rulebook's `.gitignore` and push it

1. In `~/fredlobster-race-rules-2027`, open `.gitignore` and remove exactly these three lines, nothing else: `backend/drafts/`, `backend/__pycache__/`, `backend/*.log`. (Match them as written in the file — if a line reads differently, report it and stop instead of guessing.)
2. Verify with `git diff .gitignore` that only those three lines changed.
3. Commit with this message:
   `Remove stale backend/ lines from .gitignore`
   Push to `origin main` on race-rulebook and verify on GitHub that the commit is on `main`. Report the commit SHA.
4. The push re-runs the Pages deploy workflow — check that it completes successfully and curl the live site: expect `200` and the footer stamp still reading v1.0. If the workflow fails or the site version changes, report it and stop.
5. If the push fails, report the exact error and stop — do not force-push.

## Step 3 — Fix the manager repo's runbook table and commit the runbook files

1. In `~/fredlobster-race-rules-manager`, open `prompts/README.md` and fix it: add `phase-2-backend.md` to the prompts table (it is in `prompts/` — confirm the file is there first), and correct the "prompts still to be added" list so it no longer lists anything that is already in `prompts/`. Change nothing else in the file.
2. Save this prompt as `prompts/tidy-up-after-move.md` in the manager repo and add it to the `prompts/README.md` table as well.
3. Commit in the manager repo — the README fix, `prompts/move-to-manager-repo.md`, and `prompts/tidy-up-after-move.md` — with this message:
   `Fix prompts README table and file the move and tidy-up prompts`
   Push to `origin main` on the manager repo and verify on GitHub that the commit is on `main`. Report the commit SHA.
4. If the push fails, report the exact error and stop — do not force-push.

## Step 4 — Report back

1. Report: the diff check result for the three duplicates and confirmation they are deleted; the race-rulebook `.gitignore` commit SHA and the live-site check after the Pages rebuild; the manager repo commit SHA; and the final `git status` of both working copies (what, if anything, is still uncommitted). Then stop.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the two working copies only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelling anywhere — directory, file, or page.
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
