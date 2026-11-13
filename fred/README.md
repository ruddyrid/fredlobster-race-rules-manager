# `fred` — terminal client for the rulebook backend

A small terminal GUI for working on the rules. It talks **only** to the backend
HTTP API and never edits rule files directly. Python standard library only — no
dependencies.

The backend binds either `http://127.0.0.1:8100` or the OptiPlex's Tailscale
address `http://100.108.5.126:8100` depending on `FL_HOST`; `fred` tries both
(override with `FRED_API`).

## Getting `fred` on your PATH

Nothing is installed system-wide. A new terminal already has `~/.local/bin` on
`PATH`, so one user-local link is enough to run `fred` from `~/` or anywhere
else:

```bash
ln -sfn ~/fredlobster-race-rules-manager/fred/fred ~/.local/bin/fred
cd ~
fred status
```

The launcher follows that symlink back to `fred.py`. Without the link, call it
by path (`./fred/fred status` from the repo) or `export PATH="$PWD/fred:$PATH"`
for the current shell only.

The launcher uses the project venv's Python when it exists, otherwise `python3`.

## Commands

All commands print a plain-language error and exit non-zero on failure — no stack
traces. Set `FRED_DEBUG=1` if you ever want the traceback.

| Command | What it does |
|---|---|
| `fred status` | Published version, open drafts, and git state (clean/uncommitted, in sync with `origin/main`) |
| `fred sections` | Section list with titles and file paths, in `mkdocs.yml` nav order |
| `fred show <section>` | Open that section's Markdown in `glow`; plain text when piped (or `--plain`) |
| `fred edit <section>` | Open the section in `$EDITOR` as a **draft**; saved via the backend, never into `docs/` |
| `fred diff` | Draft vs published, line by line |
| `fred publish` | Run the backend pipeline: validate → bump → build → one commit → push → verify live |
| `fred rollback` | `git revert` the last publish commit, rebuild, redeploy |
| `fred tmux` | Build the Herdr three-pane layout (editor, log, numbered overview menu). Outside Herdr it prints the plan. `--dry-run` shows the plan without touching panes |

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

Agents: the latest working setup (user-local `fred` link, reuse existing panes,
Herdr not tmux) is `init/fred-tmux.md`. Follow that file instead of improvising.

Run `fred tmux` in the pane you want as the editor. It builds three panes and
never more:

```text
+------------------+------------------+
| editor           | overview         |
| (you type here)  | numbered fred    |
+------------------+ menu             |
| log              |                  |
+------------------+------------------+
```

- **editor** (left, top) — where you run `fred edit <section>` and `fred publish`.
- **log** (left, bottom) — `journalctl --user -u fredlobster-backend -f`.
- **overview** (right, full height) — the fred menu. Type a number, no commands
  to remember:

| Key | Action |
|---|---|
| `1` | Status (version, drafts, git, site) |
| `2` | List sections |
| `3` | Read a section in `glow` (pick by number or name) |
| `4` | Edit a section as a draft (`$EDITOR` opens in this pane) |
| `5` | Review drafts (diff) |
| `6` | Publish drafts (asks you to type `yes`) |
| `7` | Roll back the last publish (asks you to type `yes`) |
| `8` | Workspaces: switch, **new rules directory** (`n`), copy (`c`), add (`a`), remove (`r`) |
| `q` | Quit the menu (the pane returns to a shell) |

Rebuilding is safe. If the tab already has the three-pane geometry (editor
top-left, log directly below it, overview full height on the right, nothing
else), those panes are reused whatever their labels. If the tab has other panes,
`fred tmux` refuses to split and asks for a tab with only the editor pane, so it
never leaves more than three fred panes. Splits start in the directory you ran
`fred tmux` from. A leftover `workspace` pane from the earlier four-pane layout is
ignored; close it by hand if you do not want it.

`fred tmux --dry-run` prints the plan (panes that would be created and the
command each runs) and changes nothing.

## Notes

- Backend must be running: `systemctl --user status fredlobster-backend`.
- `fred publish` waits for GitHub Pages to serve the new version (up to ~5 min), then
  reports the commit and live link; it does not return early.
- `fred publish` refuses to run if `docs/`, `mkdocs.yml` or `requirements.txt` have
  uncommitted changes — that keeps each publish exactly one revertible commit.
