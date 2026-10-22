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

    def test_secrets_in_urls_args_and_hook_commands_are_masked(self):
        blob = "LEAKMEblob1234567890abcdefghijklmnopqrstu"
        commands = [
            'curl -H "Authorization: Bearer LEAKME2"',
            'curl -H "Authorization: Basic LEAKMEbasic=="',
            "srv --token LEAKMEflag",
        ]
        servers = {
            "tok_a": {"type": "http", "url": "https://h/mcp?token=LEAKME1234567890abcdefghijklmnopqrs"},
            "tok_b": {"type": "http", "url": "https://h/mcp?token=LEAKMEother"},
            "ws_a": {"type": "http", "url": "https://w/mcp?workspace=a"},
            "ws_b": {"type": "http", "url": "https://w/mcp?workspace=b"},
            "userinfo": {"type": "http", "url": "https://user:LEAKMEpw@u/mcp"},
            "sig": {"type": "http", "url": f"https://s/mcp?sig={blob}&x=1"},
            "path": {"type": "http", "url": f"https://p/mcp/{blob}"},
            "stdio": {"command": "srv", "args": ["--token", "LEAKMEshort"]},
        }
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            home = tmp / "home"
            project = tmp / "project"
            home.mkdir()
            project.mkdir()
            (home / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "*", "hooks": [{"type": "command", "command": c} for c in commands]},
            ]}}), encoding="utf-8")
            (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
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
        keys = {m["name"]: m["key"] for m in data["mcp"]}
        self.assertEqual(keys["tok_a"], keys["tok_b"])
        self.assertEqual(keys["tok_a"], "url:https://h/mcp?token=***")
        self.assertNotEqual(keys["ws_a"], keys["ws_b"])
        self.assertEqual(keys["userinfo"], "url:https://u/mcp")
        self.assertEqual(keys["sig"], "url:https://s/mcp?sig=***&x=1")
        self.assertEqual(keys["path"], "url:https://p/mcp/***")
        self.assertEqual(keys["stdio"], "cmd:srv --token ***")
        dup = [x for x in data["mcp_duplicates"] if x["key"] == "url:https://h/mcp?token=***"]
        self.assertEqual(sorted(e["name"] for e in dup[0]["entries"]), ["tok_a", "tok_b"])

if __name__ == "__main__":
    unittest.main()
