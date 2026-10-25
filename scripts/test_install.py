from pathlib import Path
import json
import tempfile
import unittest

import install


class InstallerTests(unittest.TestCase):
    def test_install_creates_adapters_skills_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(
                install.install(project, {"codex", "claude", "antigravity", "copilot"}, False),
                0,
            )
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertTrue((project / "CLAUDE.md").is_file())
            self.assertTrue((project / ".agents/rules/aes.md").is_file())
            self.assertTrue((project / ".github/copilot-instructions.md").is_file())
            manifest = json.loads(
                (project / ".agent-engineering/manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn("AGENTS.md", manifest["files"])
            self.assertIn(".agent-engineering/core/workflow.md", manifest["files"])

    def test_update_preserves_local_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            agents = project / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8") + "\nLocal rule.\n", encoding="utf-8")
            self.assertEqual(install.install(project, selected, True), 3)
            self.assertIn("Local rule.", agents.read_text(encoding="utf-8"))

    def test_update_accepts_unmodified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            self.assertEqual(install.install(project, selected, True), 0)
            self.assertTrue((project / ".agent-engineering/manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
