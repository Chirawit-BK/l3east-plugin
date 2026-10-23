"""Hooks for /l3east:sleep: keep an unattended run going until it prints SLEEP-DONE or SLEEP-BLOCKED.

Usage (from hooks/hooks.json): python3 -I sleep_hook.py prompt|stop  < hook JSON on stdin
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SLEEP_PROMPT_RE = re.compile(r"^\s*/(?:[\w-]+:)?sleep\b")
DONE_RE = re.compile(r"^\s*SLEEP-DONE\s*$", re.M)
BLOCKED_RE = re.compile(r"^\s*SLEEP-BLOCKED\b", re.M)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_BUDGET = 40

CONTINUE_REASON = (
    "Sleep mode is still active ({left} forced continuations left). The user is away: do not ask them anything. "
    "Do the next step of the task now. When the exit condition is met, write the morning report and end with a "
    "line that is exactly SLEEP-DONE. If every remaining step is truly blocked, end with SLEEP-BLOCKED: <reason>."
)


def state_path(session_id: str) -> Path:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return home / "l3east" / "sleep" / f"{session_id}.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


def budget() -> int:
    try:
        return max(1, int(os.environ.get("L3EAST_SLEEP_BUDGET", DEFAULT_BUDGET)))
    except ValueError:
        return DEFAULT_BUDGET


def on_prompt(path: Path, payload: dict, state: dict | None) -> None:
    if SLEEP_PROMPT_RE.match(payload.get("prompt") or ""):
        save(path, {"status": "active", "started_at": now(), "continuations": 0, "budget": budget()})
    elif state and state["status"] == "active":
        save(path, {**state, "status": "ended", "ended_at": now()})


def on_stop(path: Path, payload: dict, state: dict | None) -> None:
    if not state or state["status"] != "active":
        return
    message = payload.get("last_assistant_message") or ""
    if DONE_RE.search(message):
        save(path, {**state, "status": "done", "ended_at": now()})
        return
    if BLOCKED_RE.search(message):
        save(path, {**state, "status": "blocked", "ended_at": now()})
        return
    if payload.get("background_tasks"):
        return
    if state["continuations"] >= state["budget"]:
        save(path, {**state, "status": "budget", "ended_at": now()})
        print(json.dumps({"systemMessage": f"sleep: continuation budget of {state['budget']} used up, stopping"}))
        return
    count = state["continuations"] + 1
    save(path, {**state, "continuations": count})
    print(json.dumps({"decision": "block", "reason": CONTINUE_REASON.format(left=state["budget"] - count)}))


def handle(event: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not SESSION_ID_RE.match(session_id):
        return
    path = state_path(session_id)
    state = json.loads(path.read_text()) if path.exists() else None
    {"prompt": on_prompt, "stop": on_stop}[event](path, payload, state)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("prompt", "stop"):
        print("usage: sleep_hook.py prompt|stop", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if os.environ.get("L3EAST_SLEEP_DEBUG"):
        log_path = state_path("debug").with_suffix(".log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as log:
            log.write(json.dumps({"event": sys.argv[1], "payload": payload}) + "\n")
    handle(sys.argv[1], payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
