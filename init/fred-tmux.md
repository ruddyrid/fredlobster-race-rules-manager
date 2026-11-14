# Latest fred TMUX setup

This is the procedure OpenCode must follow to set up the fred terminal.
"fred TMUX" means this **Herdr** layout, not a `tmux` session. `TMUX` is unset
inside Herdr. Use `herdr`, not `tmux`.

Source of truth for the layout idea: `fred/README.md` ("herdr three-pane working
layout"). This file is the latest working version of that setup, including
corrections. If they disagree, follow this file.

## Quick Start Guide

To start working, launch the `opencode` LLM agent and prompt it:

```text
fred tmux
```

That opens the fred terminal for the FRedlobster Race Rules Manager: the editor
on the left, the backend log below it, and a numbered overview menu on the right.
Every common action, including creating a new rules directory, is a number in
that menu (see "The overview menu" below).

Do this when the user says **start**, asks to initialize the workspace, or asks
for help interfacing with **fred**, the **fred terminal**, **fred TMUX**, or the
**fred CLI**. Do not set up panes for an unrelated task. Do not edit rule files.
Do not publish or roll back unless the user asks.

## Preconditions

Work from either `~/fredlobster-race-rules-manager` or the rulebook working copy
`~/fredlobster-race-rules-2027`. `fred` and the backend are location-independent;
the pane you run `fred tmux` in becomes the editor pane, and both splits and the
log/overview panes start in that pane's `$PWD`. The menu acts on the backend's
active workspace, not on the directory, so `$PWD` only sets where new shells open.

```bash
test "${HERDR_ENV:-}" = 1
```

If that fails, say you are not running inside Herdr and stop. Do not inspect or
control the focused Herdr session from outside.

If the Herdr skill is not already in context, run `herdr --skill` and follow it
before any pane command. The installed `herdr` binary is the authority for
syntax. Do not probe a mutating command by omitting arguments.

The backend must be running:

```bash
systemctl --user status fredlobster-backend
```

If it is inactive, start it (`systemctl --user start fredlobster-backend`) and
recheck. Do not restart a backend that is already active.

## `fred` on PATH

A new terminal can run `fred` from `~/` because `~/.local/bin` is already on
`PATH`. Keep this link in place (the launcher follows it back to `fred.py`):

```bash
ln -sfn "$HOME/fredlobster-race-rules-manager/fred/fred" "$HOME/.local/bin/fred"
```

Do not replace that link with a copy of the script. If `command -v fred` fails
in a pane, fall back to:

```bash
export PATH="$HOME/fredlobster-race-rules-manager/fred:$PATH"
```

The launcher uses `$root/.venv/bin/python` when that exists, otherwise `python3`.

`fred` talks only to the backend HTTP API (`127.0.0.1:8100` or
`100.108.5.126:8100`, override with `FRED_API`). It never edits `docs/`.

## Layout

Three panes, IDs dynamic. Never hardcode pane IDs. Read them from JSON. Never
create more than three panes.

Desired geometry, with the **editor** as the calling pane:

- **editor** — left, top (the caller). Day-to-day: `fred edit <section>`, then
  `fred publish` only when the user asks.
- **log** — directly below the editor. `journalctl --user -u fredlobster-backend -f`
- **overview** — to the right, full height. The fred numbered menu (`fred tmux`
  run with `FRED_TMUX_PANE=hub`).

```text
+------------------+------------------+
| editor           | overview         |
|                  |                  |
+------------------+ (fred menu)      |
| log              |                  |
+------------------+------------------+
```

1. Discover live state. Do not trust an example ID from an older session.

   ```bash
   herdr pane current --current
   herdr pane layout --pane "$HERDR_PANE_ID"
   herdr pane list --workspace "$HERDR_WORKSPACE_ID"
   ```

2. If this tab already has that geometry (caller top-left, one pane below it,
   one pane to the right spanning the column height, and no other panes), **reuse
   those panes**, whatever their labels. Do not split again. Do not close panes you
   did not create. A leftover `workspace` pane from the old four-pane layout is not
   part of this setup; leave it and tell the user it can be closed.

   If the tab has other panes but not that geometry, do **not** split and do not
   reuse panes by label. Stop and ask the user to run it from a tab where the
   editor pane is the only pane, or from a tab already arranged as the three-pane
   layout. Never leave the tab with more than three fred panes.

3. Only when the caller is the sole pane in the tab, split from the editor pane.
   `--no-focus` keeps focus on the editor. Both splits come off the same pane.
   Read each new id from `.result.pane.pane_id`.

   ```bash
   herdr pane split --current --direction right --cwd "$PWD" --no-focus
   herdr pane split --current --direction down  --cwd "$PWD" --no-focus
   ```

   Swap `right` for `left` only if the user wants the overview on the left.

4. Label them (display only): `herdr pane rename <id> editor|overview|log`.

Shortcut: `fred tmux --dry-run` prints the same plan without changing anything;
plain `fred tmux` (run in the editor pane) performs steps 1–4 and the start
commands below, with the same geometry check and the same refusal when the tab
has other panes.

## Start the panes

Run a command only in an idle shell: bash itself in the foreground, at a prompt,
no editor, agent, or `journalctl` already running. Check with
`herdr pane process-info --pane <id>` and `herdr pane read`.

Overview (the menu):

```bash
herdr pane run <overview-id> 'FRED_TMUX_PANE=hub "$HOME/.local/bin/fred" tmux'
```

If that pane cannot see `fred`, the `~/.local/bin` link is missing. Create it,
then rerun. Do not start a second menu if the pane already shows one.

Log — leave this running:

```bash
herdr pane run <log-id> journalctl --user -u fredlobster-backend -f
```

Skip this if that pane is already following the unit.

Editor — do not open `$EDITOR` during setup. `fred edit` waits for a section
the user names (`rules-safety`, `rules/safety.md`, `rules/safety`, or `Safety`).

## The overview menu

The overview pane shows the workspace, version, drafts and git state, then:

| Key | Action |
|---|---|
| `1` | Status |
| `2` | List sections |
| `3` | Read a section in `glow` (`q` quits glow) |
| `4` | Edit a section as a draft (`$EDITOR` in the overview pane) |
| `5` | Review drafts (diff) |
| `6` | Publish drafts — only when the user asks; needs `yes` |
| `7` | Roll back the last publish — only when the user asks; needs `yes` |
| `8` | Workspaces: switch, new rules directory (`n`), copy (`c`), add (`a`), remove (`r`) |
| `9` | Section management: add, copy, reorder, archive, restore, permanently delete |
| `10` | Recover interrupted publish staging — requires typing `RESTORE` |
| `q` | Quit the menu |

Section management lists active and archived sections. Add/copy ask for a title
and path under `docs/`; archive, restore, and permanent delete require
confirmation, and deletion is limited to archived sections. Structural changes
are backend-only drafts until an explicitly requested publish. Permanent deletion
cannot be undone after publish. The existing publish (`6`) and rollback (`7`)
confirmations remain in place.

Recovery (`10`) is only offered when a previous publish stopped during staging.
It restores the saved pre-publish working-copy files and preserves backend drafts;
the user must type `RESTORE`.

Setup never presses `6` or `7`.

## Verify

```bash
herdr pane layout --pane "$HERDR_PANE_ID"
herdr pane read <overview-id> --source recent-unwrapped --lines 40
herdr pane read <log-id> --source recent-unwrapped --lines 30
```

Expect the overview to show the menu header (workspace, version, drafts, git)
with items 1–10 and q, and the log to show `fredlobster-backend` journal lines.
Focus stays on the editor pane. Only three panes exist in the tab.

## Do not

- Hardcode pane, tab, or workspace IDs. Closed IDs are not reused.
- Close workspaces, tabs, or panes you did not create.
- Run `herdr server stop`, or kill Herdr.
- Edit `docs/`, `mkdocs.yml`, or the rulebook working copy
  (`~/fredlobster-race-rules-2027`) from this setup.
- Run `fred publish` or `fred rollback` as part of setup.
- Copy `fred` into `~/.local/bin`. A symlink to `fred/fred` is the install.
