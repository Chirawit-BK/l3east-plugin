"""Hooks for /l3east:sleep: keep an unattended run going until it prints SLEEP-DONE or SLEEP-BLOCKED.

Usage (from hooks/hooks.json): python3 -I sleep_hook.py prompt|stop|pretool  < hook JSON on stdin

Only /sleep opens a run. Only an end marker, the budget, or /wake closes it: prompts Claude Code injects
(usage-limit auto-continue, task notifications, loop wakeups) arrive as UserPromptSubmit too, so an
ordinary prompt never closes a run.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SLEEP_RE = re.compile(r"^\s*/(?:[\w-]+:)?sleep(?:\s+(?P<arg>\S+))?(?:\s|$)")
WAKE_RE = re.compile(r"^\s*/(?:[\w-]+:)?wake(?:\s|$)")
MARKER_STRIP = "`*_ \t"
DONE = "SLEEP-DONE"
BLOCKED_RE = re.compile(r"^SLEEP-BLOCKED:\s*\S")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_BUDGET = 40
DEBUG_FIELD_CAP = 300

CONTINUE_REASON = (
    "Sleep mode is still active ({left} forced continuations left). The user is away: do not ask them anything. "
    "Do the next step of the task now. To wait for CI or a process, wait with a tool (gh pr checks --watch, "
    "a watcher subagent), never with a text-only reply. When the exit condition is met, write the morning "
    "report and end with a last line that is exactly SLEEP-DONE. If every remaining step is truly blocked, "
    "end with SLEEP-BLOCKED: <reason>."
)
LAST_REASON = (
    "Sleep mode: this is the last forced continuation. Stop the task work now, write the morning report, "
    "and end with a last line that is exactly SLEEP-BLOCKED: continuation budget spent"
)
ASK_DENY = "Sleep mode is active and the user is away. Decide this yourself by the sleep skill's tiers and log it."


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


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
        if state["status"] in ("active", "done", "blocked", "budget", "ended") and int(state["budget"]) >= 1:
            return state
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {"status": "corrupt"}


def budget() -> int:
    try:
        return max(1, int(os.environ.get("L3EAST_SLEEP_BUDGET", DEFAULT_BUDGET)))
    except ValueError:
        return DEFAULT_BUDGET


def last_line(message: str) -> str:
    lines = [ln for ln in message.splitlines() if ln.strip()]
    return lines[-1].strip(MARKER_STRIP).rstrip(".") if lines else ""


def emit(obj: dict) -> None:
    print(json.dumps(obj))


def on_prompt(path: Path, payload: dict, state: dict | None) -> None:
    prompt = payload.get("prompt") or ""
    if WAKE_RE.match(prompt):
        if state and state["status"] == "active":
            save(path, {**state, "status": "ended", "ended_at": now()})
        return
    match = SLEEP_RE.match(prompt)
    if not match:
        return
    merge = match.group("arg") == "merge"
    if state and state["status"] == "active":
        save(path, {**state, "merge": merge})
    else:
        save(path, {"status": "active", "merge": merge, "started_at": now(), "continuations": 0, "budget": budget()})
    emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext":
          f"l3east sleep hook: run is active, merge granted: {'yes' if merge else 'no'}."}})


def on_stop(path: Path, payload: dict, state: dict | None) -> None:
    if state and state["status"] == "corrupt":
        emit({"systemMessage": f"sleep: state file {path} is unreadable, the run is not being kept alive"})
        return
    if not state or state["status"] != "active":
        return
    line = last_line(payload.get("last_assistant_message") or "")
    if line == DONE:
        save(path, {**state, "status": "done", "ended_at": now()})
        return
    if BLOCKED_RE.match(line):
        save(path, {**state, "status": "blocked", "ended_at": now()})
        return
    if payload.get("background_tasks") or payload.get("session_crons"):
        return
    if state["continuations"] >= state["budget"]:
        save(path, {**state, "status": "budget", "ended_at": now()})
        emit({"systemMessage": f"sleep: continuation budget of {state['budget']} used up, stopping"})
        return
    count = state["continuations"] + 1
    save(path, {**state, "continuations": count})
    reason = LAST_REASON if count == state["budget"] else CONTINUE_REASON.format(left=state["budget"] - count)
    emit({"decision": "block", "reason": reason})


def on_pretool(path: Path, payload: dict, state: dict | None) -> None:
    if state and state["status"] == "active" and payload.get("tool_name") == "AskUserQuestion":
        emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                     "permissionDecisionReason": ASK_DENY}})


HANDLERS = {"prompt": on_prompt, "stop": on_stop, "pretool": on_pretool}


def handle(event: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not SESSION_ID_RE.match(session_id):
        return
    path = state_path(session_id)
    HANDLERS[event](path, payload, load(path))


def debug_log(event: str, payload: dict) -> None:
    trimmed = {k: (v[:DEBUG_FIELD_CAP] if isinstance(v, str) else v) for k, v in payload.items()}
    log_path = state_path("debug").with_name("debug.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as log:
        log.write(json.dumps({"event": event, "payload": trimmed}) + "\n")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        print("usage: sleep_hook.py prompt|stop|pretool", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if os.environ.get("L3EAST_SLEEP_DEBUG"):
        debug_log(sys.argv[1], payload)
    handle(sys.argv[1], payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
