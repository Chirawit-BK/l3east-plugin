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
SCRIPT = ROOT / "scripts" / "sleep" / "sleep_hook.py"
sys.path.insert(0, str(SCRIPT.parent))
import sleep_hook  # noqa: E402

AUTO_CONTINUE = "Your claude.ai usage limit has reset. Continue the task you were working on."
TASK_NOTIFICATION = "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>"
SUBAGENT = {"id": "a1", "type": "subagent", "status": "running", "description": "review"}
DONE_SUBAGENT = {"id": "a2", "type": "subagent", "status": "completed", "description": "review"}
SHELL = {"id": "b1", "type": "shell", "status": "running", "description": "npm run dev"}
CRON = {"id": "c1", "schedule": "*/10 * * * *", "recurring": True}
GOOD_MERGE = "gh pr merge 5 --repo o/r --squash --match-head-commit abc1234"


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

    def shell(self, command, tool="Bash"):
        return self.run_event("pretool", {"tool_name": tool, "tool_input": {"command": command}})

    def reason(self, out):
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        return out["hookSpecificOutput"]["permissionDecisionReason"]

    # opening

    def test_sleep_opens_run_and_states_grant_and_skill_path(self):
        out = self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["status"], "active")
        self.assertIs(self.state()["merge"], False)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("merge granted: no", ctx)
        self.assertIn(str(sleep_hook.SKILL_PATH), ctx)

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

    def test_retyping_sleep_keeps_counters_updates_grant_and_restarts_ttl(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=17)).isoformat()
        self.write_state(status="active", merge=True, continuations=4, budget=40, started_at=old)
        self.prompt("/l3east:sleep")
        st = self.state()
        self.assertEqual(st["continuations"], 4)
        self.assertIs(st["merge"], False)
        self.assertGreater(datetime.fromisoformat(st["started_at"]), datetime.fromisoformat(old))

    # staying open

    def test_injected_prompts_keep_run_open_restate_grant_and_show_no_hint(self):
        self.prompt("/l3east:sleep merge")
        for text, source in ((AUTO_CONTINUE, None), (TASK_NOTIFICATION, None), ("tick", "loop_wakeup")):
            out = self.prompt(text, **({"source": source} if source else {}))
            self.assertIn("merge granted: yes", out["hookSpecificOutput"]["additionalContext"])
            self.assertNotIn("systemMessage", out, text)
        self.assertEqual(self.state()["status"], "active")

    def test_prompt_that_looks_human_gets_wake_hint(self):
        self.prompt("/l3east:sleep")
        for text, extra in (("how did it go?", {}), ("how did it go?", {"source": "user"}),
                            ("did it say: usage limit has reset?", {})):
            out = self.prompt(text, **extra)
            self.assertIn("/l3east:wake", out["systemMessage"], text)
        self.assertEqual(self.state()["status"], "active")

    def test_prompts_outside_a_run_are_silent(self):
        self.assertIsNone(self.prompt("hello"))

    def test_wake_closes_run_without_a_later_notice(self):
        self.prompt("/l3east:sleep")
        self.prompt("/l3east:wake")
        self.assertEqual(self.state()["status"], "ended")
        self.assertIsNone(self.prompt("hello"))

    def test_first_prompt_after_close_says_grant_is_revoked_once(self):
        self.prompt("/l3east:sleep merge")
        self.stop("SLEEP-DONE")
        out = self.prompt("morning")
        self.assertIn("run is closed (done)", out["hookSpecificOutput"]["additionalContext"])
        self.assertIn("revoked", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.prompt("again"))

    def test_machine_prompt_after_unattended_close_keeps_merges_blocked(self):
        os.environ["L3EAST_SLEEP_BUDGET"] = "1"
        self.prompt("/l3east:sleep merge")
        self.stop("a")
        self.stop("b", background_tasks=[SUBAGENT])
        self.assertEqual(self.state()["status"], "budget")
        out = self.prompt(TASK_NOTIFICATION)
        self.assertIn("run is closed (budget)", out["hookSpecificOutput"]["additionalContext"])
        for _ in range(2):
            self.assertIn("run is closed", self.reason(self.shell(GOOD_MERGE)))
            self.assertIn("run is closed", self.reason(self.shell("git push origin main")))
        self.assertIsNone(self.shell("git push origin feat/x"))
        self.prompt("ok, I'm here")
        self.assertIsNone(self.shell(GOOD_MERGE))

    def test_wake_on_a_closed_run_skips_the_notice(self):
        self.prompt("/l3east:sleep")
        self.stop("SLEEP-DONE")
        self.prompt("/l3east:wake")
        self.assertIsNone(self.prompt("hello"))

    def test_stale_run_expires_says_so_and_keeps_merges_blocked(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=19)).isoformat()
        self.write_state(status="active", merge=True, continuations=3, budget=40, started_at=old)
        self.assertIn("expired", self.stop("step")["systemMessage"])
        self.assertEqual(self.state()["status"], "expired")
        for _ in range(2):
            self.assertIn("run is closed (expired)", self.reason(self.shell(GOOD_MERGE)))

    # stop

    def test_stop_without_run_allows(self):
        self.assertIsNone(self.stop("hi"))

    def test_stop_while_active_blocks_and_restates_grant(self):
        self.prompt("/l3east:sleep merge")
        out = self.stop("step 1 done")
        self.assertEqual(out["decision"], "block")
        for text in ("SLEEP-DONE", "Wait for CI", "with a tool", "merge granted: yes", str(sleep_hook.SKILL_PATH)):
            self.assertIn(text, out["reason"])
        self.assertEqual(self.state()["continuations"], 1)

    def test_continuations_left_counts_down(self):
        os.environ["L3EAST_SLEEP_BUDGET"] = "5"
        self.prompt("/l3east:sleep")
        self.assertIn("(4 forced", self.stop("a")["reason"])
        self.assertIn("(3 forced", self.stop("b")["reason"])

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

    def test_running_subagent_lets_turn_end_without_counting(self):
        self.prompt("/l3east:sleep")
        for _ in range(10):
            self.assertIsNone(self.stop("waiting", background_tasks=[SUBAGENT]))
            self.prompt(TASK_NOTIFICATION)
        self.assertEqual(self.state()["continuations"], 0)

    def test_finished_subagent_does_not_count_as_pending(self):
        self.prompt("/l3east:sleep")
        self.assertEqual(self.stop("waiting", background_tasks=[DONE_SUBAGENT])["decision"], "block")

    def test_any_live_non_shell_task_wakes_and_paused_shell_does_not(self):
        self.prompt("/l3east:sleep")
        for kind in ("teammate", "cloud session", "MCP task", "monitor", "workflow"):
            task = {"id": "t", "type": kind, "status": "pending", "description": ""}
            self.assertIsNone(self.stop("waiting", background_tasks=[task]), kind)
        paused = {**SHELL, "status": "paused"}
        self.assertEqual(self.stop("waiting", background_tasks=[paused])["decision"], "block")

    def test_only_shells_or_crons_pending_blocks_and_names_them(self):
        self.prompt("/l3east:sleep")
        out = self.stop("waiting", background_tasks=[SHELL], session_crons=[CRON])
        self.assertEqual(out["decision"], "block")
        self.assertIn("1 background shell(s) and 1 session cron(s)", out["reason"])

    def test_last_continuation_asks_only_for_the_report_then_budget_closes(self):
        os.environ["L3EAST_SLEEP_BUDGET"] = "2"
        self.prompt("/l3east:sleep")
        self.assertIn("left", self.stop("a")["reason"])
        last = self.stop("b", background_tasks=[SHELL])["reason"]
        self.assertTrue(last.startswith("Sleep mode: this is the last forced continuation"), last)
        self.assertIn("SLEEP-BLOCKED: continuation budget spent", last)
        out = self.stop("c")
        self.assertIn("budget", out["systemMessage"])
        self.assertNotIn("decision", out)
        self.assertEqual(self.state()["status"], "budget")

    # corrupt state

    def test_unparseable_partial_or_naive_state_warns_on_stop(self):
        naive = {"status": "active", "budget": 40, "merge": False, "continuations": 0,
                 "started_at": "2026-01-01T00:00:00"}
        for content in ("{not json", json.dumps({"status": "active", "budget": 40, "merge": False}),
                        json.dumps({**naive, "budget": "x", "started_at": "2026-01-01T00:00:00+00:00"}),
                        json.dumps(naive)):
            self.state_file().parent.mkdir(parents=True, exist_ok=True)
            self.state_file().write_text(content)
            self.assertIn("unreadable", self.stop("step")["systemMessage"], content)

    def test_corrupt_state_fails_closed_on_ask_and_merge(self):
        self.write_state(status="active")
        self.assertIn("/l3east:wake", self.reason(self.run_event("pretool", {"tool_name": "AskUserQuestion"})))
        self.reason(self.shell(GOOD_MERGE))
        self.assertIsNone(self.shell("ls"))
        self.assertIn("/l3east:wake", self.prompt("what's going on?")["systemMessage"])

    def test_sleep_or_wake_replaces_a_corrupt_state(self):
        self.write_state(status="active")
        self.prompt("/l3east:sleep")
        self.assertEqual(self.state()["status"], "active")
        self.write_state(status="active")
        out = self.prompt("/l3east:wake")
        self.assertIn("removed", out["systemMessage"])
        self.assertIsNone(self.state())

    # PreToolUse

    def test_ask_user_question_is_denied_only_during_a_run(self):
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))
        self.prompt("/l3east:sleep")
        self.reason(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))
        self.stop("SLEEP-DONE")
        self.assertIsNone(self.run_event("pretool", {"tool_name": "AskUserQuestion"}))

    def test_merge_denied_without_grant(self):
        self.prompt("/l3east:sleep")
        self.assertIn("not granted", self.reason(self.shell(GOOD_MERGE)))

    def test_only_the_canonical_merge_form_passes(self):
        self.prompt("/l3east:sleep merge")
        bad = [
            "gh pr -R o/r merge 5 --squash --match-head-commit abc1234",
            "gh pr merge 5 -R o/r --squash --match-head-commit abc1234",
            "gh pr merge 5 --repo=o/r --squash --match-head-commit abc1234",
            "cd ../other && " + GOOD_MERGE,
            GOOD_MERGE + " && gh pr merge 9 --repo o/r --squash --match-head-commit abc1234",
            "gh pr merge --repo o/r --squash --match-head-commit abc1234",
            "gh pr merge 5 --repo o/r --squash",
            "gh pr merge 5 --squash --match-head-commit abc1234",
            "gh pr merge 5 --repo o/r --squash --admin --match-head-commit abc1234",
            "gh pr merge 5 --repo o/r --squash --auto --match-head-commit abc1234",
            "gh pr merge 5 --repo o/r --squash --delete-branch --match-head-commit abc1234",
            "gh pr merge 5 --repo o/r --squash --merge --match-head-commit abc1234",
            "gh api -X PUT repos/o/r/pulls/5/merge",
            "gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'",
            "gh api -X POST repos/o/r/merges -f base=feat -f head=x",
            "gh api graphql -f query='mutation { mergeBranch(input: {}) { clientMutationId } }'",
            "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
            "curl -X PUT https://api.github.com/repos/o/r/pulls/5/merge",
            'g""h pr mer\\ge 5 --repo o/r --squash --match-head-commit abc1234',
            "gh pr merge 5 --repo o/r --squash --match-head-commit abc1234 > out.txt",
        ]
        with mock.patch.object(sleep_hook, "pr_base", return_value="dev") as base:
            for cmd in bad:
                self.assertIn(sleep_hook.MERGE_FORM, self.reason(self.shell(cmd)), cmd)
            self.assertIn("$( )", self.reason(self.shell("echo $(" + GOOD_MERGE + ")")))
            base.assert_not_called()
            self.assertIsNone(self.shell(GOOD_MERGE))
            self.assertIsNone(self.shell(f'bash -c "{GOOD_MERGE}"'))
            self.assertEqual(base.call_count, 2)
            base.assert_called_with("5", "o/r")

    def test_ordinary_commands_that_mention_merge_pass_without_a_grant(self):
        self.prompt("/l3east:sleep")
        for cmd in ('gh pr create --title "Fix merge conflict in auth" --body "ready to merge"',
                    'gh pr comment 5 --body "merge-ready"', "gh pr checkout feat/merge-fix",
                    "gh run list --workflow merge.yml", "gh pr view 5 --json mergeable,mergeStateStatus",
                    "gh api repos/o/r --jq '[.allow_merge_commit,.allow_squash_merge]'",
                    "gh pr checks 5 --watch && git merge origin/dev", 'git commit -m "fix gh merge conflict"'):
            self.assertIsNone(self.shell(cmd), cmd)

    def test_merge_into_main_or_unknown_base_denied(self):
        self.prompt("/l3east:sleep merge")
        with mock.patch.object(sleep_hook, "pr_base", return_value="main"):
            self.assertIn("never merge into main", self.reason(self.shell(GOOD_MERGE)))
        with mock.patch.object(sleep_hook, "pr_base", return_value=None):
            self.assertIn("could not read", self.reason(self.shell(GOOD_MERGE)))

    def test_pr_base_asks_gh_for_that_repo(self):
        done = subprocess.CompletedProcess([], 0, stdout="develop\n", stderr="")
        with mock.patch.object(sleep_hook.subprocess, "run", return_value=done) as run:
            self.assertEqual(sleep_hook.pr_base("12", "o/r"), "develop")
        self.assertEqual(run.call_args.args[0],
                         ["gh", "pr", "view", "12", "--repo", "o/r", "--json", "baseRefName", "-q", ".baseRefName"])

    def test_push_to_protected_or_unnamed_branches_denied(self):
        self.prompt("/l3east:sleep merge")
        denied = {
            "git push origin main": "never push to main",
            "git push origin HEAD:refs/heads/master": "never push to master",
            "git -C ../wt push origin dev": "never push to dev",
            "git checkout develop && git merge feat/x && git push origin develop": "never push to develop",
            "git push": "name the remote and the branch",
            "git push origin HEAD": "instead of HEAD",
            "git push --all origin": "--all",
            "git push --mirror origin": "--mirror",
            "git push origin :feat/x": "deleting",
            "git push -f origin feat/x": "force-push",
            "git push origin +feat/x": "force-push",
            "env GIT_TRACE=1 git push origin main": "never push to main",
        }
        for cmd, why in denied.items():
            self.assertIn(why, self.reason(self.shell(cmd)), cmd)

    def test_ordinary_pushes_and_commands_pass(self):
        self.prompt("/l3east:sleep merge")
        for cmd in ("git push -u origin feat/main-menu", "git push origin main-fix",
                    "git push --force-with-lease origin feat/x", "git push origin HEAD:feat/x",
                    "git push -u origin feat/x && gh pr create --base main --fill", "git checkout main",
                    "git merge origin/dev", "ls"):
            self.assertIsNone(self.shell(cmd), cmd)

    def test_other_shell_tools_are_checked_too(self):
        self.prompt("/l3east:sleep")
        for tool in ("Monitor", "mcp__terminal__run_in_terminal", "mcp__plugin_serena_serena__execute_shell_command"):
            self.assertIn("not granted", self.reason(self.shell(GOOD_MERGE, tool=tool)), tool)
        self.assertIsNone(self.shell(GOOD_MERGE, tool="Read"))

    # entry point and wiring

    def run_cli(self, event, data, **env):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        return subprocess.run([sys.executable, "-I", str(SCRIPT), event], input=raw, capture_output=True,
                              env={**os.environ, **env})

    def test_cli_debug_log_redacts_long_and_nested_text(self):
        self.run_cli("prompt", {"session_id": "s1", "prompt": "/l3east:sleep"}, L3EAST_SLEEP_DEBUG="1")
        res = self.run_cli("pretool", {"session_id": "s1", "tool_name": "Bash",
                                       "tool_input": {"command": "GH_TOKEN=ghp_secret gh pr view 5"}},
                           L3EAST_SLEEP_DEBUG="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        res = self.run_cli("stop", {"session_id": "s1", "last_assistant_message": "x" * 500}, L3EAST_SLEEP_DEBUG="1")
        self.assertEqual(json.loads(res.stdout)["decision"], "block")
        log = (Path(self.tmp.name) / "l3east" / "sleep" / "debug.log").read_text()
        self.assertIn("<500 chars>", log)
        self.assertNotIn("ghp_secret", log)

    def test_cli_survives_bad_input(self):
        for raw in (b"[]", b"\xff\xfe not json", b'{"session_id": "s1\\n", "prompt": "/l3east:sleep"}'):
            res = self.run_cli("prompt", raw)
            self.assertEqual(res.returncode, 0, res.stderr)
        self.assertFalse((Path(self.tmp.name) / "l3east" / "sleep").exists())

    def test_handler_error_fails_closed_on_merge_and_warns_elsewhere(self):
        self.prompt("/l3east:sleep merge")

        def run_main(event, payload):
            out = io.StringIO()
            stdin = mock.Mock(buffer=io.BytesIO(json.dumps({"session_id": "s1", **payload}).encode()))
            with mock.patch.object(sys, "argv", ["sleep_hook.py", event]), mock.patch.object(sys, "stdin", stdin), \
                    mock.patch.object(sleep_hook, "HANDLERS", {k: boom for k in sleep_hook.HANDLERS}), \
                    redirect_stdout(out):
                self.assertEqual(sleep_hook.main(), 0)
            return json.loads(out.getvalue())

        def boom(*_):
            raise RuntimeError("kaboom")

        out = run_main("pretool", {"tool_name": "Bash", "tool_input": {"command": GOOD_MERGE}})
        self.assertIn("kaboom", self.reason(out))
        self.assertIn("kaboom", run_main("stop", {"last_assistant_message": "x"})["systemMessage"])

    def test_hooks_json_wires_every_event_to_the_script(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        wired = {ev: h["hooks"][0]["command"] for ev, (h,) in hooks.items()}
        self.assertEqual(set(wired), {"UserPromptSubmit", "Stop", "PreToolUse"})
        for ev, arg in (("UserPromptSubmit", "prompt"), ("Stop", "stop"), ("PreToolUse", "pretool")):
            self.assertTrue(wired[ev].endswith(f'scripts/sleep/sleep_hook.py" {arg}'), wired[ev])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"],
                         "AskUserQuestion|Bash|Monitor|.*run_in_terminal|.*execute_shell_command")


if __name__ == "__main__":
    unittest.main()
