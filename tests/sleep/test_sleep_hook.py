import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "sleep"))
import sleep_hook  # noqa: E402

AUTO_CONTINUE = "Your claude.ai usage limit has reset. Continue the task you were working on."
TASK_NOTIFICATION = "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>"


class SleepHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = {k: os.environ.get(k) for k in ("CLAUDE_CONFIG_DIR", "L3EAST_SLEEP_BUDGET")}
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        os.environ.pop("L3EAST_SLEEP_BUDGET", None)

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

    def prompt(self, text):
        return self.run_event("prompt", {"prompt": text})

    def stop(self, message, **extra):
        return self.run_event("stop", {"last_assistant_message": message, **extra})

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

    def test_merge_word_later_in_text_does_not_grant(self):
        self.prompt("/l3east:sleep fix the merge-queue bug, then merge it")
        self.assertIs(self.state()["merge"], False)

    def test_bare_sleep_alias_opens(self):
        self.prompt("  /sleep")
        self.assertEqual(self.state()["status"], "active")

    def test_lookalikes_do_not_open(self):
        for text in ("how does /l3east:sleep work?", "/sleeper go", "/l3east:sleep-notes", "sleep"):
            self.prompt(text)
        self.assertIsNone(self.state())

    def test_retyping_sleep_keeps_counters(self):
        self.prompt("/l3east:sleep")
        self.stop("step 1")
        self.prompt("/l3east:sleep merge")
        st = self.state()
        self.assertEqual(st["continuations"], 1)
        self.assertIs(st["merge"], True)

    # staying open

    def test_injected_and_ordinary_prompts_keep_run_open(self):
        self.prompt("/l3east:sleep")
        for text in (AUTO_CONTINUE, TASK_NOTIFICATION, "check CI", "hello"):
            self.prompt(text)
        self.assertEqual(self.state()["status"], "active")

    def test_wake_closes_run(self):
        self.prompt("/l3east:sleep")
        self.prompt("/l3east:wake")
        self.assertEqual(self.state()["status"], "ended")

    def test_wake_without_run_does_nothing(self):
        self.prompt("/l3east:wake")
        self.assertIsNone(self.state())

    # stop

    def test_stop_without_run_allows(self):
        self.assertIsNone(self.stop("hi"))

    def test_stop_while_active_blocks_and_counts(self):
        self.prompt("/l3east:sleep")
        out = self.stop("step 1 done")
        self.assertEqual(out["decision"], "block")
        self.assertIn("SLEEP-DONE", out["reason"])
        self.assertIn("wait with a tool", out["reason"])
        self.assertEqual(self.state()["continuations"], 1)

    def test_done_marker_on_last_line_closes(self):
        self.prompt("/l3east:sleep")
        self.assertIsNone(self.stop("report\n\nSLEEP-DONE\n"))
        self.assertEqual(self.state()["status"], "done")

    def test_formatted_done_marker_is_accepted(self):
        for marker in ("`SLEEP-DONE`", "**SLEEP-DONE**", "SLEEP-DONE."):
            self.prompt("/l3east:sleep")
            self.assertIsNone(self.stop(f"report\n{marker}"), marker)
            self.assertEqual(self.state()["status"], "done", marker)
            self.state_file().unlink()

    def test_marker_not_on_last_line_keeps_working(self):
        self.prompt("/l3east:sleep")
        out = self.stop("```\nSLEEP-DONE\n```\nI will print it at the end.")
        self.assertEqual(out["decision"], "block")

    def test_blocked_marker_needs_a_reason(self):
        self.prompt("/l3east:sleep")
        self.assertEqual(self.stop("report\nSLEEP-BLOCKED")["decision"], "block")
        self.assertIsNone(self.stop("report\nSLEEP-BLOCKED: needs prod creds"))
        self.assertEqual(self.state()["status"], "blocked")

    def test_pending_background_work_or_cron_allows_without_counting(self):
        self.prompt("/l3east:sleep")
        self.assertIsNone(self.stop("waiting", background_tasks=[{"id": "a1"}]))
        self.assertIsNone(self.stop("waiting", session_crons=[{"id": "c1"}]))
        self.assertEqual(self.state()["status"], "active")
        self.assertEqual(self.state()["continuations"], 0)

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

    def test_corrupt_state_warns_and_does_not_crash(self):
        self.state_file().parent.mkdir(parents=True)
        self.state_file().write_text("{not json")
        out = self.stop("step")
        self.assertIn("unreadable", out["systemMessage"])
        self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["status"], "active")

    # AskUserQuestion

    def test_ask_user_question_is_denied_while_active(self):
        self.prompt("/l3east:sleep")
        out = self.run_event("pretool", {"tool_name": "AskUserQuestion"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_ask_user_question_is_allowed_otherwise(self):
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))
        self.prompt("/l3east:sleep")
        self.stop("SLEEP-DONE")
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))

    # entry point

    def test_cli_entry_with_debug_on_fresh_home(self):
        script = Path(sleep_hook.__file__)
        env = {**os.environ, "L3EAST_SLEEP_DEBUG": "1"}
        for event, payload in (("prompt", {"session_id": "s1", "prompt": "/l3east:sleep"}),
                               ("stop", {"session_id": "s1", "last_assistant_message": "step 1"})):
            res = subprocess.run([sys.executable, "-I", str(script), event], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["decision"], "block")
        self.assertTrue((Path(self.tmp.name) / "l3east" / "sleep" / "debug.log").exists())

    def test_non_object_payload_and_bad_session_id_are_ignored(self):
        script = Path(sleep_hook.__file__)
        res = subprocess.run([sys.executable, "-I", str(script), "stop"], input="[]", capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.run_event("prompt", {"session_id": "../x", "prompt": "/l3east:sleep"})
        self.assertFalse((Path(self.tmp.name) / "l3east" / "sleep").exists())


if __name__ == "__main__":
    unittest.main()
