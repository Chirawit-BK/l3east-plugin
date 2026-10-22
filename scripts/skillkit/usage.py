#!/usr/bin/env python3
"""Count Skill invocations, slash commands and MCP tool calls in Claude Code transcripts.

The transcript format is undocumented and may change; this script fails soft.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import claude_home, write_json  # noqa: E402

CMD_RE = re.compile(r"<command-name>([^<]+)</command-name>")


def bump(table: dict, key: str, slug: str) -> None:
    row = table.setdefault(key, {"total": 0, "by_project": {}})
    row["total"] += 1
    row["by_project"][slug] = row["by_project"].get(slug, 0) + 1


def scan_file(path: Path, slug: str, acc: dict, stats: dict) -> None:
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "<command-name>" in line:
                for c in CMD_RE.findall(line):
                    bump(acc["slash"], c.strip(), slug)
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                stats["tool_uses"] += 1
                name = str(block.get("name", ""))
                if name == "Skill":
                    skill = (block.get("input") or {}).get("skill")
                    if skill:
                        bump(acc["skills"], str(skill), slug)
                elif name.startswith("mcp__"):
                    parts = name.split("__")
                    if len(parts) >= 2 and parts[1]:
                        bump(acc["mcp_servers"], parts[1], slug)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projects-dir", default=None, help="defaults to <claude-home>/projects")
    ap.add_argument("--claude-home", default=None)
    ap.add_argument("--since", type=int, default=30, help="days; files older than this are skipped")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    home = Path(a.claude_home).resolve() if a.claude_home else claude_home()
    projects = Path(a.projects_dir).resolve() if a.projects_dir else home / "projects"
    cutoff = time.time() - a.since * 86400
    acc = {"skills": {}, "slash": {}, "mcp_servers": {}}
    stats = {"files": 0, "tool_uses": 0, "bad_lines": 0}
    warnings: list[str] = []

    if not projects.is_dir():
        warnings.append(f"projects dir not found: {projects}")
    else:
        for f in sorted(projects.rglob("*.jsonl")):
            try:
                if f.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            slug = f.relative_to(projects).parts[0]
            stats["files"] += 1
            try:
                scan_file(f, slug, acc, stats)
            except OSError as exc:
                warnings.append(f"unreadable {f}: {exc}")

    status = "ok"
    if stats["files"] > 0 and stats["tool_uses"] == 0:
        status = "unavailable"
        warnings.append("no tool_use records parsed; transcript format may have changed. Ask the user to run /skill-doctor instead.")
    elif stats["files"] == 0:
        status = "unavailable"
        warnings.append("no transcripts in window; run /skill-doctor for usage.")

    write_json(a.out, {
        "status": status,
        "since_days": a.since,
        "files_scanned": stats["files"],
        "tool_uses_seen": stats["tool_uses"],
        "bad_lines": stats["bad_lines"],
        "skills": acc["skills"],
        "slash": acc["slash"],
        "mcp_servers": acc["mcp_servers"],
        "warnings": warnings,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
