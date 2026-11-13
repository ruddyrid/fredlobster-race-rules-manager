# `fred tmux` quickstart — the Herdr working layout

`fred tmux` is the **Herdr** three-pane working layout for the Fred Lobster race
rules. The name is historical: it has nothing to do with `tmux` (inside Herdr
`TMUX` is unset). It is the terminal front door to the **same backend HTTP API
and publish pipeline the admin GUI uses** — see the [demo](../demo/) for that
flow. `fred` and the GUI never edit rule files and never talk to each other;
only the backend writes `docs/`, commits, and pushes.

> **Never publish, roll back, or create/switch workspaces without admin
> approval.** Actions 6 and 7 below change the live site.

## Preconditions

```bash
systemctl --user status fredlobster-backend   # must be active (port 8100)
command -v fred                               # ~/.local/bin/fred symlink
test "${HERDR_ENV:-}" = 1 && echo inside Herdr
```

`fred` tries `http://127.0.0.1:8100`, then `http://100.108.5.126:8100`
(override with `FRED_API`). If `fred` is not on PATH:
`ln -sfn ~/fredlobster-race-rules-manager/fred/fred ~/.local/bin/fred`.

## The three panes

Run `fred tmux` in the pane you want as the editor; it builds exactly three
panes and never more:

```text
+------------------+------------------+
| editor           | overview         |
| (you type here)  | numbered fred    |
+------------------+ menu             |
| log              |                  |
+------------------+------------------+
```

| Pane | Position | Process it starts |
|---|---|---|
| editor | left, top (the caller, focus stays here) | your shell — run `fred edit <section>`, `fred publish` |
| log | directly below editor | `journalctl --user -u fredlobster-backend -f` |
| overview | right, full height | `FRED_TMUX_PANE=hub fred tmux` — the numbered menu |

## Build the layout

1. Inside Herdr, in a tab where the editor pane is the **only** pane, run:
   ```bash
   fred tmux
   ```
2. `fred tmux` prints its plan header (`fred tmux — Herdr working layout`,
   manager dir, cwd), labels the caller `editor`, splits `overview` right and
   `log` down (both start in the directory you ran it from), starts the two
   commands above, and finishes with:
   `Layout ready. In the overview pane (right), type a number to act.`
3. Rebuild safety:
   - If the tab **already has this geometry**, the existing panes are reused
     whatever their labels; a pane whose command is already running prints
     `already running — left alone`, a busy one prints `busy (…) — left alone`.
   - If the tab has **other panes**, it refuses and asks for a tab where the
     editor pane is the only one — it never leaves more than three fred panes.
   - Outside Herdr it prints `You are not inside Herdr (HERDR_ENV != 1).` and
     the layout it would create; nothing changes.
4. To preview without touching anything:
   ```bash
   fred tmux --dry-run   # prints the plan, then: dry run — nothing was changed
   ```

## Navigation

Herdr's default keys (Herdr 0.9.1, from `herdr --default-config`; a local
Herdr config may customize them) — all start with the prefix **Ctrl+B**, then
the key:

| Keys | What it does |
|---|---|
| `Ctrl+B` `h` / `j` / `k` / `l` | focus pane left / down / up / right |
| `Ctrl+B` `n` / `p` | next / previous tab |
| `Ctrl+B` `Shift+X` | close the focused pane |

`fred tmux` leaves focus on the editor pane; use the keys above to reach the
overview (right) or log (below).
- **Overview menu**: type a key below and press Enter. The screen redraws each
  loop with the header (workspace title, version, draft count, working-copy
  clean/`UNCOMMITTED changes`, branch) and prompt `fred>`. After most actions it
  waits for `press Enter to return to the menu…`.
- **glow** (action 3): scroll normally, quit with `q`.
- **$EDITOR** (action 4): save and quit as usual — saving posts the draft to
  the backend; nothing lands in `docs/` until publish.

## The numbered actions (overview pane)

| Key | Action | What the code does |
|---|---|---|
| `1` | Status | Same output as `fred status` (site, workspace, version, drafts, git branch/head, sync state) |
| `2` | List sections | Same as `fred sections` (nav order, titles, ids) |
| `3` | Read a section (glow) | Picks by number or name (`blank cancels`), then `fred show` |
| `4` | Edit a section (draft) | Pick as above, opens `$EDITOR` in this pane; save = backend draft |
| `5` | Review drafts (diff) | Same as `fred diff` — draft vs published, line by line |
| `6` | Publish drafts | Confirmation `Publish all drafts to the live site? Type yes to continue` (`yes`/`y`; anything else prints `publish cancelled`) |
| `7` | Roll back the last publish | Confirmation `Roll back the last publish on the live site? Type yes to continue`; cancel prints `rollback cancelled` |
| `8` | Workspaces | Opens the workspace submenu (see below); returns without a pause |
| `q` | Quit this pane | Menu exits; the overview pane returns to its shell |

### Publish (6) — only with admin approval

Runs the backend pipeline over HTTP — validate → version bump → build → one
commit → push → verify the live site (waits up to ~7 min; it does not return
early). Publish refuses if `docs/`, `mkdocs.yml` or `requirements.txt` have
uncommitted changes, keeping every publish one revertible commit. Output is one
`[ok]`/`[FAIL]` line per step, then:

```text
published <old> -> <new>
  commit  <sha>
  live    <site URL>
```

### Roll back (7) — only with admin approval

`git revert`s the last publish commit, rebuilds, and redeploys; prints the per
steps plus `rolled back to <version> (commit <sha>)`.

## Workspaces: switch and create a rules directory (8)

The submenu header lists every workspace (`*` marks active) with version and
directory, and the line:
`[number] switch   n new   c copy   a add existing   r remove   l refresh   q quit`
at the `workspace>` prompt.

1. **Switch**: type the row number (blank cancels) — `fred workspace use` on
   that entry; prints `active workspace: <title> (…)`.
2. **New rules directory**: press `n` (blank template) — answer the prompts:
   `directory` (a suggestion is offered), `year` (2000–2100), `title`,
   `GitHub repo URL (optional)`, `initialize git? [Y/n]`. The backend creates
   the directory from the template, optionally inits git, and **switches the
   active workspace to it** (`active workspace switched to the new directory`).
3. **Copy**: press `c` — same as `n` plus a `copy from` prompt (defaults to the
   active workspace).
4. **Add existing**: press `a` — give the path of a rules directory that has
   `docs/` + `mkdocs.yml`; it becomes active.
5. **Remove from list**: press `r` — pick a number (the active workspace is
   not offered); files are not deleted.
6. **Quit**: `q` returns to the main menu.

Equivalent CLI (editor pane): `fred workspace [list|use|add|create|forget]`.

## Clean exit

- Overview: type `q` at `fred>` → pane is just a shell again (Ctrl+C also works).
- Log: Ctrl+C stops `journalctl -f` — leaving it following is fine.
- Editor: your shell; close it with `Ctrl+B` `Shift+X` (close focused pane) or
  close the Herdr tab. `fred tmux` itself never closes panes, and setup never
  presses `6` or `7`.

## Same backend, same pipeline, GUI included

Every action above calls the backend's `/api/*` — the exact endpoints behind
the admin GUI at `http://100.108.5.126:8100/ui/` (tailnet-only). Drafts are
backend-only (`backend/drafts/`, gitignored) until published, whichever client
you use. See the [demo](../demo/) and `fred/README.md` / `init/fred-tmux.md`
for the full layout procedure.
