import json
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
        self.assertEqual(sorted(c["id"] for c in data["clusters"]), ["c01", "c02"])
        commit_cluster = next(c for c in data["clusters"] if "commit-helper" in c["members"])
        self.assertTrue(any("mentions" in r for r in commit_cluster["reasons"]))
        self.assertTrue(all("jaccard" in p for p in commit_cluster["pairs"]))

    def test_same_name_same_source_keeps_both_entries(self):
        entry = {"name": "dup", "source": "personal", "description": "duplicate entry", "mentions_skills": [],
                 "disable_model_invocation": False, "slash_names": []}
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv = tmp / "inventory.json"
            inv.write_text(json.dumps({"entries": [entry, dict(entry)]}), encoding="utf-8")
            out = tmp / "clusters.json"
            res = run_script("cluster.py", "--inventory", str(inv), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            data = load(out)
        keys = {m for c in data["clusters"] for m in c["members"]} | set(data["singletons"])
        self.assertEqual(keys, {"dup@personal", "dup@personal#2"})
        self.assertEqual(len(data["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
