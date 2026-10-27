from pathlib import Path
import json
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr

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
            self.assertIn("AGENTS.md", manifest["blocks"])
            self.assertNotIn("AGENTS.md", manifest["files"])
            self.assertIn(".agent-engineering/core/workflow.md", manifest["files"])
            self.assertIn(".agent-engineering/scripts/innovation.py", manifest["files"])
            self.assertIn(".agent-engineering/scripts/gateway.py", manifest["files"])
            self.assertIn(".agent-engineering/research/sources.json", manifest["files"])
            self.assertIn("Before indexing, summarizing", (project / "AGENTS.md").read_text(encoding="utf-8"))
            child_env = dict(os.environ)
            child_env["AES_STATE_DIR"] = str(project / "aes-state")
            scan = subprocess.run(
                [sys.executable, str(project / ".agent-engineering/scripts/innovation.py"),
                 "scan", str(project / "AGENTS.md"), "--action", "publish"],
                capture_output=True, text=True, check=False, env=child_env,
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertTrue((project / "aes-state/private/audit.jsonl").is_file())
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

    def test_update_preserves_project_content_outside_block(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            agents = project / "AGENTS.md"
            agents.write_text(agents.read_text(encoding="utf-8") + "\nLocal rule.\n", encoding="utf-8")
            self.assertEqual(install.install(project, selected, True), 0)
            self.assertIn("Local rule.", agents.read_text(encoding="utf-8"))

    def test_update_refuses_edits_inside_block(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            agents = project / "AGENTS.md"
            edited = agents.read_text(encoding="utf-8").replace("Shared AI Engineering Guidance", "Edited inside")
            agents.write_text(edited, encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(install.install(project, selected, True), 3)
            self.assertIn("edited inside the AES block", stderr.getvalue())
            self.assertEqual(agents.read_text(encoding="utf-8"), edited)

    def test_install_merges_into_existing_claude_md(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            own = "# My project\n\nAlways run `npm test` before committing.\n"
            (project / "CLAUDE.md").write_bytes(own.replace("\n", "\r\n").encode("utf-8"))
            self.assertEqual(install.install(project, {"claude"}, False), 0)
            raw = (project / "CLAUDE.md").read_bytes().decode("utf-8")
            self.assertNotIn("\n", raw.replace("\r\n", ""))
            text = raw.replace("\r\n", "\n")
            self.assertTrue(text.startswith("<!-- AES:BEGIN"))
            self.assertIn("@AGENTS.md", text)
            self.assertTrue(text.endswith(own))
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertEqual(install.install(project, {"claude"}, True), 0)
            self.assertEqual(text.count("AES:BEGIN"), 1)
            self.assertTrue((project / "CLAUDE.md").read_bytes().decode("utf-8").replace("\r\n", "\n").endswith(own))

    def test_install_keeps_frontmatter_first(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "AGENTS.md").write_text("---\ndescription: project\n---\n# Rules\n", encoding="utf-8")
            self.assertEqual(install.install(project, {"codex"}, False), 0)
            text = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\ndescription: project\n---\n\n<!-- AES:BEGIN"))
            self.assertTrue(text.endswith("# Rules\n"))

    def test_update_replaces_only_the_block(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            agents = project / "AGENTS.md"
            agents.write_text("# Team notes\n\n" + agents.read_text(encoding="utf-8") + "\nLocal rule.\n", encoding="utf-8")
            proposed = install.managed_content(selected)
            proposed["AGENTS.md"] = proposed["AGENTS.md"].replace(b"<!-- AES:END -->", b"New AES guidance.\n<!-- AES:END -->")
            with mock.patch.object(install, "managed_content", return_value=proposed):
                self.assertEqual(install.install(project, selected, True), 0)
            text = agents.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Team notes\n"))
            self.assertIn("New AES guidance.", text)
            self.assertTrue(text.endswith("Local rule.\n"))
            self.assertEqual(install.install(project, selected, True), 0)

    def test_update_migrates_unmodified_whole_file_from_0_1_0(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            agents = project / "AGENTS.md"
            agents.write_text(install.AGENTS, encoding="utf-8")
            manifest_path = project / ".agent-engineering/manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["AGENTS.md"] = install.digest(agents)
            del manifest["blocks"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(install.install(project, selected, True), 0)
            text = agents.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<!-- AES:BEGIN"))
            self.assertNotIn(install.MARKER, text)
            migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("AGENTS.md", migrated["files"])
            self.assertIn("AGENTS.md", migrated["blocks"])

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

    def test_manifest_rejects_invalid_structure_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            manifest = project / ".agent-engineering/manifest.json"
            cases = [
                {"version": "invalid", "files": {"AGENTS.md": "0" * 64}},
                {"version": "0.1.0", "files": {"AGENTS.md": "not-a-hash"}},
                {"version": "0.1.0", "files": {"AGENTS.md": 123}},
                {"version": "0.1.0", "files": {"unknown.txt": "0" * 64}},
                {"version": "0.1.0", "files": {"AGENTS.md": "0" * 64}, "extra": True},
            ]
            for case in cases:
                with self.subTest(case=case):
                    manifest.write_text(json.dumps(case), encoding="utf-8")
                    self.assertEqual(install.install(project, selected, True), 3)

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

    def test_symlinked_managed_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            external = Path(outside) / "agents.md"
            external.write_text("external", encoding="utf-8")
            agents = project / "AGENTS.md"
            agents.unlink()
            try:
                agents.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            self.assertEqual(install.install(project, selected, True), 3)
            self.assertEqual(external.read_text(encoding="utf-8"), "external")

    def test_broken_managed_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            selected = {"codex"}
            self.assertEqual(install.install(project, selected, False), 0)
            workflow = project / ".agent-engineering/core/workflow.md"
            workflow.unlink()
            try:
                workflow.symlink_to(project / "missing-workflow.md")
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            self.assertEqual(install.install(project, selected, True), 3)
            self.assertTrue(workflow.is_symlink())

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
            first_destination = None

            def fail_on_second(source, destination):
                nonlocal calls, first_destination
                calls += 1
                if first_destination is None:
                    first_destination = Path(destination)
                    return original_replace(source, destination)
                if calls == 2 or Path(destination) == first_destination:
                    raise OSError("simulated failure")
                return original_replace(source, destination)

            target = ".agent-engineering/core/workflow.md"
            proposed = install.managed_content(selected)
            proposed[target] += b"\nupdated content\n"
            proposed = {
                target: proposed[target],
                **{relative: data for relative, data in proposed.items() if relative != target},
            }
            stderr = io.StringIO()
            with mock.patch.object(install.os, "replace", side_effect=fail_on_second):
                with mock.patch.object(install, "managed_content", return_value=proposed):
                    with redirect_stderr(stderr):
                        self.assertEqual(install.install(project, selected, True), 3)
            message = stderr.getvalue()
            self.assertIn("rollback was incomplete", message)
            match = re.search(r"backup preserved at (.+?)\. Failed restorations", message)
            self.assertIsNotNone(match)
            backup = Path(match.group(1))
            self.assertTrue(backup.is_dir())
            self.assertTrue(any(path.is_file() for path in backup.rglob("*")))
            after = {
                path: path.read_bytes()
                for path in project.rglob("*")
                if path.is_file() and ".aes-backup-" not in str(path)
            }
            workflow = project / target
            self.assertNotEqual(before[workflow], after[workflow])
            self.assertEqual((backup / target).read_bytes(), before[workflow])


if __name__ == "__main__":
    unittest.main()
