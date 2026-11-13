# Fred Lobster race-rules manager

Tooling repo for the Fred Lobster Race Rules 2027. The rules are not here. They
live in the working copy `~/fredlobster-race-rules-2027` (GitHub
`ruddyrid/fredlobster-race-rules-2027`). This repo is the backend, `fred` CLI, and admin GUI.

- `fred` and the admin GUI talk only to the backend HTTP API. Never edit rule
  files, `docs/`, or `mkdocs.yml` directly.
- Backend: `systemctl --user status fredlobster-backend` (port 8100, tailnet).
- Drafts are backend-only (`backend/drafts/`, gitignored) until `fred publish`.
- Do not publish, roll back, or push unless the user asks.
- Never print, log, or store secrets.

## fred terminal

When the user says **start**, asks to initialize this workspace, or asks for
help interfacing with **fred**, the **fred terminal**, **fred TMUX**, or the
**fred CLI**, read `init/fred-tmux.md` and set up that layout. It is the latest
procedure. Do not improvise a different layout, and do not follow an older one
from memory.

`/init` must keep this section and must not delete `init/fred-tmux.md`.
