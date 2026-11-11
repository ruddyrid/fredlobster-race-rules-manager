# Fred Lobster Race Rules 2027 — Phase 3 terminal GUI prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It commits the backend into the same repo (owner decision) and then builds the terminal GUI — the `fred` command-line tool for working on the rules from the terminal. Phase 2 is done (backend proven end-to-end: test publish v1.0→v1.1, rollback to v1.0, include fix intact, live site at v1.0).

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). All work happens here. The pristine clone at `~/race-rulebook` stays untouched.
- Phase 3 is the terminal GUI (inward-facing, terminal). Done when: the owner can run `fred` commands from a terminal on the OptiPlex to check status, list and read sections, draft an edit, see the diff, publish, and roll back — all through the backend API — and the herdr pane layout for working is documented.
- The plan (owner's Muse space, "Fred Lobster Race Rules Management Plan"): Markdown in git stays the single source of truth; all interfaces talk to the backend, never to each other; the public site stays read-only; admin/backend stay tailnet-only.
- Decisions settled: (1) GitHub Pages; (2) build the small custom admin GUI; (3) single admin for 2027; (4) one working copy per season. Phase order per the plan page: terminal GUI is Phase 3, admin GUI is Phase 4 (after this).
- Backend-location decision (settled 2026-11-11): the backend lives in the SAME repo — commit it in as Step 1 below.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` — **yes**.
   2. Read files outside that folder (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Run local commands against the backend on localhost — **yes**.
   4. Fetch from the internet (pip installs — the CLI must be Python stdlib only, so expect none) — **yes, only if a genuine need appears; prefer stdlib**.
   5. Install packages (pip, only if the CLI genuinely needs one — prefer stdlib) — **yes**.
   6. Push to GitHub — **yes, race-rulebook repo only** (the backend commit in Step 1, plus any publish commits the pipeline makes).
   7. Publish (GitHub Pages, this repo, via the backend pipeline only) — **yes**.
   8. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   9. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Commit the backend into the same repo

1. Run `git status --short` in the working copy and note everything uncommitted.
2. Commit ONLY `backend/` — nothing else: `git add backend/ && git commit -m "Add Fred Lobster backend (FastAPI service)"` (keep the message factual; adjust the wording only if the backend's own README names it differently). Then `git push origin main`. Verify the push on GitHub (the commit is on `main`).
3. Do NOT commit anything else in this step — not `prompts/`, not the Phase 1 or include-fix source changes (`mkdocs.yml`, `docs/`, `docs/css/`), not `site/`. Report the full remaining uncommitted list in the report-back so the owner can decide on each.
4. If the push fails, report the exact error and stop — do not force-push, do not retry with different credentials.

## Step 2 — Inspect what is already there

1. Read `backend/main.py` (or wherever the Phase 2 code lives) and list the exact endpoints: status, sections, draft, diff, publish, rollback. Note their request/response shapes and the base URL (localhost port and/or tailnet Serve URL).
2. Read `prompts/phase-2-backend.md` and `backend/README.md` for the service setup (port, service name, how it is reached).
3. Note the current published version and head commit SHA. Report what you found before writing any CLI code.

## Step 3 — Build the `fred` CLI

1. Create `fred/` in the working copy: a small Python CLI (`fred/fred.py`, stdlib only — `argparse` + `urllib`, no new dependencies), a `fred/README.md` (every command, with examples), and a launcher so the owner can run it as `fred` from anywhere in the working copy (for example a small shell wrapper or install step documented in the README — do not install anything system-wide).
2. Commands — exactly these, nothing extra. Every command talks to the backend API and nothing else — the CLI never edits rule files directly:
   - `fred status` — published version, draft state, sync state (from `GET /api/status`).
   - `fred sections` — the section list with titles and file paths.
   - `fred show <section>` — prints that section's Markdown.
   - `fred edit <section>` — opens the section in `$EDITOR` as a draft and saves it with `PUT /api/draft/:section`. Show clearly that it is a DRAFT — the public site never sees it until publish.
   - `fred diff` — draft vs published, line by line.
   - `fred publish` — runs the backend pipeline and prints the result: the new version, the commit SHA, the live link.
   - `fred rollback` — restores the previous published version and prints the result.
   - Every command prints a plain-language error and a non-zero exit code on failure — never a stack trace.
3. Herdr pane layout (the "terminal multiplexer" side): document a three-pane working layout in `fred/README.md` — left pane: `fred sections` / `fred status` (the working overview); main pane: the editor via `fred edit`; bottom pane: the backend log (`journalctl --user -u fredlobster-backend -f`) — plus the herdr commands to open that layout (split panes, start the commands in each). Do not hardcode pane IDs; give the commands so the owner can open the layout in any herdr workspace.
4. Do not change any backend endpoint behavior. If the CLI needs an endpoint that does not exist, do not invent it — report it as missing and stop that part.

## Step 4 — Prove it end to end through the CLI

1. Run `fred status` and `fred sections` and confirm they read correctly against the live backend.
2. Draft a small, reversible test change with `fred edit` (for example a comment line in the quick-reference — no rule-text changes), then `fred diff` and confirm it shows exactly that change and nothing else.
3. `fred publish` — confirm it lands as one clean commit, the live GitHub Pages site updates (curl, expect `200`, footer stamp shows the new version).
4. `fred rollback` — confirm the live site is back to exactly what it was before the test publish, and the rollback itself is a clean commit.
5. If any step fails, report the exact error and stop — do not retry the publish, do not hand-edit files to cover it.

## Step 5 — Save the prompt and report back

1. Save this prompt as `prompts/phase-3-terminal-gui.md` in the working copy, and update `prompts/README.md` to list it.
2. Do not commit the CLI code — it stays uncommitted in the working copy for the owner's review. The only commits in this run are the Step 1 backend commit and the publish/rollback commits the pipeline makes.
3. Report: the backend commit SHA and confirmation it is on `main`; the remaining uncommitted list; the `fred` commands and where the README lives; the prove-it results (draft, diff, publish version, rollback); and any open items (anything the CLI needs that the backend lacks). Then stop. The owner reviews the terminal GUI before Phase 4 (the admin GUI).

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelled variant of the project name anywhere — directory, file, or page. (This line is reworded from the original so the forbidden spelling is not itself written into a file.)
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
