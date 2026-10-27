import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import innovation


class InnovationTests(unittest.TestCase):
    def test_scan_detects_secret_without_echoing_value(self):
        secret = "ghp_" + "A" * 36
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.md"
            path.write_text(f"token: {secret}", encoding="utf-8")
            findings = innovation.scan([Path(directory)])
        self.assertEqual(findings[0]["rules"], ["provider_token"])
        self.assertNotIn(secret, json.dumps(findings))

    def test_scan_flags_sensitive_document_locations_and_opaque_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = root / "customer-data" / "report.txt"
            doc.parent.mkdir()
            doc.write_text("Quarterly metrics", encoding="utf-8")
            pdf = root / "public.pdf"
            pdf.write_bytes(b"not a real PDF")
            findings = innovation.scan([root])
        rules = {Path(item["path"]).name: item["rules"] for item in findings}
        self.assertIn("sensitive_location", rules["report.txt"])
        self.assertIn("unscanned_binary", rules["public.pdf"])

    def test_scan_flags_missing_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            self.assertEqual(innovation.scan([missing])[0]["rules"], ["missing_path"])

    def test_feed_urls_reject_local_and_non_https_endpoints(self):
        self.assertFalse(innovation.safe_feed_url("http://example.com/feed"))
        self.assertFalse(innovation.safe_feed_url("https://127.0.0.1/feed"))
        self.assertFalse(innovation.safe_feed_url("https://metadata.google.internal/computeMetadata/v1"))
        self.assertTrue(innovation.safe_feed_url("https://example.com/feed"))

    def test_feed_parser_rejects_entity_declarations(self):
        with self.assertRaisesRegex(ValueError, "DTD/entity"):
            innovation.parse_feed(b"<!DOCTYPE rss [<!ENTITY x 'x'>]><rss/>", {"name": "test"}, 1)

    def test_feed_content_may_mention_html_doctype(self):
        xml = b'''<rss><channel><item><title>Example</title><link>https://example.invalid/1</link>
        <description><![CDATA[Example markup: <!DOCTYPE html>]]></description></item></channel></rss>'''
        self.assertEqual(len(innovation.parse_feed(xml, {"name": "source", "url": "https://example.invalid/feed"}, 1)), 1)

    def test_add_record_rejects_sensitive_metadata(self):
        payload = {"title": "Research", "source": "docs", "date": "2026-10-27",
                   "evidence": "contact person" + "@example.com", "limitations": "none",
                   "applicability": "unknown", "status": "hypothesis"}
        with tempfile.TemporaryDirectory() as directory, patch.object(innovation, "REGISTER", Path(directory) / "register.jsonl"):
            with self.assertRaisesRegex(ValueError, "email_address"):
                innovation.add_record("discovery", payload)
            self.assertFalse((Path(directory) / "register.jsonl").exists())

    def test_add_record_persists_and_deduplicates(self):
        payload = {"title": "Capability", "source": "https://example.invalid", "date": "2026-10-27",
                   "evidence": "Unverified", "limitations": "None tested", "applicability": "Hypothesis",
                   "status": "hypothesis"}
        with tempfile.TemporaryDirectory() as directory, patch.object(innovation, "REGISTER", Path(directory) / "register.jsonl"):
            innovation.add_record("discovery", payload)
            innovation.add_record("discovery", payload)
            lines = (Path(directory) / "register.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)

    def test_proposal_decisions_are_appended_as_revisions(self):
        payload = {"title": "Capability", "source": "https://example.invalid", "date": "2026-10-27",
                   "evidence": "Verified in docs", "limitations": "No benchmark", "applicability": "Potential fit",
                   "status": "verified", "success_criteria": "Reduce task time by 10%",
                   "priority": "medium", "expected_impact": "10% faster", "confidence": "medium",
                   "effort": "two days", "decision": "proposed", "decision_rationale": "Needs review"}
        with tempfile.TemporaryDirectory() as directory, patch.object(innovation, "REGISTER", Path(directory) / "register.jsonl"):
            innovation.add_record("proposal", payload)
            payload["decision"] = "deferred"
            payload["decision_rationale"] = "Revisit after baseline measurement"
            innovation.add_record("proposal", payload)
            rows = [json.loads(row) for row in (Path(directory) / "register.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["revision"] for row in rows], [1, 2])

    def test_parse_rss_keeps_https_candidates_as_hypotheses(self):
        xml = b'''<rss version="2.0"><channel><item><title>New capability</title>
        <link>https://official.example/release/1#top</link><pubDate>Tue, 27 Oct 2026 10:00:00 GMT</pubDate>
        <description><![CDATA[<p>See the feature.</p>]]></description></item><item><title>Unsafe link</title>
        <link>http://example.invalid/</link></item></channel></rss>'''
        records = innovation.parse_feed(xml, {"name": "Official", "url": "https://official.example/feed",
                                              "authority": "official", "topics": ["tools"], "priority": 1}, 10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "hypothesis")
        self.assertEqual(records[0]["source"], "https://official.example/release/1")
        self.assertIn("See the feature.", records[0]["evidence"])

    def test_parse_atom_prefers_alternate_link_over_earlier_tag_id(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>tag:github.com,2008:Repository/1/v1.0</id>
        <updated>2026-10-27T10:00:00Z</updated><link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v1.0"/>
        <title>v1.0</title><content type="html">Release notes</content></entry></feed>'''
        records = innovation.parse_feed(xml, {"name": "Releases", "url": "https://github.com/o/r/releases.atom"}, 10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "https://github.com/o/r/releases/tag/v1.0")
        self.assertEqual(records[0]["date"], "2026-10-27")

    def test_research_cycle_deduplicates_and_writes_digest(self):
        payload = {"title": "Capability", "source": "https://example.invalid/item", "date": "2026-10-27",
                   "evidence": "Unverified", "limitations": "Feed metadata only", "applicability": "Hypothesis",
                   "status": "hypothesis", "topics": ["tools"], "source_feed": "https://example.invalid/feed",
                   "source_authority": "official", "source_priority": 1}
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            config = Path(directory) / "sources.json"
            config.write_text('{"sources":[{"id":"demo","name":"Demo","url":"https://example.invalid/feed"}]}', encoding="utf-8")
            with patch.object(innovation, "STATE", state), patch.object(innovation, "REGISTER", state / "research/register.jsonl"), \
                 patch.object(innovation, "fetch_source", return_value=[payload]):
                innovation.research_cycle(config, 5)
                innovation.research_cycle(config, 5)
            self.assertEqual(len((state / "research/register.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            digest = next((state / "research/digests").glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("unverified hypothesis", digest)
            # The second, empty run must not erase the first run's candidate.
            self.assertIn("[Capability]", digest)
            self.assertIn("No new candidates", digest)
            self.assertEqual(digest.count("# AES innovation research digest"), 1)


if __name__ == "__main__":
    unittest.main()
