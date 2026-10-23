"""Hooks for /l3east:sleep: keep an unattended run going until it prints SLEEP-DONE or SLEEP-BLOCKED.

Usage (from hooks/hooks.json): python3 -I sleep_hook.py prompt|stop|pretool  < hook JSON on stdin

Only /<plugin>:sleep opens a run. Only an end marker, the budget, /<plugin>:wake or the TTL closes it:
prompts Claude Code injects (usage-limit auto-continue, task notifications, loop wakeups) arrive as
UserPromptSubmit too, so an ordinary prompt never closes a run.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
STATUSES = ("active", "done", "blocked", "budget", "ended", "expired")
DONE_RE = re.compile(r"^[`*_\s]*SLEEP-DONE[`*_\s.]*$")
BLOCKED_RE = re.compile(r"^[`*_\s]*SLEEP-BLOCKED[`*_]*:[`*_\s]*[^`*_\s]")
MERGE_CMD_RE = re.compile(r"\bgh\s+pr\s+merge\b")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
WAKING_TASK_TYPES = {"subagent", "monitor", "workflow"}
PROTECTED_BASES = {"main", "master"}
DEFAULT_BUDGET = 40
DEFAULT_TTL_HOURS = 18
PENDING_ALLOW_CAP = 6
DEBUG_STR_CAP = 80

CONTINUE_REASON = (
    "Sleep mode is still active ({left} forced continuations left, merge granted: {merge}). The user is away: "
    "do not ask them anything; follow the /{plugin}:sleep skill (re-read it if it is no longer in context). "
    "Do the next step of the task now. Wait for CI or a process with a tool (gh pr checks --watch, a watcher "
    "subagent), never with a text-only reply or a /loop. When the exit condition is met, delete crons and stop "
    "background shells you started, write the morning report, and end with a last line that is exactly "
    "SLEEP-DONE. If every remaining step is truly blocked, end with SLEEP-BLOCKED: <reason>."
)
LAST_REASON = (
    "Sleep mode: this is the last forced continuation (merge granted: {merge}). Stop the task work now, delete "
    "crons and stop background shells you started, write the morning report, and end with a last line that is "
    "exactly SLEEP-BLOCKED: continuation budget spent"
)
PENDING_REASON = (
    "Sleep mode: the turn is ending while only {what} is pending, and that will not wake this session in time. "
    "Wait on it with a tool, or stop shells and delete crons you started, then do the next step. {rest}"
)
ASK_DENY = "Sleep mode is active and the user is away. Decide this yourself by the sleep skill's tiers and log it."


class CorruptState(Exception):
    pass


def plugin_name() -> str:
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]
    except (OSError, ValueError, KeyError):
        return "l3east"


def command_re(word: str) -> re.Pattern:
    return re.compile(rf"^[ \t]*/{re.escape(plugin_name())}:{word}(?:[ \t]+(?P<arg>[^\s]+))?(?=[ \t]|\n|$)")


def state_dir() -> Path:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    return home / "l3east" / "sleep"


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)


def load(path: Path) -> dict | None:
    """The validated run state, None when there is no run, or CorruptState."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        state = {
            **raw,
            "status": raw["status"],
            "merge": raw["merge"] is True,
            "continuations": int(raw["continuations"]),
            "budget": int(raw["budget"]),
            "pending_allows": int(raw.get("pending_allows", 0)),
            "started_at": datetime.fromisoformat(raw["started_at"]).isoformat(),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorruptState(str(exc)) from exc
    if state["status"] not in STATUSES or state["budget"] < 1 or state["continuations"] < 0:
        raise CorruptState(f"bad values in {path.name}")
    return state


def expire_if_stale(path: Path, state: dict | None) -> dict | None:
    if not state or state["status"] != "active":
        return state
    ttl = timedelta(hours=env_int("L3EAST_SLEEP_TTL_HOURS", DEFAULT_TTL_HOURS))
    if now() - datetime.fromisoformat(state["started_at"]) <= ttl:
        return state
    state = {**state, "status": "expired", "ended_at": stamp()}
    save(path, state)
    return state


def emit(obj: dict) -> None:
    print(json.dumps(obj))


def yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def active_context(state: dict) -> str:
    return (f"l3east sleep hook: run is active, merge granted: {yes_no(state['merge'])}. "
            f"Follow the /{plugin_name()}:sleep skill.")


def on_prompt(path: Path, payload: dict, state: dict | None) -> None:
    prompt = payload.get("prompt") or ""
    active = bool(state and state["status"] == "active")
    if command_re("wake").match(prompt):
        if active:
            save(path, {**state, "status": "ended", "ended_at": stamp()})
        return
    match = command_re("sleep").match(prompt)
    if match:
        merge = match.group("arg") == "merge"
        if active:
            state = {**state, "merge": merge}
        else:
            state = {"status": "active", "merge": merge, "started_at": stamp(), "continuations": 0,
                     "budget": env_int("L3EAST_SLEEP_BUDGET", DEFAULT_BUDGET), "pending_allows": 0}
        save(path, state)
    elif not active:
        return
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": active_context(state)}}
    if not match and payload.get("source") == "user":
        out["systemMessage"] = (f"sleep run still active ({state['continuations']} continuations used). "
                                f"Press Esc, then /{plugin_name()}:wake to end it.")
    emit(out)


def last_line(message: str) -> str:
    lines = [ln for ln in message.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def pending_that_wakes(payload: dict) -> tuple[bool, str]:
    tasks = [t for t in payload.get("background_tasks") or [] if isinstance(t, dict)]
    crons = payload.get("session_crons") or []
    if any(t.get("type") in WAKING_TASK_TYPES for t in tasks):
        return True, ""
    parts = []
    if tasks:
        parts.append(f"{len(tasks)} background shell(s)")
    if crons:
        parts.append(f"{len(crons)} session cron(s)")
    return False, " and ".join(parts)


def block(path: Path, state: dict, reason_extra: str = "") -> None:
    count = state["continuations"] + 1
    save(path, {**state, "continuations": count, "pending_allows": 0})
    merge = yes_no(state["merge"])
    if count == state["budget"]:
        reason = LAST_REASON.format(merge=merge)
    else:
        reason = CONTINUE_REASON.format(left=state["budget"] - count, merge=merge, plugin=plugin_name())
    if reason_extra:
        reason = PENDING_REASON.format(what=reason_extra, rest=reason)
    emit({"decision": "block", "reason": reason})


def on_stop(path: Path, payload: dict, state: dict | None) -> None:
    if not state or state["status"] != "active":
        return
    line = last_line(payload.get("last_assistant_message") or "")
    if DONE_RE.match(line):
        save(path, {**state, "status": "done", "ended_at": stamp()})
        return
    if BLOCKED_RE.match(line):
        save(path, {**state, "status": "blocked", "ended_at": stamp()})
        return
    if state["continuations"] >= state["budget"]:
        save(path, {**state, "status": "budget", "ended_at": stamp()})
        emit({"systemMessage": f"sleep: continuation budget of {state['budget']} used up, stopping"})
        return
    wakes, idle_what = pending_that_wakes(payload)
    if wakes and state["pending_allows"] < PENDING_ALLOW_CAP:
        save(path, {**state, "pending_allows": state["pending_allows"] + 1})
        return
    block(path, state, idle_what)


def pr_base(command: str, cwd: str | None) -> str | None:
    args = command.split()
    try:
        i = next(n for n in range(len(args) - 2) if args[n:n + 3] == ["gh", "pr", "merge"])
    except StopIteration:
        return None
    rest = args[i + 3:]
    target = next((a for a in rest if not a.startswith("-")), None)
    repo = rest[rest.index("--repo") + 1] if "--repo" in rest[:-1] else None
    cmd = ["gh", "pr", "view", *([target] if target else []), "--json", "baseRefName", "-q", ".baseRefName"]
    if repo:
        cmd += ["--repo", repo]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=cwd or None)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def merge_denial(payload: dict, state: dict) -> str | None:
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not MERGE_CMD_RE.search(command):
        return None
    if not state["merge"]:
        return "Sleep mode: merge was not granted (the user typed /sleep without merge). Stop at merge-ready."
    if "--match-head-commit" not in command:
        return "Sleep mode: merge only with --match-head-commit <verified-sha>."
    base = pr_base(command, payload.get("cwd"))
    if base is None:
        return "Sleep mode: could not read the PR's base branch, so the merge is not allowed. Log it and move on."
    if base in PROTECTED_BASES:
        return f"Sleep mode: never merge into {base}. Log it and stop at merge-ready."
    return None


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def on_pretool(path: Path, payload: dict, state: dict | None) -> None:
    if not state or state["status"] != "active":
        return
    tool = payload.get("tool_name")
    if tool == "AskUserQuestion":
        deny(ASK_DENY)
    elif tool == "Bash":
        reason = merge_denial(payload, state)
        if reason:
            deny(reason)


HANDLERS = {"prompt": on_prompt, "stop": on_stop, "pretool": on_pretool}


def handle(event: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not SESSION_ID_RE.match(session_id):
        return
    path = state_dir() / f"{session_id}.json"
    try:
        state = expire_if_stale(path, load(path))
    except CorruptState as exc:
        on_corrupt(event, path, payload, exc)
        return
    HANDLERS[event](path, payload, state)


def on_corrupt(event: str, path: Path, payload: dict, exc: CorruptState) -> None:
    """Fail closed on asking and merging, warn on stop, and let a fresh /sleep replace the file."""
    if event == "pretool":
        command = (payload.get("tool_input") or {}).get("command") or ""
        if payload.get("tool_name") == "AskUserQuestion" or MERGE_CMD_RE.search(command):
            deny(f"Sleep state file is unreadable ({exc}); not allowed until it is fixed.")
    elif event == "stop":
        emit({"systemMessage": f"sleep: state file {path} is unreadable ({exc}); the run is not kept alive"})
    elif command_re("sleep").match(payload.get("prompt") or ""):
        path.unlink(missing_ok=True)
        on_prompt(path, payload, None)


def debug_log(event: str, payload: dict) -> None:
    def short(v):
        return f"<{len(v)} chars>" if isinstance(v, str) and len(v) > DEBUG_STR_CAP else v
    entry = {"event": event, "payload": {k: short(v) for k, v in payload.items()}}
    state_dir().mkdir(parents=True, exist_ok=True)
    with (state_dir() / "debug.log").open("a") as log:
        log.write(json.dumps(entry, default=str)[:4000] + "\n")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        print("usage: sleep_hook.py prompt|stop|pretool", file=sys.stderr)
        return 2
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        if os.environ.get("L3EAST_SLEEP_DEBUG"):
            debug_log(sys.argv[1], payload)
        handle(sys.argv[1], payload)
    except Exception as exc:  # a crashed hook would silently drop the run, so say so instead
        emit({"systemMessage": f"sleep hook error in {sys.argv[1]}: {type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
