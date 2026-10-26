# Agent Engineering System (AES)

A vendor-neutral engineering system for coding agents. AES keeps authored standards in one canonical location and generates thin adapters for Codex, Claude Code, Google Antigravity, and GitHub Copilot.

## Design principles
- One canonical source for engineering standards.
- Generated adapters, not hand-maintained copies.
- Progressive disclosure: short always-on rules, detailed skills loaded when relevant.
- Evidence over claims: verification results must be reported honestly.
- Safe installation: never silently overwrite existing user instructions.
- Continuous improvement through reviewed proposals, not self-modifying rules.

## Quick start
Requirements: Python 3.10+; no third-party dependencies.

```bash
python scripts/validate.py
python -m unittest discover -s scripts -p "test_*.py"
python scripts/install.py /path/to/your/project --agents codex,claude,antigravity,copilot
```

The installer creates `.agent-engineering/` with canonical standards and skill sources, then creates native adapters only if those files do not already exist. If an adapter exists, installation stops rather than overwriting it.

An installed project contains `.agent-engineering/manifest.json`, which records
the hashes of files managed by AES. To update an existing installation, run:

```bash
python scripts/install.py /path/to/your/project --update
```

The updater refuses to overwrite a managed file that was changed locally.
Review or remove that change before retrying. It never deletes extra files or
silently merges arbitrary project instructions.

Managed files that are missing locally are treated as local removals and block
the update. Files removed from a newer AES source are retained as legacy
managed files rather than deleted automatically. This makes intervention
explicit and avoids data loss.

Updates are prepared in a temporary staging area, validated against the target
directory, and applied with backups. If a write fails, the installer restores
the files changed during that attempt and leaves the previous manifest in
place. Symbolic links, escaping manifest paths, malformed manifests, and
other unsafe destinations are rejected before writes begin.

Manifest hashes provide integrity checks for files relative to the recorded
manifest. The manifest is not digitally signed, so an attacker who can modify
both the manifest and its files cannot be detected by these hashes alone.

## Supported adapter targets
| Agent | Project instruction entry point | Skills |
|---|---|---|
| Codex | `AGENTS.md` | `.agents/skills/` |
| Claude Code | `CLAUDE.md` importing `AGENTS.md` | `.claude/skills/` wrappers |
| Google Antigravity | `AGENTS.md` plus `.agents/rules/` | `.agents/skills/` |
| GitHub Copilot | `.github/copilot-instructions.md` | `.github/skills/` wrappers |

Discovery varies by product version, IDE, and harness. Confirm the active harness and verify effective instruction discovery after installation.

## Updating
Edit `core/` and `skills/` in this repository. Do not hand-edit generated adapter
files in consumer projects as the long-term source of truth. Re-run the installer
with `--update` after reviewing changes. The updater intentionally refuses to
merge arbitrary local edits.

## Limitations
AES does not guarantee that a model follows instructions, does not run agents continuously in the background, and does not automatically approve changes to its own standards. Enforcement requires project-specific tests, linters, CI, hooks, and review.
