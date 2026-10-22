import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_PROJECTS, load, run_script


class UsageTests(unittest.TestCase):
    def run_usage(self, tmp: Path, projects_dir: Path) -> dict:
        out = tmp / "usage.json"
        res = run_script("usage.py", "--projects-dir", str(projects_dir), "--since", "36500", "--out", str(out))
        self.assertEqual(res.returncode, 0, res.stderr)
        return load(out)

    def test_counts_skills_slash_and_mcp(self):
        with tempfile.TemporaryDirectory() as d:
            u = self.run_usage(Path(d), FIX_PROJECTS)
        self.assertEqual(u["status"], "ok")
        self.assertEqual(u["files_scanned"], 2)
        self.assertEqual(u["bad_lines"], 1)
        self.assertEqual(u["skills"]["commit-helper"]["total"], 2)
        self.assertEqual(u["skills"]["alpha:smart-commit"]["total"], 1)
        self.assertEqual(u["skills"]["verify"]["by_project"], {"-Users-test-other": 1})
        self.assertEqual(u["slash"]["/commit"]["total"], 1)
        self.assertEqual(u["mcp_servers"]["figma"]["total"], 1)
        self.assertNotIn("Bash", u.get("skills", {}))

    def test_unavailable_when_nothing_parses(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "projects" / "-x"
            empty.mkdir(parents=True)
            (empty / "s.jsonl").write_text('{"type":"user","message":{"content":"hi"}}\n', encoding="utf-8")
            u = self.run_usage(Path(d), Path(d) / "projects")
        self.assertEqual(u["status"], "unavailable")
        self.assertTrue(any("skill-doctor" in w for w in u["warnings"]))


if __name__ == "__main__":
    unittest.main()
