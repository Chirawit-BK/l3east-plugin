import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "sleep"))
import sleep_hook  # noqa: E402

AUTO_CONTINUE = "Your claude.ai usage limit has reset. Continue the task you were working on."
TASK_NOTIFICATION = "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>"
SUBAGENT = {"id": "a1", "type": "subagent", "status": "running", "description": "review"}
SHELL = {"id": "b1", "type": "shell", "status": "running", "description": "npm run dev"}
CRON = {"id": "c1", "schedule": "*/10 * * * *", "recurring": True}


class SleepHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        keys = ("CLAUDE_CONFIG_DIR", "L3EAST_SLEEP_BUDGET", "L3EAST_SLEEP_TTL_HOURS", "L3EAST_SLEEP_DEBUG")
        self._old = {k: os.environ.get(k) for k in keys}
        for k in keys:
            os.environ.pop(k, None)
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def run_event(self, event, payload):
        out = io.StringIO()
        with redirect_stdout(out):
            sleep_hook.handle(event, {"session_id": "s1", **payload})
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def state_file(self):
        return Path(self.tmp.name) / "l3east" / "sleep" / "s1.json"

    def state(self):
        p = self.state_file()
        return json.loads(p.read_text()) if p.exists() else None

    def write_state(self, **fields):
        self.state_file().parent.mkdir(parents=True, exist_ok=True)
        self.state_file().write_text(json.dumps(fields))

    def prompt(self, text, **extra):
        return self.run_event("prompt", {"prompt": text, **extra})

    def stop(self, message, **extra):
        return self.run_event("stop", {"last_assistant_message": message, **extra})

    def bash(self, command):
        return self.run_event("pretool", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})

    def denied(self, out):
        return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    # opening

    def test_sleep_opens_run_and_tells_claude_merge_is_not_granted(self):
        out = self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["status"], "active")
        self.assertIs(self.state()["merge"], False)
        self.assertIn("merge granted: no", out["hookSpecificOutput"]["additionalContext"])

    def test_merge_first_token_grants_merge(self):
        out = self.prompt("/l3east:sleep merge")
        self.assertIs(self.state()["merge"], True)
        self.assertIn("merge granted: yes", out["hookSpecificOutput"]["additionalContext"])

    def test_merge_word_later_or_on_next_line_does_not_grant(self):
        self.prompt("/l3east:sleep fix the merge-queue bug, then merge it")
        self.assertIs(self.state()["merge"], False)
        self.state_file().unlink()
        self.prompt("/l3east:sleep\nmerge conflicts are expected, resolve them")
        self.assertIs(self.state()["merge"], False)

    def test_only_this_plugins_command_opens(self):
        for text in ("/sleep", "/other:sleep", "how does /l3east:sleep work?", "/l3east:sleeper",
                     "/l3east:sleep-notes", "sleep"):
            self.prompt(text)
        self.assertIsNone(self.state())

    def test_retyping_sleep_keeps_counters_and_updates_grant(self):
        self.prompt("/l3east:sleep merge")
        self.stop("step 1")
        self.prompt("/l3east:sleep")
        st = self.state()
        self.assertEqual(st["continuations"], 1)
        self.assertIs(st["merge"], False)

    # staying open

    def test_injected_and_ordinary_prompts_keep_run_open_and_restate_grant(self):
        self.prompt("/l3east:sleep merge")
        for text in (AUTO_CONTINUE, TASK_NOTIFICATION, "check CI"):
            out = self.prompt(text)
            self.assertIn("merge granted: yes", out["hookSpecificOutput"]["additionalContext"])
            self.assertNotIn("systemMessage", out)
        self.assertEqual(self.state()["status"], "active")

    def test_user_typed_prompt_during_run_gets_wake_hint(self):
        self.prompt("/l3east:sleep")
        out = self.prompt("how did it go?", source="user")
        self.assertIn("/l3east:wake", out["systemMessage"])
        self.assertEqual(self.state()["status"], "active")

    def test_prompts_outside_a_run_are_silent(self):
        self.assertIsNone(self.prompt("hello", source="user"))

    def test_wake_closes_run(self):
        self.prompt("/l3east:sleep")
        self.prompt("/l3east:wake")
        self.assertEqual(self.state()["status"], "ended")

    def test_stale_run_expires(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=19)).isoformat()
        self.write_state(status="active", merge=True, continuations=3, budget=40, started_at=old)
        self.assertIsNone(self.stop("step"))
        self.assertEqual(self.state()["status"], "expired")
        self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["continuations"], 0)
        self.assertIs(self.state()["merge"], False)

    # stop

    def test_stop_without_run_allows(self):
        self.assertIsNone(self.stop("hi"))

    def test_stop_while_active_blocks_and_restates_grant(self):
        self.prompt("/l3east:sleep merge")
        out = self.stop("step 1 done")
        self.assertEqual(out["decision"], "block")
        for text in ("SLEEP-DONE", "Wait for CI", "with a tool", "merge granted: yes", "/l3east:sleep"):
            self.assertIn(text, out["reason"])
        self.assertEqual(self.state()["continuations"], 1)

    def test_done_marker_variants_on_last_line_close(self):
        for marker in ("SLEEP-DONE", "`SLEEP-DONE`", "**SLEEP-DONE**", "SLEEP-DONE.", "`SLEEP-DONE`."):
            self.prompt("/l3east:sleep")
            self.assertIsNone(self.stop(f"report\n\n{marker}\n"), marker)
            self.assertEqual(self.state()["status"], "done", marker)
            self.state_file().unlink()

    def test_marker_not_on_last_line_keeps_working(self):
        self.prompt("/l3east:sleep")
        self.assertEqual(self.stop("```\nSLEEP-DONE\n```\nI will print it at the end.")["decision"], "block")

    def test_blocked_marker_needs_a_reason_and_accepts_bold(self):
        self.prompt("/l3east:sleep")
        self.assertEqual(self.stop("report\nSLEEP-BLOCKED")["decision"], "block")
        self.assertEqual(self.stop("report\nSLEEP-BLOCKED: **")["decision"], "block")
        self.assertIsNone(self.stop("report\n**SLEEP-BLOCKED**: needs prod creds"))
        self.assertEqual(self.state()["status"], "blocked")

    def test_pending_subagent_lets_turn_end_up_to_a_cap(self):
        self.prompt("/l3east:sleep")
        for _ in range(sleep_hook.PENDING_ALLOW_CAP):
            self.assertIsNone(self.stop("waiting", background_tasks=[SUBAGENT]))
        self.assertEqual(self.state()["continuations"], 0)
        self.assertEqual(self.stop("waiting", background_tasks=[SUBAGENT])["decision"], "block")
        self.assertEqual(self.state()["pending_allows"], 0)

    def test_only_shells_or_crons_pending_blocks_and_names_them(self):
        self.prompt("/l3east:sleep")
        out = self.stop("waiting", background_tasks=[SHELL], session_crons=[CRON])
        self.assertEqual(out["decision"], "block")
        self.assertIn("1 background shell(s) and 1 session cron(s)", out["reason"])

    def test_last_continuation_asks_for_the_report_then_budget_closes(self):
        os.environ["L3EAST_SLEEP_BUDGET"] = "2"
        self.prompt("/l3east:sleep")
        self.assertIn("left", self.stop("a")["reason"])
        last = self.stop("b")
        self.assertIn("morning report", last["reason"])
        self.assertIn("SLEEP-BLOCKED: continuation budget spent", last["reason"])
        out = self.stop("c")
        self.assertIn("budget", out["systemMessage"])
        self.assertNotIn("decision", out)
        self.assertEqual(self.state()["status"], "budget")

    def test_closed_run_never_blocks(self):
        self.prompt("/l3east:sleep")
        self.stop("SLEEP-DONE")
        self.assertIsNone(self.stop("more"))

    # corrupt state

    def test_unparseable_or_partial_state_warns_on_stop(self):
        for content in ("{not json", json.dumps({"status": "active", "budget": 40, "merge": False}),
                        json.dumps({"status": "active", "budget": "x", "merge": False, "continuations": 0,
                                    "started_at": "2026-01-01T00:00:00+00:00"})):
            self.state_file().parent.mkdir(parents=True, exist_ok=True)
            self.state_file().write_text(content)
            self.assertIn("unreadable", self.stop("step")["systemMessage"], content)

    def test_corrupt_state_fails_closed_on_ask_and_merge_and_sleep_replaces_it(self):
        self.write_state(status="active")
        self.assertTrue(self.denied(self.run_event("pretool", {"tool_name": "AskUserQuestion"})))
        self.assertTrue(self.denied(self.bash("gh pr merge 5 --merge")))
        self.assertIsNone(self.bash("ls"))
        self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["status"], "active")

    # PreToolUse

    def test_ask_user_question_is_denied_only_during_a_run(self):
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))
        self.prompt("/l3east:sleep")
        self.assertTrue(self.denied(self.run_event("pretool", {"tool_name": "AskUserQuestion"})))
        self.stop("SLEEP-DONE")
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))

    def test_merge_denied_without_grant(self):
        self.prompt("/l3east:sleep")
        out = self.bash("gh pr merge 5 --merge --match-head-commit abc")
        self.assertIn("not granted", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_merge_denied_without_head_guard(self):
        self.prompt("/l3east:sleep merge")
        out = self.bash("gh pr merge 5 --squash")
        self.assertIn("--match-head-commit", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_merge_into_main_denied_and_feature_base_allowed(self):
        self.prompt("/l3east:sleep merge")
        cmd = "gh pr merge 5 --repo o/r --squash --match-head-commit abc"
        with mock.patch.object(sleep_hook, "pr_base", return_value="main"):
            self.assertIn("never merge into main", self.bash(cmd)["hookSpecificOutput"]["permissionDecisionReason"])
        with mock.patch.object(sleep_hook, "pr_base", return_value=None):
            self.assertTrue(self.denied(self.bash(cmd)))
        with mock.patch.object(sleep_hook, "pr_base", return_value="dev"):
            self.assertIsNone(self.bash(cmd))

    def test_pr_base_reads_target_and_repo(self):
        done = subprocess.CompletedProcess([], 0, stdout="develop\n", stderr="")
        with mock.patch.object(sleep_hook.subprocess, "run", return_value=done) as run:
            base = sleep_hook.pr_base("cd x && gh pr merge 12 --repo o/r --merge --match-head-commit abc", "/w")
        self.assertEqual(base, "develop")
        self.assertEqual(run.call_args.args[0],
                         ["gh", "pr", "view", "12", "--json", "baseRefName", "-q", ".baseRefName", "--repo", "o/r"])

    def test_other_bash_commands_pass_during_a_run(self):
        self.prompt("/l3east:sleep")
        self.assertIsNone(self.bash("gh pr view 5"))

    # entry point and wiring

    def run_cli(self, event, payload, **env):
        return subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sleep" / "sleep_hook.py"), event],
                              input=payload if isinstance(payload, str) else json.dumps(payload),
                              capture_output=True, text=True, env={**os.environ, **env})

    def test_cli_entry_with_debug_logs_lengths_not_text(self):
        self.run_cli("prompt", {"session_id": "s1", "prompt": "/l3east:sleep"}, L3EAST_SLEEP_DEBUG="1")
        res = self.run_cli("stop", {"session_id": "s1", "last_assistant_message": "x" * 500}, L3EAST_SLEEP_DEBUG="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["decision"], "block")
        log = (Path(self.tmp.name) / "l3east" / "sleep" / "debug.log").read_text()
        self.assertIn("<500 chars>", log)
        self.assertNotIn("x" * 100, log)

    def test_cli_survives_bad_input_and_reports_handler_errors(self):
        self.assertEqual(self.run_cli("stop", "[]").returncode, 0)
        self.assertEqual(self.run_cli("stop", b"\xff".decode("latin-1")).returncode, 0)
        self.state_file().parent.mkdir(parents=True)
        self.state_file().mkdir()
        res = self.run_cli("stop", {"session_id": "s1", "last_assistant_message": "x"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("sleep", json.loads(res.stdout)["systemMessage"])

    def test_bad_session_id_is_ignored(self):
        self.run_event("prompt", {"session_id": "../x", "prompt": "/l3east:sleep"})
        self.assertFalse((Path(self.tmp.name) / "l3east" / "sleep").exists())

    def test_hooks_json_wires_every_event_to_the_script(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        wired = {ev: h["hooks"][0]["command"] for ev, (h,) in hooks.items()}
        self.assertEqual(set(wired), {"UserPromptSubmit", "Stop", "PreToolUse"})
        for ev, arg in (("UserPromptSubmit", "prompt"), ("Stop", "stop"), ("PreToolUse", "pretool")):
            self.assertTrue(wired[ev].endswith(f'scripts/sleep/sleep_hook.py" {arg}'), wired[ev])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "AskUserQuestion|Bash")


if __name__ == "__main__":
    unittest.main()
