import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gateway


def provider(name, env):
    return {"id": name, "enabled": True, "local": False,
            "base_url": "https://gateway.example/v1", "model": name,
            "api_key_env": env, "tasks": ["research"], "capabilities": ["chat"],
            "input_cost_per_million": 1, "output_cost_per_million": 2,
            "allowed_sensitivity": ["public"]}


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, selected, messages, max_tokens, timeout):
        self.calls.append(selected["id"])
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def success(text="ok"):
    return {"choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2}}


class GatewayTests(unittest.TestCase):
    def config(self, providers, **overrides):
        return {"providers": providers, "max_attempts": 2, "max_requests_per_run": 4,
                "max_cost_usd_per_run": 1, "max_concurrency": 1,
                "max_output_tokens": 20, **overrides}

    def test_sensitive_content_is_blocked_before_external_transport(self):
        transport = FakeTransport([success()])
        provider_config = provider("remote", "AES_TEST_KEY")
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"AES_TEST_KEY": "never-log-this-key"}):
            client = gateway.Gateway(self.config([provider_config]), transport, directory)
            with self.assertRaises(gateway.PolicyBlocked):
                client.complete("research", [{"role": "user", "content": "Contact person" + "@example.com"}])
            self.assertEqual(transport.calls, [])
            audit = (Path(directory) / "gateway/events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("example.com", audit)
        self.assertNotIn("never-log-this-key", audit)
        self.assertIn('"event": "blocked"', audit)

    def test_fallback_is_bounded_and_logs_metadata_only(self):
        first, second = provider("first", "AES_TEST_KEY"), provider("second", "AES_TEST_KEY")
        transport = FakeTransport([OSError("network secret"), success("answer")])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"AES_TEST_KEY": "private-key-value"}):
            client = gateway.Gateway(self.config([first, second]), transport, directory)
            answer = client.complete("research", [{"role": "user", "content": "public prompt"}], max_tokens=5)
            rows = [json.loads(line) for line in (Path(directory) / "gateway/events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(transport.calls, ["first", "second"])
        self.assertEqual(answer["content"], "answer")
        self.assertEqual([row["event"] for row in rows], ["failure", "success"])
        self.assertNotIn("public prompt", json.dumps(rows))
        self.assertNotIn("private-key-value", json.dumps(rows))
        self.assertNotIn("network secret", json.dumps(rows))

    def test_sensitive_fallback_chain_excludes_unapproved_provider(self):
        approved = provider("reviewed", "AES_TEST_KEY")
        approved.update({"sensitive_authorized": True, "retention_reviewed_at": "2026-10-27",
                         "allowed_sensitivity": ["public", "sensitive"]})
        unapproved = provider("unreviewed", "AES_TEST_KEY")
        transport = FakeTransport([OSError("provider unavailable")])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"AES_TEST_KEY": "secret"}):
            client = gateway.Gateway(self.config([approved, unapproved]), transport, directory)
            with self.assertRaises(gateway.GatewayUnavailable):
                client.complete("research", [{"role": "user", "content": "personal" + "@example.com"}],
                                allow_sensitive_external=True)
        self.assertEqual(transport.calls, ["reviewed"])

    def test_budget_blocks_before_provider_call(self):
        transport = FakeTransport([success()])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"AES_TEST_KEY": "key"}):
            client = gateway.Gateway(self.config([provider("remote", "AES_TEST_KEY")], max_cost_usd_per_run=0), transport, directory)
            with self.assertRaisesRegex(gateway.GatewayError, "spend limit"):
                client.complete("research", [{"role": "user", "content": "hello"}], max_tokens=5)
        self.assertEqual(transport.calls, [])

    def test_local_provider_requires_loopback(self):
        self.assertTrue(gateway.endpoint_is_valid({"local": True, "base_url": "http://127.0.0.1:11434/v1"}))
        self.assertFalse(gateway.endpoint_is_valid({"local": True, "base_url": "http://0.0.0.0:11434/v1"}))
        self.assertFalse(gateway.endpoint_is_valid({"local": False, "base_url": "http://gateway.example/v1"}))
        self.assertFalse(gateway.endpoint_is_valid({"local": False, "base_url": "https://metadata.google.internal/v1"}))
        self.assertFalse(gateway.endpoint_is_valid({"local": False, "base_url": "https://127.0.0.1/v1"}))


if __name__ == "__main__":
    unittest.main()
