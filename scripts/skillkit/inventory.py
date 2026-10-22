#!/usr/bin/env python3
"""Scan every skill and slash command Claude Code would load, write inventory.json."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DESC_LIMIT, claude_home, est_tokens, load_plugin_list, parse_frontmatter, read_json, write_json  # noqa: E402

FIRST_ACTION_RE = re.compile(
    r"(?i)(before any (?:response|action|other)|before (?:you |starting |doing )?anything|mandatory prerequisite"
    r"|must (?:be )?(?:invoked?|loaded?|called?|read)\b.{0,60}\bbefore\b|read (?:this )?(?:first|before)|call .{0,40}\bfirst\b)"
)
SLASH_RE = re.compile(r"(?<![\w/])/([a-z0-9][\w:-]{2,})(?![\w/-])")  # not a path segment like /docs/figma/
BACKTICK_RE = re.compile(r"`([a-z0-9][\w:-]{2,})`")
SYNCED_NAMESPACE = "anthropic-skills"  # the desktop app lists ~/.claude/skills/synced/* under this namespace
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9][\w.-]*$")


def plugin_namespace(root: Path, fallback: str) -> str:
    """Slash prefix of a plugin root: plugin.json `name` when present and sane, else the fallback."""
    name = (read_json(root / ".claude-plugin" / "plugin.json") or {}).get("name")
    return name.strip() if isinstance(name, str) and PLUGIN_NAME_RE.match(name.strip()) else fallback


def _backtick_mention(tok: str) -> bool:
    """A backticked word counts as a mention only if it looks like a skill name, not `dev` or `main`."""
    return len(tok) >= 5 or "-" in tok or ":" in tok


def _entry(md: Path, source: str, slash: str, kind: str) -> dict:
    text = md.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    desc = str(meta.get("description", "")).strip()
    if meta.get("when_to_use"):
        desc = (desc + " " + str(meta["when_to_use"])).strip()
    if not desc and kind == "command":
        stripped = body.strip()
        desc = stripped.splitlines()[0].strip() if stripped else ""
    name = str(meta.get("name") or (md.parent.name if kind == "skill" else md.stem))
    return {
        "name": name,
        "kind": kind,
        "source": source,
        "path": str(md),
        "slash_names": [slash],
        "description": desc,
        "desc_chars": len(desc),
        "est_tokens": est_tokens(desc),
        "truncated": len(desc) > DESC_LIMIT,
        "body_lines": body.count("\n") + 1 if body else 0,
        "mentions_skills": [],
        "first_action_claim": bool(FIRST_ACTION_RE.search(body)),
        "disable_model_invocation": meta.get("disable-model-invocation") is True,
        "user_invocable": meta.get("user-invocable") is not False,
        "has_scripts": (md.parent / "scripts").is_dir() if kind == "skill" else False,
        "has_references": (md.parent / "references").is_dir() if kind == "skill" else False,
        "enabled": True,
        "_raw_mentions": sorted(set(SLASH_RE.findall(body) + [t for t in BACKTICK_RE.findall(body) if _backtick_mention(t)])),
    }


class Scanner:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self.seen: set[str] = set()
        self.scanned: list[str] = []
        self.warnings: list[str] = []

    def add(self, entry: dict) -> None:
        if entry["path"] in self.seen:
            return
        self.seen.add(entry["path"])
        self.entries.append(entry)

    def skills_dir(self, root: Path, source: str, prefix: str) -> None:
        if not root.is_dir():
            return
        self.scanned.append(str(root))
        for md in sorted(root.glob("*/SKILL.md")):
            self.add(_entry(md, source, f"/{prefix}{md.parent.name}", "skill"))

    def commands_dir(self, root: Path, source: str, prefix: str) -> None:
        if not root.is_dir():
            return
        self.scanned.append(str(root))
        for md in sorted(root.glob("*.md")):
            self.add(_entry(md, source, f"/{prefix}{md.stem}", "command"))

    def plugin_root(self, root: Path, source: str, short: str) -> None:
        short = plugin_namespace(root, short)
        self.skills_dir(root / "skills", source, f"{short}:")
        self.commands_dir(root / "commands", source, f"{short}:")

    def personal_skills(self, home: Path) -> None:
        root = home / "skills"
        if not root.is_dir():
            return
        self.scanned.append(str(root))
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            if (d / "SKILL.md").is_file():
                self.add(_entry(d / "SKILL.md", "personal", f"/{d.name}", "skill"))
            elif (d / "skills").is_dir():
                self.plugin_root(d, f"plugin:{d.name}@skills-dir", d.name)
            elif d.name == "synced":
                for sess in sorted(p for p in d.iterdir() if p.is_dir()):
                    self.skills_dir(sess, f"plugin:{SYNCED_NAMESPACE}@synced", f"{SYNCED_NAMESPACE}:")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--claude-home", default=None)
    ap.add_argument("--plugin-list", default=None, help="JSON file used instead of `claude plugin list --json`")
    ap.add_argument("--extra", action="append", default=[], help="candidate skill dir or plugin root, scanned as source=candidate")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    home = Path(a.claude_home).resolve() if a.claude_home else claude_home()
    project = Path(a.project).resolve()
    sc = Scanner()

    sc.personal_skills(home)
    sc.skills_dir(project / ".claude" / "skills", "project", "")
    sc.commands_dir(home / "commands", "command:user", "")
    sc.commands_dir(project / ".claude" / "commands", "command:project", "")

    plugins, warnings = load_plugin_list(home, Path(a.plugin_list) if a.plugin_list else None)
    sc.warnings.extend(warnings)
    for p in plugins:
        if p.get("enabled") is False:
            continue
        pid = str(p.get("id", "?"))
        raw_path = str(p.get("installPath") or "").strip()
        if not raw_path:
            sc.warnings.append(f"plugin {pid}: installPath unknown (synced plugin); its skills are covered by the in-session listing step")
            continue
        root = Path(raw_path)
        if not root.is_dir():
            sc.warnings.append(f"installPath missing for {pid}: {root}")
            continue
        before = len(sc.entries)
        sc.plugin_root(root, f"plugin:{pid}", pid.split("@")[0])
        if p.get("enabled") == "unknown":
            for e in sc.entries[before:]:
                e["enabled"] = "unknown"

    for x in a.extra:
        root = Path(x).resolve()
        if (root / "SKILL.md").is_file():
            sc.add(_entry(root / "SKILL.md", "candidate", f"/{root.name}", "skill"))
        else:
            sc.plugin_root(root, f"candidate:{root.name}", root.name)

    names = {e["name"] for e in sc.entries}
    slash_to_name = {s.lstrip("/"): e["name"] for e in sc.entries for s in e["slash_names"]}
    for e in sc.entries:
        found = set()
        for tok in e.pop("_raw_mentions"):
            bare = tok.split(":")[-1]
            if tok in slash_to_name and slash_to_name[tok] != e["name"]:
                found.add(slash_to_name[tok])
            elif bare in names and bare != e["name"]:
                found.add(bare)
        e["mentions_skills"] = sorted(found)

    by_name: dict[str, list[str]] = {}
    for e in sc.entries:
        by_name.setdefault(e["name"], []).append(e["source"])
    same_name = {n: sorted(s) for n, s in by_name.items() if len(s) > 1}

    write_json(a.out, {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": str(project),
        "claude_home": str(home),
        "entries": sc.entries,
        "same_name": same_name,
        "est_listing_tokens": sum(e["est_tokens"] for e in sc.entries if not e["disable_model_invocation"]),
        "sources_scanned": sc.scanned,
        "warnings": sc.warnings,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
