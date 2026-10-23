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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shell_gate  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = PLUGIN_ROOT / "skills" / "sleep" / "SKILL.md"
STATUSES = ("active", "done", "blocked", "budget", "ended", "expired")
DONE_RE = re.compile(r"^[`*_\s]*SLEEP-DONE[`*_\s.]*$")
BLOCKED_RE = re.compile(r"^[`*_\s]*SLEEP-BLOCKED[`*_]*:[`*_\s]*[^`*_\s]")
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
SHELL_TOOL_RE = re.compile(r"^(Bash|Monitor|.*run_in_terminal|.*execute_shell_command)$")
REPO_RE = re.compile(r"[\w.-]+/[\w.-]+")
SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}")
PLAIN_COMMAND_RE = re.compile(r"[`$<>\\]")
MERGE_METHODS = {"--merge", "--squash", "--rebase"}
MACHINE_SOURCES = {"system", "loop_wakeup", "schedule_wakeup", "poll_event", "sdk"}
MACHINE_PROMPT_RE = re.compile(r"^\s*(?:<task-notification>|Your claude\.ai usage limit has reset)")
IDLE_TASK_TYPES = {"shell"}
LIVE_TASK_STATUSES = {"running", "pending"}
PROTECTED_BASES = {"main", "master"}
DEFAULT_BUDGET = 40
DEFAULT_TTL_HOURS = 18
DEBUG_STR_CAP = 80

CONTINUE_REASON = (
    "Sleep mode is still active ({left} forced continuations left, merge granted: {merge}). The user is away: "
    "do not ask them anything; follow the sleep skill ({skill}, read it again if it is no longer in context). "
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
IDLE_REASON = (
    "Sleep mode: the turn is ending while only {what} is pending. The hook cannot tell a shell that will exit "
    "from one that never will (a dev server), or when a cron fires. Wait in the foreground or with Monitor "
    "instead, and stop servers and delete crons you started, then do the next step. {rest}"
)
MERGE_FORM = "gh pr merge <number> --repo <owner/repo> --match-head-commit <sha> --merge|--squash|--rebase"
ASK_DENY = "Sleep mode is active and the user is away. Decide this yourself by the sleep skill's tiers and log it."


class CorruptState(Exception):
    pass


def _read_plugin_name() -> str:
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())["name"]
    except (OSError, ValueError, KeyError):
        return "l3east"


PLUGIN_NAME = _read_plugin_name()
SLEEP_CMD_RE = re.compile(rf"^[ \t]*/{re.escape(PLUGIN_NAME)}:sleep(?:[ \t]+(?P<arg>\S+))?(?=[ \t]|\n|$)")
WAKE_CMD_RE = re.compile(rf"^[ \t]*/{re.escape(PLUGIN_NAME)}:wake(?=[ \t]|\n|$)")


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
        started = datetime.fromisoformat(raw["started_at"])
        state = {
            **raw,
            "status": raw["status"],
            "merge": raw["merge"] is True,
            "continuations": int(raw["continuations"]),
            "budget": int(raw["budget"]),
            "notified": raw.get("notified") is True,
            "started_at": started.isoformat(),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorruptState(str(exc)) from exc
    if started.tzinfo is None or state["status"] not in STATUSES or state["budget"] < 1 or state["continuations"] < 0:
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


def is_open(state: dict | None) -> bool:
    return bool(state and state["status"] == "active")


def closed_unannounced(state: dict | None) -> bool:
    return bool(state and state["status"] != "active" and not state["notified"])


def closed_notice(state: dict) -> str:
    return (f"l3east sleep hook: run is closed ({state['status']}). The merge grant is revoked and ship's "
            "Sleep runs section no longer applies. Merges and refused pushes stay blocked until the user speaks.")


def prompt_context(state: dict) -> str:
    return (f"l3east sleep hook: run is active, merge granted: {yes_no(state['merge'])}. Follow the sleep skill "
            f"({SKILL_PATH}). If this prompt comes from a person, tell them /{PLUGIN_NAME}:wake ends the run.")


def looks_human(payload: dict) -> bool:
    return payload.get("source") not in MACHINE_SOURCES and not MACHINE_PROMPT_RE.search(payload.get("prompt") or "")


def on_prompt(path: Path, payload: dict, state: dict | None) -> None:
    prompt = payload.get("prompt") or ""
    if WAKE_CMD_RE.match(prompt):
        if is_open(state):
            save(path, {**state, "status": "ended", "ended_at": stamp(), "notified": True})
        elif state:
            save(path, {**state, "notified": True})
        return
    match = SLEEP_CMD_RE.match(prompt)
    if match:
        merge = match.group("arg") == "merge"
        base = state if is_open(state) else {"continuations": 0, "budget": env_int("L3EAST_SLEEP_BUDGET", DEFAULT_BUDGET)}
        state = {**base, "status": "active", "merge": merge, "started_at": stamp(), "notified": False}
        save(path, state)
    elif closed_unannounced(state):
        if looks_human(payload):
            save(path, {**state, "notified": True})
        emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": closed_notice(state)}})
        return
    elif not is_open(state):
        return
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": prompt_context(state)}}
    if not match and looks_human(payload):
        out["systemMessage"] = (f"sleep run still active ({state['continuations']} continuations used). "
                                f"Press Esc, then /{PLUGIN_NAME}:wake to end it.")
    emit(out)


def last_line(message: str) -> str:
    lines = [ln for ln in message.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def pending_work(payload: dict) -> tuple[bool, str]:
    """Whether pending work will wake the session, and a description of idle work that will not."""
    live = [t for t in payload.get("background_tasks") or []
            if isinstance(t, dict) and t.get("status") in LIVE_TASK_STATUSES]
    if any(t.get("type") not in IDLE_TASK_TYPES for t in live):
        return True, ""
    crons = payload.get("session_crons") or []
    parts = []
    if live:
        parts.append(f"{len(live)} background shell(s)")
    if crons:
        parts.append(f"{len(crons)} session cron(s)")
    return False, " and ".join(parts)


def block(path: Path, state: dict, idle_what: str) -> None:
    count = state["continuations"] + 1
    save(path, {**state, "continuations": count})
    merge = yes_no(state["merge"])
    if count == state["budget"]:
        reason = LAST_REASON.format(merge=merge)
    else:
        reason = CONTINUE_REASON.format(left=state["budget"] - count, merge=merge, skill=SKILL_PATH)
        if idle_what:
            reason = IDLE_REASON.format(what=idle_what, rest=reason)
    emit({"decision": "block", "reason": reason})


def on_stop(path: Path, payload: dict, state: dict | None) -> None:
    if not is_open(state):
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
    wakes, idle_what = pending_work(payload)
    if not wakes:
        block(path, state, idle_what)


def parse_merge(argv: list[str]) -> tuple[str, str] | str:
    """(number, repo) for argv in exactly MERGE_FORM, else the reason it is not allowed."""
    if argv[:3] != ["gh", "pr", "merge"] or len(argv) < 4 or not argv[3].isdigit():
        return "the merge must start with gh pr merge <number>"
    opts, methods, rest = {}, [], argv[4:]
    while rest:
        flag = rest.pop(0)
        if flag in MERGE_METHODS:
            methods.append(flag)
        elif flag in ("--repo", "--match-head-commit") and rest and flag not in opts:
            opts[flag] = rest.pop(0)
        else:
            return f"{flag} is not allowed in a sleep-run merge"
    if len(methods) != 1:
        return "pick exactly one of --merge, --squash or --rebase"
    if not REPO_RE.fullmatch(opts.get("--repo", "")):
        return "--repo <owner/repo> is required"
    if not SHA_RE.fullmatch(opts.get("--match-head-commit", "")):
        return "--match-head-commit <sha> is required"
    return argv[3], opts["--repo"]


def pr_base(number: str, repo: str) -> str | None:
    cmd = ["gh", "pr", "view", number, "--repo", repo, "--json", "baseRefName", "-q", ".baseRefName"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (res.stdout.strip() or None) if res.returncode == 0 else None


def shell_command(payload: dict) -> str | None:
    if not SHELL_TOOL_RE.match(str(payload.get("tool_name") or "")):
        return None
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else ""


def shell_denial(command: str, state: dict) -> str | None:
    try:
        argvs = shell_gate.segments(command)
    except ValueError:
        if shell_gate.RISKY_WORD_RE.search(command):
            return "Sleep mode: this command could not be parsed, and it mentions merge or push. Rewrite it plainly."
        return None
    if shell_gate.SUBSTITUTION_RE.search(command) and shell_gate.RISKY_WORD_RE.search(command):
        return "Sleep mode: no $( ), backticks or <( ) in a command that merges or pushes. Run it plainly."
    for argv in argvs:
        problem = shell_gate.push_problem(argv)
        if problem:
            return f"Sleep mode: {problem}."
    if not any(shell_gate.is_merge(argv) for argv in argvs):
        return None
    if not state["merge"]:
        return "Sleep mode: merge was not granted (the user typed /sleep without merge). Stop at merge-ready."
    if len(argvs) != 1 or PLAIN_COMMAND_RE.search(command):
        parsed = "a merge must be one plain command (no cd, &&, ;, |, $( ) or redirects)"
    else:
        parsed = parse_merge(argvs[0])
    if isinstance(parsed, str):
        return f"Sleep mode: {parsed}. The only allowed form is: {MERGE_FORM}"
    base = pr_base(*parsed)
    if base is None:
        return "Sleep mode: could not read the PR's base branch, so the merge is not allowed. Log it and move on."
    if base in PROTECTED_BASES:
        return f"Sleep mode: never merge into {base}. Log it and stop at merge-ready."
    return None


def deny(reason: str) -> None:
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def risky_shell(payload: dict) -> bool:
    command = shell_command(payload)
    return bool(command and shell_gate.looks_risky(command))


def risky_call(payload: dict) -> bool:
    return payload.get("tool_name") == "AskUserQuestion" or risky_shell(payload)


def on_pretool(path: Path, payload: dict, state: dict | None) -> None:
    if closed_unannounced(state) and risky_shell(payload):
        deny(closed_notice(state))
        return
    if not is_open(state):
        return
    if payload.get("tool_name") == "AskUserQuestion":
        deny(ASK_DENY)
        return
    command = shell_command(payload)
    reason = shell_denial(command, state) if command else None
    if reason:
        deny(reason)


HANDLERS = {"prompt": on_prompt, "stop": on_stop, "pretool": on_pretool}


def handle(event: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not SESSION_ID_RE.fullmatch(session_id):
        return
    path = state_dir() / f"{session_id}.json"
    try:
        loaded = load(path)
    except CorruptState as exc:
        on_corrupt(event, path, payload, exc)
        return
    state = expire_if_stale(path, loaded)
    if event == "stop" and is_open(loaded) and not is_open(state):
        emit({"systemMessage": f"sleep: the run expired after {env_int('L3EAST_SLEEP_TTL_HOURS', DEFAULT_TTL_HOURS)}h"})
        return
    HANDLERS[event](path, payload, state)


def on_corrupt(event: str, path: Path, payload: dict, exc: CorruptState) -> None:
    """Fail closed on asking and merging, warn on stop, and let /sleep or /wake replace the file."""
    prompt = payload.get("prompt") or ""
    if event == "pretool":
        if risky_call(payload):
            deny(f"Sleep state file {path} is unreadable ({exc}); type /{PLUGIN_NAME}:wake to clear it.")
    elif event == "stop":
        emit({"systemMessage": f"sleep: state file {path} is unreadable ({exc}); the run is not kept alive"})
    elif SLEEP_CMD_RE.match(prompt):
        path.unlink(missing_ok=True)
        on_prompt(path, payload, None)
    elif WAKE_CMD_RE.match(prompt):
        path.unlink(missing_ok=True)
        emit({"systemMessage": f"sleep: removed the unreadable state file {path}"})
    else:
        emit({"systemMessage": f"sleep: state file {path} is unreadable ({exc}); type /{PLUGIN_NAME}:wake to clear it"})


def redact(value):
    if isinstance(value, str):
        return f"<{len(value)} chars>" if len(value) > DEBUG_STR_CAP else value
    if isinstance(value, dict):
        return {k: (f"<{len(v)} chars>" if k in ("command", "prompt") and isinstance(v, str) else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def debug_log(event: str, payload: dict) -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        with (state_dir() / "debug.log").open("a") as log:
            log.write(json.dumps({"event": event, "payload": redact(payload)}, default=str) + "\n")
    except (OSError, TypeError, ValueError):
        pass


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
    if os.environ.get("L3EAST_SLEEP_DEBUG"):
        debug_log(sys.argv[1], payload)
    try:
        handle(sys.argv[1], payload)
    except Exception as exc:  # a crashed hook would silently drop the run, so say so, and fail closed on risky calls
        if sys.argv[1] == "pretool" and risky_call(payload):
            deny(f"Sleep hook error ({type(exc).__name__}: {exc}); not allowed until it is fixed.")
        else:
            emit({"systemMessage": f"sleep hook error in {sys.argv[1]}: {type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
