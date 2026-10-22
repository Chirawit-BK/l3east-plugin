#!/usr/bin/env python3
"""Flag weak skill descriptions: too long, too short, no trigger, no exclusion, overbroad, unused."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DESC_LIMIT, read_json, write_json  # noqa: E402

TRIGGER_RE = re.compile(r"(?i)\b(use (?:this )?(?:skill )?(?:when|for|whenever)|trigger|when the user|whenever|invoke when|use when|run when)\b")
NOT_FOR_RE = re.compile(r"(?i)\b(not for|do not use|don't use|never (?:use|for)|not when|skip when|instead of|except)\b")
BROAD_RE = re.compile(r"(?i)\b(any|anything|everything|all|every)\b")
NEAR_LIMIT = 1200
TOO_SHORT = 60


def uses_for(e: dict, usage: dict) -> int:
    keys = {e["name"]} | {s.lstrip("/") for s in e.get("slash_names", [])}
    src = e.get("source", "")
    if src.startswith("plugin:"):
        keys.add(f"{src[len('plugin:'):].split('@')[0]}:{e['name']}")
    total = 0
    for k in keys:
        total += (usage.get("skills", {}).get(k) or {}).get("total", 0)
        total += (usage.get("slash", {}).get("/" + k) or {}).get("total", 0)
    return total


def lint(e: dict, usage: dict, usage_ok: bool) -> list[str]:
    desc = e.get("description", "")
    n = len(desc)
    issues = []
    if n == 0:
        issues.append("empty")
    elif n < TOO_SHORT:
        issues.append("too_short")
    if n > DESC_LIMIT:
        issues.append("truncated_over_1536")
    elif n > NEAR_LIMIT:
        issues.append("near_limit")
    if n and not TRIGGER_RE.search(desc):
        issues.append("no_trigger_phrase")
    if n and not NOT_FOR_RE.search(desc):
        issues.append("no_not_for")
    if n and BROAD_RE.search(desc) and not NOT_FOR_RE.search(desc):
        issues.append("overbroad")
    if usage_ok and uses_for(e, usage) == 0:
        issues.append("never_used_in_window")
    if e.get("first_action_claim"):
        issues.append("claims_first_action")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--usage", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    inv = read_json(a.inventory) or {}
    usage = read_json(a.usage) or {}
    usage_ok = usage.get("status") == "ok"
    rows, summary = [], {}
    for e in inv.get("entries", []):
        issues = lint(e, usage, usage_ok)
        if not issues:
            continue
        for i in issues:
            summary[i] = summary.get(i, 0) + 1
        rows.append({"name": e["name"], "source": e["source"], "desc_chars": e.get("desc_chars", 0),
                     "uses": uses_for(e, usage) if usage_ok else None, "issues": issues})
    rows.sort(key=lambda r: (-len(r["issues"]), r["name"]))
    write_json(a.out, {"usage_status": usage.get("status", "unknown"), "summary": summary, "entries": rows})
    return 0


if __name__ == "__main__":
    sys.exit(main())
