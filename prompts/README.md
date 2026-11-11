# Fred Lobster Race Rules 2027 — Prompt Runbook

This directory holds the compiled prompts for this project. They are the project's own
runbook; the management plan in the owner's Muse space ("Fred Lobster Race Rules Management
Plan") is the overview and the place where decisions are recorded.

Guiding decisions already settled:

- Markdown in git is the single source of truth for the rules.
- The public site is read-only.
- Admin/backend stay tailnet-only.
- Decision 1: publish on GitHub Pages.

## Prompts in this set

| File | Phase | Purpose |
|------|-------|---------|
| `phase-0-startup.md` | Phase 0 | Set up the working copy, build, serve a local preview, and inventory the existing rulebook. |
| `phase-1-public-render.md` | Phase 1 | Polish the public render (theme, search, footer version stamp, print CSS for the quick reference) and deploy to GitHub Pages. |
| `phase-1b-include-fix.md` | Phase 1b | Fix the broken combined "Full Rules" blocks — one supported include pattern for every include site-wide. **Run before Phase 2.** |
| `phase-2-backend.md` | Phase 2 | Build the backend core: FastAPI service, the six API endpoints, the publish pipeline (validate → bump → build → commit → push → verify live), and the localhost/tailnet binding. |
| `phase-3-terminal-gui.md` | Phase 3 | Commit the backend into the repo and build the `fred` terminal client (status, sections, show, edit, diff, publish, rollback). |
| `phase-4-admin-gui.md` | Phase 4 | Build the tailnet-only admin GUI served at `/ui/` by the backend (sections, draft edit, diff, publish, rollback, status). |
| `phase-5-hardening-handoff.md` | Phase 5 | Hardening and handoff: preflight smoke tests, publish audit, fresh-clone restore proof, operator notes. No commits, no publishes. |
| `move-to-manager-repo.md` | Move | Move the tooling (backend, `fred`, admin GUI, operator notes, prompts) out of race-rulebook into this repo, re-point the service, remove the backend from race-rulebook. No publish. |
| `tidy-up-after-move.md` | Tidy-up | Remove the post-move duplicates from the rulebook working copy, drop the stale `backend/` lines from its `.gitignore`, and fix this runbook table. No publish. |

## Prompts still to be added as the plan advances

- **Public GUI polish** — navigation, readability, mobile. Not yet planned; the public
  site has only the polish Phase 1 gave it. The backend, CLI, admin GUI, and publish
  flow are all built and documented in the prompts above.

## Working rules

- The working copy is `~/fredlobster-race-rules-2027`. The pristine clone is
  `~/race-rulebook` and is never edited.
- The project name is **Fred Lobster**; directory `fredlobster-race-rules-2027`, display
  title **Fred Lobster Race Rules 2027**. The earlier misspelled variant of this name is
  retired and must not reappear anywhere — directory, file, or page.
- Deploys target the `race-rulebook` GitHub repo only.
- Never print, log, or store secrets.
