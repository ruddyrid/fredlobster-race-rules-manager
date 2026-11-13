# Changelog

All notable changes to this tooling repo are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 2026-11-13 — follow-up

### Added

- GitHub Pages for the manager repo is live (serving `main` root): site index [README.md](https://ruddyrid.github.io/fredlobster-race-rules-manager/README.md), public demo at https://ruddyrid.github.io/fredlobster-race-rules-manager/demo/, and quick starts under `/docs/*.md`. Verified by QA: demo and both guide links return 200 and the demo's relative guide links resolve.
- `.nojekyll` so Pages serves the repo as static files; without it the legacy Jekyll build stalled. Site root `/` intentionally has no index page (the demo and docs are the entry points).

### Changed

- README's "public demo" link now resolves — no longer dead pending activation.

## 2026-11-13

### Added

- `docs/admin-gui-quickstart.md` — tailnet-only admin GUI: controls, workflow, and safety (with QA wording corrections).
- `docs/fred-tmux-quickstart.md` — fred terminal: Herdr three-pane layout, keys, numbered tasks, and safety.
- `demo/index.html` — self-contained demo: fake data, working in-memory controls, and links to the guides.

### Changed

- README: wired live and demo links plus the quick-start guide links. The intended GitHub Pages link is in place, but Pages activation is pending approval.

*Verified: Reviewer passed final wording and diff checks. QA read-only checks passed on the live GUI and `fred tmux --dry-run`, and on demo controls, memory-only state, zero-network behavior, and relative links; manager Pages deliberately NOT VERIFIED pending approval.*
