import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bfa.cli import main


class CliTests(unittest.TestCase):
    def invoke(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args), env={})
        return code, stdout.getvalue(), stderr.getvalue()

    def test_config_check_dry_run_example_exits_zero(self):
        code, stdout, stderr = self.invoke("config-check", "--env-file", ".env.example")
        payload = json.loads(stdout)

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["errors"], [])

    def test_invalid_live_config_exits_nonzero_with_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            env_path.write_text("BFA_MODE=live\n", encoding="utf-8")

            code, stdout, _stderr = self.invoke("config-check", "--env-file", str(env_path))

        payload = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertFalse(payload["valid"])
        self.assertIn("BINANCE_API_KEY is required for live mode", payload["errors"])
        self.assertIn("BINANCE_API_SECRET is required for live mode", payload["errors"])

    def test_config_check_redacts_synthetic_sensitive_values(self):
        synthetic_key = "synthetic-binance-key-abcdef"
        synthetic_secret = "synthetic-binance-secret-abcdef"
        synthetic_openai = "synthetic-openai-key-abcdef"

        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / "env"
            env_path.write_text(
                "\n".join(
                    [
                        "BFA_MODE=live",
                        "BFA_OPENAI_ENABLED=true",
                        f"BINANCE_API_KEY={synthetic_key}",
                        f"BINANCE_API_SECRET={synthetic_secret}",
                        f"OPENAI_API_KEY={synthetic_openai}",
                    ]
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self.invoke("config-check", "--env-file", str(env_path))

        combined = stdout + stderr
        payload = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertTrue(payload["valid"])
        self.assertNotIn(synthetic_key, combined)
        self.assertNotIn(synthetic_secret, combined)
        self.assertNotIn(synthetic_openai, combined)
        self.assertIn("redacted", payload)


if __name__ == "__main__":
    unittest.main()
