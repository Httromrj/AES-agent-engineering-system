# Continuous Improvement Protocol

Agents may detect improvements at any time, but must not silently rewrite canonical instructions.

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
