#!/usr/bin/env python3
"""Merge hooks and MCP servers from every scope, flag overlaps and duplicates, mask secrets."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import claude_home, has_plaintext_secret, load_plugin_list, mask_secrets, mask_strings, mask_text, mask_url, read_json, write_json  # noqa: E402

PROJECT_TOOL_WORDS = ("pnpm", "npm ", "npx ", "yarn", "bun ", "pytest", "cargo ", "go test", "make ", "gradle", "mvn ")


def collect_hooks(cfg, source: str, hooks: dict) -> None:
    if not isinstance(cfg, dict):
        return
    table = cfg.get("hooks") if isinstance(cfg.get("hooks"), dict) else None
    if table is None and any(isinstance(v, list) for v in cfg.values()) and "modules" not in cfg:
        table = cfg  # bare {Event: [...]} form
    if isinstance(table, dict):
        for event, groups in table.items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                if not isinstance(g, dict):
                    continue
                matcher = g.get("matcher") or "*"
                for h in g.get("hooks") or []:
                    if not isinstance(h, dict):
                        continue
                    hooks.setdefault(event, []).append({
                        "source": source,
                        "matcher": matcher,
                        "type": h.get("type", "command"),
                        "command": mask_text(str(h.get("command") or h.get("module") or h.get("prompt") or "")),
                    })
    mods = cfg.get("modules")
    if isinstance(mods, list):
        hooks.setdefault("(mod modules)", []).extend(
            {"source": source, "matcher": "*", "type": "module", "command": mask_text(str(m))} for m in mods
        )


def collect_mcp(cfg, source: str, mcp: list) -> None:
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if not isinstance(servers, dict):
        return
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        masked = mask_strings(mask_secrets(spec))
        if spec.get("url"):
            kind = spec.get("type") or "http"
            base, sep, query = mask_url(str(spec["url"])).partition("?")
            key = "url:" + base.rstrip("/") + sep + query
        else:
            kind = spec.get("type") or "stdio"
            key = "cmd:" + mask_text(" ".join([str(masked.get("command", ""))] + [str(x) for x in masked.get("args") or []]))
        mcp.append({
            "name": str(name),
            "source": source,
            "kind": kind,
            "key": key,
            "has_plaintext_secret": has_plaintext_secret(spec),
            "spec": masked,
        })


def plugin_hooks(root: Path, source: str, hooks: dict, warnings: list) -> None:
    hj = read_json(root / "hooks" / "hooks.json")
    if hj is not None:
        collect_hooks(hj, source, hooks)
    pj = read_json(root / ".claude-plugin" / "plugin.json") or {}
    h = pj.get("hooks") if isinstance(pj, dict) else None
    if isinstance(h, dict):
        collect_hooks(h, source, hooks)
    elif isinstance(h, str):
        inline = read_json(root / h)
        if inline is None:
            warnings.append(f"{source}: hooks file not readable: {h}")
        else:
            collect_hooks(inline, source, hooks)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True)
    ap.add_argument("--claude-home", default=None)
    ap.add_argument("--plugin-list", default=None)
    ap.add_argument("--extra", action="append", default=[], help="candidate plugin root")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    home = Path(a.claude_home).resolve() if a.claude_home else claude_home()
    project = Path(a.project).resolve()
    hooks: dict = {}
    mcp: list = []
    warnings: list[str] = []

    settings_files = [
        ("user settings", home / "settings.json"),
        ("user settings.local", home / "settings.local.json"),
        ("project settings", project / ".claude" / "settings.json"),
        ("project settings.local", project / ".claude" / "settings.local.json"),
    ]
    for label, path in settings_files:
        cfg = read_json(path)
        if cfg is not None:
            collect_hooks(cfg, f"{label} ({path})", hooks)

    dot_claude_json = next((p for p in (home / ".claude.json", Path.home() / ".claude.json") if p.is_file()), None)
    if dot_claude_json is not None:
        cfg = read_json(dot_claude_json) or {}
        collect_mcp(cfg, "~/.claude.json", mcp)
        proj_cfg = (cfg.get("projects") or {}).get(str(project)) if isinstance(cfg, dict) else None
        if isinstance(proj_cfg, dict):
            collect_mcp(proj_cfg, f"~/.claude.json projects[{project}]", mcp)
    for label, path in (("~/.claude/.mcp.json", home / ".mcp.json"), ("project .mcp.json", project / ".mcp.json")):
        cfg = read_json(path)
        if cfg is not None:
            collect_mcp(cfg, label, mcp)

    plugins, w = load_plugin_list(home, Path(a.plugin_list) if a.plugin_list else None)
    warnings.extend(w)
    for p in plugins:
        if p.get("enabled") is False:
            continue
        root = Path(str(p.get("installPath", "")))
        if not root.is_dir():
            continue
        src = f"plugin:{p.get('id', '?')}"
        plugin_hooks(root, src, hooks, warnings)
        cfg = read_json(root / ".mcp.json")
        if cfg is not None:
            collect_mcp(cfg, src, mcp)

    for x in a.extra:
        root = Path(x).resolve()
        src = f"candidate:{root.name}"
        plugin_hooks(root, src, hooks, warnings)
        cfg = read_json(root / ".mcp.json")
        if cfg is not None:
            collect_mcp(cfg, src, mcp)

    overlaps = []
    for event, rows in hooks.items():
        by_matcher: dict[str, list[str]] = {}
        for r in rows:
            by_matcher.setdefault(r["matcher"], []).append(r["source"])
        for matcher, sources in by_matcher.items():
            uniq = sorted(set(sources))
            if len(uniq) > 1:
                overlaps.append({"event": event, "matcher": matcher, "sources": uniq})

    suspicious = []
    for event, rows in hooks.items():
        for r in rows:
            if r["source"].startswith("user settings") and any(w_ in r["command"] for w_ in PROJECT_TOOL_WORDS):
                suspicious.append({"source": r["source"], "event": event, "command": r["command"],
                                   "why": "project tool in user scope runs in every repo"})

    by_key: dict[str, list[dict]] = {}
    by_name: dict[str, list[str]] = {}
    for m in mcp:
        by_key.setdefault(m["key"], []).append({"name": m["name"], "source": m["source"]})
        by_name.setdefault(m["name"], []).append(m["source"])
    duplicates = [{"key": k, "entries": v} for k, v in sorted(by_key.items()) if len(v) > 1]
    same_name = [{"name": n, "sources": sorted(s)} for n, s in sorted(by_name.items()) if len(s) > 1]

    write_json(a.out, {
        "hooks": hooks,
        "hook_overlaps": overlaps,
        "suspicious_global_hooks": suspicious,
        "mcp": mcp,
        "mcp_duplicates": duplicates,
        "mcp_same_name": same_name,
        "warnings": warnings,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
