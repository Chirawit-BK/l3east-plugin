import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.skillkit.helpers import FIX_HOME, FIX_PROJECT, FIXTURE_TOKEN, SCRIPTS, write_plugin_list


class RunShTests(unittest.TestCase):
    def test_writes_all_five_files_without_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            out = tmp / "out"
            res = subprocess.run(
                ["bash", str(SCRIPTS / "run.sh"), "--project", str(FIX_PROJECT), "--out", str(out),
                 "--claude-home", str(FIX_HOME), "--plugin-list", str(write_plugin_list(tmp)), "--since", "36500"],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout.strip().splitlines()[-1], str(out))
            for name in ("inventory.json", "usage.json", "hooks_mcp.json", "clusters.json", "desc_lint.json"):
                self.assertTrue((out / name).is_file(), name)
                self.assertNotIn(FIXTURE_TOKEN, (out / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
