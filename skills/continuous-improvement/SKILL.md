---
name: continuous-improvement
description: Use after substantial tasks, repeated defects, or a planned engineering audit to identify evidence-based improvements to the project or agent standards.
---

# Continuous Improvement

1. Read `.agent-engineering/core/continuous-improvement.md` and the project's improvement backlog.
2. At the project's agreed cadence, run the configured AES research cycle and inspect its local digest. Look for relevant improvements across product capabilities, dependencies, frameworks, APIs, AI techniques, architecture, design, UX, accessibility, security, and delivery practices. Compare promising findings with the project's current state and alternatives; sort by expected impact, confidence, effort, and risk.
3. Before any indexing, summarizing, external model request, publication, or sharing, run the AES sensitivity scan on all in-scope files. Treat findings and scan failures as a hard stop pending review. Do not echo matched content. The scan is best-effort and does not establish that a file is safe.
4. Support every finding with reproducible evidence, not a general preference. Compare relevant current alternatives using primary sources where possible; record date, limitations, applicability, and evidence type.
5. Rank by impact, likelihood, cost, and confidence.
6. Prefer deterministic tests, linters, scripts, or clearer local documentation over vague global instructions.
7. Distinguish project-specific improvements from changes to the reusable engineering system.
8. Propose changes; do not silently modify canonical standards or weaken safety controls.
9. Record discoveries and proposals with success criteria; retain unproven opportunities as hypotheses, and record accepted, rejected, and deferred decisions with rationale.
10. When a capability is accepted for a consumer project, teach its agent how to use it: explain the user benefit, local conventions, safe integration points, setup, verification, accessible UX, failure handling, and rollback. Implement consumer changes only within the task authorization. Report what was investigated, applied, measured, and left undecided.
