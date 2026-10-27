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

## Continuous improvement and sensitive files
AES includes a local, stdlib-only sensitivity scan, configurable RSS/Atom research cycle, and append-only discovery/proposal register. Before indexing, summarizing, using an external model, publishing, or sharing project files, scan all in-scope paths:

```bash
python scripts/innovation.py scan path/to/project --action external_model
# In an installed consumer, use .agent-engineering/scripts/innovation.py
```

Any finding, missing path, or scan/audit error blocks the action pending review. A clear result means only that configured detectors found no match; it does not prove a file is safe. The scanner reports paths and detector IDs without matched values. Its audit and research state are stored in the per-user AES state directory by default; set `AES_STATE_DIR` for a protected service-owned directory. Do not send sensitive files to external models without explicit authorization and suitable controls; sensitivity checks precede provider fallback.

Collect configured feeds with `python scripts/innovation.py research`; source definitions are in `research/sources.json`. It stores leads as hypotheses and produces a dated digest in the AES state directory. The separate `scripts/gateway.py` module provides a bounded OpenAI-compatible call interface, but no model providers are configured by default. Record verified discoveries and proposals with `python scripts/innovation.py record discovery record.json` or `... record proposal record.json`. See `research/README.md` for fields. The cycle does not independently verify claims, run experiments, schedule itself, call model providers, or deploy to a VPS.

## Limitations
The research command runs one bounded cycle and can be scheduled externally; no timer is enabled by this repository. It does not summarize articles with a model, validate product claims, run experiments, update dependencies, edit consumer projects, or open pull requests automatically. See `deployment/README.md` for a read-only VPS preflight and an uninstalled systemd template. AES does not guarantee that an agent follows instructions or approve changes to its own standards; project tests and human review remain necessary.
