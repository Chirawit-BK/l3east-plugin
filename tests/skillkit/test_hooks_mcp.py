import json
import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_CANDIDATE, FIX_HOME, FIX_PROJECT, FIXTURE_TOKEN, load, run_script, write_plugin_list


class HooksMcpTests(unittest.TestCase):
    def run_it(self, tmp: Path, *extra: str) -> tuple[dict, str]:
        out = tmp / "hooks_mcp.json"
        res = run_script(
            "hooks_mcp.py",
            "--project", str(FIX_PROJECT),
            "--claude-home", str(FIX_HOME),
            "--plugin-list", str(write_plugin_list(tmp)),
            "--out", str(out),
            *extra,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return load(out), out.read_text(encoding="utf-8")

    def test_overlaps_duplicates_and_masking(self):
        with tempfile.TemporaryDirectory() as d:
            data, raw = self.run_it(Path(d))
        self.assertNotIn(FIXTURE_TOKEN, raw)
        ov = [o for o in data["hook_overlaps"] if o["event"] == "UserPromptSubmit"]
        self.assertEqual(len(ov), 1)
        self.assertTrue(any(s.startswith("user settings") for s in ov[0]["sources"]))
        self.assertIn("plugin:alpha@mkt", ov[0]["sources"])
        self.assertEqual(len(data["mcp_duplicates"]), 1)
        self.assertEqual(data["mcp_duplicates"][0]["key"], "url:https://mcp.example.com/mcp")
        jira = next(m for m in data["mcp"] if m["name"] == "jira")
        self.assertTrue(jira["has_plaintext_secret"])
        self.assertEqual(jira["spec"]["env"]["JIRA_API_TOKEN"], "***")
        sus = data["suspicious_global_hooks"]
        self.assertTrue(any("pnpm lint" in s["command"] for s in sus))
        self.assertEqual(data["mcp_same_name"][0]["name"], "figma")

    def test_candidate_dir_adds_hooks_and_mcp(self):
        with tempfile.TemporaryDirectory() as d:
            data, _ = self.run_it(Path(d), "--extra", str(FIX_CANDIDATE))
        ov = next(o for o in data["hook_overlaps"] if o["event"] == "UserPromptSubmit")
        self.assertIn("candidate:candidate", ov["sources"])
        dup = data["mcp_duplicates"][0]
        self.assertEqual(len(dup["entries"]), 3)


    def test_url_query_and_hook_command_are_masked(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            home = tmp / "home"
            project = tmp / "project"
            home.mkdir()
            project.mkdir()
            (home / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": 'curl -H "Authorization: Bearer LEAKME2"'}]},
            ]}}), encoding="utf-8")
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {
                "a": {"type": "http", "url": "https://h/mcp?token=LEAKME1234567890abcdefghijklmnopqrs"},
                "b": {"type": "http", "url": "https://h/mcp"},
            }}), encoding="utf-8")
            plugin_list = tmp / "plugin-list.json"
            plugin_list.write_text("[]", encoding="utf-8")
            out = tmp / "hooks_mcp.json"
            res = run_script(
                "hooks_mcp.py",
                "--project", str(project),
                "--claude-home", str(home),
                "--plugin-list", str(plugin_list),
                "--out", str(out),
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            raw = out.read_text(encoding="utf-8")
            data = load(out)
        self.assertNotIn("LEAKME", raw)
        dup = [x for x in data["mcp_duplicates"] if x["key"] == "url:https://h/mcp"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(sorted(e["name"] for e in dup[0]["entries"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
