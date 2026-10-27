# Continuous Improvement Protocol

Agents may detect improvements at any time, but must not silently rewrite canonical instructions.

## Research and project freshness
At the project's agreed cadence and after significant product or platform changes, review current technology, dependencies, APIs, AI capabilities, architecture, design, UX, accessibility, and relevant techniques. Run `python .agent-engineering/scripts/innovation.py research` in an installed consumer or `python scripts/innovation.py research` in the AES source repository to collect configured RSS/Atom leads. Configure trusted sources in `.agent-engineering/research/sources.json`; prefer official docs, maintained releases, changelogs, standards, and primary research. The feed digest is a lead list, never an endorsement.

For each promising lead, inspect primary evidence and compare it with the project's current implementation and relevant alternatives. Consolidate what the tool promises, what documentation establishes, what experiments demonstrate, and what remains unknown. Record source and review date, evidence, alternatives, limitations, applicability, and whether each claim is verified, a hypothesis, commercial, or experimental. Assess product benefit, compatibility, security, privacy, cost, effort, design quality, accessibility, and regression risk. Define measurable success and failure criteria before experiments. Keep unproven ideas as hypotheses; do not perform indiscriminate upgrades.

## Sensitive information gate
Before indexing, summarizing, sending to an external model, publishing, or sharing files, run `python .agent-engineering/scripts/innovation.py scan <paths> --action <index|summarize|external_model|publish|share>` in an installed consumer, or `python scripts/innovation.py ...` in this AES source repository. Any finding or scan failure blocks external use pending human review. Inspect instructions, skills, ADRs, docs, configs, scripts, logs, and generated artifacts; location or extension does not imply safety. The built-in rules are a best-effort pattern screen, not proof of absence: review detector gaps and false positives, use existing secret scanners where available, and never include matched values in reports. Do not automatically modify or delete source files. Secret clearing requires an explicit, recorded authorization and a policy-compatible destination. Never send sensitive content to a model without explicit authorization and appropriate controls; this restriction applies before provider fallback too.

The scanner stores audit data outside the repository in the per-user AES state directory; set `AES_STATE_DIR` to select another protected location. It records paths, detector IDs, action, and decision only. Review local access controls before operational use. Scan results are not a publication guarantee and do not replace review.

Research discoveries and proposals may be recorded with `python scripts/innovation.py record discovery <json-file>` or `... record proposal <json-file>`. Use the schema described in `research/README.md`. The register and generated digests live in the per-user AES state directory, outside the repository by default, to avoid accidental publication of unreviewed research.

Periodic research is a one-shot command that can be scheduled by an operator; it does not install its own scheduler. Research ingestion uses only configured feeds and does not upload project content or call a model. Experiments, edits to consumer projects, core changes, publishing, and deployment still require approved scope and permissions. AES does not self-approve recommendations. The dashboard's adoption flow may commit generated skills to a registered repository's default branch, but only after an admin reviews the preview, only as `SKILL.md` files plus an index, and with a one-click revert; it never writes application code.

## When to raise a proposal
- A defect or omission recurs.
- An instruction is ambiguous or conflicts with observed tool behavior.
- A deterministic check could prevent a repeated failure.
- A new tool or standard demonstrably improves quality or reduces risk.
- A workflow has become unnecessarily costly or slow.

## Proposal format
- Observation and evidence (file, test, incident, or reproducible example).
- User/business impact and likelihood.
- Proposed change and alternatives considered.
- Risks, compatibility implications, and maintenance cost.
- Validation method and measurable success criterion.
- Whether the change belongs in code, tests, documentation, a skill, an adapter, or the core standard.

## Governance
Prefer a focused pull request or explicit user approval. Validate generated adapters after changing canonical sources. Do not weaken security or verification rules to make a test pass. Do not add dependencies or external skills solely because they are popular. Keep a dated backlog of accepted, rejected, and deferred proposals. Remove obsolete rules when evidence shows they are no longer useful.
