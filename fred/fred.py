#!/usr/bin/env python3
"""fred — terminal client for the Fred Lobster Race Rules 2027 backend.

Talks only to the backend HTTP API (default http://127.0.0.1:8100) and never
edits rule files directly. Standard library only: argparse + urllib.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API_ENV = os.environ.get("FRED_API", "").rstrip("/")
# The backend binds localhost or the Tailscale address depending on deployment;
# try the explicit override first, then both defaults.
API_BASES = [API_ENV] if API_ENV else ["http://127.0.0.1:8100", "http://100.108.5.126:8100"]
PUBLISH_TIMEOUT = 420


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


# --------------------------------------------------------------------------- commands


def cmd_status(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/status")
    git = data["git"]
    drafts = data["drafts"]
    print(data["site"])
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


def cmd_show(args: argparse.Namespace) -> None:
    data = _call("GET", "/api/sections")
    section = _find_section(data["sections"], args.section)
    sys.stdout.write(section["content"].rstrip("\n") + "\n")


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


# --------------------------------------------------------------------------- entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fred",
        description="Terminal client for the Fred Lobster Race Rules 2027 backend.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    status = sub.add_parser("status", help="published version, drafts, git/sync state")
    status.set_defaults(func=cmd_status)

    sections = sub.add_parser("sections", help="list rule sections")
    sections.set_defaults(func=cmd_sections)

    show = sub.add_parser("show", help="print a section's Markdown")
    show.add_argument("section", help="section id, path, or title (see `fred sections`)")
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
