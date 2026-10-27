# ADR-0001: Single Canonical Source with Generated Adapters

- Status: Accepted for prototype
- Date: 2026-10-25

## Context
Coding-agent tools use overlapping but non-identical instruction and skill discovery mechanisms. Manually maintaining full copies creates drift.

## Decision
Author common standards and skill procedures once in this repository. Install canonical material under `.agent-engineering/` in each consumer project. Generate native entry-point files and skill wrappers that point to canonical material. Shared entry points (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`) receive a delimited AES block merged into any existing file, so project-specific instructions are preserved; AES-named files and skills are never overwritten.

## Consequences
- One authored source reduces drift.
- Consumer projects contain a versioned snapshot; updating requires rerunning an installer and reviewing changes.
- Some generated adapter text is duplicated by design.
- Tool behavior and discovery must be tested per harness/version.
- Future versions may add upgrade/diff support after safe installation is validated.
