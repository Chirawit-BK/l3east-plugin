import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_HOME, FIX_PROJECT, load, run_script, write_plugin_list


class ClusterTests(unittest.TestCase):
    def test_commit_family_and_same_name_cluster(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv = tmp / "inventory.json"
            res = run_script("inventory.py", "--project", str(FIX_PROJECT), "--claude-home", str(FIX_HOME),
                             "--plugin-list", str(write_plugin_list(tmp)), "--out", str(inv))
            self.assertEqual(res.returncode, 0, res.stderr)
            out = tmp / "clusters.json"
            res = run_script("cluster.py", "--inventory", str(inv), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            data = load(out)
        members = [set(c["members"]) for c in data["clusters"]]
        self.assertIn({"commit", "commit-helper", "smart-commit"}, members)
        self.assertIn({"verify@personal", "verify@project"}, members)
        self.assertIn("bigdesc", data["singletons"])
        self.assertIn("deploy", data["singletons"])
        commit_cluster = next(c for c in data["clusters"] if "commit-helper" in c["members"])
        self.assertTrue(any("mentions" in r for r in commit_cluster["reasons"]))
        self.assertTrue(all("jaccard" in p for p in commit_cluster["pairs"]))


if __name__ == "__main__":
    unittest.main()
