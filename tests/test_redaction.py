import json
import unittest

from bfa.redaction import is_sensitive_key, redact_object, redact_value


class RedactionTests(unittest.TestCase):
    def test_sensitive_key_detection_is_case_insensitive(self):
        sensitive = [
            "BINANCE_API_KEY",
            "api_secret",
            "OpenAiToken",
            "session_cookie",
            "db_password",
            "private_key_path",
        ]

        for key in sensitive:
            with self.subTest(key=key):
                self.assertTrue(is_sensitive_key(key))

        self.assertFalse(is_sensitive_key("BFA_MODE"))
        self.assertFalse(is_sensitive_key("max_position_notional"))
        self.assertFalse(is_sensitive_key("OPENAI_MAX_OUTPUT_TOKENS"))
        self.assertFalse(is_sensitive_key("max_tokens"))

    def test_scalar_redaction_preserves_empty_values(self):
        self.assertEqual(redact_value(""), "")
        self.assertIsNone(redact_value(None))

    def test_scalar_redaction_hides_short_and_long_values(self):
        short_secret = "abc123"
        long_secret = "synthetic-secret-value-123456"

        self.assertEqual(redact_value(short_secret), "<redacted>")
        redacted_long = redact_value(long_secret)

        self.assertNotEqual(redacted_long, long_secret)
        self.assertNotIn(long_secret, redacted_long)
        self.assertTrue(redacted_long.startswith("synt"))
        self.assertTrue(redacted_long.endswith("3456"))

    def test_redact_object_preserves_non_sensitive_values(self):
        payload = {
            "BFA_MODE": "dry_run",
            "BFA_MAX_LEVERAGE": 3,
            "BINANCE_API_SECRET": "synthetic-secret-value-123456",
        }

        redacted = redact_object(payload)

        self.assertEqual(redacted["BFA_MODE"], "dry_run")
        self.assertEqual(redacted["BFA_MAX_LEVERAGE"], 3)
        self.assertNotIn("synthetic-secret-value-123456", json.dumps(redacted))

    def test_recursive_redaction_handles_dicts_lists_and_tuples(self):
        payload = {
            "outer": {
                "OPENAI_API_KEY": "synthetic-openai-key-abcdef",
                "items": [
                    {"cookie": "synthetic-cookie-value-abcdef"},
                    ("safe", {"token": "synthetic-token-value-abcdef"}),
                ],
            },
            "safe_list": ["BTCUSDT", 100],
        }

        redacted = redact_object(payload)
        serialized = json.dumps(redacted, sort_keys=True)

        self.assertEqual(redacted["safe_list"], ["BTCUSDT", 100])
        self.assertNotIn("synthetic-openai-key-abcdef", serialized)
        self.assertNotIn("synthetic-cookie-value-abcdef", serialized)
        self.assertNotIn("synthetic-token-value-abcdef", serialized)

    def test_nested_diagnostic_output_contains_no_exact_secret_values(self):
        secrets = {
            "binance": "synthetic-binance-secret-abcdef",
            "openai": "synthetic-openai-secret-abcdef",
            "cookie": "synthetic-cookie-secret-abcdef",
        }
        payload = {
            "exchange": {
                "api_key": secrets["binance"],
                "nested": [{"OPENAI_TOKEN": secrets["openai"]}],
            },
            "browser": {"session_cookie": secrets["cookie"]},
            "mode": "dry_run",
        }

        serialized = json.dumps(redact_object(payload), sort_keys=True)

        for secret in secrets.values():
            self.assertNotIn(secret, serialized)
        self.assertIn("dry_run", serialized)


if __name__ == "__main__":
    unittest.main()
