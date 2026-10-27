import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import adopt
import pipeline
import signals
import translate


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        state = Path(self.directory.name)
        self.register = state / "research" / "register.jsonl"
        self.register.parent.mkdir(parents=True)
        rows = [
            {"kind": "discovery", "title": "Popular tool", "source": "https://github.com/acme/tool", "date": "2099-01-01",
             "evidence": "x", "source_authority": "official"},
            {"kind": "discovery", "title": "Funding news", "source": "https://news.example/funding", "date": "2099-01-01", "evidence": "x"},
            {"kind": "discovery", "title": "Quiet tip", "source": "https://blog.example/tip", "date": "2099-01-01", "evidence": "x"},
        ]
        self.register.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        self.patches = [patch.object(adopt.innovation, "STATE", state), patch.object(adopt.innovation, "REGISTER", self.register),
                        patch.dict(os.environ, {"DEEPSEEK_API_KEY": "k", "AES_GITHUB_TOKEN": "t"})]
        for item in self.patches:
            item.start()
        adopt._jobs.clear()
        adopt.save_settings("deepseek", "deepseek-chat", "aes")

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_score_combines_popularity_relevance_and_authority(self):
        quiet = signals.score({}, None, None)
        self.assertEqual((quiet["score"], quiet["relevance_points"]), (0, None))
        hot = signals.score({"hn_points": 900, "hn_comments": 400, "stars": 20000, "stars_delta": 3000}, 9, "official")
        self.assertEqual(hot["popularity"], 50)
        self.assertEqual(hot["score"], 96)
        self.assertLess(signals.score({"stars": 50000}, 1, None)["score"], signals.score({"stars": 500}, 9, None)["score"])

    def test_refresh_records_hn_and_github_signals_and_weekly_growth(self):
        def fake_get(url, headers=None, timeout=20):
            if "hn.algolia" in url:
                return {"hits": [{"url": "https://github.com/acme/tool", "points": 120, "num_comments": 40, "objectID": "77"}]}
            return {"stargazers_count": 1500, "forks_count": 90, "full_name": "acme/tool"}
        with patch.object(signals, "_get_json", side_effect=fake_get):
            self.assertEqual(signals.refresh(), 3)
        sig = signals.latest()["https://github.com/acme/tool"]
        self.assertEqual((sig["hn_points"], sig["stars"], sig["hn_url"]), (120, 1500, "https://news.ycombinator.com/item?id=77"))
        self.assertEqual(signals.latest()["https://news.example/funding"]["hn_points"], 0)
        with signals._path().open("a", encoding="utf-8") as f:
            f.write(json.dumps({"source": "https://github.com/acme/tool", "at": "2999-01-01T00:00:00+00:00", "stars": 1900}) + "\n")
        self.assertEqual(signals.latest()["https://github.com/acme/tool"]["stars_delta"], 400)

    def test_trending_skips_repos_without_forks_or_description(self):
        items = [{"full_name": "a/real", "html_url": "https://github.com/a/real", "description": "Agent skills for design reviews",
                  "stargazers_count": 900, "forks_count": 40, "created_at": "2026-10-20T00:00:00Z", "language": "Python"},
                 {"full_name": "b/bought", "html_url": "https://github.com/b/bought", "description": "Debloat your TV",
                  "stargazers_count": 40000, "forks_count": 2, "created_at": "2026-10-20T00:00:00Z"},
                 {"full_name": "c/empty", "html_url": "https://github.com/c/empty", "description": "",
                  "stargazers_count": 500, "forks_count": 50, "created_at": "2026-10-20T00:00:00Z"}]
        with patch.object(signals, "_github", return_value={"items": items}), patch("builtins.print"):
            self.assertEqual(signals.discover_trending(), 1)
        titles = [json.loads(line)["title"] for line in self.register.read_text(encoding="utf-8").splitlines()]
        self.assertIn("a/real: Agent skills for design reviews", titles)
        self.assertFalse(any(t.startswith("b/bought") for t in titles))

    def test_autopilot_respects_thresholds_limits_and_history(self):
        ranked = [{"source": "https://github.com/acme/tool", "score": 80, "relevance": 8, "actionable": True, "triage": "new"},
                  {"source": "https://news.example/funding", "score": 90, "relevance": 9, "actionable": False, "triage": "new"},
                  {"source": "https://blog.example/tip", "score": 70, "relevance": 7, "actionable": True, "triage": "dismissed"},
                  {"source": "https://blog.example/low", "score": 30, "relevance": 9, "actionable": True, "triage": "new"}]
        self.assertEqual(adopt.autopilot_run(ranked)["state"], "off")
        adopt.save_autopilot(True, 60, 6, 1, "aes")
        self.assertEqual(adopt.autopilot_run(ranked)["state"], "waiting")
        with open(adopt._dir() / "projects.json", "w", encoding="utf-8") as f:
            json.dump({"projects": [{"repo": "romulo/app", "branch": "main", "agents": ["claude"]}]}, f)
        generated = []

        def fake_generate(source, note, repos, transport=None):
            generated.append(source)
            return {"name": "aes-tool", "description": "d", "body": "b", "summary_pt": "s", "source": source, "title": "t",
                    "model": "m", "provider": "deepseek", "cost_usd": 0}

        def fake_deploy(job_id, actor, run_async=True):
            record = adopt._jobs.pop(job_id)
            record.update(status="deployed", results={"romulo/app": {"status": "deployed", "at": adopt._now()}})
            adopt._save(record)

        with patch.object(adopt, "generate", side_effect=fake_generate), patch.object(adopt, "deploy", side_effect=fake_deploy):
            result = adopt.autopilot_run(ranked)
            self.assertEqual((result["adopted"], generated), (1, ["https://github.com/acme/tool"]))
            self.assertEqual(adopt.autopilot_run(ranked)["adopted"], 0)  # daily limit reached
            adopt.save_autopilot(True, 60, 6, 5, "aes")
            self.assertEqual(adopt.autopilot_run(ranked)["adopted"], 0)  # already adopted; others filtered out
        self.assertEqual(generated, ["https://github.com/acme/tool"])
        with self.assertRaises(adopt.AdoptionError):
            adopt.save_autopilot(True, 150, 6, 1, "aes")

    def test_ranked_uses_translation_ratings(self):
        with open(translate._path(), "w", encoding="utf-8") as f:
            f.write(json.dumps({"source": "https://blog.example/tip", "title": "Dica", "summary": "", "relevance": 9,
                                "actionable": True, "why": "Útil"}) + "\n")
        top = pipeline.ranked()[0]
        self.assertEqual((top["source"], top["score"], top["why"]), ("https://blog.example/tip", 36, "Útil"))


if __name__ == "__main__":
    unittest.main()
