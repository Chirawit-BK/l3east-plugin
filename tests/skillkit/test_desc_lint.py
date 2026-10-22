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
        issues = {(e["name"], e["source"]): set(e["issues"]) for e in data["entries"]}
        self.assertIn("truncated_over_1536", issues[("bigdesc", "personal")])
        self.assertIn("never_used_in_window", issues[("deploy", "command:project")])
        self.assertIn("no_not_for", issues[("smart-commit", "plugin:alpha@mkt")])
        self.assertNotIn(("commit-helper", "personal"), issues)  # used twice, has trigger + not-for
        self.assertEqual(data["summary"]["truncated_over_1536"], 1)


if __name__ == "__main__":
    unittest.main()
