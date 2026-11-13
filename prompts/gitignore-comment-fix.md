# Fred Lobster Race Rules 2027 — Fix the .gitignore comment prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. One tiny cleanup: the stale comment at the top of race-rulebook's `.gitignore`. The live site stays at v1.0 — no publish, no rule changes.

## Context

- Rulebook working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). Head is 9bdbeec ("Remove stale backend/ lines from .gitignore").
- After the backend moved to the manager repo, `.gitignore` still opens with this comment line:
  `# Backend runtime artifacts (never committed, never published)`
  It now sits above generic `__pycache__/` and `*.pyc` rules, where it no longer makes sense. Reword it or drop it — dropping it is fine, or reword it to something generic like `# Python bytecode (never committed)`.
- Change ONLY that one comment line. Nothing else in the file.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` and `~/fredlobster-race-rules-manager` — **yes**.
   2. Read files outside those folders (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Push to GitHub — **yes, race-rulebook repo only, `main` branch only**, this one commit.
   4. Publish (GitHub Pages) — **no**. The push re-runs the Pages deploy workflow (it triggers on any push to `main`) — that is a rebuild, not a publish, and the site must still read v1.0 afterward.
   5. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   6. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Fix the comment line

1. Open `.gitignore` in the rulebook working copy and confirm the comment line `# Backend runtime artifacts (never committed, never published)` is there at the top. If the line reads differently, report what it actually says and stop instead of guessing.
2. Reword it or drop it (dropping is fine). Verify with `git diff .gitignore` that ONLY that one line changed — no other lines added, removed, or altered.
3. Commit with a message that matches what you did:
   - If dropped: `Remove stale backend comment from .gitignore`
   - If reworded: `Reword .gitignore header comment`
   Push to `origin main` on race-rulebook and verify on GitHub that the commit is on `main`. Report the commit SHA.
4. The push re-runs the Pages deploy workflow — check that it completes successfully and curl the live site: expect `200` and the footer stamp still reading v1.0. If the workflow fails or the site version changes, report it and stop.
5. If the push fails, report the exact error and stop — do not force-push.

## Step 2 — Save the prompt and report back

1. Save this prompt as `prompts/gitignore-comment-fix.md` in the manager repo (`~/fredlobster-race-rules-manager/prompts/`). Leave it uncommitted and report it — do not commit it on your own.
2. Report: the commit SHA and confirmation it is on `main`; the live-site check after the Pages rebuild; and confirmation the prompt file is saved. Then stop.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the two working copies only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelling anywhere — directory, file, or page.
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
