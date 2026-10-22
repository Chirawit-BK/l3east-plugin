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

    def test_env_interpolation_anywhere_is_a_reference(self):
        self.assertFalse(common.has_plaintext_secret({"headers": {"Authorization": "Bearer ${TOKEN}"}}))
        self.assertFalse(common.has_plaintext_secret({"url": "postgres://${U}:${P}@h/db"}))
        self.assertFalse(common.has_plaintext_secret({"args": ["--token", "${TOKEN}"]}))

    def test_plaintext_userinfo_jwt_and_secret_arg(self):
        self.assertTrue(common.has_plaintext_secret({"args": ["x", "mysql://u:pw@h/db"]}))
        self.assertTrue(common.has_plaintext_secret({"url": "wss://u:pw@h/mcp"}))
        self.assertTrue(common.has_plaintext_secret({"command": "srv eyJa.eyJb.sig"}))
        self.assertTrue(common.has_plaintext_secret({"args": ["--api-key", "k2"]}))
        self.assertFalse(common.has_plaintext_secret({"args": ["--verbose", "x"], "url": "https://h/mcp"}))


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

    def test_basic_auth_header(self):
        out = common.mask_text('curl -H "Authorization: Basic dXNlcjpwdw=="')
        self.assertNotIn("dXNlcjpwdw", out)

    def test_dashed_flag_then_short_value(self):
        out = common.mask_text("srv --token shortval --verbose")
        self.assertNotIn("shortval", out)
        self.assertIn("--verbose", out)

    def test_userinfo_in_any_scheme(self):
        for scheme in ("postgresql", "mysql", "mongodb", "redis", "amqp", "wss"):
            out = common.mask_text(f"run {scheme}://admin:pwq1@db:1/x --flag")
            self.assertNotIn("pwq1", out, scheme)
            self.assertIn(f"{scheme}://db:1/x", out)

    def test_env_style_names_with_alnum_prefix(self):
        out = common.mask_text("PGPASSWORD=pwq1 psql; DB_PWD=pwq2 x; MYSECRETKEY: pwq3")
        for v in ("pwq1", "pwq2", "pwq3"):
            self.assertNotIn(v, out)
        self.assertIn("PGPASSWORD=***", out)
        self.assertIn("psql", out)

    def test_curl_user_forms(self):
        for cmd in ("curl -u admin:pwq1 h", "curl -su admin:pwq1 h", "curl --user admin:pwq1 h", "curl --user=admin:pwq1 h"):
            self.assertNotIn("pwq1", common.mask_text(cmd), cmd)
        self.assertEqual(common.mask_text("python3 -u script.py"), "python3 -u script.py")

    def test_jwt(self):
        out = common.mask_text("srv --header x eyJa1.eyJb2.sig3 end")
        self.assertNotIn("eyJa1", out)
        self.assertIn("end", out)

    def test_url_inside_text_goes_through_mask_url(self):
        out = common.mask_text("curl https://u:pwsecret@h/m?x=1 -o f")
        self.assertNotIn("pwsecret", out)
        self.assertIn("https://h/m?x=1", out)


class MaskUrlTests(unittest.TestCase):
    BLOB = "Zq9Xw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0FeDcBa98765"

    def test_drops_userinfo_and_fragment(self):
        out = common.mask_url("https://u:pwsecret@h:8443/m#frag")
        self.assertEqual(out, "https://h:8443/m")

    def test_blob_query_value_with_following_param(self):
        out = common.mask_url(f"https://h/m?sig={self.BLOB}&x=1")
        self.assertNotIn(self.BLOB, out)
        self.assertEqual(out, "https://h/m?sig=***&x=1")

    def test_blob_path_segment(self):
        out = common.mask_url(f"https://h/mcp/{self.BLOB}/sse")
        self.assertEqual(out, "https://h/mcp/***/sse")

    def test_secret_key_collapses_and_plain_values_stay_distinct(self):
        self.assertEqual(common.mask_url("https://h/m?token=A"), common.mask_url("https://h/m?token=B"))
        self.assertEqual(common.mask_url("https://h/m?token=A"), "https://h/m?token=***")
        self.assertNotEqual(common.mask_url("https://h/m?workspace=a"), common.mask_url("https://h/m?workspace=b"))


class MaskStringsTests(unittest.TestCase):
    def test_masks_value_after_secret_named_arg(self):
        out = common.mask_strings({"command": "srv", "args": ["--token", "shortval", "--api-key", "k2", "-v", "plain"]})
        self.assertEqual(out["args"], ["--token", "***", "--api-key", "***", "-v", "plain"])

    def test_self_contained_arg_does_not_mask_next(self):
        out = common.mask_strings(["--token=abc", "--verbose"])
        self.assertEqual(out, ["--token=***", "--verbose"])


class MiscTests(unittest.TestCase):
    def test_project_slug(self):
        self.assertEqual(common.project_slug("/Users/me/Dev/my app"), "-Users-me-Dev-my-app")

    def test_est_tokens(self):
        self.assertEqual(common.est_tokens("abcd"), 1)
        self.assertEqual(common.est_tokens("abcde"), 2)
        self.assertEqual(common.est_tokens(""), 0)


if __name__ == "__main__":
    unittest.main()
