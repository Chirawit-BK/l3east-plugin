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
        self.assertEqual(cand[0]["slash_names"], ["/cand:quick-commit"])  # prefix from plugin.json name

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

    def test_mentions_ignore_paths_and_short_backtick_words(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            home, project = tmp / "home", tmp / "project"
            for name in ("dev", "docs", "commit-helper"):
                (home / "skills" / name).mkdir(parents=True)
                (home / "skills" / name / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: Use when testing {name}. Not for anything else.\n---\n\nBody.\n", encoding="utf-8")
            (home / "commands").mkdir()
            (home / "commands" / "branchy.md").write_text(
                "checkout `dev` branch, see /docs/figma/ and `commit-helper` then /dev \n", encoding="utf-8")
            project.mkdir()
            pl = tmp / "pl.json"
            pl.write_text("[]", encoding="utf-8")
            out = tmp / "inventory.json"
            res = run_script("inventory.py", "--project", str(project), "--claude-home", str(home), "--plugin-list", str(pl), "--out", str(out))
            self.assertEqual(res.returncode, 0, res.stderr)
            inv = load(out)
        cmd = next(e for e in inv["entries"] if e["name"] == "branchy")
        self.assertEqual(cmd["mentions_skills"], ["commit-helper", "dev"])


    def run_temp(self, tmp: Path, *extra: str) -> dict:
        """inventory.py against a temp home and project, empty plugin list."""
        home, project = tmp / "home", tmp / "project"
        home.mkdir(exist_ok=True)
        project.mkdir(exist_ok=True)
        pl = tmp / "pl.json"
        pl.write_text("[]", encoding="utf-8")
        out = tmp / "inventory.json"
        res = run_script("inventory.py", "--project", str(project), "--claude-home", str(home), "--plugin-list", str(pl), "--out", str(out), *extra)
        self.assertEqual(res.returncode, 0, res.stderr)
        return load(out)

    @staticmethod
    def write_skill(d: Path, name: str) -> Path:
        d.mkdir(parents=True, exist_ok=True)
        md = d / "SKILL.md"
        md.write_text(f"---\nname: {name}\ndescription: Use when testing {name}. Not for anything else.\n---\n\nBody.\n", encoding="utf-8")
        return md

    def test_non_object_plugin_json_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            cand = tmp / "oddcand"
            (cand / ".claude-plugin").mkdir(parents=True)
            (cand / ".claude-plugin" / "plugin.json").write_text('["oops"]', encoding="utf-8")
            self.write_skill(cand / "skills" / "odd-skill", "odd-skill")
            inv = self.run_temp(tmp, "--extra", str(cand))
        odd = [e for e in inv["entries"] if e["name"] == "odd-skill"]
        self.assertEqual(len(odd), 1)
        self.assertEqual(odd[0]["source"], "candidate:oddcand")
        self.assertEqual(odd[0]["slash_names"], ["/oddcand:odd-skill"])
        self.assertTrue(any("plugin.json" in w for w in inv["warnings"]))

    def test_empty_extra_root_warns(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            empty = tmp / "empty"
            empty.mkdir()
            inv = self.run_temp(tmp, "--extra", str(empty))
        self.assertIn(f"extra root yielded no skills or commands: {empty.resolve()}", inv["warnings"])

    def test_synced_copies_inventoried_once_newest_wins(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            synced = tmp / "home" / "skills" / "synced"
            old = self.write_skill(synced / "sess-a" / "docs", "docs")
            new = self.write_skill(synced / "sess-b" / "docs", "docs")
            os.utime(old, (2_000_000_000, 2_000_000_000))  # sess-a sorts first and is the newer copy
            os.utime(new, (1_000_000_000, 1_000_000_000))
            inv = self.run_temp(tmp)
        docs = [e for e in inv["entries"] if e["name"] == "docs"]
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["path"], str(old.resolve()))
        self.assertEqual(docs[0]["slash_names"], ["/anthropic-skills:docs"])
        self.assertNotIn("docs", inv["same_name"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read a chmod 000 file")
    def test_unreadable_skill_is_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            locked = self.write_skill(tmp / "home" / "skills" / "locked", "locked")
            self.write_skill(tmp / "home" / "skills" / "fine", "fine")
            locked.chmod(0)
            try:
                inv = self.run_temp(tmp)
            finally:
                locked.chmod(0o644)
        names = {e["name"] for e in inv["entries"]}
        self.assertIn("fine", names)
        self.assertNotIn("locked", names)
        self.assertTrue(any("unreadable" in w and "locked" in w for w in inv["warnings"]))


if __name__ == "__main__":
    unittest.main()
