import json
import os
import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_CANDIDATE, FIX_HOME, FIX_PROJECT, FIXTURE, load, run_script, write_plugin_list


class InventoryTests(unittest.TestCase):
    def run_inventory(self, tmp: Path, *extra: str) -> dict:
        out = tmp / "inventory.json"
        res = run_script(
            "inventory.py",
            "--project", str(FIX_PROJECT),
            "--claude-home", str(FIX_HOME),
            "--plugin-list", str(write_plugin_list(tmp)),
            "--out", str(out),
            *extra,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return load(out)

    def test_entries_from_every_source(self):
        with tempfile.TemporaryDirectory() as d:
            inv = self.run_inventory(Path(d))
        by_key = {(e["name"], e["source"]): e for e in inv["entries"]}
        self.assertIn(("commit-helper", "personal"), by_key)
        self.assertIn(("verify", "personal"), by_key)
        self.assertIn(("verify", "project"), by_key)
        self.assertIn(("commit", "command:user"), by_key)
        self.assertIn(("deploy", "command:project"), by_key)
        self.assertIn(("smart-commit", "plugin:alpha@mkt"), by_key)
        self.assertNotIn(("disabled-thing", "plugin:off@mkt"), by_key)
        self.assertEqual(by_key[("smart-commit", "plugin:alpha@mkt")]["slash_names"], ["/alpha:smart-commit"])
        self.assertEqual(by_key[("deploy", "command:project")]["description"], "Deploy this project to staging. Not for production.")
        self.assertEqual(by_key[("commit", "command:user")]["description"], "You are my commit assistant. Do NOT invoke the `commit-helper` skill for this command.")

    def test_same_name_mentions_truncation_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            inv = self.run_inventory(Path(d))
        self.assertEqual(sorted(inv["same_name"]["verify"]), ["personal", "project"])
        cmd = next(e for e in inv["entries"] if e["name"] == "commit" and e["kind"] == "command")
        self.assertEqual(cmd["mentions_skills"], ["commit-helper"])
        big = next(e for e in inv["entries"] if e["name"] == "bigdesc")
        self.assertTrue(big["truncated"])
        self.assertGreater(inv["est_listing_tokens"], 0)
        self.assertEqual(inv["est_listing_tokens"], sum(e["est_tokens"] for e in inv["entries"] if not e["disable_model_invocation"]))

    def test_extra_candidate_dir(self):
        with tempfile.TemporaryDirectory() as d:
            inv = self.run_inventory(Path(d), "--extra", str(FIX_CANDIDATE))
        cand = [e for e in inv["entries"] if e["source"].startswith("candidate")]
        self.assertEqual([c["name"] for c in cand], ["quick-commit"])
        self.assertEqual(cand[0]["source"], "candidate:candidate")

    def test_empty_install_path_is_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            pl = tmp / "pl.json"
            pl.write_text(json.dumps([{"id": "ghost@synced", "version": "x", "scope": "synced", "enabled": True, "installPath": ""}]), encoding="utf-8")
            out = tmp / "inventory.json"
            res = run_script("inventory.py", "--project", str(FIX_PROJECT), "--claude-home", str(FIX_HOME), "--plugin-list", str(pl), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            inv = load(out)
        self.assertFalse(any(e["source"] == "plugin:ghost@synced" for e in inv["entries"]))
        # an empty installPath must not resolve to cwd (the repo root): every entry comes from the fixture
        self.assertTrue(all(e["path"].startswith(str(FIXTURE) + os.sep) for e in inv["entries"]))
        self.assertTrue(any("ghost@synced" in w and "installPath" in w for w in inv["warnings"]))

    def test_synced_bucket_is_scanned_as_anthropic_skills(self):
        with tempfile.TemporaryDirectory() as d:
            inv = self.run_inventory(Path(d))
        docs = next(e for e in inv["entries"] if e["name"] == "docs")
        self.assertEqual(docs["source"], "plugin:anthropic-skills@synced")
        self.assertEqual(docs["slash_names"], ["/anthropic-skills:docs"])


if __name__ == "__main__":
    unittest.main()
