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
| `phase-3-terminal-gui.md` | Phase 3 | Commit the backend into the repo and build the `fred` terminal client (status, sections, show, edit, diff, publish, rollback). |
| `phase-4-admin-gui.md` | Phase 4 | Build the tailnet-only admin GUI served at `/ui/` by the backend (sections, draft edit, diff, publish, rollback, status). |
| `phase-5-hardening-handoff.md` | Phase 5 | Hardening and handoff: preflight smoke tests, publish audit, fresh-clone restore proof, operator notes. No commits, no publishes. |

## Prompts still to be added as the plan advances

- **Phase 2** — backend (content model, data/storage, tailnet-only admin access).
- **Phase 3** — admin GUI.
- **Phase 4** — public GUI polish (navigation, readability, mobile).
- **Phase 5** — CLI/TUI for editing and publishing the rulebook.
- **Phase 6** — publish flow (review, versioning, changelog enforcement, deploy).

## Working rules

- The working copy is `~/fredlobster-race-rules-2027`. The pristine clone is
  `~/race-rulebook` and is never edited.
- The project name is **Fred Lobster**; directory `fredlobster-race-rules-2027`, display
  title **Fred Lobster Race Rules 2027**. The earlier misspelled variant of this name is
  retired and must not reappear anywhere — directory, file, or page.
- Deploys target the `race-rulebook` GitHub repo only.
- Never print, log, or store secrets.
