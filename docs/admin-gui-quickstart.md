# Admin GUI quickstart

The admin GUI is the browser console for the Fred Lobster rulebook: it edits,
diffs, publishes and rolls back the rule Markdown through the backend API. It is
plain HTML/CSS/JS (`backend/static/`) served by the backend itself — no
framework, no separate deploy. See the [demo](../demo/) for an interactive
sample of the GUI.

## Reaching it (tailnet only)

Open **http://100.108.5.126:8100/ui/** from a device on your Tailscale network
(the backend binds the OptiPlex's tailnet address via `FL_HOST`, port 8100).

There is **no login**: the tailnet itself is the access control. The GUI is
**never public** — do not expose port 8100 to the internet, do not use Tailscale
Funnel, and do not forward the port on the router. The deployed service binds
**only** the tailnet address above: there is no public URL for the GUI, and a
device off the tailnet cannot reach it at all.

## The page

The top strip is the live status bar (`/api/status`): workspace, version, draft
count, git state (`working tree clean` / `uncommitted changes`, in sync with
`origin/main` or ahead/behind), branch @ commit, and a link to the public site.
Read it before and after every action.

Header buttons, left to right:

| Control | What it does |
|---|---|
| **Workspaces** | Opens the workspaces modal (see below). |
| **☀ Light / 🌙 Dark** | Toggles the theme; your choice is remembered in the browser (`localStorage`), dark is the default. |
| **Publish to live site** | Disabled while there are no drafts. Asks for confirmation, then runs the whole publish pipeline and switches to the Result tab (see below). |
| **Rollback last publish** | Asks for confirmation, then `git revert`s the most recent publish commit, rebuilds, redeploys and waits for the live site. Refuses if the last commit isn't a publish or the working tree has uncommitted changes. |

**Sections** (left sidebar) lists every rule section from the active
workspace's nav, each with its bare path (e.g. `rules/safety.md`); the editor
header shows the full file location prefixed with `docs/`. Search/filter the
list, select multiple sections to copy or archive them, or select a section and
use the up/down arrows to adjust navigation order. **Add section** creates a
new page draft; copying an existing section gives it a new title and path.
A `●` dot marks sections that have a saved content draft. Clicking a section
loads its Markdown into the editor; if you have unsaved edits the GUI asks
before discarding them.

The **Archived sections** disclosure lists pages removed from navigation.
Restore returns an archived page to its original group when possible. A
separate **Delete permanently** action requires confirmation and is irreversible
after publishing. Add, copy, reorder, archive, restore, and permanent deletion
are all structural drafts: the rulebook working copy and public site remain
unchanged until you explicitly publish. Archived pages are preserved outside
`docs/` in the rulebook repository, so they are not built into the public site.

The main panel has three tabs:

- **Editor** — the raw Markdown of the selected section. Typing shows
  "unsaved edits — click Save draft". **Save draft** stores it on the backend
  only (`backend/drafts/`, per workspace); the public site cannot see it yet.
  A yellow DRAFT banner reminds you of this, and an empty draft is refused.
- **Diff** — structural draft summaries plus unified diffs of content drafts
  against the published files, line-by-line and colour-coded. **Refresh**
  re-fetches it. Nothing is live until you publish.
- **Result** — the step log of the last publish or rollback: `[ok]/[FAIL]`
  lines for validate → stage → build → commit → push → live, then the resulting
  version, commit hash and live URL (cache-busted). Failures show the plain-
  language reason here.

The **Workspaces** modal manages the rule directories the backend can operate
on:

- *Current workspace* — title, path, version, branch @ head, draft count,
  clean/dirty state, and links to its site and repo.
- *Switch workspace* — pick a known one, or *Add & switch* with a path to an
  existing rules directory (must contain `docs/` and `mkdocs.yml`). Switching
  clears the editor (confirming first if you had unsaved edits).
- *Create a new workspace* — a directory, from a blank template or a copy of an
  existing workspace, with title/year (year fills the title) and an optional
  GitHub repo URL; by default it initialises git, makes the first commit, and
  switches to the new workspace.
- *Remove from list* — hides a non-active directory from the list only; files
  are never deleted.

## The safe workflow: edit → diff → publish → verify → rollback

1. **Edit or manage sections.** Save Markdown drafts, or add/copy/reorder/
   archive/restore sections. These changes exist only as backend drafts; the
   live site is untouched.
2. **Diff.** Open the Diff tab and review both the structure summary and
   content changes — this is what will change.
3. **Publish.** Click **Publish to live site** and confirm. One run validates
   (all nav sections present, non-empty, `mkdocs build --strict` clean),
   applies the drafts, bumps the version (`v1.0` → `v1.1`), stamps it into
   every page footer, adds a changelog entry, makes **one** git commit, pushes
   to GitHub, and waits for the live site to show the new version. If any step
   fails, nothing is published and the reason appears in the Result tab.
4. **Verify.** Check the Result tab shows `live [ok]`, the status bar is back
   to `working tree clean` / `in sync with origin/main` with no drafts, and the
   public site footer shows the new version.
5. **Rollback** (if needed). **Rollback last publish** reverts the most recent
   publish commit the same way — rebuild, push, wait — and the footer shows the
   previous version again.

If a publish or rollback commit succeeds locally but its push or live-site check
fails, the GUI shows a pending retry in Diff and enables the matching action.
Confirming it retries the same commit; it does not create another publish or
rollback commit.

## Don'ts

- **Don't hand-edit `docs/` or `mkdocs.yml` in the working copy while the
  backend is running.** Publish refuses to run on a dirty tree to keep each
  publish one clean commit; an editor left open elsewhere is the usual cause of
  an "uncommitted changes" warning. All edits go through this GUI (or `fred`).
- **Don't run two admins at once in 2027.** A single admin is the settled
  decision for the season; the GUI has no locking between browsers, so two open
  sessions can overwrite each other's drafts.
- **Don't expose the GUI.** No port forwarding, no Funnel, no `FL_HOST=0.0.0.0`
  — there is no login behind the tailnet.
- **Don't publish or roll back casually.** Both push to `main` and redeploy the
  live site; check the Diff tab first, and check the status bar's git pills
  after.
- **Don't kill the backend to "reset" it.** Publish failures already leave the
  working copy untouched; check the Result tab and `journalctl --user -u
  fredlobster-backend -f` first.

## See also

- [demo](../demo/) — an interactive sample of the GUI.
- `OPERATOR-NOTES.md` (repo root) — day-to-day operations and troubleshooting.
- `backend/README.md` — the API and publish pipeline details.
