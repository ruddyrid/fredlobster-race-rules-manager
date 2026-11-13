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
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
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

app = FastAPI(title="Fred Lobster Race Rules Manager — backend", docs_url=None, redoc_url=None)

STATIC_DIR = BACKEND / "static"


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
    return _drafts_dir(root) / f"{sid}.md"


def _changed_paths(root: Path | None = None) -> list[str]:
    proc = _git("status", "--porcelain", "--", "docs", "mkdocs.yml", "requirements.txt",
                root=root, check=False)
    return [line for line in proc.stdout.splitlines() if line.strip()]


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
    for section in _sections():
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
    info["drafts"] = len(_drafts(path))
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
        "drafts": {"count": len(drafts), "sections": list(drafts)},
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


@app.get("/api/sections")
def sections() -> dict:
    root = _active_root()
    items = []
    for section in _sections(root):
        body = (root / "docs" / section["path"]).read_text() if section["exists"] else ""
        items.append({**{k: v for k, v in section.items() if k != "file"},
                      "last_published_version": _version(root),
                      "content": body})
    return {"version": _version(root), "sections": items}


@app.put("/api/draft/{section}")
def save_draft(section: str, payload: DraftIn) -> dict:
    root = _active_root()
    _section_or_404(section)
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="refusing to store an empty draft")
    _drafts_dir(root).mkdir(parents=True, exist_ok=True)
    _draft_file(section, root).write_text(payload.content)
    return {"ok": True, "section": section, "bytes": len(payload.content),
            "drafts": len(_drafts(root))}


@app.get("/api/diff")
def diff() -> dict:
    root = _active_root()
    entries, added, removed = [], 0, 0
    for sid, _meta in _drafts(root).items():
        section = _section_or_404(sid) if any(s["id"] == sid for s in _sections(root)) else None
        if section is None:
            continue
        published = (root / "docs" / section["path"]).read_text().splitlines(keepends=True)
        draft = _draft_file(sid, root).read_text().splitlines(keepends=True)
        text = "".join(difflib.unified_diff(
            published, draft,
            fromfile=f"published/{section['path']}",
            tofile=f"draft/{section['path']}",
        ))
        added += sum(1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++"))
        removed += sum(1 for line in text.splitlines() if line.startswith("-") and not line.startswith("---"))
        entries.append({"section": sid, "path": section["path"], "diff": text, "changed": bool(text)})
    return {"version": _version(root), "added": added, "removed": removed, "entries": entries}


@app.post("/api/publish")
def publish(payload: PublishIn | None = None) -> dict:
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str) -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})

    root = _active_root()
    drafts = _drafts(root)
    if not drafts:
        raise HTTPException(status_code=409, detail="nothing to publish: no drafts saved")

    dirty = _changed_paths(root)
    if dirty:
        raise HTTPException(status_code=409, detail=(
            "working tree has uncommitted changes in the published sources; "
            "commit or discard them before publishing so the publish stays one clean commit: "
            + ", ".join(line.strip().split()[-1] for line in dirty)))

    problem = _validate(root)
    if problem:
        step("validate", False, problem)
        return {"ok": False, "error": problem, "steps": steps}
    step("validate", True, "all nav sections present, non-empty, mkdocs build --strict clean")

    known = {s["id"]: s for s in _sections(root)}
    changed_titles = [known[sid]["title"] for sid in drafts if sid in known]
    summary = ", ".join(changed_titles) + " updated" if changed_titles else "content updated"

    old_version, new_version = _version(root), _bump(_version(root))
    try:
        for sid, _meta in drafts.items():
            section = known.get(sid)
            if section is None:
                raise RuntimeError(f"draft '{sid}' has no matching section")
            (root / "docs" / section["path"]).write_text(_draft_file(sid, root).read_text())
        _stamp_version(new_version)
        _append_changelog(new_version, summary + (f" ({payload.message})" if payload and payload.message else ""))
        step("stage", True, f"drafts applied, footer stamped {new_version}, changelog entry added")
    except Exception as exc:
        _git("checkout", "--", "docs", "mkdocs.yml", root=root, check=False)
        return {"ok": False, "error": str(exc), "steps": steps}

    ok, detail = _run_build(strict=True, root=root)
    step("build", ok, detail)
    if not ok:
        _git("checkout", "--", "docs", "mkdocs.yml", root=root, check=False)
        return {"ok": False, "error": f"build failed, nothing published: {detail}", "steps": steps}

    try:
        _git("add", "--", "docs", "mkdocs.yml", root=root)
        message = f"Publish {new_version}: {summary}"
        if payload and payload.message:
            message += f" — {payload.message}"
        _git("commit", "-m", message, root=root)
        commit = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
        step("commit", True, f"{commit} {message}")
    except Exception as exc:
        return {"ok": False, "error": f"commit failed: {exc}", "steps": steps}

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

    for sid in list(drafts):
        _draft_file(sid, root).unlink(missing_ok=True)
    site_url = _site_url(root)
    return {"ok": True, "version": new_version, "previous_version": old_version,
            "commit": commit, "site_url": site_url + "?_cb=" + str(int(time.time())),
            "steps": steps}


@app.post("/api/rollback")
def rollback() -> dict:
    steps: list[dict] = []
    root = _active_root()
    head_message = _git("log", "-1", "--pretty=%s", root=root).stdout.strip()
    if not head_message.startswith("Publish v"):
        raise HTTPException(status_code=409, detail=(
            f"HEAD is not a publish commit ('{head_message}'); refusing to revert it"))

    before_version = _version(root)
    revert = _git("revert", "--no-edit", "HEAD", root=root, check=False)
    if revert.returncode != 0:
        _git("revert", "--abort", root=root, check=False)
        return {"ok": False, "error": f"git revert failed; nothing changed: {revert.stderr.strip()}", "steps": steps}

    commit = _git("rev-parse", "--short", "HEAD", root=root).stdout.strip()
    version = _version(root)
    steps.append({"step": "revert", "ok": True, "detail": f"{commit} reverts {before_version} publish; version now {version}"})

    ok, detail = _run_build(strict=True, root=root)
    steps.append({"step": "build", "ok": ok, "detail": detail})
    if not ok:
        _git("reset", "--hard", "HEAD~1", root=root, check=False)
        return {"ok": False, "error": f"build failed after revert, revert undone: {detail}", "steps": steps}

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
    return {"ok": True, "version": version, "commit": commit, "steps": steps}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("FL_HOST", "127.0.0.1"),
        port=int(os.environ.get("FL_PORT", "8100")),
        log_level="info",
    )
