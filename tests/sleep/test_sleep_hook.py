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
            sleep_hook.handle(event, payload)
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def state(self, sid="s1"):
        p = Path(self.tmp.name) / "l3east" / "sleep" / f"{sid}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def start(self, prompt="/l3east:sleep fix the report endpoint"):
        self.run_event("prompt", {"session_id": "s1", "prompt": prompt})

    def test_sleep_prompt_starts_active_state(self):
        self.start()
        st = self.state()
        self.assertEqual(st["status"], "active")
        self.assertEqual(st["continuations"], 0)

    def test_bare_sleep_alias_also_starts(self):
        self.start("  /sleep merge do the thing")
        self.assertEqual(self.state()["status"], "active")

    def test_word_sleep_inside_prompt_does_not_start(self):
        self.run_event("prompt", {"session_id": "s1", "prompt": "how does /l3east:sleep work?"})
        self.run_event("prompt", {"session_id": "s1", "prompt": "/sleeper go"})
        self.assertIsNone(self.state())

    def test_other_prompt_without_state_does_nothing(self):
        self.run_event("prompt", {"session_id": "s1", "prompt": "hello"})
        self.assertIsNone(self.state())

    def test_other_prompt_ends_active_sleep(self):
        self.start()
        self.run_event("prompt", {"session_id": "s1", "prompt": "I'm back, what happened?"})
        self.assertEqual(self.state()["status"], "ended")

    def test_stop_without_state_allows(self):
        self.assertIsNone(self.run_event("stop", {"session_id": "s1", "last_assistant_message": "hi"}))

    def test_stop_while_active_blocks_and_counts(self):
        self.start()
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "step 1 done"})
        self.assertEqual(out["decision"], "block")
        self.assertIn("SLEEP-DONE", out["reason"])
        self.assertEqual(self.state()["continuations"], 1)

    def test_done_marker_allows_and_closes(self):
        self.start()
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "report\nSLEEP-DONE"})
        self.assertIsNone(out)
        self.assertEqual(self.state()["status"], "done")

    def test_blocked_marker_allows_and_closes(self):
        self.start()
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "report\nSLEEP-BLOCKED: needs prod creds"})
        self.assertIsNone(out)
        self.assertEqual(self.state()["status"], "blocked")

    def test_marker_must_be_its_own_line(self):
        self.start()
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "I will print SLEEP-DONE later"})
        self.assertEqual(out["decision"], "block")

    def test_background_work_allows_without_counting(self):
        self.start()
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "waiting", "background_tasks": [{"id": "a1"}]})
        self.assertIsNone(out)
        self.assertEqual(self.state()["status"], "active")
        self.assertEqual(self.state()["continuations"], 0)

    def test_budget_exhausted_allows_and_reports(self):
        os.environ["L3EAST_SLEEP_BUDGET"] = "2"
        self.start()
        self.run_event("stop", {"session_id": "s1", "last_assistant_message": "a"})
        self.run_event("stop", {"session_id": "s1", "last_assistant_message": "b"})
        out = self.run_event("stop", {"session_id": "s1", "last_assistant_message": "c"})
        self.assertIn("budget", out["systemMessage"])
        self.assertNotIn("decision", out)
        self.assertEqual(self.state()["status"], "budget")

    def test_closed_state_never_blocks(self):
        self.start()
        self.run_event("stop", {"session_id": "s1", "last_assistant_message": "SLEEP-DONE"})
        self.assertIsNone(self.run_event("stop", {"session_id": "s1", "last_assistant_message": "more"}))

    def test_cli_entry_with_debug_on_fresh_home(self):
        script = Path(sleep_hook.__file__)
        env = {**os.environ, "L3EAST_SLEEP_DEBUG": "1"}
        for event, payload in (("prompt", {"session_id": "s1", "prompt": "/l3east:sleep go"}),
                               ("stop", {"session_id": "s1", "last_assistant_message": "step 1"})):
            res = subprocess.run([sys.executable, "-I", str(script), event], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout)["decision"], "block")
        self.assertTrue((Path(self.tmp.name) / "l3east" / "sleep" / "debug.log").exists())

    def test_bad_session_id_is_ignored(self):
        self.run_event("prompt", {"session_id": "../x", "prompt": "/l3east:sleep go"})
        self.assertFalse((Path(self.tmp.name) / "l3east" / "sleep").exists())


if __name__ == "__main__":
    unittest.main()
