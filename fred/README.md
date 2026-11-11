# `fred` — terminal client for the rulebook backend

A small terminal GUI for working on the rules. It talks **only** to the backend
HTTP API and never edits rule files directly. Python standard library only — no
dependencies.

The backend binds either `http://127.0.0.1:8100` or the OptiPlex's Tailscale
address `http://100.108.5.126:8100` depending on `FL_HOST`; `fred` tries both
(override with `FRED_API`).

## Getting `fred` on your PATH

Nothing is installed system-wide. Pick one:

```bash
cd ~/fredlobster-race-rules-manager

# a) put this folder on PATH for the current shell
export PATH="$PWD/fred:$PATH"

# b) or a user-local symlink (optional)
ln -s "$PWD/fred/fred" ~/.local/bin/fred

# c) or just call it by path
./fred/fred status
```

The launcher uses the project venv's Python when it exists, otherwise `python3`.

## Commands

All commands print a plain-language error and exit non-zero on failure — no stack
traces. Set `FRED_DEBUG=1` if you ever want the traceback.

| Command | What it does |
|---|---|
| `fred status` | Published version, open drafts, and git state (clean/uncommitted, in sync with `origin/main`) |
| `fred sections` | Section list with titles and file paths, in `mkdocs.yml` nav order |
| `fred show <section>` | Print that section's Markdown |
| `fred edit <section>` | Open the section in `$EDITOR` as a **draft**; saved via the backend, never into `docs/` |
| `fred diff` | Draft vs published, line by line |
| `fred publish` | Run the backend pipeline: validate → bump → build → one commit → push → verify live |
| `fred rollback` | `git revert` the last publish commit, rebuild, redeploy |

`<section>` accepts the id (`rules-safety`), the path (`rules/safety.md`), the path
without extension (`rules/safety`), or the title (`Safety`).

### Examples

```bash
fred status
fred sections
fred show quick-reference
fred edit rules-technical          # opens $EDITOR; saving creates a draft
fred diff                          # review exactly what publish would change
fred publish                       # prints version, commit SHA, live link
fred rollback                      # undo the last publish on the live site
```

A draft is backend-only (`backend/drafts/`, gitignored). The public site cannot see
it until you publish. Rollback restores the previous published version as a clean
`git revert` commit.

## herdr three-pane working layout

A comfortable layout: **overview** pane, **editor** pane, and a **backend log** pane.
Pane IDs are dynamic, so nothing below hardcodes them.

From `~/fredlobster-race-rules-manager`, in the pane you want as the editor:

```bash
# add a pane to the right (becomes the overview) and one below (becomes the log)
herdr pane split --current --direction right --cwd "$PWD" --no-focus
herdr pane split --current --direction down  --cwd "$PWD" --no-focus
```

`--no-focus` keeps you in the editor pane; both splits come off the same pane, so
you get: editor on the left (top), log bottom-left, overview on the right. Mirror it
by swapping `right` for `left` if you prefer the overview on the left.

Then start each command in its pane — either click into it, or drive it from the
editor pane (needs `jq`):

```bash
herdr pane list                      # show pane ids
herdr pane run <overview-id> sh -c 'cd ~/fredlobster-race-rules-manager && fred status'
herdr pane run <log-id> journalctl --user -u fredlobster-backend -f
```

Day-to-day in the panes:

- **overview** — `fred status`, `fred sections`, `fred diff`
- **editor** — `fred edit <section>` (drafts), then `fred publish` when happy
- **log** — `journalctl --user -u fredlobster-backend -f` (every API call the backend handles)

## Notes

- Backend must be running: `systemctl --user status fredlobster-backend`.
- `fred publish` waits for GitHub Pages to serve the new version (up to ~5 min), then
  reports the commit and live link; it does not return early.
- `fred publish` refuses to run if `docs/`, `mkdocs.yml` or `requirements.txt` have
  uncommitted changes — that keeps each publish exactly one revertible commit.
