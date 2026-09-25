"""scrub.py: stored values and token shapes go, commit SHAs and ordinary text stay."""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import scrub  # noqa: E402

SHA = "4904e6d0b1c2a3f4e5d6c7b8a9f0e1d2c3b4a5f6"


class Scrub(unittest.TestCase):
    def test_stored_value_is_replaced_everywhere(self):
        secret = "oauth-token-value-1234567890"
        text = f"env: CLAUDE_CODE_OAUTH_TOKEN={secret}\nagain {secret}"
        self.assertNotIn(secret, scrub.scrub(text, [secret]))
        self.assertEqual(scrub.scrub(text, [secret]).count(scrub.REDACTED), 2)

    def test_token_shapes_are_replaced_without_being_stored(self):
        samples = [
            "sk-ant-oat01-" + "A" * 40,
            "ghp_" + "b" * 36,
            "gho_" + "c" * 40,
            "github_pat_" + "D" * 60,
            "dop_v1_" + "e" * 64,
        ]
        for sample in samples:
            self.assertEqual(scrub.scrub(f"x {sample} y"), f"x {scrub.REDACTED} y", sample)

    def test_commit_shas_and_ordinary_text_survive(self):
        text = f"commit {SHA}\nmerged main into fleet/lane-1\nbase64 aGVsbG8gd29ybGQ="
        self.assertEqual(scrub.scrub(text, ["short"]), text)

    def test_a_stored_value_never_bites_into_a_longer_token(self):
        text = f"commit {SHA} and a databaseless design"
        self.assertEqual(scrub.scrub(text, [SHA[:8], "database"]), text)

    def test_a_stored_value_is_found_between_delimiters(self):
        secret = "stored-value-1234"
        for text in (f"TOKEN={secret}", f'"{secret}"', f"{secret}\n", f"x:{secret}/y"):
            self.assertNotIn(secret, scrub.scrub(text, [secret]), text)

    def test_a_tiny_stored_value_is_not_hunted(self):
        self.assertEqual(scrub.scrub("the cat sat", ["cat"]), "the cat sat")

    def test_longest_value_first(self):
        long_value, short_value = "abcdefgh12345678", "abcdefgh"
        self.assertEqual(scrub.scrub(long_value, [short_value, long_value]), scrub.REDACTED)

    def test_stored_secrets_reads_every_stored_key(self):
        with tempfile.TemporaryDirectory() as state:
            folder = os.path.join(state, "secrets")
            os.makedirs(folder)
            with open(os.path.join(folder, "demo.key"), "w") as handle:
                handle.write("demo-model-key-value\n")
            with open(os.path.join(folder, "empty.key"), "w") as handle:
                handle.write("\n")
            self.assertEqual(scrub.stored_secrets(state), ["demo-model-key-value"])

    def test_filter_mode_scrubs_a_stream(self):
        with tempfile.TemporaryDirectory() as state:
            folder = os.path.join(state, "secrets")
            os.makedirs(folder)
            with open(os.path.join(folder, "demo.key"), "w") as handle:
                handle.write("stream-secret-value-99")
            result = subprocess.run(
                [sys.executable, os.path.join(HERE, "..", "lib", "scrub.py")],
                input="a stream-secret-value-99 b\n", capture_output=True, text=True,
                env=dict(os.environ, FLEET_STATE=state), timeout=30)
            self.assertEqual(result.stdout, f"a {scrub.REDACTED} b\n")


if __name__ == "__main__":
    unittest.main()
