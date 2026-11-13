# Fred Lobster Race Rules — manager

Management tooling for the **Fred Lobster Race Rules 2027**. The rules themselves are
**not** in this repo — they live in the rulebook repo:

- Rulebook content: https://github.com/ruddyrid/fredlobster-race-rules-2027
- Public site (read-only): https://ruddyrid.github.io/fredlobster-race-rules-2027/

This repo holds the machinery that edits, validates, publishes and rolls back that
rulebook. Markdown in git stays the single source of truth; nothing here is published.

## What lives here

| Path | What it is |
|---|---|
| `backend/` | FastAPI service — the **single writer** for the rule Markdown files. Drafts, diff, publish pipeline, rollback. Runs as the `fredlobster-backend` systemd user service on port 8100. |
| `backend/static/` | The admin GUI, served by the backend at `/ui/` (plain HTML/CSS/JS, no framework). |
| `fred/` | `fred`, the terminal client (`fred.py` + launcher, Python standard library only). |
| `demo/index.html` | Offline sample of the admin GUI (layout mirrors `backend/static/`): invented data only, every action stays in the page, nothing persists. Open it directly in a browser, or the backend serves it at `/ui/demo/`. |
| `OPERATOR-NOTES.md` | The one-page guide: where things live, how to publish, how to roll back. |
| `prompts/` | The prompt runbook for each build phase. |

## How the pieces fit

```
        fred (terminal) ──┐
                          ├──► backend HTTP API (/api/*) ──► rulebook working copy
  admin GUI (/ui/) ───────┘                                  (docs/, mkdocs.yml, git)
                                                                    │
                                                                    └──► GitHub Pages
```

- `fred` and the admin GUI talk **only** to the backend API; neither edits rule files
  directly and they never talk to each other.
- The backend is the only thing that writes `docs/` and `mkdocs.yml`, makes the single
  publish commit, and pushes to the rulebook repo. GitHub Actions then builds and
  deploys the public site.
- Access is **tailnet-only**: the backend binds the OptiPlex's Tailscale address
  (`FL_HOST=100.108.5.126`), never `0.0.0.0`, no Funnel, no port forwarding, no login
  beyond the tailnet itself.

## Where the rulebook is

The backend operates on the rulebook **working copy**, which is a separate checkout —
`~/fredlobster-race-rules-2027` on the OptiPlex. It is told where that is by `FL_REPO`
(set in the systemd unit); without it, the backend falls back to assuming the old
layout where `backend/` sat inside the rulebook repo.

## Running it

```bash
systemctl --user status fredlobster-backend     # the service
fred status                                     # via the CLI
curl -s http://100.108.5.126:8100/api/status    # raw check
```

See [Try it / Use it](#try-it--use-it) below for the live admin and sample demo links.

See `OPERATOR-NOTES.md` for day-to-day use and `backend/README.md` for the API,
the publish pipeline, and the service setup.

## Try it / Use it

- **Live admin GUI (Tailscale only, admin):** http://100.108.5.126:8100/ui/ — the real thing, tailnet only.
- **Sample admin GUI (public demo, fake data):** https://ruddyrid.github.io/fredlobster-race-rules-manager/demo/ — click around freely; nothing is saved. Without deploying, open [`demo/index.html`](demo/index.html) straight from this checkout, or reach it through the backend at http://100.108.5.126:8100/ui/demo/ (linked from the admin GUI header as **Sample GUI**).

## Quick starts

- [Admin GUI quick start](docs/admin-gui-quickstart.md)
- [`fred tmux` quick start](docs/fred-tmux-quickstart.md)
