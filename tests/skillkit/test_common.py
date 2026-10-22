import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "skillkit"))
import common  # noqa: E402


class FrontmatterTests(unittest.TestCase):
    def test_single_line_values(self):
        meta, body = common.parse_frontmatter("---\nname: foo\ndescription: Use when X. Not for Y.\n---\nBody line\n")
        self.assertEqual(meta["name"], "foo")
        self.assertEqual(meta["description"], "Use when X. Not for Y.")
        self.assertEqual(body, "Body line")

    def test_folded_block_and_quotes(self):
        text = '---\nname: "bar"\ndescription: >\n  first part\n  second part\ndisable-model-invocation: true\n---\n'
        meta, _ = common.parse_frontmatter(text)
        self.assertEqual(meta["name"], "bar")
        self.assertEqual(meta["description"], "first part second part")
        self.assertIs(meta["disable-model-invocation"], True)

    def test_no_frontmatter(self):
        meta, body = common.parse_frontmatter("Just a command body\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "Just a command body\n")


class SecretTests(unittest.TestCase):
    def test_masks_env_headers_and_token_keys(self):
        cfg = {
            "command": "uvx",
            "args": ["mcp-x", "--token", "A" * 40],
            "env": {"JIRA_API_TOKEN": "abc", "PLAIN": "ok"},
            "headers": {"Authorization": "Bearer x"},
            "apiKey": "k",
            "url": "https://example.com/mcp",
        }
        masked = common.mask_secrets(cfg)
        self.assertEqual(masked["env"], {"JIRA_API_TOKEN": "***", "PLAIN": "***"})
        self.assertEqual(masked["headers"], {"Authorization": "***"})
        self.assertEqual(masked["apiKey"], "***")
        self.assertEqual(masked["args"][2], "***")
        self.assertEqual(masked["url"], "https://example.com/mcp")
        self.assertEqual(cfg["env"]["JIRA_API_TOKEN"], "abc")  # input untouched

    def test_masks_list_and_dict_under_secret_key(self):
        masked = common.mask_secrets({"tokens": ["abc"], "authorization": {"value": "x"}, "password": None})
        self.assertEqual(masked["tokens"], "***")
        self.assertEqual(masked["authorization"], "***")
        self.assertIsNone(masked["password"])

    def test_has_plaintext_secret(self):
        self.assertTrue(common.has_plaintext_secret({"env": {"X_TOKEN": "abc"}}))
        self.assertFalse(common.has_plaintext_secret({"env": {"X_TOKEN": "${X_TOKEN}"}}))
        self.assertFalse(common.has_plaintext_secret({"url": "https://a"}))


class MaskTextTests(unittest.TestCase):
    def test_url_query_key(self):
        out = common.mask_text("https://x/mcp?api_key=abc&v=1")
        self.assertIn("api_key=***", out)
        self.assertNotIn("abc", out)

    def test_bearer_header(self):
        out = common.mask_text('curl -H "Authorization: Bearer tok123"')
        self.assertNotIn("tok123", out)

    def test_long_blob_in_args(self):
        blob = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
        out = common.mask_text(f"server --flag {blob} --other x")
        self.assertNotIn(blob, out)
        self.assertIn("***", out)

    def test_env_style_name_prefix(self):
        out = common.mask_text("GITHUB_TOKEN=ghx123 run")
        self.assertNotIn("ghx123", out)

    def test_plain_command_unchanged(self):
        self.assertEqual(common.mask_text("pnpm lint"), "pnpm lint")


class MiscTests(unittest.TestCase):
    def test_project_slug(self):
        self.assertEqual(common.project_slug("/Users/me/Dev/my app"), "-Users-me-Dev-my-app")

    def test_est_tokens(self):
        self.assertEqual(common.est_tokens("abcd"), 1)
        self.assertEqual(common.est_tokens("abcde"), 2)
        self.assertEqual(common.est_tokens(""), 0)


if __name__ == "__main__":
    unittest.main()
