import json
import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_HOME, FIX_PROJECT, FIX_PROJECTS, load, run_script, write_plugin_list


class DescLintTests(unittest.TestCase):
    def test_issue_codes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv, usage, out = tmp / "inventory.json", tmp / "usage.json", tmp / "desc_lint.json"
            r = run_script("inventory.py", "--project", str(FIX_PROJECT), "--claude-home", str(FIX_HOME),
                           "--plugin-list", str(write_plugin_list(tmp)), "--out", str(inv))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run_script("usage.py", "--projects-dir", str(FIX_PROJECTS), "--since", "36500", "--out", str(usage))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run_script("desc_lint.py", "--inventory", str(inv), "--usage", str(usage), "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = load(out)
            n_entries = len(load(inv)["entries"])
        issues = {(e["name"], e["source"]): set(e["issues"]) for e in data["entries"]}
        self.assertIn("truncated_over_1536", issues[("bigdesc", "personal")])
        self.assertIn("never_used_in_window", issues[("deploy", "command:project")])
        self.assertIn("no_not_for", issues[("smart-commit", "plugin:alpha@mkt")])
        self.assertNotIn(("commit-helper", "personal"), issues)  # used twice, has trigger + not-for
        self.assertEqual(data["summary"]["truncated_over_1536"], 1)
        uses = {(u["name"], u["source"]): u["uses"] for u in data["uses_all"]}
        self.assertEqual(uses[("commit-helper", "personal")], 2)  # no issues, still listed in uses_all
        self.assertEqual(uses[("smart-commit", "plugin:alpha@mkt")], 1)
        self.assertEqual(len(data["uses_all"]), n_entries)


    def test_trigger_phrase_variants(self):
        descs = {
            "triggers": "Triggers on: chart, graph, plot requests from the user in any medium.",
            "use-after": "Use after Phase 1 crawl completes to dedupe the module documents.",
            "plain": "Summarize a video into takeaways.",
        }
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv, usage, out = tmp / "inventory.json", tmp / "usage.json", tmp / "desc_lint.json"
            inv.write_text(json.dumps({"entries": [
                {"name": n, "source": "personal", "description": t, "desc_chars": len(t), "slash_names": ["/" + n]}
                for n, t in descs.items()
            ]}), encoding="utf-8")
            usage.write_text(json.dumps({"status": "unavailable"}), encoding="utf-8")
            r = run_script("desc_lint.py", "--inventory", str(inv), "--usage", str(usage), "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            data = load(out)
        issues = {e["name"]: set(e["issues"]) for e in data["entries"]}
        self.assertNotIn("no_trigger_phrase", issues.get("triggers", set()))
        self.assertNotIn("no_trigger_phrase", issues.get("use-after", set()))
        self.assertIn("no_trigger_phrase", issues["plain"])
        self.assertNotIn("never_used_in_window", set().union(*issues.values()))
        self.assertEqual(sorted(u["name"] for u in data["uses_all"]), sorted(descs))
        self.assertTrue(all(u["uses"] is None for u in data["uses_all"]))


if __name__ == "__main__":
    unittest.main()
