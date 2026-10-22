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

    def test_common_name_token_does_not_chain_everything(self):
        entries = []
        for i in range(30):
            # distinct filler per entry keeps pairwise jaccard under the threshold, so only the name token could link them
            filler = " ".join(f"task{i:02d}w{k}" for k in range(12))
            entries.append({"name": f"figma-{i:02d}", "source": "personal", "description": f"Use when doing figma {filler}.",
                            "mentions_skills": [], "disable_model_invocation": False, "slash_names": [f"/figma-{i:02d}"]})
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv = tmp / "inventory.json"
            inv.write_text(json.dumps({"entries": entries}), encoding="utf-8")
            out = tmp / "clusters.json"
            res = run_script("cluster.py", "--inventory", str(inv), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            data = load(out)
        self.assertTrue(all(len(c["members"]) <= 20 for c in data["clusters"]))
        self.assertEqual(data["oversized"], [])
        self.assertFalse(any("name token 'figma'" in r for c in data["clusters"] for r in c["reasons"]))

    def test_weak_merge_respects_size_cap(self):
        # 25 entries share the rare token "zzzz" (DF 25 > 5) so no name-token edge; 3 entries share "qqqq" (DF 3) and do link.
        entries = [{"name": f"qqqq-{k}", "source": "personal", "description": f"Totally different text {k} alpha beta gamma.", "mentions_skills": [],
                    "disable_model_invocation": False, "slash_names": [f"/qqqq-{k}"]} for k in ("a", "b", "c")]
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            inv = tmp / "inventory.json"
            inv.write_text(json.dumps({"entries": entries}), encoding="utf-8")
            out = tmp / "clusters.json"
            res = run_script("cluster.py", "--inventory", str(inv), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            data = load(out)
        self.assertEqual([set(c["members"]) for c in data["clusters"]], [{"qqqq-a", "qqqq-b", "qqqq-c"}])


if __name__ == "__main__":
    unittest.main()
