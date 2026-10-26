from pathlib import Path
import json
import hashlib
import tempfile
import unittest
from unittest import mock

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
            for relative, expected in manifest["files"].items():
                self.assertEqual(
                    expected,
                    hashlib.sha256((project / relative).read_bytes()).hexdigest(),
                )
            self.assertIn(
                ".agent-engineering/skills/product-engineering/SKILL.md",
                (project / ".agents/skills/product-engineering/SKILL.md").read_text(
                    encoding="utf-8"
                ),
            )

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
            before = {
                path: path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(install.install(project, selected, True), 0)
            after = {
                path: path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_missing_managed_file_is_reported_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            workflow = project / ".agent-engineering/core/workflow.md"
            workflow.unlink()
            self.assertEqual(install.install(project, selected, True), 3)
            self.assertFalse(workflow.exists())

    def test_extra_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            extra = project / "project-data.txt"
            extra.write_text("keep me", encoding="utf-8")
            self.assertEqual(install.install(project, selected, True), 0)
            self.assertEqual(extra.read_text(encoding="utf-8"), "keep me")

    def test_invalid_manifest_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            manifest = project / ".agent-engineering/manifest.json"
            manifest.write_text('{"files":{"..\\\\outside.txt":"bad"}}', encoding="utf-8")
            original = (project / "AGENTS.md").read_bytes()
            self.assertEqual(install.install(project, selected, True), 3)
            self.assertEqual((project / "AGENTS.md").read_bytes(), original)

    def test_symlinked_managed_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            project = Path(directory)
            selected = {"codex"}
            try:
                (project / ".agents").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            self.assertEqual(install.install(project, selected, False), 3)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_failed_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            before = {
                path: path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            original_replace = install.os.replace
            calls = 0

            def fail_on_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated failure")
                return original_replace(source, destination)

            with mock.patch.object(install.os, "replace", side_effect=fail_on_second):
                self.assertEqual(install.install(project, selected, True), 3)
            after = {
                path: path.read_bytes()
                for path in project.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
