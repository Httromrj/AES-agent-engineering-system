import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import dashboard


class DashboardTests(unittest.TestCase):
    def test_status_summarizes_runs_register_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            research = state / "research"
            (research / "digests").mkdir(parents=True)
            (research / "runs.jsonl").write_text(json.dumps({
                "started_at": "2026-10-27T10:00:00+00:00", "finished_at": "2026-10-27T10:00:02+00:00",
                "duration_seconds": 2, "sources_configured": 4, "source_counts": [{"source_id": "demo", "items": 3}],
                "fetched": 3, "new": 2, "rejected_by_sensitivity_rules": 0,
                "source_errors": [{"source_id": "offline", "error": "NetworkError"}],
            }) + "\n", encoding="utf-8")
            (research / "register.jsonl").write_text(
                '{"kind":"discovery"}\n{"kind":"proposal"}\n', encoding="utf-8")
            (research / "digests" / "2026-10-27.md").write_text("# Digest\n", encoding="utf-8")
            with patch.object(dashboard.innovation, "STATE", state):
                result = dashboard.dashboard_status()
        self.assertEqual(result["latest_run"]["new"], 2)
        self.assertEqual(result["latest_run"]["source_errors_count"], 1)
        self.assertEqual(result["discovery_count"], 1)
        self.assertEqual(result["proposal_count"], 1)
        self.assertEqual(result["digest"], "# Digest\n")

    def test_manual_start_uses_fixed_command_and_rejects_parallel_process(self):
        class Running:
            def poll(self):
                return None

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(dashboard.innovation, "STATE", Path(directory)), \
             patch.object(dashboard.subprocess, "Popen", return_value=Running()) as spawn, \
             patch.object(dashboard, "_manual_process", None):
            self.assertTrue(dashboard.start_research())
            self.assertFalse(dashboard.start_research())
        args = spawn.call_args.args[0]
        self.assertEqual(args[-3:], ["research", "--per-source", "10"])
        self.assertNotIn("shell", spawn.call_args.kwargs)

    def test_http_requires_auth_and_blocks_cross_origin_trigger(self):
        from http.server import ThreadingHTTPServer
        from threading import Thread

        server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        auth = "Basic " + base64.b64encode(b"aes:" + b"x" * 24).decode("ascii")
        try:
            with patch.object(dashboard, "PASSWORD", "x" * 24):
                with self.assertRaises(HTTPError) as unauth:
                    urlopen(f"http://{host}:{port}/api/status")
                self.assertEqual(unauth.exception.code, 401)
                unauth.exception.close()
                req = Request(f"http://{host}:{port}/api/run", data=b"{}", method="POST",
                              headers={"Authorization": auth, "Origin": "https://attacker.example"})
                with self.assertRaises(HTTPError) as forbidden:
                    urlopen(req)
                self.assertEqual(forbidden.exception.code, 403)
                forbidden.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
