# Backend — Fred Lobster Race Rules 2027

Small FastAPI service that is the **single writer** for the rule Markdown files in the
rulebook repo (https://github.com/ruddyrid/fredlobster-race-rules-2027). No database: the Markdown
files and git are the storage. This code lives in the manager repo; the content lives
in the rulebook working copy, `~/fredlobster-race-rules-2027`, found via `FL_REPO`.

- Binds the Tailscale address (`FL_HOST=100.108.5.126` in the systemd unit) or
  localhost, never `0.0.0.0`, no Funnel, no port forwarding. The public site is the
  static MkDocs output on GitHub Pages and contains no part of this backend.
- Serves the admin GUI at **`/ui/`** (plain HTML/JS in `backend/static/`), over the
  same tailnet-only binding: `http://100.108.5.126:8100/ui/` when `FL_HOST` is the
  Tailscale address. No framework, no extra dependencies.
- Storage: `docs/**/*.md`, `mkdocs.yml` (nav + footer version stamp), git history — all
  inside the rulebook working copy (`FL_REPO`).
- Drafts live in this repo's `backend/drafts/` — backend-only, gitignored, never under
  `docs/`, so a half-finished rule can never reach the public site.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/ui/` | Admin GUI (static HTML/JS; tailnet-only, same binding) |
| GET | `/api/status` | version, draft state, git clean/sync state |
| GET | `/api/sections` | nav sections in `mkdocs.yml` order + file contents |
| PUT | `/api/draft/{section}` | save a draft (`{"content": "..."}`) |
| GET | `/api/diff` | draft vs published, unified diff per section |
| POST | `/api/publish` | validate → bump → build → commit → push → verify live |
| POST | `/api/rollback` | `git revert` the last publish commit, rebuild, redeploy |

Section ids are the nav path without `.md`, with `/` as `-`:
`rules-safety`, `rules-technical`, `quick-reference`, `changelog`, `index`, …

## Publish pipeline

One operation, stops at the first failure and publishes nothing:

1. **validate** — every nav section exists and is non-empty, no leftover include
   syntax, `mkdocs build --strict` (this is also the broken-internal-link check).
2. **stage** — drafts are written into `docs/`, the footer version is bumped
   (`v1.0` → `v1.1`, same `copyright:` mechanism as Phase 1), and the changelog
   entry is appended.
3. **build** — `mkdocs build --strict`; on failure the staged files are rolled back
   and nothing is committed.
4. **commit** — one commit, message `Publish v1.x: <sections> updated`, containing
   the drafts, the version stamp, and the changelog entry together.
5. **deploy** — `git push origin main`; the repo's existing GitHub Actions workflow
   (`deploy.yml`) builds and gh-deploys to `gh-pages`. No second deploy mechanism.
6. **verify** — polls the public site until it serves the new version string.

`POST /api/rollback` reverts the most recent `Publish v…` commit with `git revert`
(a clean commit), rebuilds, pushes, and waits for the live site to show the older
version again.

## Run it

```bash
cd ~/fredlobster-race-rules-manager
source .venv/bin/activate
pip install -r backend/requirements.txt
export FL_REPO=~/fredlobster-race-rules-2027    # the rulebook working copy
python -m backend.app            # 127.0.0.1:8100 by default (FL_HOST / FL_PORT)
```

`FL_REPO` tells the service where the rulebook working copy is; if it is unset the
service falls back to the old same-repo layout (`backend/` inside the rulebook).
The `mkdocs` binary used to build the book is taken from that working copy's own
`.venv` (`$FL_REPO/.venv/bin/mkdocs`) — this repo's venv only needs the FastAPI stack.

As a user service:

```bash
systemctl --user enable --now fredlobster-backend
systemctl --user status fredlobster-backend
curl -s http://127.0.0.1:8100/api/status
```

To expose it to the tailnet later, set `FL_HOST` to the Tailscale address
(`tailscale ip -4`) — never `0.0.0.0`.

## Notes / deliberate choices

- Section metadata (id, title, last-published version) is derived from `mkdocs.yml`
  nav plus the footer version rather than YAML front matter in the rule files: front
  matter without the `meta` extension would render as page text, and with it would
  leak into the include-markdown combined pages.
- `site/` is tracked in git upstream, so `mkdocs build` dirties it. The cleanliness
  check only looks at `docs/`, `mkdocs.yml` and `requirements.txt`, so builds don't
  block a publish.
- `publish` refuses to run when those published sources already have uncommitted
  changes, so the publish is always exactly one clean commit (and `rollback` can
  revert only that commit).
