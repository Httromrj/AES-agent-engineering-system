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

    def test_discoveries_triage_and_source_health(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            research = state / "research"
            research.mkdir(parents=True)
            sources = state / "sources.json"
            sources.write_text(json.dumps({"sources": [
                {"id": "demo", "name": "Demo", "url": "https://demo.example/feed"},
                {"id": "offline", "name": "Offline", "url": "https://offline.example/feed"}]}), encoding="utf-8")
            (research / "runs.jsonl").write_text(json.dumps({
                "finished_at": "2026-10-27T10:00:02+00:00", "fetched": 2, "new": 2,
                "source_counts": [{"source_id": "demo", "items": 2}],
                "source_errors": [{"source_id": "offline", "error": "Timeout"}]}) + "\n", encoding="utf-8")
            rows = [{"kind": "discovery", "title": f"Item {n}", "source": f"https://demo.example/{n}",
                     "date": f"2026-10-2{n}", "evidence": f"RSS/Atom metadata from Demo. Summary {n}",
                     "source_feed": "https://demo.example/feed", "topics": ["tools"]} for n in (1, 2)]
            rows.append({"kind": "discovery", "title": "Unsafe", "source": "javascript:alert(1)", "date": "2026-10-20"})
            (research / "register.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            with patch.object(dashboard.innovation, "STATE", state), patch.object(dashboard.innovation, "SOURCES", sources):
                self.assertTrue(dashboard.set_triage("https://demo.example/1", "interesting"))
                self.assertFalse(dashboard.set_triage("https://unknown.example/", "dismissed"))
                with self.assertRaises(ValueError):
                    dashboard.set_triage("https://demo.example/1", "approved")
                listing = dashboard.dashboard_discoveries()
                status = dashboard.dashboard_status()
        by_title = {item["title"]: item for item in listing["discoveries"]}
        self.assertEqual([item["title"] for item in listing["discoveries"]], ["Item 2", "Item 1", "Unsafe"])
        self.assertEqual(by_title["Item 1"]["triage"], "interesting")
        self.assertEqual(by_title["Item 1"]["summary"], "Summary 1")
        self.assertEqual(by_title["Item 1"]["feed_name"], "Demo")
        self.assertIsNone(by_title["Unsafe"]["url"])
        self.assertEqual(status["triage_counts"], {"new": 2, "interesting": 1, "dismissed": 0})
        health = {s["id"]: s for s in status["sources"]}
        self.assertEqual(health["demo"]["items"], 2)
        self.assertEqual(health["offline"]["error"], "Timeout")

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
        try:
            with patch.object(dashboard, "PASSWORD", "x" * 24):
                with self.assertRaises(HTTPError) as unauth:
                    urlopen(f"http://{host}:{port}/api/status")
                self.assertEqual(unauth.exception.code, 401)
                unauth.exception.close()
                req = Request(f"http://{host}:{port}/api/run", data=b"{}", method="POST",
                              headers={"Origin": "https://attacker.example"})
                with self.assertRaises(HTTPError) as forbidden:
                    urlopen(req)
                self.assertEqual(forbidden.exception.code, 403)
                forbidden.exception.close()
                triage = Request(f"http://{host}:{port}/api/triage", method="POST",
                                 data=json.dumps({"source": "https://x.example", "state": "dismissed"}).encode(),
                                 headers={"Origin": "https://attacker.example",
                                          "Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as forbidden_triage:
                    urlopen(triage)
                self.assertEqual(forbidden_triage.exception.code, 403)
                forbidden_triage.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
