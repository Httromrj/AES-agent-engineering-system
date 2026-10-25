# Benchmark Tasks

Use the same representative tasks before and after changing AES. Choose tasks from a real project and keep a baseline.

Score 0–2 for each dimension:
- Context investigation: 0 absent, 1 partial, 2 grounded in relevant code and constraints.
- Requirement depth: 0 happy path only, 1 some edge cases, 2 key states and failure paths considered.
- Architecture: 0 unjustified or fragile, 1 reasonable with gaps, 2 proportional with material trade-offs explained.
- Verification: 0 unverified/unsupported claims, 1 partial checks, 2 relevant checks executed and reported honestly.
- Product quality: 0 incomplete workflow, 1 main path works with gaps, 2 appropriate states, accessibility and UX considered.
- Scope discipline: 0 unrelated/broad changes, 1 minor drift, 2 focused and compatible.
- Learning: 0 no useful findings, 1 findings without evidence/owner, 2 actionable evidence-based follow-up.

Maximum: 14 points. The score does not replace review of actual code or outcomes.

## Scenarios
1. Add a form with validation and role-based access to an existing application.
2. Fix a cross-system integration bug where events may be retried or duplicated.
3. Change a database model with existing production data and backward-compatibility concerns.
4. Improve a dashboard without breaking established design patterns.
5. Audit a recurring defect and propose a deterministic guardrail.

Record baseline, agent/version, harness, task prompt, score, defects found after review, and test results. Compare equivalent tasks; avoid optimizing only for the rubric.
