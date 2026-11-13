#!/usr/bin/env python3
"""fred — terminal client for the Fred Lobster race rules backend.

Talks only to the backend HTTP API (default http://127.0.0.1:8100) and never
edits rule files directly. Standard library only: argparse + urllib.

A workspace is one race rules directory (its own repo, version and drafts).
`fred workspace` lists, switches, creates and forgets workspaces; `fred tmux`
builds a Herdr layout: editor, backend log, and an overview pane that is the numbered fred menu.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API_ENV = os.environ.get("FRED_API", "").rstrip("/")
# The backend binds localhost or the Tailscale address depending on deployment;
# try the explicit override first, then both defaults.
API_BASES = [API_ENV] if API_ENV else ["http://127.0.0.1:8100", "http://100.108.5.126:8100"]
PUBLISH_TIMEOUT = 420
MANAGER_ROOT = Path(__file__).resolve().parent.parent
FRED_BIN = MANAGER_ROOT / "fred" / "fred"
SHELLS = {"bash", "zsh", "sh", "fish", "dash", "ksh"}


class FredError(Exception):
    """Expected, user-facing failure."""


# --------------------------------------------------------------------------- HTTP


def _call(method: str, path: str, payload: dict | None = None, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    last_error: Exception | None = None
    for base in API_BASES:
        request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            if isinstance(detail, list):
                detail = "; ".join(
                    f"{'.'.join(str(part) for part in item.get('loc', []))}: {item.get('msg', 'invalid input')}"
                    for item in detail if isinstance(item, dict)
                ) or "invalid input"
            raise FredError(f"{method} {path} failed (HTTP {exc.code}): {detail}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            continue
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            raise FredError(f"the backend returned something that is not JSON: {body[:200]!r}") from None
    raise FredError(
        "cannot reach the backend at " + " or ".join(API_BASES) + f" ({last_error}).\n"
        "Is it running?  systemctl --user status fredlobster-backend"
    )


def _find_section(sections: list[dict], wanted: str) -> dict:
    key = wanted.strip()
    for section in sections:
        if key in (section["id"], section["path"], section["path"][:-3]):
            return section
    for section in sections:
        if section["title"].lower() == key.lower():
            return section
    ids = ", ".join(section["id"] for section in sections)
    raise FredError(f"unknown section {wanted!r}. Available: {ids}")


# --------------------------------------------------------------------------- workspaces


def _short_path(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def _truncate(text: str, width: int) -> str:
    text = str(text or "")
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def _workspace_rows(data: dict | None = None) -> dict:
    return data if data is not None else _call("GET", "/api/workspaces")


def _active_workspace(row: dict) -> dict | None:
    active = row.get("active") or ""
    for workspace in row.get("workspaces") or []:
        if workspace.get("path") == active:
            return workspace
    return None


def _print_workspaces(row: dict) -> None:
    workspaces = row.get("workspaces") or []
    if not workspaces:
        print("no workspaces known yet. Create one with:  fred workspace create <directory>")
        return
    active = row.get("active") or ""
    width = max(32, min(46, max(len(str(ws.get("title") or "")) for ws in workspaces)))
    print(f"{'#':>2}  {'workspace':<{width}}  {'version':<7}  directory")
    for index, workspace in enumerate(workspaces, 1):
        mark = "*" if workspace.get("path") == active else " "
        title = _truncate(workspace.get("title") or workspace.get("name") or "?", width)
        version = workspace.get("version") or "—"
        status = "" if workspace.get("valid") else "  (invalid)"
        print(f"{index:>2}{mark} {title:<{width}}  {version:<7}  {_short_path(workspace.get('path') or '')}{status}")
    active_ws = _active_workspace(row)
    if active_ws:
        site = active_ws.get("site_url") or "no site URL"
        print(f"\nactive: {active_ws.get('title')}  ({active_ws.get('path')})")
        print(f"site:   {site}")
    else:
        print("\nactive: none — choose one with  fred workspace use <directory>")


def _resolve_workspace(value: str, row: dict | None = None) -> str:
    """Accept a literal path, ~/path, or a unique part of a known workspace name."""
    value = (value or "").strip()
    if not value:
        raise FredError("a workspace directory (or part of its name) is required")

    if value.startswith("~") or os.sep in value:
        try:
            return str(Path(value).expanduser().resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise FredError(f"invalid workspace path: {exc}") from None

    row = _workspace_rows(row)
    workspaces = row.get("workspaces") or []
    exact = [ws for ws in workspaces if ws.get("name") == value or Path(ws.get("path") or "").name == value]
    if exact:
        return exact[0]["path"]
    matches = [ws for ws in workspaces if value.lower() in str(ws.get("name") or "").lower()]
    if len(matches) == 1:
        return matches[0]["path"]
    if len(matches) > 1:
        names = ", ".join(ws.get("name") or ws.get("path") or "?" for ws in matches)
        raise FredError(f"{value!r} matches several workspaces: {names}")
    # No match: treat it as a directory inside the home folder.
    try:
        return str((Path.home() / value).resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise FredError(f"invalid workspace path: {exc}") from None


def _use_workspace(path: str, quiet: bool = False) -> dict:
    result = _call("POST", "/api/workspaces/select", {"path": path})
    workspace = result.get("workspace") or {}
    if not quiet:
        print(f"active workspace: {workspace.get('title')}  ({workspace.get('path')})")
        print(f"  version {workspace.get('version') or '—'}   repo {workspace.get('repo_url') or 'none'}")
        print(f"  site    {workspace.get('site_url') or 'no GitHub Pages URL'}")
    return workspace


def _create_workspace(path: str, mode: str, source: str | None, title: str | None,
                      year: int | None, repo: str | None, git_init: bool,
                      activate: bool, timeout: int = 300) -> tuple[dict, list[str]]:
    payload = {
        "path": path,
        "mode": mode,
        "source_path": source,
        "title": title or None,
        "year": year,
        "repo_url": repo or None,
        "git_init": git_init,
        "activate": activate,
    }
    result = _call("POST", "/api/workspaces/create", payload, timeout=timeout)
    return result.get("workspace") or {}, result.get("warnings") or []


def _print_created(workspace: dict, warnings: list[str], activated: bool) -> None:
    print(f"created {workspace.get('title')}  ({workspace.get('path')})")
    print(f"  version {workspace.get('version') or '—'}   git {workspace.get('branch') or 'none'} @ {workspace.get('head') or '—'}")
    if workspace.get("site_url"):
        print(f"  site    {workspace['site_url']}")
    for warning in warnings:
        print(f"  warning {warning}")
    if activated:
        print("active workspace switched to the new directory")


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _pause() -> None:
    try:
        input("\npress Enter to return to the menu…")
    except EOFError:
        pass


def _prompt_create(mode: str, row: dict) -> None:
    suggested = row.get("suggested") or {}
    valid_workspaces = [workspace for workspace in row.get("workspaces", []) if workspace.get("valid")]
    source_default = row.get("active") or (valid_workspaces[0].get("path") if valid_workspaces else "")
    print(f"\ncreate a new workspace {'from the blank template' if mode == 'blank' else 'by copying an existing one'}")

    path = _ask("directory", suggested.get("path") or "")
    year_text = _ask("year", str(suggested.get("year") or ""))
    try:
        year = int(year_text) if year_text else None
    except ValueError:
        raise FredError(f"year must be a number, got {year_text!r}") from None
    if year is not None and not 2000 <= year <= 2100:
        raise FredError("year must be between 2000 and 2100")
    title_default = suggested.get("title") or (f"Fred Lobster Race Rules {year}" if year else "")
    if year is not None and year != suggested.get("year"):
        title_default = f"Fred Lobster Race Rules {year}"
    title = _ask("title", title_default)
    repo = _ask("GitHub repo URL (optional)", "")
    source = _ask("copy from", source_default) if mode == "copy" else None
    git_init = _ask("initialize git? [Y/n]", "y").lower() not in {"n", "no"}

    workspace, warnings = _create_workspace(
        path, mode, source, title, year, repo, git_init, activate=True,
    )
    _print_created(workspace, warnings, activated=True)


def _prompt_switch(row: dict) -> None:
    workspaces = row.get("workspaces") or []
    if not workspaces:
        return
    choice = _ask("number to switch to (blank cancels)", "")
    if not choice:
        return
    if not choice.isdigit() or not (1 <= int(choice) <= len(workspaces)):
        print("not a listed number")
        return
    _use_workspace(workspaces[int(choice) - 1]["path"])


def _prompt_add(row: dict) -> None:
    value = _ask("existing rules directory (docs/ + mkdocs.yml)", "")
    if not value:
        return
    _use_workspace(_resolve_workspace(value, row))


def _prompt_forget(row: dict) -> None:
    workspaces = row.get("workspaces") or []
    active = row.get("active") or ""
    removable = [(index, ws) for index, ws in enumerate(workspaces, 1) if ws.get("path") != active]
    if not removable:
        print("nothing else in the list")
        return
    print("\nremove from the list (files are not deleted):")
    for index, workspace in removable:
        print(f"  {index:>2}  {workspace.get('title')}  ({_short_path(workspace.get('path') or '')})")
    choice = _ask("number to remove (blank cancels)", "")
    if not choice:
        return
    selected = next((ws for index, ws in removable if str(index) == choice), None)
    if selected is None:
        print("not a listed number")
        return
    _call("POST", "/api/workspaces/forget", {"path": selected["path"]})
    print(f"removed {selected.get('title')} from the workspace list")


def _workspace_menu() -> None:
    while True:
        try:
            row = _workspace_rows()
        except FredError as exc:
            print(f"\n{exc}")
            print("Is fredlobster-backend running?  systemctl --user status fredlobster-backend")
            _pause()
            return

        try:
            print("\033[2J\033[H", end="")
        except OSError:
            pass
        print("Race rules workspaces")
        print("--------------------")
        _print_workspaces(row)
        print("\n  [number] switch   n new   c copy   a add existing   r remove   l refresh   q quit")

        try:
            choice = input("\nworkspace> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        try:
            if choice in {"q", "quit", "exit"}:
                return
            if choice in {"", "l", "list"}:
                continue
            if choice in {"n", "new"}:
                _prompt_create("blank", row)
            elif choice in {"c", "copy"}:
                _prompt_create("copy", row)
            elif choice in {"a", "add"}:
                _prompt_add(row)
            elif choice in {"r", "remove", "forget"}:
                _prompt_forget(row)
            elif choice.isdigit():
                workspaces = row.get("workspaces") or []
                if 1 <= int(choice) <= len(workspaces):
                    _use_workspace(workspaces[int(choice) - 1]["path"])
                else:
                    print("not a listed number")
            else:
                print("unknown choice")
        except FredError as exc:
            print(f"error: {exc}")
        _pause()


def cmd_workspace(args: argparse.Namespace) -> None:
    action = args.action or "menu"
    if action == "menu" and not sys.stdin.isatty():
        action = "list"

    if action == "list":
        _print_workspaces(_workspace_rows())
        return

    if action in {"use", "add"}:
        if not args.value:
            raise FredError(f"usage: fred workspace {action} <directory-or-name>")
        _use_workspace(_resolve_workspace(args.value))
        return

    if action == "forget":
        if not args.value:
            raise FredError("usage: fred workspace forget <directory-or-name>")
        row = _workspace_rows()
        path = _resolve_workspace(args.value, row)
        _call("POST", "/api/workspaces/forget", {"path": path})
        print(f"removed {_short_path(path)} from the workspace list (files untouched)")
        return

    if action == "create":
        if not args.value:
            raise FredError(
                "usage: fred workspace create <directory> [--from SOURCE | --mode copy] "
                "[--title TITLE] [--year YEAR] [--repo URL] [--no-git] [--no-switch]"
            )
        if args.mode == "blank" and args.source is not None:
            raise FredError("--from cannot be used with --mode blank")
        mode = args.mode or ("copy" if args.source is not None else "blank")
        source = args.source
        if mode == "copy" and not source:
            row = _workspace_rows()
            source = row.get("active") or next(
                (workspace.get("path") for workspace in row.get("workspaces", [])
                 if workspace.get("valid")),
                "",
            )
            if not source:
                raise FredError("--from is required when there is no active workspace to copy")
        workspace, warnings = _create_workspace(
            args.value, mode, source, args.title, args.year, args.repo,
            git_init=not args.no_git, activate=not args.no_switch,
        )
        _print_created(workspace, warnings, activated=not args.no_switch)
        return

    if action == "menu":
        _workspace_menu()
        return

    raise FredError(f"unknown workspace action {action!r}")


# --------------------------------------------------------------------------- commands


def cmd_status(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/status")
    git = data["git"]
    drafts = data["drafts"]
    workspace = data.get("workspace") or {}
    print(data["site"])
    if workspace:
        print(f"  workspace {workspace.get('title')}   ({workspace.get('path')})")
    stamp = data["version_stamp"].replace("&nbsp;", " ").replace(data["site"], "")
    stamp = " ".join(stamp.replace("·", " ").split())
    stamp = stamp.replace(data["version"], "", 1).strip().strip("() ")
    print(f"  version   {data['version']}   ({stamp})")
    draft_text = str(drafts["count"])
    if drafts["count"]:
        draft_text += " — " + ", ".join(drafts["sections"])
    print(f"  drafts    {draft_text}")
    print(f"  git       {git['branch']} @ {git['head']}")
    if git["clean"]:
        print("  working   clean")
    else:
        print("  working   UNCOMMITTED: " + ", ".join(git["uncommitted"]))
    if git["in_sync"] is None:
        print(f"  github    unknown ({git['error']})")
    elif git["in_sync"]:
        print("  github    in sync with origin/main")
    else:
        print(f"  github    out of sync (ahead {git['ahead']}, behind {git['behind']})")
    print(f"  site      {data['site_url']}")


def cmd_sections(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/sections")
    sections = data["sections"]
    width = max(len(section["id"]) for section in sections)
    print(f"sections ({data['version']}):")
    for section in sections:
        print(f"  {section['id']:<{width}}  {section['title']:<28}  docs/{section['path']}")


def _show_rendered(text: str) -> bool:
    """Open Markdown in glow. False means the caller should print plain text."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    glow = shutil.which("glow")
    if not glow:
        return False
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", prefix="fred-show-", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(text)
        path = Path(handle.name)
    try:
        subprocess.run([glow, str(path)], check=False)
    except OSError:
        return False
    finally:
        path.unlink(missing_ok=True)
    return True


def cmd_show(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/sections")
    section = _find_section(data["sections"], args.section)
    text = section["content"].rstrip("\n") + "\n"
    if not args.plain and _show_rendered(text):
        return
    sys.stdout.write(text)


def cmd_edit(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/sections")
    section = _find_section(data["sections"], args.section)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise FredError("no editor set. Export one first, e.g.  export EDITOR=nano")

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", prefix=f"fred-{section['id']}-", delete=False, encoding="utf-8")
    try:
        handle.write(section["content"])
        handle.close()
        path = Path(handle.name)
        print(f"DRAFT — editing {section['title']} ({section['id']})")
        print("The public site will not change until you run:  fred publish")
        try:
            subprocess.run(shlex.split(editor) + [str(path)], check=False)
        except FileNotFoundError:
            raise FredError(f"editor not found: {editor}") from None
        edited = path.read_text(encoding="utf-8")
    finally:
        Path(handle.name).unlink(missing_ok=True)

    if edited == section["content"]:
        print("no changes — no draft saved")
        return
    result = _call("PUT", f"/api/draft/{section['id']}", {"content": edited})
    print(f"draft saved for {section['id']} ({result['bytes']} bytes, {result['drafts']} draft(s) open)")
    print("Review with:  fred diff      Publish with:  fred publish")


def cmd_diff(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/diff")
    entries = [entry for entry in data["entries"] if entry["changed"]]
    if not entries:
        print("no drafts — the working copy matches the published rulebook")
        return
    for entry in entries:
        text = entry["diff"].rstrip("\n")
        if sys.stdout.isatty():
            for line in text.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    print(f"\033[32m{line}\033[0m")
                elif line.startswith("-") and not line.startswith("---"):
                    print(f"\033[31m{line}\033[0m")
                elif line.startswith("@@"):
                    print(f"\033[36m{line}\033[0m")
                else:
                    print(line)
        else:
            print(text)
    print(f"\n{data['added']} added, {data['removed']} removed (draft vs published)")


def cmd_publish(args: argparse.Namespace) -> None:
    result = _call("POST", "/api/publish", timeout=PUBLISH_TIMEOUT)
    for step in result.get("steps", []):
        mark = "ok  " if step["ok"] else "FAIL"
        print(f"  [{mark}] {step['step']}: {step['detail']}")
    if not result.get("ok"):
        raise FredError(result.get("error") or "publish failed")
    print(f"published {result.get('previous_version', '?')} -> {result['version']}")
    print(f"  commit  {result['commit']}")
    print(f"  live    {result['site_url']}")


def cmd_rollback(args: argparse.Namespace) -> None:
    result = _call("POST", "/api/rollback", timeout=PUBLISH_TIMEOUT)
    for step in result.get("steps", []):
        mark = "ok  " if step["ok"] else "FAIL"
        print(f"  [{mark}] {step['step']}: {step['detail']}")
    if not result.get("ok"):
        raise FredError(result.get("error") or "rollback failed")
    print(f"rolled back to {result['version']} (commit {result['commit']})")


# --------------------------------------------------------------------------- herdr layout


def _herdr(*args: str, check: bool = True) -> dict:
    herdr = shutil.which("herdr")
    if not herdr:
        raise FredError("herdr is not installed; fred tmux needs Herdr")
    proc = subprocess.run([herdr, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}"
        if check:
            raise FredError(f"herdr {' '.join(args)} failed: {detail}")
        return {"error": detail}
    text = proc.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _herdr_result(payload: dict) -> dict:
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _herdr_current() -> dict:
    pane_id = os.environ.get("HERDR_PANE_ID", "")
    if pane_id:
        result = _herdr_result(_herdr("pane", "get", pane_id, check=False))
        pane = result.get("pane")
        if isinstance(pane, dict):
            return pane
    result = _herdr_result(_herdr("pane", "current", "--current", check=False))
    pane = result.get("pane")
    return pane if isinstance(pane, dict) else {}


def _herdr_panes(workspace_id: str) -> list[dict]:
    result = _herdr_result(_herdr("pane", "list", "--workspace", workspace_id, check=False))
    panes = result.get("panes")
    return panes if isinstance(panes, list) else []


def _pane_processes(pane_id: str) -> list[dict]:
    result = _herdr_result(_herdr("pane", "process-info", "--pane", pane_id, check=False))
    info = result.get("process_info") or {}
    processes = info.get("foreground_processes")
    return processes if isinstance(processes, list) else []


def _process_name(process: dict) -> str:
    name = str(process.get("name") or "")
    return name.rsplit("/", 1)[-1].lower()


def _idle_shell(pane_id: str) -> tuple[bool, str]:
    processes = _pane_processes(pane_id)
    if not processes:
        return True, ""
    if {_process_name(process) for process in processes} <= SHELLS:
        return True, ""
    detail = ", ".join(str(process.get("cmdline") or process.get("name") or "?")
                       for process in processes)
    return False, detail


def _wait_for_shell(pane_id: str, timeout: float = 6.0) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout
    detail = ""
    while True:
        ok, detail = _idle_shell(pane_id)
        if ok or time.monotonic() >= deadline:
            return ok, detail
        time.sleep(0.25)


def _already_running(label: str, pane_id: str) -> bool:
    processes = _pane_processes(pane_id)
    if not processes:
        return False
    cmdline = " ".join(str(process.get("cmdline") or "") for process in processes)
    if label == "log":
        return "journalctl" in cmdline and "fredlobster-backend" in cmdline
    if label == "overview":
        return "fred.py" in cmdline and " tmux" in cmdline
    return False


def _split_pane(parent: str, direction: str, cwd: str, label: str, dry_run: bool) -> str:
    if dry_run:
        return f"<new {label}>"
    result = _herdr_result(_herdr(
        "pane", "split", parent, "--direction", direction, "--cwd", cwd, "--no-focus",
    ))
    pane = result.get("pane") or {}
    pane_id = pane.get("pane_id")
    if not pane_id:
        raise FredError(f"herdr did not return a pane id for the new {label} pane")
    _herdr("pane", "rename", pane_id, label, check=False)
    return str(pane_id)


def _run_in_pane(label: str, pane_id: str, command: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  {label:<9} {pane_id}  {command}")
        return
    if _already_running(label, pane_id):
        print(f"  {label:<9} {pane_id}  already running — left alone")
        return
    ok, detail = _wait_for_shell(pane_id)
    if not ok:
        print(f"  {label:<9} {pane_id}  busy ({detail}) — left alone")
        return
    result = _herdr("pane", "run", pane_id, command, check=False)
    if result.get("error"):
        print(f"  {label:<9} {pane_id}  could not start ({result['error']})")
        return
    print(f"  {label:<9} {pane_id}  {command}")


HUB_ROLE_ENV = "FRED_TMUX_PANE"
HUB_MENU = [
    ("1", "Status"),
    ("2", "List sections"),
    ("3", "Read a section (glow)"),
    ("4", "Edit a section (draft, opens $EDITOR here)"),
    ("5", "Review drafts (diff)"),
    ("6", "Publish drafts to the live site"),
    ("7", "Roll back the last publish"),
    ("8", "Workspaces: switch, NEW rules directory, copy, add, remove"),
    ("q", "Quit this pane"),
]


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def _hub_header() -> None:
    try:
        data = _call("GET", "/api/status")
    except FredError as exc:
        print(f"  {exc}")
        return
    workspace = data.get("workspace") or {}
    clean = "clean" if data["git"]["clean"] else "UNCOMMITTED changes"
    print(f"  {workspace.get('title') or 'no workspace'}   version {data['version']}")
    print(f"  drafts {data['drafts']['count']}   working copy {clean}   branch {data['git']['branch']}")


def _pick_section() -> str:
    sections = _call("GET", "/api/sections")["sections"]
    for index, section in enumerate(sections, 1):
        print(f"  {index:>2}  {section['title']:<28}  {section['id']}")
    choice = _ask("section number or name (blank cancels)", "")
    if not choice:
        return ""
    if choice.isdigit() and 1 <= int(choice) <= len(sections):
        return sections[int(choice) - 1]["id"]
    return choice


def _confirm(question: str) -> bool:
    return _ask(f"{question} Type yes to continue", "").lower() in {"y", "yes"}


def _hub_action(choice: str) -> bool:
    """Run one hub choice. False means the pane returns to the menu without a pause."""
    if choice == "1":
        cmd_status(_ns())
    elif choice == "2":
        cmd_sections(_ns())
    elif choice in {"3", "4"}:
        section = _pick_section()
        if not section:
            print("cancelled")
        elif choice == "3":
            cmd_show(_ns(section=section, plain=False))
        else:
            cmd_edit(_ns(section=section))
    elif choice == "5":
        cmd_diff(_ns())
    elif choice == "6":
        if _confirm("Publish all drafts to the live site?"):
            cmd_publish(_ns())
        else:
            print("publish cancelled")
    elif choice == "7":
        if _confirm("Roll back the last publish on the live site?"):
            cmd_rollback(_ns())
        else:
            print("rollback cancelled")
    elif choice == "8":
        _workspace_menu()
        return False
    else:
        print("unknown choice")
    return True


def _hub() -> None:
    """Interactive menu for the overview pane: every common action is a number."""
    while True:
        try:
            print("\033[2J\033[H", end="")
        except OSError:
            pass
        print("Fred Lobster race rules")
        print("-----------------------")
        _hub_header()
        print()
        for key, label in HUB_MENU:
            print(f"  {key}  {label}")
        try:
            choice = input("\nfred> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in {"q", "quit", "exit"}:
            return
        if not choice:
            continue
        try:
            if _hub_action(choice):
                _pause()
        except FredError as exc:
            print(f"error: {exc}")
            _pause()
        except (EOFError, KeyboardInterrupt):
            print()
            return


def _herdr_layout(pane_id: str) -> dict:
    result = _herdr_result(_herdr("pane", "layout", "--pane", pane_id, check=False))
    layout = result.get("layout")
    return layout if isinstance(layout, dict) else {}


def _match_fred_layout(layout: dict, caller: str) -> tuple[str, str] | None:
    """(overview_id, log_id) when the tab is exactly the fred three-pane geometry.

    Editor is the caller at top-left; log sits directly below it in the same
    column; overview fills the full height to the right.
    """
    panes = layout.get("panes") or []
    area = layout.get("area") or {}
    if len(panes) != 3 or not area:
        return None
    rects = {str(pane.get("pane_id")): pane.get("rect") or {} for pane in panes}
    me = rects.get(caller)
    if not me:
        return None
    tol = 1
    cx, cy = me["x"], me["y"]
    cw, ch = me["width"], me["height"]
    if abs(cx - area.get("x", 0)) > tol or abs(cy - area.get("y", 0)) > tol:
        return None
    overview = log = None
    for pane_id, rect in rects.items():
        if pane_id == caller:
            continue
        if abs(rect["x"] - (cx + cw)) <= tol and abs(rect["y"] - area.get("y", 0)) <= tol \
                and abs(rect["height"] - area.get("height", 0)) <= tol:
            overview = pane_id
        elif abs(rect["x"] - cx) <= tol and abs(rect["y"] - (cy + ch)) <= tol \
                and abs(rect["width"] - cw) <= tol:
            log = pane_id
    if overview and log:
        return overview, log
    return None


def cmd_tmux(args: argparse.Namespace) -> None:
    if os.environ.get(HUB_ROLE_ENV) == "hub":
        _hub()
        return

    dry_run = bool(getattr(args, "dry_run", False))
    workdir = Path.cwd().resolve()
    in_herdr = os.environ.get("HERDR_ENV") == "1"

    print("fred tmux — Herdr working layout")
    print(f"  manager   {MANAGER_ROOT}")
    print(f"  cwd       {workdir}")
    print()

    if not in_herdr:
        print("You are not inside Herdr (HERDR_ENV != 1).")
        print("Start/attach Herdr, open a pane, then run:")
        print("  herdr")
        print("  fred tmux")
        print()
        print("Layout it creates: editor (left, top), log (left, bottom),")
        print("overview (right, full height) = the numbered fred menu.")
        return

    current = _herdr_current()
    caller = str(current.get("pane_id") or os.environ.get("HERDR_PANE_ID") or "")
    if not caller:
        raise FredError("could not determine the current Herdr pane")
    workspace_id = str(current.get("workspace_id") or os.environ.get("HERDR_WORKSPACE_ID") or "")
    tab_id = str(current.get("tab_id") or os.environ.get("HERDR_TAB_ID") or "")
    if not workspace_id:
        raise FredError("could not determine the Herdr workspace id")
    if not tab_id:
        raise FredError("could not determine the Herdr tab id")

    panes = [pane for pane in _herdr_panes(workspace_id) if pane.get("tab_id") == tab_id]
    by_label: dict[str, dict] = {}
    for pane in panes:
        label = str(pane.get("label") or "").strip()
        if label and label not in by_label:
            by_label[label] = pane

    duplicate_editor = by_label.get("editor")
    if duplicate_editor and duplicate_editor.get("pane_id") != caller:
        if dry_run:
            print(f"plan: clear duplicate editor label on {duplicate_editor.get('pane_id')}")
        else:
            _herdr("pane", "rename", str(duplicate_editor["pane_id"]), "--clear", check=False)
            by_label.pop("editor", None)

    if not dry_run:
        _herdr("pane", "rename", caller, "editor", check=False)

    layout = _herdr_layout(caller)
    geometry = _match_fred_layout(layout, caller)
    if geometry:
        overview_id, log_id = geometry
    else:
        tab_ids = {str(pane.get("pane_id")) for pane in panes}
        tab_ids |= {str(pane.get("pane_id")) for pane in layout.get("panes") or []}
        others = sorted(pane_id for pane_id in tab_ids if pane_id != caller)
        if others:
            raise FredError(
                f"this tab already has {len(others)} other pane(s) and is not the fred three-pane "
                "layout, so fred tmux will not split it. Run it from a tab where the editor pane is "
                "the only pane, or from a tab already arranged as editor | overview with log below "
                "the editor."
            )
        overview_id = ""
        log_id = ""

    actions: list[str] = []
    if not overview_id:
        overview_id = _split_pane(caller, "right", str(workdir), "overview", dry_run)
        actions.append("overview")
    if not log_id:
        log_id = _split_pane(caller, "down", str(workdir), "log", dry_run)
        actions.append("log")

    if actions and not dry_run:
        time.sleep(0.4)
    if not dry_run:
        for label, pane_id in (("overview", overview_id), ("log", log_id)):
            if label not in actions:
                _herdr("pane", "rename", pane_id, label, check=False)

    fred_cmd = shlex.quote(str(FRED_BIN)) if FRED_BIN.is_file() else "fred"
    api_url = os.environ.get("FRED_API", "").strip()
    api_prefix = f"FRED_API={shlex.quote(api_url)} " if api_url else ""
    commands = {
        "overview": (overview_id, f"{api_prefix}{HUB_ROLE_ENV}=hub {fred_cmd} tmux"),
        "log": (log_id, "journalctl --user -u fredlobster-backend -f"),
    }

    print(f"  editor    {caller}  (focus stays here; use: fred edit <section>)")
    for label in ("overview", "log"):
        pane_id, command = commands[label]
        _run_in_pane(label, pane_id, command, dry_run)

    if dry_run:
        print("\ndry run — nothing was changed")
        return
    print("\nLayout ready. In the overview pane (right), type a number to act.")


# --------------------------------------------------------------------------- entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fred",
        description="Terminal client for the Fred Lobster race rules backend.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    status = sub.add_parser("status", help="workspace, version, drafts, git/sync state")
    status.set_defaults(func=cmd_status)

    sections = sub.add_parser("sections", help="list rule sections")
    sections.set_defaults(func=cmd_sections)

    show = sub.add_parser("show", help="open a section in glow (plain Markdown when piped)")
    show.add_argument("section", help="section id, path, or title (see `fred sections`)")
    show.add_argument(
        "-p", "--plain", action="store_true",
        help="print the raw Markdown instead of rendering with glow",
    )
    show.set_defaults(func=cmd_show)

    edit = sub.add_parser("edit", help="edit a section as a draft in $EDITOR")
    edit.add_argument("section", help="section id, path, or title (see `fred sections`)")
    edit.set_defaults(func=cmd_edit)

    diff = sub.add_parser("diff", help="draft vs published, line by line")
    diff.set_defaults(func=cmd_diff)

    publish = sub.add_parser("publish", help="run the backend publish pipeline")
    publish.set_defaults(func=cmd_publish)

    rollback = sub.add_parser("rollback", help="restore the previous published version")
    rollback.set_defaults(func=cmd_rollback)

    workspace = sub.add_parser(
        "workspace",
        help="list, switch, create and forget race rules workspaces (interactive by default)",
    )
    workspace.add_argument(
        "action", nargs="?", default="menu",
        choices=["menu", "list", "use", "add", "create", "forget"],
        help="menu (default), list, use, add, create, forget",
    )
    workspace.add_argument(
        "value", nargs="?",
        help="directory or part of a workspace name (use/add/forget/create)",
    )
    workspace.add_argument("--from", dest="source", help="copy an existing workspace from this directory")
    workspace.add_argument("--mode", choices=["blank", "copy"], help="create from a blank template or copy")
    workspace.add_argument("--title", help="site title for a new workspace")
    workspace.add_argument("--year", type=int, help="season year for a new workspace")
    workspace.add_argument("--repo", help="GitHub repo URL for a new workspace")
    workspace.add_argument("--no-git", action="store_true", help="skip git init and the first commit")
    workspace.add_argument("--no-switch", action="store_true", help="create without making it active")
    workspace.set_defaults(func=cmd_workspace)

    tmux = sub.add_parser("tmux", help="build the fred Herdr layout (editor, log, numbered overview menu)")
    tmux.add_argument("--dry-run", action="store_true", help="show the plan without changing panes")
    tmux.set_defaults(func=cmd_tmux)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except FredError as exc:
        print(f"fred: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fred: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # never show a stack trace to the owner
        if os.environ.get("FRED_DEBUG"):
            raise
        print(f"fred: unexpected error: {exc} (set FRED_DEBUG=1 for details)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
