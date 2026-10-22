"""Shared helpers for skillkit tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "skillkit"
FIXTURE = Path(__file__).resolve().parent / "fixture"
FIX_HOME = FIXTURE / "home"
FIX_PROJECT = FIXTURE / "project"
FIX_PROJECTS = FIX_HOME / "projects"
FIX_CANDIDATE = FIXTURE / "candidate"
FIXTURE_TOKEN = "FIXTURE-SECRET-TOKEN-VALUE-1234567890abcdef"


def run_script(name: str, *args: str) -> subprocess.CompletedProcess:
    """Run scripts/skillkit/<name> under python3 -I exactly as the skills do."""
    cmd = [sys.executable, "-I", str(SCRIPTS / name), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def write_plugin_list(tmp: Path) -> Path:
    """Plugin list pointing at the fixture plugin with an absolute installPath."""
    data = [
        {
            "id": "alpha@mkt",
            "version": "1.0.0",
            "scope": "user",
            "enabled": True,
            "installPath": str(FIX_HOME / "plugins" / "cache" / "mkt" / "alpha" / "1.0.0"),
        },
        {
            "id": "off@mkt",
            "version": "1.0.0",
            "scope": "user",
            "enabled": False,
            "installPath": str(FIX_HOME / "plugins" / "cache" / "mkt" / "off" / "1.0.0"),
        },
    ]
    p = tmp / "plugin-list.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
