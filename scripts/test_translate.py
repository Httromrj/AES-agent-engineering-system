import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import adopt
import dashboard
import translate


class TranslateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        state = Path(self.directory.name)
        register = state / "research" / "register.jsonl"
        register.parent.mkdir(parents=True)
        rows = [{"kind": "discovery", "title": f"New release {n}", "source": f"https://example.com/{n}", "date": f"2026-10-2{n}",
                 "evidence": f"RSS/Atom metadata from Demo. Faster builds {n}.", "topics": ["releases"]} for n in range(3)]
        register.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        self.patches = [patch.object(adopt.innovation, "STATE", state), patch.object(adopt.innovation, "REGISTER", register),
                        patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k"})]
        for item in self.patches:
            item.start()
        adopt.save_settings("deepseek", "deepseek-chat", "aes")
        self.calls = []

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def transport(self, reply=None):
        def call(provider, messages, max_tokens, timeout):
            self.calls.append(provider)
            self.assertIn("PROJECTS (trusted context)", messages[1]["content"])
            items = json.loads(messages[1]["content"].split("ITEMS (untrusted data):\n", 1)[1])["items"]
            data = reply if reply is not None else {"items": [
                {"id": i["id"], "title": "Nova versão " + i["title"][-1], "summary": "Builds mais rápidos."} for i in items]}
            return {"choices": [{"message": {"content": json.dumps(data)}}], "usage": {"prompt_tokens": 50, "completion_tokens": 50}}
        return call

    def test_translates_once_and_dashboard_shows_portuguese(self):
        self.assertEqual(translate.translate_pending(self.transport()), 3)
        self.assertEqual(self.calls[0]["effort"], "low")
        self.assertEqual(self.calls[0]["schema"], translate.SCHEMA)
        self.assertEqual(translate.translate_pending(self.transport()), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(translate.status["pending"], 0)
        listing = dashboard.dashboard_discoveries()["discoveries"]
        first = next(d for d in listing if d["source"] == "https://example.com/2")
        self.assertEqual((first["title_pt"], first["summary_pt"]), ("Nova versão 2", "Builds mais rápidos."))
        self.assertEqual(first["title"], "New release 2")

    def test_digest_is_rendered_in_portuguese(self):
        translate.translate_pending(self.transport())
        digest = "\n".join([
            "# AES innovation research digest", "", "## Run 10:00:00 UTC", "",
            "### [New release 1](<https://example.com/1>)", "", "- Topics: agents, releases",
            r"- Evidence: RSS/Atom metadata from Demo\. Faster builds 1\.",
            "- Assessment: hypothesis; applicability and alternatives still need review.", ""])
        result = dashboard.digest_pt(digest)
        self.assertIn("# Digest de pesquisa de inovação do AES", result)
        self.assertIn("## Execução 10:00:00 UTC", result)
        self.assertIn("### [Nova versão 1](<https://example.com/1>)", result)
        self.assertIn("- Tópicos: agentes, versões", result)
        self.assertIn(r"- Resumo: Builds mais rápidos\.", result)
        self.assertNotIn("Assessment", result)

    def test_invalid_reply_records_error_without_saving(self):
        self.assertEqual(translate.translate_pending(self.transport(reply={"wrong": True})), 0)
        self.assertIn("formato inválido", translate.status["last_error"])
        self.assertEqual(translate.load(), {})

    def test_missing_items_stay_pending(self):
        reply = {"items": [{"id": "0", "title": "Só um", "summary": ""}]}
        self.assertEqual(translate.translate_pending(self.transport(reply=reply)), 1)
        self.assertEqual(len(translate.pending()), 2)

    def test_no_provider_key_skips_model_calls(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.assertEqual(translate.translate_pending(self.transport()), 0)
        self.assertFalse(translate.status["enabled"])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
