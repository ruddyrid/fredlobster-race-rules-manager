# Fred Lobster Race Rules 2027 — Operator Notes

One page. Everything you need to run the rulebook day to day.

## Where things live

| Thing | Where |
|---|---|
| The rulebook (the real copy) | `~/fredlobster-race-rules-2027` — the Markdown in `docs/` is the single source of truth |
| GitHub repo (rules) | https://github.com/ruddyrid/fredlobster-race-rules-2027 (`main` = source, `gh-pages` = the built site) |
| Public site | https://ruddyrid.github.io/fredlobster-race-rules-2027/ — read-only |
| Management tooling | `~/fredlobster-race-rules-manager` — backend, `fred`, admin GUI, these notes, prompts (https://github.com/ruddyrid/fredlobster-race-rules-manager) |
| Backend service | `fredlobster-backend` (user service, port 8100, binds the Tailscale IP `100.108.5.126`, runs from `~/fredlobster-race-rules-manager`) |
| `fred` (terminal) | `fred` from any directory, including `~/`. Link: `~/.local/bin/fred` → `~/fredlobster-race-rules-manager/fred/fred` |
| Admin GUI | http://100.108.5.126:8100/ui/ — tailnet only |
| Prompt runbook | `prompts/` in the manager repo; the plan itself lives in the Muse space |

The backend is told where the rulebook is by `FL_REPO` in
`~/.config/systemd/user/fredlobster-backend.service` (currently
`/home/ruddyrid/fredlobster-race-rules-2027`). The old 2026 clone at `~/race-rulebook`
is a spare copy of the previous season — never edit it.

## Publishing a rule change

1. **Draft it.** `fred edit rules-safety` (or pick a section in the admin GUI). A draft
   is held by the backend only. The public site cannot see it yet.
2. **Look at it.** `fred diff` (or the GUI's Diff tab) shows exactly what will change,
   line by line.
3. **Publish it.** `fred publish` (or the Publish button). One command does the whole job:
   checks the book builds and no links are broken → bumps the version (`v1.0` → `v1.1`) →
   stamps that version and the date into the footer of every page → adds a changelog entry
   → makes **one** git commit → pushes to GitHub → waits until the live site shows the new
   version.

If any check fails, nothing is committed or published — the publish stops and tells you
why in plain language.

## Rolling back

`fred rollback` (or the Rollback button) undoes the most recent publish with a clean
`git revert` commit, rebuilds, redeploys, and waits for the live site to show the older
version again.

Check afterwards:

- footer on the live site shows the expected version (e.g. `v1.0`),
- `fred status` says `working clean` and `in sync with origin/main`.

## Reaching the admin GUI

Open http://100.108.5.126:8100/ui/ from a device on your Tailscale network. There is **no
login** — the tailnet itself is the access control, so do not expose port 8100 to the
internet, do not use Tailscale Funnel, and do not forward it on the router.

The backend's address is set by `FL_HOST` in
`~/.config/systemd/user/fredlobster-backend.service`. It is currently the Tailscale IP.
To make it reachable only on this machine again, change it to `127.0.0.1` and run
`systemctl --user daemon-reload && systemctl --user restart fredlobster-backend`.
(`fred` tries both addresses, so it keeps working either way.)

## If something seems broken

```bash
systemctl --user status fredlobster-backend     # is the backend up?
journalctl --user -u fredlobster-backend -f     # watch what it is doing
fred status                                     # version, drafts, git state
curl -s http://100.108.5.126:8100/api/status    # raw check
```

A broken backend does not affect the public site — the site is static on GitHub Pages.

## End of season (freeze procedure — do not do this until the season is over)

Decision 4: one working copy per season, archived read-only at season's end, and the next
season starts from a fresh copy.

1. Publish any last change, then confirm `fred status` is clean and in sync.
2. Archive the working copy: copy it somewhere read-only (or `chmod -R a-w` it), and tag
   the season's final state in git (`git tag 2027-final && git push origin 2027-final`).
3. Stop the backend if the season is truly finished: `systemctl --user stop fredlobster-backend`.
4. Start the next season from a fresh clone of the repo into a new directory; bump the
   year in the title, footer and changelog; never reuse the archived copy.

Do not freeze or archive anything now — the 2027 season has not happened yet.
