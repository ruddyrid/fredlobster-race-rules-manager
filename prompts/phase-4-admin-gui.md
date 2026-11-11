# Fred Lobster Race Rules 2027 — Phase 4 admin GUI prompt for the OptiPlex

Paste this into a Copilot (or Gemini) pane in herdr on the OptiPlex. It commits the backend into the same repo (owner decision, 2026-11-11) and then builds the inward-facing admin GUI. Phase 2 is done (backend proven end-to-end: test publish v1.0→v1.1, rollback to v1.0, include fix intact, live site at v1.0).

## Context

- Working copy: `~/fredlobster-race-rules-2027` (a copy of https://github.com/ruddyrid/race-rulebook). All work happens here. The pristine clone at `~/race-rulebook` stays untouched.
- Phase 4 is the admin GUI (inward-facing, tailnet-only). Done when: the owner can open the admin GUI over the tailnet, edit a section as a draft, see the diff, publish it, and roll it back — all through the GUI, with the live site updating.
- The plan (owner's Muse space, "Fred Lobster Race Rules Management Plan"): Markdown in git stays the single source of truth; all interfaces talk to the backend, never to each other; the public site stays read-only; admin/backend stay tailnet-only.
- Decisions 2–4 are settled: custom admin GUI, single admin for 2027, one working copy per season. Proceed on those decisions and flag anything that needs a new decision instead of guessing.
- Backend-location decision (settled 2026-11-11): the backend lives in the SAME repo — commit it in as Step 1 below.

## Step 0 — Herdr checks and authorizations

1. Confirm you are in a herdr pane (`echo $HERDR_ENV` should be `1`). If it is not `1`, stop and say so — do not proceed from a plain terminal.
2. Answer the authorization questions below before any sensitive action. The owner has pre-approved the following for THIS job only:
   1. Write/edit files in `~/fredlobster-race-rules-2027` — **yes**.
   2. Read files outside that folder (the `~/race-rulebook` clone, the repo contents) — **yes**.
   3. Run local servers on localhost — **yes**.
   4. Fetch from the internet (pip installs, only what the GUI needs — keep new dependencies minimal) — **yes**.
   5. Install packages (pip, minimal) — **yes**.
   6. Restart the `fredlobster-backend` systemd user service to pick up GUI changes — **yes**.
   7. Run `sudo tailscale serve` for the GUI port only if the backend's existing Serve setup does not already cover it (Serve only, never Funnel) — **yes**.
   8. Push to GitHub — **yes, race-rulebook repo only** (the backend commit in Step 1, plus any publish commits the pipeline makes).
   9. Publish (GitHub Pages, this repo, via the backend pipeline only) — **yes**.
   10. Touch the TealsUnltd repo, the Big Cartel store, or tealsunltd.com — **no**.
   11. Read, print, log, or store any secret (password, API key, token) — **no**.
3. If any step needs something outside these approvals, stop and ask the owner first.

## Step 1 — Commit the backend into the same repo

1. Run `git status --short` in the working copy and note everything uncommitted.
2. Commit the backend if it is not already committed: if `git status --short backend/` shows changes, commit ONLY `backend/` — nothing else: `git add backend/ && git commit -m "Add Fred Lobster backend (FastAPI service)"` (keep the message factual; adjust the wording only if the backend's own README names it differently). Then `git push origin main`. Verify the push on GitHub (the commit is on `main`). If there is nothing to commit under `backend/` (Phase 3 already committed it), note that and move on.
3. Do NOT commit anything else in this step — not `prompts/`, not the Phase 1 or include-fix source changes (`mkdocs.yml`, `docs/`, `docs/css/`), not `site/`. Report the full remaining uncommitted list in the report-back so the owner can decide on each.
4. If the push fails, report the exact error and stop — do not force-push, do not retry with different credentials.

## Step 2 — Inspect what is already there

1. Read `backend/main.py` (or wherever the Phase 2 code lives) and list the exact endpoints: status, sections, draft, diff, publish, rollback. Note their request/response shapes.
2. Read `prompts/phase-2-backend.md` and `backend/README.md` for the service setup (port, service name, how it is served on the tailnet).
3. Note the current published version and head commit SHA. Report what you found before writing any GUI code.

## Step 3 — Build the admin GUI

1. Build a small web UI that talks to the backend API and nothing else — the GUI never edits rule files directly. Keep it dependency-light: prefer plain HTML/JS served from the backend's static directory (or Jinja templates in the backend if that is simpler). No new framework unless the backend's existing stack already has one.
2. Features — exactly these, nothing extra:
   - **Sections list** (from `GET /api/sections`): every rule section with its title and file path.
   - **Edit as draft**: open a section, edit its Markdown in a text area, save with `PUT /api/draft/:section`. Show clearly that it is a DRAFT — the public site never sees it until publish.
   - **Diff view** (`GET /api/diff`): draft vs published, line by line, before anything publishes.
   - **Publish** (`POST /api/publish`): runs the backend pipeline (validate → commit → version bump → build → deploy → changelog) and shows the result: the new version, the commit SHA, the live link.
   - **Rollback** (`POST /api/rollback`): restores the previous published version and shows the result.
   - **Status panel** (`GET /api/status`): published version, draft state, sync state (clean vs uncommitted, in sync with GitHub or not).
3. Access: tailnet-only. The GUI rides the backend's existing serving (same port/service if that works, or a second loopback port with its own Serve entry if it does not). The backend currently binds localhost only (Phase 3 finding) — set `FL_HOST=100.108.5.126` (the OptiPlex's Tailscale IP) so the backend binds the tailnet address and the admin GUI is reachable over Tailscale, and verify the GUI loads over the tailnet. Do not bind 0.0.0.0. No public address, no Funnel, no router port forwarding. No login screen — access control is the tailnet itself, exactly as Phase 2 set up the backend ("no auth beyond localhost binding"). If that assumption is wrong for the GUI, say so in the report-back instead of inventing auth.
4. Do not change any backend endpoint behavior. If the GUI needs an endpoint that does not exist, do not invent it — report it as missing and stop that part.

## Step 4 — Prove it end to end through the GUI

1. Load the GUI over the tailnet and confirm the sections list and status panel read correctly.
2. Draft a small, reversible test change through the GUI (for example a comment line in the quick-reference — no rule-text changes), then view the diff in the GUI and confirm it shows exactly that change and nothing else.
3. Publish through the GUI — confirm it lands as one clean commit, the live GitHub Pages site updates (curl, expect `200`, footer stamp shows the new version).
4. Roll back through the GUI — confirm the live site is back to exactly what it was before the test publish, and the rollback itself is a clean commit.
5. If any step fails, report the exact error and stop — do not retry the publish, do not hand-edit files to cover it.

## Step 5 — Save the prompt and report back

1. Save this prompt as `prompts/phase-4-admin-gui.md` in the working copy, and update `prompts/README.md` to list it. Also, if the owner attached the Phase 2 prompt file (`fredlobster-phase2-prompt.md`), save it as `prompts/phase-2-backend.md` — the Phase 3 run found it absent from the runbook. If it was not attached, note the gap and move on.
2. Do not commit the GUI code — it stays uncommitted in the working copy for the owner's review. The only commits in this run are the Step 1 backend commit and the publish/rollback commits the pipeline makes.
3. Report: the backend commit SHA and confirmation it is on `main`; the remaining uncommitted list; the GUI's tailnet URL; the prove-it results (draft, diff, publish version, rollback); and any open items (anything the GUI needs that the backend lacks). Then stop. The owner reviews the admin GUI.

## Standing rules

- Do not touch the SBF V8 repo (`20261107-sbf-v8-tech`), the RX-7 13BT repo (`20261107-rx7-13bt-tech`), the TealsUnltd repo, the Big Cartel store, tealsunltd.com, or the home-server-status page.
- The owner's passwords and API keys are the owner's. Never print them, log them, or store them in a file.
- Work in the working copy only. Never edit the `~/race-rulebook` original. Never reintroduce the retired misspelled variant of the project name anywhere — directory, file, or page. (This line is reworded from the original so the forbidden spelling is not itself written into a file.)
- If the owner says "Stop", stop immediately and say plainly what was done, what was verified, and what was not done.
