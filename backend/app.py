"""Fred Lobster Race Rules — backend core.

Thin FastAPI service that is the single writer for the rule Markdown files.
No database: the Markdown files and git are the storage.

Endpoints:
    GET  /api/status                 active workspace version, drafts, sync state
    GET  /api/sections               section list + contents (nav order from mkdocs.yml)
    PUT  /api/draft/{section}        save a draft edit (backend-only, never in docs/)
    GET  /api/diff                   draft vs published, unified diff per section
    POST /api/publish                validate -> bump -> build -> commit -> push -> verify live
    POST /api/rollback               git-revert the last publish, rebuild, redeploy
    GET  /api/workspaces             known rules workspaces + active one
    POST /api/workspaces/select      switch to (or add) a rules workspace
    POST /api/workspaces/create      create a rules workspace from blank/copy
    POST /api/workspaces/forget      remove a workspace from the list (files untouched)

The service binds to localhost/tailnet only (see the systemd unit). It never serves
the public site; the public site is the static MkDocs output on GitHub Pages.
"""

from __future__ import annotations

import base64
import copy
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from functools import wraps
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictInt

MANAGER_ROOT = Path(__file__).resolve().parent.parent
BACKEND = Path(__file__).resolve().parent
DRAFTS = BACKEND / "drafts"
STATE_FILE = Path(os.environ.get("FL_STATE") or BACKEND / "workspaces.json")
TEMPLATE_DIR = MANAGER_ROOT / "templates" / "blank"
HOME = Path.home().resolve()
DEFAULT_WORKSPACE = Path(
    os.environ.get("FL_REPO") or HOME / "fredlobster-race-rules-2027"
).expanduser()
LIVE_TIMEOUT = 300  # seconds to wait for GitHub Pages to serve a new version
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
STATE_LOCK = threading.Lock()
PUBLISH_LOCK = threading.Lock()

app = FastAPI(title="Fred Lobster Race Rules Manager — backend", docs_url=None, redoc_url=None)


def _serialized_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with PUBLISH_LOCK:
            return function(*args, **kwargs)
    return wrapped

STATIC_DIR = BACKEND / "static"
DEMO_FILE = MANAGER_ROOT / "demo" / "index.html"


@app.get("/ui/demo", include_in_schema=False)
@app.get("/ui/demo/", include_in_schema=False)
def ui_demo() -> FileResponse:
    """Read-only sample of the admin GUI: fake data, self-contained page, no /api
    calls. Registered before the /ui mount (which would swallow the path) so it
    rides the same tailnet-only binding without copying the file into static/."""
    if not DEMO_FILE.is_file():
        raise HTTPException(status_code=404, detail="demo/index.html is missing from the manager checkout")
    return FileResponse(DEMO_FILE, media_type="text/html")


if STATIC_DIR.is_dir():
    # Admin GUI: plain HTML/JS, talks to the same /api endpoints. Served from the
    # backend so it rides the same tailnet-only binding. No framework, no new deps.
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# --------------------------------------------------------------------------- workspace state


def _rules_root(path: Path) -> bool:
    """True when path looks like a rules working copy the backend can operate on."""
    return path.is_dir() and (path / "docs").is_dir() and (path / "mkdocs.yml").is_file()


def _discover_workspaces() -> list[Path]:
    """Top-level home directories that look like rulebook working copies."""
    found: list[Path] = []
    try:
        children = sorted(HOME.iterdir())
    except OSError:
        return found
    for child in children:
        if child.is_dir() and not child.is_symlink() and _rules_root(child):
            found.append(child.resolve())
    return found


def _read_state_file() -> dict:
    try:
        raw = json.loads(STATE_FILE.read_text())
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_state() -> dict:
    raw = _read_state_file()
    known: list[Path] = []

    def add(value) -> None:
        try:
            path = Path(str(value)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return
        if path not in known:
            known.append(path)

    for value in raw.get("known") or []:
        add(value)
    for path in _discover_workspaces():
        add(path)

    active: Path | None = None
    raw_active = str(raw.get("active") or "").strip()
    if raw_active:
        try:
            candidate = Path(raw_active).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            candidate = None
        if candidate is not None and _rules_root(candidate):
            active = candidate
    if active is None:
        for candidate in [DEFAULT_WORKSPACE, *known]:
            if _rules_root(candidate.resolve()):
                active = candidate.resolve()
                break
    if active is not None and active not in known:
        known.insert(0, active)

    return {
        "active": str(active) if active else "",
        "known": [str(path) for path in known],
    }


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n")
    temp.replace(STATE_FILE)


def _active_root() -> Path:
    state = _load_state()
    if not state["active"]:
        raise HTTPException(
            status_code=409,
            detail="no rules workspace is selected. Choose one in the Workspaces panel.",
        )
    path = Path(state["active"])
    if not _rules_root(path):
        raise HTTPException(
            status_code=409,
            detail=f"active workspace is not a rules directory: {path}",
        )
    return path


def _normalize_path(raw: str) -> Path:
    """Resolve a user-supplied path and keep it inside the user's home directory."""
    value = (raw or "").strip()
    if not value:
        raise HTTPException(status_code=422, detail="a directory path is required")
    if value in {".", ".."}:
        raise HTTPException(status_code=422, detail="choose a concrete directory path")
    try:
        path = Path(value).expanduser()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid path: {exc}") from None
    if not path.is_absolute():
        path = HOME / path
    try:
        path = path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid path: {exc}") from None
    if path != HOME and HOME not in path.parents:
        raise HTTPException(status_code=422, detail="the directory must be inside your home folder")
    if path == HOME:
        raise HTTPException(status_code=422, detail="choose a subdirectory, not your home folder")
    return path


def _suggested_workspace() -> dict:
    state = _load_state()
    year = date.today().year
    if state["active"]:
        match = re.search(r"(20\d\d)", Path(state["active"]).name)
        if match:
            year = int(match.group(1)) + 1
    return {
        "path": str(HOME / f"fredlobster-race-rules-{year}"),
        "title": f"Fred Lobster Race Rules {year}",
        "year": year,
    }


# --------------------------------------------------------------------------- generic helpers


def _git(*args: str, root: Path | None = None, timeout: int = 120,
         check: bool = True) -> subprocess.CompletedProcess:
    cwd = root or _active_root()
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        env=GIT_ENV, timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} failed")
    return proc


def _git_config(root: Path, *args: str) -> str:
    proc = _git(*args, root=root, check=False, timeout=20)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _config(root: Path | None = None) -> dict:
    path = (root or _active_root()) / "mkdocs.yml"
    try:
        return yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _site_name(root: Path | None = None) -> str:
    root = root or _active_root()
    return str(_config(root).get("site_name") or root.name)


def _copyright_value(root: Path | None = None) -> str:
    path = (root or _active_root()) / "mkdocs.yml"
    try:
        text = path.read_text()
    except OSError:
        return ""
    match = re.search(r'^copyright:\s*"(.*)"\s*$', text, re.M)
    return match.group(1) if match else ""


def _version(root: Path | None = None) -> str:
    match = re.search(r"v(\d+)\.(\d+)", _copyright_value(root))
    return f"v{match.group(1)}.{match.group(2)}" if match else "v0.0"


def _bump(version: str) -> str:
    match = re.match(r"v(\d+)\.(\d+)$", version)
    if not match:
        return "v1.0"
    return f"v{match.group(1)}.{int(match.group(2)) + 1}"


def _repo_url(root: Path | None = None) -> str:
    root = root or _active_root()
    value = str(_config(root).get("repo_url") or "").strip()
    if value:
        return value
    return _git_config(root, "remote", "get-url", "origin")


def _site_url(root: Path | None = None) -> str:
    """Derive the GitHub Pages URL for a workspace.

    Explicit site_url wins, then repo_url, then the git origin remote. Only
    GitHub Pages layouts are inferred; local-only workspaces return "".
    """
    root = root or _active_root()
    config = _config(root)
    explicit = str(config.get("site_url") or "").strip()
    if explicit:
        return explicit.rstrip("/") + "/"

    repo = _repo_url(root)
    match = re.match(
        r"(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$",
        repo,
    )
    if not match:
        return ""
    owner, name = match.group(1), match.group(2)
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


def _workspace_key(root: Path) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-") or "workspace"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _drafts_dir(root: Path | None = None, create: bool = True) -> Path:
    root = root or _active_root()
    path = DRAFTS / _workspace_key(root)
    if create:
        path.mkdir(parents=True, exist_ok=True)
        default_root = DEFAULT_WORKSPACE.resolve()
        legacy = sorted(DRAFTS.glob("*.md"))
        if root == default_root and legacy and not any(path.glob("*.md")):
            for file in legacy:
                shutil.move(str(file), path / file.name)
    return path


def _drafts(root: Path | None = None) -> dict[str, dict]:
    directory = _drafts_dir(root)
    found = {}
    for file in sorted(directory.glob("*.md")):
        found[file.stem] = {
            "section": file.stem,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(file.stat().st_mtime)),
            "bytes": file.stat().st_size,
        }
    return found


def _draft_file(sid: str, root: Path | None = None) -> Path:
    if not sid or sid in {".", ".."} or "/" in sid or "\\" in sid or "\x00" in sid:
        raise HTTPException(status_code=422, detail="section id is not a safe draft filename")
    directory = _drafts_dir(root).resolve()
    path = directory / f"{sid}.md"
    if path.is_symlink():
        raise HTTPException(status_code=409, detail="draft file cannot be a symlink")
    try:
        path.resolve().relative_to(directory)
    except ValueError:
        raise HTTPException(status_code=422, detail="draft path must stay inside the backend draft directory") from None
    return path


def _structure_file(root: Path | None = None) -> Path:
    return _drafts_dir(root) / "structure.json"


def _pending_publish_file(root: Path | None = None) -> Path:
    return _drafts_dir(root) / "publish-pending.json"


def _publish_transaction_file(root: Path | None = None) -> Path:
    return _drafts_dir(root) / "publish-transaction.json"


def _ensure_no_pending_operation(root: Path) -> None:
    pending = _read_json(_pending_publish_file(root), None)
    if isinstance(pending, dict):
        action = "rollback" if pending.get("action") == "rollback" else "publish"
        raise HTTPException(status_code=409, detail=f"a {action} retry is pending; finish it before changing drafts")


def _recovery_required(root: Path, pending: dict | None) -> bool:
    if not _publish_transaction_file(root).is_file():
        return False
    if not isinstance(pending, dict):
        return True
    if pending.get("action") == "publish" and not pending.get("commit") and pending.get("parent"):
        head = _git("rev-parse", "HEAD", root=root, check=False).stdout.strip()
        return head == pending["parent"]
    return False


def _archive_file(root: Path | None = None) -> Path:
    workspace = (root or _active_root()).resolve()
    archive_dir = workspace / ".fred-archive"
    if archive_dir.is_symlink() or (archive_dir / "index.json").is_symlink():
        raise HTTPException(status_code=409, detail="archive storage cannot be a symlink")
    return archive_dir / "index.json"


def _read_json(path: Path, fallback):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _published_nav(root: Path | None = None):
    nav = _config(root).get("nav") or []
    return copy.deepcopy(nav) if isinstance(nav, list) else []


def _nav_leaves(nav, groups: list[str] | None = None) -> list[dict]:
    """Flatten MkDocs navigation leaves without losing their group context."""
    groups = groups or []
    out: list[dict] = []
    if isinstance(nav, list):
        for index, item in enumerate(nav):
            if isinstance(item, dict):
                for title, value in item.items():
                    if isinstance(value, str) and value.endswith(".md"):
                        out.append({"id": _section_id(value), "title": str(title), "path": value,
                                    "groups": groups[:], "index": index})
                    else:
                        out.extend(_nav_leaves(value, groups + [str(title)]))
    return out


def _load_structure(root: Path | None = None) -> dict | None:
    raw = _read_json(_structure_file(root), None)
    if not isinstance(raw, dict) or not isinstance(raw.get("nav"), list):
        return None
    archived = raw.get("archived")
    deleted = raw.get("deleted")
    return {
        "nav": raw["nav"],
        "archived": archived if isinstance(archived, list) else [],
        "deleted": deleted if isinstance(deleted, list) else [],
    }


def _load_archived(root: Path | None = None) -> list[dict]:
    raw = _read_json(_archive_file(root), [])
    if not isinstance(raw, list):
        return []
    archived = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id") or not item.get("path"):
            continue
        path = _safe_section_path(root or _active_root(), str(item["path"]))
        if _section_id(path) != item["id"]:
            raise HTTPException(status_code=409, detail="archive index has an id/path mismatch")
        archived.append(item)
    return archived


def _effective_nav(root: Path | None = None):
    draft = _load_structure(root)
    return copy.deepcopy(draft["nav"] if draft else _published_nav(root))


def _effective_archived(root: Path | None = None) -> list[dict]:
    draft = _load_structure(root)
    return copy.deepcopy(draft["archived"] if draft else _load_archived(root))


def _structure_changed(root: Path | None = None) -> bool:
    draft = _load_structure(root)
    if not draft:
        return False
    return (draft["nav"] != _published_nav(root)
            or draft["archived"] != _load_archived(root)
            or bool(draft["deleted"]))


def _save_structure(root: Path, nav, archived: list[dict], deleted: list[dict] | None = None) -> None:
    value = {"nav": nav, "archived": archived, "deleted": deleted or []}
    if (nav == _published_nav(root) and archived == _load_archived(root) and not value["deleted"]):
        _structure_file(root).unlink(missing_ok=True)
    else:
        _write_json(_structure_file(root), value)


def _section_items(root: Path, nav) -> list[dict]:
    docs = root / "docs"
    out = []
    for leaf in _nav_leaves(nav):
        path = _safe_section_path(root, leaf["path"])
        file = docs / path
        out.append({**leaf, "file": str(file.relative_to(root)), "exists": file.is_file()})
    return out


def _section_content(root: Path, section: dict) -> str:
    path = _safe_section_path(root, section["path"])
    if _section_id(path) != section.get("id"):
        raise HTTPException(status_code=409, detail="section id does not match its Markdown path")
    draft = _draft_file(section["id"], root)
    file = root / "docs" / path
    if draft.is_file():
        target = draft
    elif file.is_file():
        target = file
    else:
        target = _archive_path(root, path)
    try:
        return target.read_text(encoding="utf-8")
    except OSError:
        return ""


def _section_source(root: Path, section_id: str) -> dict | None:
    for section in _section_items(root, _effective_nav(root)):
        if section["id"] == section_id:
            return section
    for section in _effective_archived(root):
        path = _safe_section_path(root, str(section.get("path") or ""))
        if _section_id(path) != section.get("id"):
            raise HTTPException(status_code=409, detail="archived section id does not match its Markdown path")
        if section["id"] == section_id:
            return {**section, "path": path}
    return None


def _safe_section_path(root: Path, value: str) -> str:
    path = PurePosixPath((value or "").strip())
    if (not value or path.is_absolute() or path.suffix != ".md"
            or "\\" in value or any(part in {"", ".", ".."} for part in path.parts)):
        raise HTTPException(status_code=422, detail="section path must be a safe relative .md path")
    workspace = root.resolve()
    docs_entry = workspace / "docs"
    if docs_entry.is_symlink():
        raise HTTPException(status_code=422, detail="docs/ cannot be a symlink")
    docs = docs_entry.resolve()
    try:
        docs.relative_to(workspace)
    except ValueError:
        raise HTTPException(status_code=422, detail="docs/ must stay inside the workspace") from None
    current = docs_entry
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(status_code=422, detail="section paths cannot traverse symlinks")
    target = (docs / Path(*path.parts)).resolve()
    try:
        target.relative_to(docs)
    except ValueError:
        raise HTTPException(status_code=422, detail="section path must stay inside docs/") from None
    return path.as_posix()


def _archive_path(root: Path, value: str) -> Path:
    relative = PurePosixPath(_safe_section_path(root, value))
    workspace = root.resolve()
    archive_dir = workspace / ".fred-archive"
    if archive_dir.is_symlink() or (archive_dir / "index.json").is_symlink():
        raise HTTPException(status_code=409, detail="archive storage cannot be a symlink")
    resolved_archive = archive_dir.resolve()
    try:
        resolved_archive.relative_to(workspace)
        candidate = archive_dir / Path(*relative.parts)
        current = archive_dir
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise HTTPException(status_code=409, detail="archive paths cannot traverse symlinks")
        target = candidate.resolve()
        target.relative_to(resolved_archive)
    except ValueError:
        raise HTTPException(status_code=409, detail="archive destination must stay inside the workspace") from None
    return candidate


def _find_nav_position(nav, wanted: str, groups: list[str] | None = None,
                       group_indexes: list[int] | None = None):
    groups = groups or []
    group_indexes = group_indexes or []
    if not isinstance(nav, list):
        return None
    for index, item in enumerate(nav):
        if isinstance(item, dict):
            for title, value in item.items():
                if value == wanted:
                    return groups, index, group_indexes
                if not isinstance(value, str):
                    found = _find_nav_position(value, wanted, groups + [str(title)], group_indexes + [index])
                    if found:
                        return found
    return None


def _nav_group_members(nav, groups: list[str], group_indexes: list[int]) -> list[list[str]]:
    parent = nav
    members = []
    for index, group in enumerate(groups):
        entry = None
        position = group_indexes[index] if index < len(group_indexes) else -1
        if 0 <= position < len(parent):
            candidate = parent[position]
            if isinstance(candidate, dict) and group in candidate and isinstance(candidate[group], list):
                entry = candidate
        if entry is None:
            matches = [item for item in parent if isinstance(item, dict) and group in item
                       and isinstance(item[group], list)]
            if len(matches) == 1:
                entry = matches[0]
        if entry is None:
            members.append([])
            break
        parent = entry[group]
        members.append(sorted(leaf["path"] for leaf in _nav_leaves(parent)))
    return members


def _remove_nav_path(nav, wanted: str):
    """Return a copy of nav without one leaf and its original group/index."""
    removed = None
    pruned_group_depths: set[int] = set()

    def walk(items, groups):
        nonlocal removed
        if not isinstance(items, list):
            return items, False
        result = []
        removed_here = False
        for index, item in enumerate(items):
            if isinstance(item, dict):
                replacement = {}
                for title, value in item.items():
                    if value == wanted:
                        removed = (str(title), groups[:], index)
                        removed_here = True
                        continue
                    if isinstance(value, str):
                        replacement[title] = value
                    else:
                        children, child_removed = walk(value, groups + [str(title)])
                        removed_here = removed_here or child_removed
                        if children:
                            replacement[title] = children
                        elif child_removed:
                            pruned_group_depths.add(len(groups) + 1)
                if replacement:
                    result.append(replacement)
            else:
                result.append(item)
        return result, removed_here

    result, _removed = walk(copy.deepcopy(nav), [])
    return result, removed, sorted(pruned_group_depths)


def _reorder_nav(nav, ids: list[str]):
    nav = copy.deepcopy(nav)
    slots: list[tuple[list, int]] = []

    def collect(items):
        if not isinstance(items, list):
            return
        for index, item in enumerate(items):
            if isinstance(item, dict):
                for _title, value in item.items():
                    if isinstance(value, str) and value.endswith(".md"):
                        slots.append((items, index))
                    elif not isinstance(value, str):
                        collect(value)

    collect(nav)
    leaves = {leaf["id"]: leaf for leaf in _nav_leaves(nav)}
    if len(ids) != len(set(ids)) or set(ids) != set(leaves) or len(ids) != len(slots):
        raise HTTPException(status_code=422, detail="order must include every active section exactly once")
    for (parent, index), section_id in zip(slots, ids):
        leaf = leaves[section_id]
        parent[index] = {leaf["title"]: leaf["path"]}
    return nav


def _insert_nav(nav, section: dict, groups: list[str] | None = None, index: int | None = None,
                group_indexes: list[int] | None = None,
                force_create_depths: list[int] | None = None,
                group_members: list[list[str]] | None = None):
    groups = groups or []
    saved_group_indexes = group_indexes if isinstance(group_indexes, list) else []
    group_indexes = list(saved_group_indexes)
    force_create = set(force_create_depths or [])
    parent = nav
    actual_group_indexes = []
    for group_index, group in enumerate(groups):
        entry = None
        depth = group_index + 1
        matches = [(position, item) for position, item in enumerate(parent)
                   if isinstance(item, dict) and group in item and isinstance(item[group], list)]
        anchors = (group_members[group_index] if group_index < len(group_members or []) else [])
        if depth not in force_create and anchors:
            scores = [(len(set(anchors) & {leaf["path"] for leaf in _nav_leaves(item[group])}), position, item)
                      for position, item in matches]
            best = max((score for score, _position, _item in scores), default=0)
            if best:
                tied = [(position, item) for score, position, item in scores if score == best]
                original = group_indexes[group_index] if group_index < len(group_indexes) else 0
                _position, entry = min(tied, key=lambda pair: abs(pair[0] - original))
        elif depth not in force_create and group_index < len(group_indexes):
            position = group_indexes[group_index]
            if 0 <= position < len(parent):
                candidate = parent[position]
                if isinstance(candidate, dict) and group in candidate and isinstance(candidate[group], list):
                    entry = candidate
        if entry is None and depth not in force_create and not anchors:
            candidates = [item for _position, item in matches]
            if len(candidates) == 1:
                entry = candidates[0]
            elif candidates and group_index < len(group_indexes):
                position = group_indexes[group_index]
                entry = min(candidates, key=lambda item: abs(parent.index(item) - position))
        if entry is None:
            child = []
            position = group_indexes[group_index] if group_index < len(group_indexes) else len(parent)
            actual_position = min(max(position, 0), len(parent))
            parent.insert(actual_position, {group: child})
            actual_group_indexes.append(actual_position)
            parent = child
        else:
            actual_group_indexes.append(parent.index(entry))
            parent = entry[group]
    if saved_group_indexes is not group_indexes:
        saved_group_indexes[:] = actual_group_indexes
    at = min(max(index if index is not None else len(parent), 0), len(parent))
    parent.insert(at, {section["title"]: section["path"]})
    return nav


def _nav_group_exists_at(nav, groups: list[str], group_indexes: list[int], depth: int) -> bool:
    parent = nav
    for group_index in range(depth):
        if group_index >= len(group_indexes):
            return False
        position = group_indexes[group_index]
        if not isinstance(parent, list) or not 0 <= position < len(parent):
            return False
        entry = parent[position]
        group = groups[group_index]
        if not isinstance(entry, dict) or group not in entry or not isinstance(entry[group], list):
            return False
        parent = entry[group]
    return True


def _write_nav(root: Path, nav) -> None:
    path = root / "mkdocs.yml"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"^nav\s*:", line)), None)
    if start is None:
        rendered = yaml.safe_dump({"nav": nav}, sort_keys=False, allow_unicode=True)
        path.write_text(text.rstrip() + "\n\n" + rendered, encoding="utf-8")
        return
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^[^\s#][^:]*:", lines[i]):
            end = i
            break
    rendered = yaml.safe_dump({"nav": nav}, sort_keys=False, allow_unicode=True)
    path.write_text("".join(lines[:start]) + rendered + "".join(lines[end:]), encoding="utf-8")


def _structure_summary(root: Path) -> list[str]:
    draft = _load_structure(root)
    if not draft:
        return []
    old = _nav_leaves(_published_nav(root))
    new = _nav_leaves(draft["nav"])
    old_ids = [item["id"] for item in old]
    new_ids = [item["id"] for item in new]
    archived_old = {item["id"] for item in _load_archived(root)}
    archived_new = {item["id"] for item in draft["archived"]}
    deleted_ids = {item.get("id") for item in draft["deleted"]}
    summary = []
    for item in new:
        if item["id"] not in old_ids:
            summary.append(f"added section: {item['title']} ({item['path']})")
    for item in old:
        if item["id"] not in new_ids:
            if item["id"] in deleted_ids:
                summary.append(f"permanently delete section: {item['title']} ({item['path']})")
            elif item["id"] in archived_new:
                summary.append(f"archived section: {item['title']} ({item['path']})")
    for item in _load_archived(root):
        if item["id"] in archived_old - archived_new and item["id"] in new_ids:
            summary.append(f"restore section: {item['title']} ({item['path']})")
    for item in draft["deleted"]:
        if item.get("id") in archived_old:
            summary.append(f"permanently delete section: {item['title']} ({item['path']})")
    common = set(old_ids) & set(new_ids)
    if [sid for sid in old_ids if sid in common] != [sid for sid in new_ids if sid in common]:
        summary.append("section order changed")
    return summary


def _changed_paths(root: Path | None = None) -> list[str]:
    proc = _git("status", "--porcelain", "--", "docs", "mkdocs.yml", "requirements.txt", ".fred-archive",
                root=root, check=False)
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _all_changed_paths(root: Path | None = None) -> list[str]:
    proc = _git("status", "--porcelain", "--untracked-files=all", root=root, check=False)
    changed = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path == "site" or path.startswith("site/"):
            continue
        changed.append(line)
    return changed


def _sync_state(root: Path | None = None) -> dict:
    root = root or _active_root()
    try:
        subprocess.run(["git", "fetch", "--quiet", "origin", "main"], cwd=root,
                       capture_output=True, text=True, env=GIT_ENV, timeout=45)
        counts = _git("rev-list", "--left-right", "--count", "HEAD...origin/main",
                      root=root).stdout.split()
        ahead, behind = int(counts[0]), int(counts[1])
        return {"in_sync": ahead == 0 and behind == 0, "ahead": ahead,
                "behind": behind, "error": None}
    except Exception as exc:  # network down, no remote, etc.
        return {"in_sync": None, "ahead": None, "behind": None, "error": str(exc)}


def _mkdocs_bin(root: Path | None = None) -> str:
    root = root or _active_root()
    for candidate in (root / ".venv" / "bin" / "mkdocs",
                      MANAGER_ROOT / ".venv" / "bin" / "mkdocs"):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("mkdocs") or str(root / ".venv" / "bin" / "mkdocs")


def _run_build(strict: bool = True, root: Path | None = None) -> tuple[bool, str]:
    root = root or _active_root()
    cmd = [_mkdocs_bin(root), "build"] + (["--strict"] if strict else [])
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return False, ("mkdocs is not installed for this workspace. Install the MkDocs "
                       "requirements (see requirements.txt).")
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        return False, "\n".join(output.splitlines()[-15:])
    return True, "mkdocs build --strict clean"


def _nav(root: Path | None = None) -> list[tuple[str, str]]:
    config = _config(root)
    leaves: list[tuple[str, str]] = []

    def walk(node) -> None:
        if isinstance(node, str):
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for title, value in node.items():
                if isinstance(value, str) and value.endswith(".md"):
                    leaves.append((title, value))
                else:
                    walk(value)

    walk(config.get("nav") or [])
    return leaves


def _section_id(path: str) -> str:
    return path[:-3].replace("/", "-")


def _sections(root: Path | None = None) -> list[dict]:
    root = root or _active_root()
    docs = root / "docs"
    out = []
    for title, path in _nav(root):
        file = docs / path
        out.append({
            "id": _section_id(path),
            "title": title,
            "path": path,
            "file": str(file.relative_to(root)),
            "exists": file.is_file(),
        })
    return out


def _section_or_404(sid: str) -> dict:
    for section in _section_items(_active_root(), _effective_nav()):
        if section["id"] == sid:
            return section
    raise HTTPException(status_code=404, detail=f"unknown section '{sid}'")


def _stamp_version(version: str) -> None:
    """Rewrite the copyright line with the new version and today's date."""
    root = _active_root()
    path = root / "mkdocs.yml"
    text = path.read_text()
    value = _copyright_value(root)
    if not value:
        raise RuntimeError("mkdocs.yml has no copyright line to stamp")
    today = date.today().strftime("%-d %B %Y")
    new_value = re.sub(r"v\d+\.\d+", version, value, count=1)
    if re.search(r"\(updated [^)]*\)", new_value):
        new_value = re.sub(r"\(updated [^)]*\)", f"(updated {today})", new_value)
    else:
        new_value = f"{new_value} (updated {today})"
    text = text.replace(f'copyright: "{value}"', f'copyright: "{new_value}"', 1)
    path.write_text(text)


def _validate(root: Path | None = None) -> str | None:
    """Return a plain-language reason when validation fails, else None."""
    root = root or _active_root()
    docs = root / "docs"
    for section in _sections(root):
        _safe_section_path(root, section["path"])
        if not section["exists"]:
            return f"nav entry '{section['title']}' points at {section['path']}, which does not exist"
        body = (docs / section["path"]).read_text().strip()
        if not body:
            return f"nav entry '{section['title']}' ({section['path']}) is empty"
        if "{% include \"" in body or "![[" in body:
            return f"{section['path']} still contains unprocessed include syntax"
    ok, detail = _run_build(strict=True, root=root)
    return None if ok else f"mkdocs build failed:\n{detail}"


def _append_changelog(version: str, summary: str) -> None:
    changelog = _active_root() / "docs" / "changelog.md"
    text = changelog.read_text()
    today = date.today().strftime("%-d %B %Y")
    entry = f"### {today}\n- Published {version}: {summary}\n\n"

    season = re.search(r"^## (\d{4}) Season\s*$", text, re.M)
    if season and season.group(1) == str(date.today().year):
        insert_at = season.end() + 1
        if text[insert_at:insert_at + 1] == "\n":
            insert_at += 1
        text = text[:insert_at] + entry + text[insert_at:]
    elif season:
        new_season = f"## {date.today().year} Season\n\n{entry}"
        text = text[:season.start()] + new_season + text[season.start():]
    else:
        marker = text.find("\n## ")
        insert_at = marker + 1 if marker != -1 else len(text)
        text = text[:insert_at] + f"## {date.today().year} Season\n\n{entry}" + text[insert_at:]

    changelog.write_text(text)


def _live_version(timeout: int = LIVE_TIMEOUT) -> tuple[bool, str]:
    """Poll the public site until it serves the current version string."""
    site_url = _site_url()
    if not site_url:
        return False, ("this workspace has no GitHub repo/site URL; set repo_url "
                       "in mkdocs.yml or add an origin remote")
    wanted = _version()
    deadline = time.time() + timeout
    last = "no response"
    while time.time() < deadline:
        try:
            url = f"{site_url}?_cb={int(time.time())}"
            with urllib.request.urlopen(url, timeout=20) as response:
                body = response.read().decode("utf-8", "replace")
                last = f"HTTP {response.status}, version {'present' if wanted in body else 'not yet'}"
                if response.status == 200 and wanted in body:
                    return True, f"live site serves {wanted}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(exc)
        time.sleep(10)
    return False, f"live site did not show {wanted} within {timeout}s ({last})"


def _workspace_info(path: Path) -> dict:
    path = path.resolve()
    info = {
        "path": str(path),
        "name": path.name,
        "title": path.name,
        "exists": path.is_dir(),
        "valid": False,
        "version": "—",
        "branch": "",
        "head": "",
        "clean": None,
        "remote": "",
        "repo_url": "",
        "site_url": "",
        "drafts": 0,
        "error": None,
    }
    if not info["exists"]:
        info["error"] = "directory not found"
        return info
    if not _rules_root(path):
        info["error"] = "not a rulebook (missing docs/ or mkdocs.yml)"
        return info

    info["valid"] = True
    info["title"] = _site_name(path)
    info["version"] = _version(path)
    info["branch"] = _git_config(path, "rev-parse", "--abbrev-ref", "HEAD")
    info["head"] = _git_config(path, "rev-parse", "--short", "HEAD")
    info["remote"] = _git_config(path, "remote", "get-url", "origin")
    info["repo_url"] = _repo_url(path)
    info["site_url"] = _site_url(path)
    info["clean"] = not _changed_paths(path)
    info["drafts"] = len(_drafts(path)) + int(_structure_changed(path)) \
        + int(bool(_read_json(_pending_publish_file(path), None)))
    return info


# --------------------------------------------------------------------------- workspace creation


def _apply_blank_tokens(root: Path, title: str, year: int, repo_url: str) -> None:
    today = date.today().strftime("%-d %B %Y")
    replacements = {
        "{{TITLE}}": title,
        "{{YEAR}}": str(year),
        "{{DATE}}": today,
        "{{REPO_URL}}": repo_url,
    }
    text_suffixes = {".md", ".yml", ".yaml", ".txt", ".css", ".html", ".json"}
    for file in root.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in text_suffixes:
            continue
        text = file.read_text()
        file_replacements = replacements
        if file.name in {"mkdocs.yml", "mkdocs.yaml"}:
            file_replacements = {
                **replacements,
                "{{TITLE}}": json.dumps(title, ensure_ascii=False)[1:-1],
                "{{REPO_URL}}": json.dumps(repo_url, ensure_ascii=False)[1:-1],
            }
        for token, value in file_replacements.items():
            text = text.replace(token, value)
        text = re.sub(r'^repo_url:\s*""\s*\n', "", text, flags=re.M)
        file.write_text(text)


def _update_copied_config(root: Path, title: str | None, year: int | None,
                          repo_url: str | None, source_title: str) -> None:
    path = root / "mkdocs.yml"
    text = path.read_text()
    config = yaml.safe_load(text) or {}

    def set_scalar(key: str, value: str) -> None:
        nonlocal text
        line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        pattern = rf"^{re.escape(key)}\s*:.*$"
        if re.search(pattern, text, flags=re.M):
            text = re.sub(pattern, lambda _match: line, text, count=1, flags=re.M)
        else:
            text = line + "\n" + text

    if title:
        set_scalar("site_name", title)

    copyright = str(config.get("copyright") or "")
    if copyright:
        if title and source_title:
            copyright = copyright.replace(source_title, title)
        if year is not None:
            copyright = re.sub(r"20\d\d", str(year), copyright, count=1)
        set_scalar("copyright", copyright)
    elif title:
        set_scalar("copyright", f"{title}  ·  v1.0 (updated {date.today().strftime('%-d %B %Y')})")

    if repo_url:
        set_scalar("repo_url", repo_url)
    else:
        # Never inherit the source repo: a copied workspace must not point at
        # (or publish to) the directory it was copied from by accident.
        text = re.sub(r"^repo_url:.*\n?", "", text, count=1, flags=re.M)
    path.write_text(text)


def _init_git(root: Path, title: str) -> list[str]:
    warnings: list[str] = []
    init = subprocess.run(["git", "init", "-b", "main"], cwd=root,
                          capture_output=True, text=True, env=GIT_ENV)
    if init.returncode != 0:
        return [f"git init failed: {(init.stderr or init.stdout).strip()}"]
    add = subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True,
                         text=True, env=GIT_ENV)
    if add.returncode != 0:
        warnings.append(f"git add failed: {(add.stderr or add.stdout).strip()}")
        return warnings
    commit = subprocess.run(
        ["git", "commit", "-m", f"Create {title} rules workspace"],
        cwd=root, capture_output=True, text=True, env=GIT_ENV,
    )
    if commit.returncode != 0:
        warnings.append(
            "files are ready but the initial commit failed: "
            + (commit.stderr or commit.stdout).strip().splitlines()[-1]
        )
    return warnings


def _create_workspace(payload: "WorkspaceCreateIn") -> tuple[Path, list[str]]:
    try:
        requested_target = Path((payload.path or "").strip()).expanduser()
        if not requested_target.is_absolute():
            requested_target = HOME / requested_target
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid path: {exc}") from None
    if requested_target.is_symlink():
        raise HTTPException(status_code=422, detail="the destination must not be a symbolic link")
    target = _normalize_path(payload.path)
    mode = (payload.mode or "blank").strip().lower()
    if mode not in {"blank", "copy"}:
        raise HTTPException(status_code=422, detail="mode must be 'blank' or 'copy'")

    source: Path | None = None
    source_title = ""
    if mode == "copy":
        if not payload.source_path:
            raise HTTPException(status_code=422, detail="source_path is required when copying")
        source = _normalize_path(payload.source_path)
        if not _rules_root(source):
            raise HTTPException(status_code=422, detail=f"source is not a rules directory: {source}")
        try:
            source_config = yaml.safe_load((source / "mkdocs.yml").read_text())
            if not isinstance(source_config, dict):
                raise ValueError("mkdocs.yml must contain a YAML mapping")
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"source mkdocs.yml is invalid: {exc}") from None
        if source == target or source in target.parents or target in source.parents:
            raise HTTPException(status_code=422, detail="source and destination must be separate directories")
        source_title = _site_name(source)

    target_existed = target.exists()
    if target_existed:
        if not target.is_dir():
            raise HTTPException(status_code=409, detail=f"a file already exists at {target}")
        try:
            empty = not any(target.iterdir())
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"cannot read {target}: {exc}") from None
        if not empty:
            raise HTTPException(
                status_code=409,
                detail=f"{target} already exists and is not empty; choose a new directory",
            )
    if not target.parent.is_dir():
        raise HTTPException(status_code=422, detail=f"parent directory does not exist: {target.parent}")
    for parent in target.parents:
        if parent == HOME:
            break
        if (parent / ".git").exists():
            raise HTTPException(
                status_code=422,
                detail=f"{target} is inside another git repository; choose a top-level directory",
            )

    year = payload.year
    title = (payload.title or "").strip()
    repo_url = (payload.repo_url or "").strip()
    if year is not None and not 2000 <= year <= 2100:
        raise HTTPException(status_code=422, detail="year must be between 2000 and 2100")
    if any(ord(char) < 32 or ord(char) == 127 for char in title):
        raise HTTPException(status_code=422, detail="title must not contain control characters")
    if len(title) > 160:
        raise HTTPException(status_code=422, detail="title must be 160 characters or fewer")
    if repo_url:
        try:
            parsed = urlsplit(repo_url)
            parts = parsed.path.strip("/").split("/")
            valid_repo_url = (
                parsed.scheme in {"http", "https"} and parsed.hostname == "github.com"
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and len(parts) == 2
                and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0])
                and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1].removesuffix(".git"))
            )
        except ValueError:
            valid_repo_url = False
        if not valid_repo_url:
            raise HTTPException(
                status_code=422,
                detail="repo URL must be a GitHub repository URL, such as https://github.com/owner/repo",
            )

    suggested = _suggested_workspace()
    year = year if year is not None else suggested["year"]
    title = title or f"Fred Lobster Race Rules {year}"

    def cleanup_target() -> None:
        if not target.exists():
            return
        if not target_existed:
            shutil.rmtree(target, ignore_errors=True)
            return
        for child in target.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    if mode == "blank":
        if not TEMPLATE_DIR.is_dir():
            raise HTTPException(status_code=500, detail=f"blank template is missing: {TEMPLATE_DIR}")
        try:
            shutil.copytree(TEMPLATE_DIR, target, dirs_exist_ok=True)
            _apply_blank_tokens(target, title, year, repo_url)
            if not _rules_root(target):
                raise ValueError("template did not produce docs/ and mkdocs.yml")
            created_config = yaml.safe_load((target / "mkdocs.yml").read_text())
            if not isinstance(created_config, dict) or not created_config.get("site_name"):
                raise ValueError("template mkdocs.yml must contain a site_name mapping")
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            cleanup_target()
            raise HTTPException(status_code=500, detail=f"could not create workspace: {exc}") from None
    else:
        assert source is not None
        try:
            shutil.copytree(
                source, target, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    ".git", ".venv", "site", "__pycache__", "*.pyc", "*.log",
                    "node_modules", ".opencode", "drafts",
                ),
            )
            _update_copied_config(target, title, year, repo_url or None, source_title)
            copied_config = yaml.safe_load((target / "mkdocs.yml").read_text())
            if not _rules_root(target) or not isinstance(copied_config, dict):
                raise ValueError("copy did not produce a valid rulebook directory")
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            cleanup_target()
            raise HTTPException(status_code=500, detail=f"could not copy workspace: {exc}") from None

    warnings: list[str] = []
    if payload.git_init:
        warnings.extend(_init_git(target, title or _site_name(target)))
    return target, warnings


# --------------------------------------------------------------------------- models


class DraftIn(BaseModel):
    content: str


class SectionCreateIn(BaseModel):
    title: str
    path: str
    content: str | None = None
    copy_from: str | None = None


class SectionIdsIn(BaseModel):
    ids: list[str]


class SectionOrderIn(BaseModel):
    ids: list[str]


class RecoveryIn(BaseModel):
    confirm: str


class PublishIn(BaseModel):
    message: str | None = None


class WorkspaceSelectIn(BaseModel):
    path: str


class WorkspaceCreateIn(BaseModel):
    path: str
    mode: str = "blank"
    source_path: str | None = None
    title: str | None = None
    year: StrictInt | None = None
    repo_url: str | None = None
    git_init: bool = True
    activate: bool = True


class WorkspaceForgetIn(BaseModel):
    path: str


# --------------------------------------------------------------------------- endpoints


@app.get("/api/status")
def status() -> dict:
    root = _active_root()
    info = _workspace_info(root)
    sync = _sync_state(root)
    drafts = _drafts(root)
    draft_sections = set(drafts)
    if _structure_changed(root):
        draft_sections.add("navigation")
    pending_publish = _read_json(_pending_publish_file(root), None)
    if isinstance(pending_publish, dict):
        draft_sections.add("rollback-retry" if pending_publish.get("action") == "rollback" else "publish-retry")
    return {
        "site": info["title"],
        "site_url": info["site_url"],
        "workspace": {
            "path": info["path"],
            "name": info["name"],
            "title": info["title"],
        },
        "repo_url": info["repo_url"],
        "version": _version(root),
        "version_stamp": _copyright_value(root),
        "drafts": {"count": len(draft_sections), "sections": sorted(draft_sections)},
        "pending_publish": ({"action": pending_publish.get("action", "publish"),
                             "commit": pending_publish.get("commit"),
                             "version": pending_publish.get("version")}
                            if isinstance(pending_publish, dict) else None),
        "recovery_required": _recovery_required(root, pending_publish),
        "git": {
            "branch": info["branch"],
            "head": info["head"],
            "clean": info["clean"],
            "uncommitted": _changed_paths(root),
            **sync,
        },
    }


@app.get("/api/workspaces")
def workspaces() -> dict:
    state = _load_state()
    return {
        "active": state["active"],
        "workspaces": [_workspace_info(Path(path)) for path in state["known"]],
        "suggested": _suggested_workspace(),
    }


@app.post("/api/workspaces/select")
@_serialized_mutation
def select_workspace(payload: WorkspaceSelectIn) -> dict:
    path = _normalize_path(payload.path)
    if not _rules_root(path):
        raise HTTPException(
            status_code=422,
            detail=f"{path} is not a rules directory (missing docs/ or mkdocs.yml)",
        )
    with STATE_LOCK:
        state = _load_state()
        known = list(state["known"])
        if str(path) not in known:
            known.insert(0, str(path))
        _save_state({"active": str(path), "known": known})
    return {"ok": True, "workspace": _workspace_info(path)}


@app.post("/api/workspaces/create")
@_serialized_mutation
def create_workspace(payload: WorkspaceCreateIn) -> dict:
    target, warnings = _create_workspace(payload)
    with STATE_LOCK:
        state = _load_state()
        known = list(state["known"])
        if str(target) not in known:
            known.insert(0, str(target))
        active = str(target) if payload.activate else state["active"]
        _save_state({"active": active, "known": known})
    return {
        "ok": True,
        "workspace": _workspace_info(target),
        "active": str(target) if payload.activate else None,
        "warnings": warnings,
    }


@app.post("/api/workspaces/forget")
def forget_workspace(payload: WorkspaceForgetIn) -> dict:
    path = _normalize_path(payload.path)
    with STATE_LOCK:
        state = _load_state()
        if str(path) == state["active"]:
            raise HTTPException(
                status_code=409,
                detail="cannot remove the active workspace; switch to another one first",
            )
        known = [value for value in state["known"] if value != str(path)]
        _save_state({"active": state["active"], "known": known})
    return {"ok": True}


@app.post("/api/recovery/restore")
@_serialized_mutation
def restore_interrupted_publish(payload: RecoveryIn) -> dict:
    root = _active_root()
    if payload.confirm != "RESTORE":
        raise HTTPException(status_code=422, detail="type RESTORE to confirm recovery")
    pending = _read_json(_pending_publish_file(root), None)
    if isinstance(pending, dict):
        head = _git("rev-parse", "HEAD", root=root, check=False).stdout.strip()
        if (pending.get("action") != "publish" or pending.get("commit")
                or not pending.get("parent") or head != pending.get("parent")):
            raise HTTPException(status_code=409, detail="only an uncommitted publish staging transaction can be restored here")
    if not _publish_transaction_file(root).is_file():
        raise HTTPException(status_code=404, detail="no interrupted publish transaction needs recovery")
    try:
        recovered = _recover_publish_transaction(root, force=True)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"could not restore the pre-publish files: {exc}") from None
    if not recovered:
        raise HTTPException(status_code=409, detail="publish recovery journal is invalid")
    if isinstance(pending, dict):
        _pending_publish_file(root).unlink(missing_ok=True)
    return {"ok": True, "detail": "pre-publish rulebook files restored; backend drafts are still available to review"}


@app.get("/api/sections")
def sections() -> dict:
    root = _active_root()
    draft = _load_structure(root)
    deleted = {item.get("id") for item in (draft or {}).get("deleted", [])}

    def present(section: dict) -> dict:
        return {
            **{key: value for key, value in section.items() if key not in {"file", "groups", "index"}},
            "last_published_version": _version(root),
            "content": _section_content(root, section),
        }

    active = [present(item) for item in _section_items(root, _effective_nav(root))]
    archived = [present(item) for item in _effective_archived(root) if item.get("id") not in deleted]
    pending = _read_json(_pending_publish_file(root), None)
    return {"version": _version(root), "sections": active, "archived": archived,
            "structure_draft": _structure_changed(root),
            "pending_publish": ({"action": pending.get("action", "publish"),
                                 "commit": pending.get("commit"), "version": pending.get("version")}
                                if isinstance(pending, dict) else None)}


def _structure_response(root: Path) -> dict:
    draft = _load_structure(root)
    deleted = {item.get("id") for item in (draft or {}).get("deleted", [])}

    def present(section: dict) -> dict:
        return {
            **{key: value for key, value in section.items() if key not in {"file", "groups", "index"}},
            "content": _section_content(root, section),
        }

    active = [present(item) for item in _section_items(root, _effective_nav(root))]
    archived = [present(item) for item in _effective_archived(root) if item.get("id") not in deleted]
    return {"ok": True, "sections": active, "archived": archived,
            "structure_draft": _structure_changed(root)}


def _validate_structure(root: Path, nav, archived: list[dict], deleted: list[dict]) -> None:
    leaves = _nav_leaves(nav)
    ids = [item["id"] for item in leaves]
    paths = [item["path"] for item in leaves]
    archived_ids = [item.get("id") for item in archived]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise HTTPException(status_code=409, detail="section paths and ids must be unique")
    if len(archived_ids) != len(set(archived_ids)) or set(ids) & set(archived_ids):
        raise HTTPException(status_code=409, detail="active and archived sections must be distinct")
    deleted_ids = {item.get("id") for item in deleted}
    if deleted_ids & set(ids):
        raise HTTPException(status_code=409, detail="a permanently deleted section cannot remain active")
    if len(deleted_ids) != len(deleted) or not deleted_ids.issubset(set(archived_ids)):
        raise HTTPException(status_code=409, detail="permanent deletions must reference unique archived sections")
    for item in leaves + archived + deleted:
        path = _safe_section_path(root, str(item.get("path") or ""))
        if _section_id(path) != item.get("id"):
            raise HTTPException(status_code=422, detail="section id must match its Markdown path")
        if not str(item.get("title") or "").strip():
            raise HTTPException(status_code=422, detail="section title cannot be empty")
    for item in archived:
        groups = item.get("groups") or []
        index = item.get("index", 0)
        group_indexes = item.get("group_indexes") or []
        group_members = item.get("group_members") or []
        force_create_depths = item.get("force_create_depths") or []
        if (not isinstance(groups, list) or not all(isinstance(group, str) for group in groups)
                or not isinstance(group_indexes, list)
                or not all(isinstance(position, int) and position >= 0 for position in group_indexes)
                or (group_indexes and len(group_indexes) != len(groups))
                or not isinstance(group_members, list)
                or any(not isinstance(paths, list) or not all(isinstance(path, str) for path in paths)
                       for paths in group_members)
                or (group_members and len(group_members) != len(groups))) \
                or not isinstance(index, int) or index < 0:
            raise HTTPException(status_code=422, detail="archived navigation position is invalid")
        if not isinstance(force_create_depths, list) or any(
                not isinstance(depth, int) or not 1 <= depth <= len(groups) for depth in force_create_depths):
            raise HTTPException(status_code=422, detail="archived group restoration metadata is invalid")


def _persist_structure(root: Path, nav, archived: list[dict], deleted: list[dict]) -> dict:
    _validate_structure(root, nav, archived, deleted)
    _save_structure(root, nav, archived, deleted)
    return _structure_response(root)


@app.post("/api/sections")
@_serialized_mutation
def create_section(payload: SectionCreateIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    title = payload.title.strip()
    if not title or len(title) > 160:
        raise HTTPException(status_code=422, detail="section title must be 1–160 characters")
    path = _safe_section_path(root, payload.path)
    nav = _effective_nav(root)
    archived = _effective_archived(root)
    draft = _load_structure(root) or {"deleted": []}
    deleted = list(draft.get("deleted") or [])
    sid = _section_id(path)
    all_sections = _section_items(root, nav) + archived
    if any(item["id"] == sid or item["path"] == path for item in all_sections):
        raise HTTPException(status_code=409, detail="a section already uses that path")
    if (root / "docs" / path).exists():
        raise HTTPException(status_code=409, detail="a Markdown file already exists at that path")

    content = payload.content
    if payload.copy_from:
        source = _section_source(root, payload.copy_from)
        if source is None:
            raise HTTPException(status_code=404, detail=f"unknown source section '{payload.copy_from}'")
        if content is None:
            content = _section_content(root, source)
    if content is None:
        content = f"# {title}\n\n"
    if not content.strip():
        raise HTTPException(status_code=422, detail="section content cannot be empty")

    _draft_file(sid, root).write_text(content, encoding="utf-8")
    nav.append({title: path})
    return _persist_structure(root, nav, archived, deleted)


@app.put("/api/sections/order")
@_serialized_mutation
def reorder_sections(payload: SectionOrderIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    nav = _effective_nav(root)
    reordered = _reorder_nav(nav, payload.ids)
    draft = _load_structure(root) or {}
    return _persist_structure(root, reordered, _effective_archived(root), list(draft.get("deleted") or []))


@app.post("/api/sections/archive")
@_serialized_mutation
def archive_sections(payload: SectionIdsIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    nav = _effective_nav(root)
    archived = _effective_archived(root)
    draft = _load_structure(root) or {}
    deleted = list(draft.get("deleted") or [])
    if not payload.ids or len(payload.ids) != len(set(payload.ids)):
        raise HTTPException(status_code=422, detail="select one or more unique sections to archive")
    selected = []
    for sid in payload.ids:
        section = next((item for item in _section_items(root, nav) if item["id"] == sid), None)
        if section is None:
            raise HTTPException(status_code=404, detail=f"unknown active section '{sid}'")
        location = _find_nav_position(nav, section["path"])
        if location is None:
            raise HTTPException(status_code=409, detail=f"could not locate section '{sid}' in navigation")
        selected.append((section, location,
                         _nav_group_members(nav, location[0], location[2])))
    for section, location, group_members in selected:
        sid = section["id"]
        nav, removed, pruned_group_depths = _remove_nav_path(nav, section["path"])
        if not removed:
            raise HTTPException(status_code=409, detail=f"could not remove section '{sid}' from navigation")
        title, _groups, _index = removed
        groups, index, group_indexes = location
        archived.append({"id": sid, "title": title, "path": section["path"],
                         "groups": groups, "group_indexes": group_indexes,
                         "group_members": group_members,
                         "force_create_depths": pruned_group_depths, "index": index})
    if not _nav_leaves(nav):
        raise HTTPException(status_code=409, detail="at least one active section must remain")
    new_archives = archived[-len(selected):]
    for section in new_archives:
        force = set(section.get("force_create_depths") or [])
        for removed_group in new_archives:
            for depth in removed_group.get("force_create_depths") or []:
                same_group = (
                    section.get("groups", [])[:depth] == removed_group.get("groups", [])[:depth]
                    and section.get("group_indexes", [])[:depth]
                    == removed_group.get("group_indexes", [])[:depth]
                )
                if same_group:
                    force.add(depth)
        section["force_create_depths"] = sorted(force)
    return _persist_structure(root, nav, archived, deleted)


@app.post("/api/sections/restore")
@_serialized_mutation
def restore_sections(payload: SectionIdsIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    nav = _effective_nav(root)
    archived = _effective_archived(root)
    draft = _load_structure(root) or {}
    deleted = list(draft.get("deleted") or [])
    if not payload.ids or len(payload.ids) != len(set(payload.ids)):
        raise HTTPException(status_code=422, detail="select one or more unique sections to restore")
    selected = []
    for sid in payload.ids:
        section = next((item for item in archived if item.get("id") == sid), None)
        if section is None:
            raise HTTPException(status_code=404, detail=f"unknown archived section '{sid}'")
        if any(item["id"] == sid for item in _section_items(root, nav)):
            raise HTTPException(status_code=409, detail=f"section '{sid}' is already active")
        selected.append(section)
    recreated_groups: list[tuple[int, tuple[str, ...], tuple[int, ...]]] = []
    for section in sorted(selected, key=lambda item: (
        tuple(item.get("group_indexes") or []), tuple(item.get("groups") or []), item.get("index", 0),
    )):
        sid = section["id"]
        groups = section.get("groups") or []
        group_indexes = section.get("group_indexes") or []
        original_indexes = list(group_indexes)
        force = set(section.get("force_create_depths") or [])
        for depth, prior_groups, prior_indexes in recreated_groups:
            if tuple(groups[:depth]) == prior_groups and tuple(group_indexes[:depth]) == prior_indexes:
                force.discard(depth)
        nav = _insert_nav(nav, section, section.get("groups"), section.get("index"),
                          group_indexes, sorted(force), section.get("group_members"))
        for depth in force:
            recreated_groups.append((depth, tuple(groups[:depth]), tuple(group_indexes[:depth])))
        for archived_item in archived:
            if archived_item is section:
                continue
            other_groups = archived_item.get("groups") or []
            other_indexes = archived_item.get("group_indexes") or []
            shared_depth = min(len(groups), len(other_groups), len(original_indexes), len(other_indexes))
            for depth in range(1, shared_depth + 1):
                if groups[:depth] == other_groups[:depth] and original_indexes[:depth] == other_indexes[:depth]:
                    other_indexes[:depth] = group_indexes[:depth]
            pending_force = archived_item.get("force_create_depths") or []
            archived_item["force_create_depths"] = [
                depth for depth in pending_force
                if not _nav_group_exists_at(nav, other_groups, other_indexes, depth)
            ]
        archived.remove(section)
        deleted = [item for item in deleted if item.get("id") != sid]
    for section in archived:
        group_indexes = section.get("group_indexes") or []
        section["force_create_depths"] = [
            depth for depth in section.get("force_create_depths") or []
            if not _nav_group_exists_at(nav, section.get("groups") or [], group_indexes, depth)
        ]
    return _persist_structure(root, nav, archived, deleted)


@app.delete("/api/sections")
@_serialized_mutation
def delete_archived_sections(payload: SectionIdsIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    nav = _effective_nav(root)
    archived = _effective_archived(root)
    draft = _load_structure(root) or {}
    deleted = list(draft.get("deleted") or [])
    if not payload.ids or len(payload.ids) != len(set(payload.ids)):
        raise HTTPException(status_code=422, detail="select one or more unique archived sections to delete")
    already_deleted = {item.get("id") for item in deleted}
    for sid in payload.ids:
        section = next((item for item in archived if item.get("id") == sid), None)
        if section is None:
            raise HTTPException(status_code=404, detail=f"unknown archived section '{sid}'")
        if sid in already_deleted:
            raise HTTPException(status_code=409, detail=f"section '{sid}' is already marked for deletion")
        deleted.append({"id": sid, "title": section["title"], "path": section["path"]})
    return _persist_structure(root, nav, archived, deleted)


@app.put("/api/draft/{section}")
@_serialized_mutation
def save_draft(section: str, payload: DraftIn) -> dict:
    root = _active_root()
    _ensure_no_pending_operation(root)
    _section_or_404(section)
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="refusing to store an empty draft")
    _drafts_dir(root).mkdir(parents=True, exist_ok=True)
    _draft_file(section, root).write_text(payload.content, encoding="utf-8")
    return {"ok": True, "section": section, "bytes": len(payload.content),
            "drafts": len(_drafts(root)) + int(_structure_changed(root))}


@app.get("/api/diff")
def diff() -> dict:
    root = _active_root()
    entries, added, removed = [], 0, 0
    for sid, _meta in _drafts(root).items():
        section = _section_source(root, sid)
        if section is None:
            continue
        published_path = root / "docs" / section["path"]
        published = published_path.read_text(encoding="utf-8").splitlines(keepends=True) \
            if published_path.is_file() else []
        draft = _draft_file(sid, root).read_text(encoding="utf-8").splitlines(keepends=True)
        text = "".join(difflib.unified_diff(
            published, draft,
            fromfile=f"published/{section['path']}" if published else "/dev/null",
            tofile=f"draft/{section['path']}",
        ))
        added += sum(1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed += sum(1 for line in text.splitlines() if line.startswith("-") and not line.startswith("---"))
        entries.append({"section": sid, "path": section["path"], "diff": text,
                        "changed": bool(text), "kind": "content"})
    structure_summary = _structure_summary(root)
    pending_publish = _read_json(_pending_publish_file(root), None)
    return {"version": _version(root), "added": added, "removed": removed, "entries": entries,
            "structure": {"changed": bool(structure_summary), "summary": structure_summary},
            "pending_publish": ({"action": pending_publish.get("action", "publish"),
                                 "commit": pending_publish.get("commit"),
                                 "version": pending_publish.get("version")}
                                if isinstance(pending_publish, dict) else None)}


def _file_snapshot(paths: set[Path]) -> dict[Path, bytes | None]:
    snapshot = {}
    for path in paths:
        try:
            snapshot[path] = path.read_bytes() if path.is_file() else None
        except OSError:
            snapshot[path] = None
    return snapshot


def _restore_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _save_publish_transaction(root: Path, snapshot: dict[Path, bytes | None], parent: str = "") -> None:
    files = {}
    for path, content in snapshot.items():
        relative = path.relative_to(root).as_posix()
        files[relative] = base64.b64encode(content).decode("ascii") if content is not None else None
    _write_json(_publish_transaction_file(root), {"parent": parent, "files": files})


def _mark_publish_transaction_staged(root: Path) -> None:
    journal_path = _publish_transaction_file(root)
    raw = _read_json(journal_path, None)
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
        raise RuntimeError("publish recovery journal is missing")
    workspace = root.resolve()
    expected = {}
    for relative in raw["files"]:
        pure = PurePosixPath(str(relative))
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) \
                or not pure.parts or pure.parts[0] not in {"docs", "mkdocs.yml", ".fred-archive"}:
            raise RuntimeError("publish recovery journal contains an unsafe path")
        path = workspace.joinpath(*pure.parts)
        current = workspace
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError("publish recovery journal path traverses a symlink")
        content = path.read_bytes() if path.is_file() else None
        expected[relative] = base64.b64encode(content).decode("ascii") if content is not None else None
    raw["expected"] = expected
    _write_json(journal_path, raw)


def _recover_publish_transaction(root: Path, force: bool = False) -> bool:
    journal_path = _publish_transaction_file(root)
    raw = _read_json(journal_path, None)
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
        return False
    workspace = root.resolve()
    parent = str(raw.get("parent") or "")
    if not parent:
        raise RuntimeError("publish recovery journal is missing its base commit")
    if _git("rev-parse", "HEAD", root=root).stdout.strip() != parent:
        raise RuntimeError("HEAD changed since the publish journal was written")
    expected = raw.get("expected")
    for relative, original in raw["files"].items():
        pure = PurePosixPath(str(relative))
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts) \
                or not pure.parts or pure.parts[0] not in {"docs", "mkdocs.yml", ".fred-archive"}:
            raise RuntimeError("publish recovery journal contains an unsafe path")
        path = workspace.joinpath(*pure.parts)
        current = workspace
        for part in pure.parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError("publish recovery journal path traverses a symlink")
        if isinstance(expected, dict) and relative in expected:
            expected_value = expected[relative]
        else:
            expected_value = original
        current_value = base64.b64encode(path.read_bytes()).decode("ascii") if path.is_file() else None
        if current_value != expected_value and not force:
            raise RuntimeError("rulebook files changed after publish staging; refusing automatic recovery")
    for relative, encoded in raw["files"].items():
        pure = PurePosixPath(str(relative))
        path = workspace.joinpath(*pure.parts)
        if encoded is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(encoded, validate=True))

    _git("reset", "--", "docs", "mkdocs.yml", root=root, check=False)
    archive = root / ".fred-archive"
    tracked_archive = _git("ls-files", "--error-unmatch", ".fred-archive/index.json", root=root, check=False)
    if archive.exists() or tracked_archive.returncode == 0:
        _git("reset", "--", ".fred-archive", root=root, check=False)
    journal_path.unlink(missing_ok=True)
    return True


def _stage_section_structure(root: Path, structure: dict, drafts: dict[str, dict]) -> None:
    """Apply the pending navigation/content/archive plan to the working copy."""
    _validate_structure(root, structure["nav"], structure["archived"], structure["deleted"])
    active = _section_items(root, structure["nav"])
    archived = structure["archived"]
    deleted = {item.get("id"): item for item in structure["deleted"]}
    final = {item["id"]: item for item in active + archived}
    for section in archived:
        source = root / "docs" / section["path"]
        destination = _archive_path(root, section["path"])
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise RuntimeError(f"archive destination already exists for {section['path']}")
            shutil.move(str(source), str(destination))

    for section in active:
        source = _archive_path(root, section["path"])
        destination = root / "docs" / section["path"]
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise RuntimeError(f"both active and archived files exist for {section['path']}")
            shutil.move(str(source), str(destination))

    for section in deleted.values():
        (root / "docs" / section["path"]).unlink(missing_ok=True)
        _archive_path(root, section["path"]).unlink(missing_ok=True)

    archived_ids = {item.get("id") for item in archived}
    for sid in drafts:
        if sid in deleted:
            continue
        section = final.get(sid)
        if section is None:
            raise RuntimeError(f"draft '{sid}' has no matching active or archived section")
        content = _draft_file(sid, root).read_text(encoding="utf-8")
        destination = (_archive_path(root, section["path"]) if sid in archived_ids
                       else root / "docs" / section["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    _write_nav(root, structure["nav"])
    retained_archives = [item for item in archived if item.get("id") not in deleted]
    if retained_archives or _archive_file(root).exists():
        _write_json(_archive_file(root), retained_archives)


def _clear_completed_drafts(root: Path) -> None:
    for sid in list(_drafts(root)):
        _draft_file(sid, root).unlink(missing_ok=True)
    _structure_file(root).unlink(missing_ok=True)
    _pending_publish_file(root).unlink(missing_ok=True)
    _publish_transaction_file(root).unlink(missing_ok=True)


def _retry_pending_publish(root: Path, pending: dict) -> dict:
    steps = []
    expected = str(pending.get("commit") or "")
    head = _git("rev-parse", "HEAD", root=root).stdout.strip()
    if not expected:
        if head == pending.get("parent"):
            if _publish_transaction_file(root).is_file():
                try:
                    recovered = _recover_publish_transaction(root)
                except Exception as exc:
                    return {"ok": False, "error": f"interrupted publish recovery failed: {exc}", "steps": steps}
                if not recovered:
                    return {"ok": False, "error": "interrupted publish recovery journal is invalid", "steps": steps}
                _pending_publish_file(root).unlink(missing_ok=True)
                return {"ok": False, "error": "interrupted publish staging was restored; drafts remain ready to retry",
                        "steps": steps}
            if _changed_paths(root):
                return {"ok": False,
                        "error": "publish commit was not created and rulebook files remain dirty; inspect the worktree before retrying",
                        "steps": steps}
            _pending_publish_file(root).unlink(missing_ok=True)
            return {"ok": False, "error": "no publish commit was created; the draft is ready to retry",
                    "steps": steps}
        parent = _git("rev-parse", "HEAD^", root=root).stdout.strip()
        subject = _git("log", "-1", "--pretty=%s", root=root).stdout.strip()
        if parent != pending.get("parent") or subject != pending.get("message"):
            return {"ok": False,
                    "error": "could not identify the pending publish commit; inspect the rulebook repository before retrying",
                    "steps": steps, "commit": head[:7]}
        expected = head
        pending["commit"] = expected
        _write_json(_pending_publish_file(root), pending)
    if head != expected:
        return {"ok": False, "error": "pending publish does not match HEAD; inspect the rulebook repository before retrying",
                "steps": steps, "commit": expected}
    _publish_transaction_file(root).unlink(missing_ok=True)
    dirty = _changed_paths(root)
    if dirty:
        return {"ok": False, "error": "pending publish has uncommitted rulebook changes; resolve them before retrying",
                "steps": steps, "commit": expected}
    short = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    steps.append({"step": "commit", "ok": True, "detail": f"retrying publish commit {short}"})
    try:
        _git("push", "origin", "HEAD:main", root=root, timeout=180)
        steps.append({"step": "push", "ok": True,
                      "detail": "pushed main; the existing GitHub Actions workflow builds and deploys gh-pages"})
    except Exception as exc:
        steps.append({"step": "push", "ok": False, "detail": str(exc)})
        return {"ok": False, "error": f"push retry failed (commit {short} remains local): {exc}",
                "steps": steps, "commit": short, "version": pending.get("version")}

    live_ok, live_detail = _live_version()
    steps.append({"step": "live", "ok": live_ok, "detail": live_detail})
    if not live_ok:
        return {"ok": False, "error": live_detail, "steps": steps,
                "commit": short, "version": pending.get("version")}

    _clear_completed_drafts(root)
    site_url = _site_url(root)
    return {"ok": True, "version": pending.get("version"),
            "previous_version": pending.get("previous_version"), "commit": short,
            "site_url": site_url + "?_cb=" + str(int(time.time())), "steps": steps}


def _retry_pending_rollback(root: Path, pending: dict) -> dict:
    steps = []
    expected = str(pending.get("commit") or "")
    head = _git("rev-parse", "HEAD", root=root).stdout.strip()
    if not expected:
        if head == pending.get("parent"):
            if _all_changed_paths(root):
                return {"ok": False, "error": "rollback did not create a commit and the working tree is dirty; inspect it before retrying",
                        "steps": steps}
            _pending_publish_file(root).unlink(missing_ok=True)
            return {"ok": False, "error": "no rollback commit was created; you can retry the rollback action",
                    "steps": steps}
        parent = _git("rev-parse", "HEAD^", root=root).stdout.strip()
        subject = _git("log", "-1", "--pretty=%s", root=root).stdout.strip()
        if parent != pending.get("parent") or subject != pending.get("message"):
            return {"ok": False, "error": "could not identify the pending rollback commit; inspect the rulebook repository",
                    "steps": steps, "commit": head[:7]}
        expected = head
        pending["commit"] = expected
        pending["version"] = pending.get("version") or _version(root)
        _write_json(_pending_publish_file(root), pending)
    if head != expected:
        return {"ok": False, "error": "pending rollback does not match HEAD; inspect the rulebook repository",
                "steps": steps, "commit": expected}
    dirty = _changed_paths(root)
    if dirty:
        return {"ok": False, "error": "pending rollback has uncommitted rulebook changes; resolve them before retrying",
                "steps": steps, "commit": expected}
    short = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    steps.append({"step": "revert", "ok": True, "detail": f"retrying rollback commit {short}"})
    if not pending.get("build_verified"):
        ok, detail = _run_build(strict=True, root=root)
        steps.append({"step": "build", "ok": ok, "detail": detail})
        if not ok:
            return {"ok": False, "error": f"rollback build failed; retry remains pending: {detail}",
                    "steps": steps, "commit": short, "version": pending.get("version")}
        pending["build_verified"] = True
        _write_json(_pending_publish_file(root), pending)
    try:
        _git("push", "origin", "HEAD:main", root=root, timeout=180)
        steps.append({"step": "push", "ok": True, "detail": "pushed main; workflow rebuilds gh-pages"})
    except Exception as exc:
        steps.append({"step": "push", "ok": False, "detail": str(exc)})
        return {"ok": False, "error": f"rollback push retry failed (commit {short} remains local): {exc}",
                "steps": steps, "commit": short, "version": pending.get("version")}
    live_ok, live_detail = _live_version()
    steps.append({"step": "live", "ok": live_ok, "detail": live_detail})
    if not live_ok:
        return {"ok": False, "error": live_detail, "steps": steps,
                "commit": short, "version": pending.get("version")}
    _pending_publish_file(root).unlink(missing_ok=True)
    return {"ok": True, "version": pending.get("version"), "commit": short, "steps": steps}


@app.post("/api/publish")
@_serialized_mutation
def publish(payload: PublishIn | None = None) -> dict:
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str) -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})

    root = _active_root()
    pending_publish = _read_json(_pending_publish_file(root), None)
    if isinstance(pending_publish, dict):
        if pending_publish.get("action", "publish") != "publish":
            return {"ok": False, "error": "a rollback retry is pending; use the rollback action first", "steps": []}
        return _retry_pending_publish(root, pending_publish)
    if _publish_transaction_file(root).is_file():
        try:
            recovered = _recover_publish_transaction(root)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"could not recover interrupted publish staging: {exc}") from None
        if not recovered:
            raise HTTPException(status_code=409, detail="interrupted publish recovery journal is invalid")
    drafts = _drafts(root)
    structure = _load_structure(root)
    structure_changed = _structure_changed(root)
    if not drafts and not structure_changed:
        raise HTTPException(status_code=409, detail="nothing to publish: no drafts saved")

    dirty = _changed_paths(root)
    if dirty:
        raise HTTPException(status_code=409, detail=(
            "working tree has uncommitted changes in the published sources; "
            "commit or discard them before publishing so the publish stays one clean commit: "
            + ", ".join(line.strip().split()[-1] for line in dirty)))

    if structure is None:
        structure = {"nav": _published_nav(root), "archived": _load_archived(root), "deleted": []}

    records = {item["id"]: item for item in _section_items(root, _published_nav(root))}
    records.update({item["id"]: item for item in _section_items(root, structure["nav"])})
    records.update({item["id"]: item for item in _load_archived(root)})
    records.update({item["id"]: item for item in structure["archived"]})
    records.update({item["id"]: item for item in structure["deleted"]})
    changed_titles = [records[sid]["title"] for sid in drafts if sid in records]
    changed_titles.extend(_structure_summary(root))
    summary = ", ".join(changed_titles) + " updated" if changed_titles else "content updated"

    affected_paths = {root / "mkdocs.yml", root / "docs" / "changelog.md", _archive_file(root)}
    for section in records.values():
        affected_paths.add(root / "docs" / section["path"])
        affected_paths.add(_archive_path(root, section["path"]))
    snapshot = _file_snapshot(affected_paths)
    try:
        parent = _git("rev-parse", "HEAD", root=root).stdout.strip()
        _save_publish_transaction(root, snapshot, parent)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"could not save publish recovery journal: {exc}") from None

    old_version, new_version = _version(root), _bump(_version(root))
    try:
        if structure_changed:
            _stage_section_structure(root, structure, drafts)
        else:
            for sid in drafts:
                section = records.get(sid)
                if section is None:
                    raise RuntimeError(f"draft '{sid}' has no matching section")
                destination = root / "docs" / section["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(_draft_file(sid, root).read_text(encoding="utf-8"), encoding="utf-8")
        problem = _validate(root)
        if problem:
            _restore_snapshot(snapshot)
            _publish_transaction_file(root).unlink(missing_ok=True)
            step("validate", False, problem)
            return {"ok": False, "error": problem, "steps": steps}
        step("validate", True, "all nav sections present, non-empty, mkdocs build --strict clean")
        _stamp_version(new_version)
        _append_changelog(new_version, summary + (f" ({payload.message})" if payload and payload.message else ""))
        step("stage", True, f"drafts applied, footer stamped {new_version}, changelog entry added")
        _mark_publish_transaction_staged(root)
    except Exception as exc:
        _restore_snapshot(snapshot)
        _publish_transaction_file(root).unlink(missing_ok=True)
        return {"ok": False, "error": str(exc), "steps": steps}

    ok, detail = _run_build(strict=True, root=root)
    step("build", ok, detail)
    if not ok:
        _restore_snapshot(snapshot)
        _publish_transaction_file(root).unlink(missing_ok=True)
        return {"ok": False, "error": f"build failed, nothing published: {detail}", "steps": steps}

    message = f"Publish {new_version}: {summary}"
    if payload and payload.message:
        message += f" — {payload.message}"
    paths = ["docs", "mkdocs.yml"]
    if (root / ".fred-archive").exists():
        paths.append(".fred-archive")
    pending_record = {
        "action": "publish",
        "commit": "",
        "parent": _git("rev-parse", "HEAD", root=root).stdout.strip(),
        "message": message,
        "version": new_version,
        "previous_version": old_version,
    }
    try:
        _write_json(_pending_publish_file(root), pending_record)
        _git("add", "-A", "--", *paths, root=root)
        _git("commit", "-m", message, root=root)
        full_commit = _git("rev-parse", "HEAD", root=root).stdout.strip()
        commit = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    except Exception as exc:
        _pending_publish_file(root).unlink(missing_ok=True)
        _git("reset", "--", *paths, root=root, check=False)
        _restore_snapshot(snapshot)
        _publish_transaction_file(root).unlink(missing_ok=True)
        return {"ok": False, "error": f"commit failed: {exc}", "steps": steps}

    pending_record["commit"] = full_commit
    try:
        _write_json(_pending_publish_file(root), pending_record)
    except Exception as exc:
        return {"ok": False,
                "error": f"publish commit {commit} is local; retry marker update failed and can be recovered on the next publish request: {exc}",
                "steps": steps, "commit": commit, "version": new_version}
    _publish_transaction_file(root).unlink(missing_ok=True)
    step("commit", True, f"{commit} {message}")

    try:
        _git("push", "origin", "HEAD:main", root=root, timeout=180)
        step("push", True, "pushed main; the existing GitHub Actions workflow builds and deploys gh-pages")
    except Exception as exc:
        return {"ok": False, "error": f"push failed (commit {commit} is local only): {exc}",
                "steps": steps, "commit": commit}

    live_ok, live_detail = _live_version()
    step("live", live_ok, live_detail)

    if not live_ok:
        return {"ok": False, "error": live_detail, "version": new_version,
                "commit": commit, "steps": steps}

    _clear_completed_drafts(root)
    site_url = _site_url(root)
    return {"ok": True, "version": new_version, "previous_version": old_version,
            "commit": commit, "site_url": site_url + "?_cb=" + str(int(time.time())),
            "steps": steps}


@app.post("/api/rollback")
@_serialized_mutation
def rollback() -> dict:
    steps: list[dict] = []
    root = _active_root()
    pending = _read_json(_pending_publish_file(root), None)
    if isinstance(pending, dict):
        if pending.get("action") == "rollback":
            return _retry_pending_rollback(root, pending)
        raise HTTPException(status_code=409, detail="a publish retry is pending; finish it before rollback")
    if _publish_transaction_file(root).is_file():
        try:
            if not _recover_publish_transaction(root):
                raise HTTPException(status_code=409, detail="interrupted publish recovery journal is invalid")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"could not recover interrupted publish staging: {exc}") from None
    dirty = _all_changed_paths(root)
    if dirty:
        raise HTTPException(status_code=409, detail=(
            "working tree has uncommitted changes; "
            "resolve them before rollback: " + ", ".join(line.strip().split()[-1] for line in dirty)))
    head_message = _git("log", "-1", "--pretty=%s", root=root).stdout.strip()
    if not head_message.startswith("Publish v"):
        raise HTTPException(status_code=409, detail=(
            f"HEAD is not a publish commit ('{head_message}'); refusing to revert it"))

    before_version = _version(root)
    parent = _git("rev-parse", "HEAD", root=root).stdout.strip()
    pending_record = {
        "action": "rollback",
        "commit": "",
        "parent": parent,
        "message": f'Revert "{head_message}"',
        "version": "",
        "previous_version": before_version,
        "build_verified": False,
    }
    _write_json(_pending_publish_file(root), pending_record)
    revert = _git("revert", "--no-edit", "HEAD", root=root, check=False)
    if revert.returncode != 0:
        _git("revert", "--abort", root=root, check=False)
        _pending_publish_file(root).unlink(missing_ok=True)
        return {"ok": False, "error": f"git revert failed; nothing changed: {revert.stderr.strip()}", "steps": steps}

    full_commit = _git("rev-parse", "HEAD", root=root).stdout.strip()
    commit = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    version = _version(root)
    pending_record.update({"commit": full_commit, "version": version,
                           "message": _git("log", "-1", "--pretty=%s", root=root).stdout.strip()})
    _write_json(_pending_publish_file(root), pending_record)
    steps.append({"step": "revert", "ok": True, "detail": f"{commit} reverts {before_version} publish; version now {version}"})

    ok, detail = _run_build(strict=True, root=root)
    steps.append({"step": "build", "ok": ok, "detail": detail})
    if not ok:
        _git("reset", "--hard", "HEAD~1", root=root, check=False)
        _pending_publish_file(root).unlink(missing_ok=True)
        return {"ok": False, "error": f"build failed after revert, revert undone: {detail}", "steps": steps}

    pending_record["build_verified"] = True
    _write_json(_pending_publish_file(root), pending_record)

    try:
        _git("push", "origin", "HEAD:main", root=root, timeout=180)
        steps.append({"step": "push", "ok": True, "detail": "pushed main; workflow rebuilds gh-pages"})
    except Exception as exc:
        return {"ok": False, "error": f"push failed (revert commit {commit} is local only): {exc}",
                "steps": steps, "commit": commit}

    live_ok, live_detail = _live_version()
    steps.append({"step": "live", "ok": live_ok, "detail": live_detail})
    if not live_ok:
        return {"ok": False, "error": live_detail, "commit": commit,
                "version": version, "steps": steps}
    _pending_publish_file(root).unlink(missing_ok=True)
    return {"ok": True, "version": version, "commit": commit, "steps": steps}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("FL_HOST", "127.0.0.1"),
        port=int(os.environ.get("FL_PORT", "8100")),
        log_level="info",
    )
