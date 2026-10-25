# Standard Engineering Workflow

Adapt depth to risk and scope. Do not perform every step mechanically for trivial changes.

## 1. Triage
Clarify outcome, acceptance conditions, constraints, and risk. Classify as low-risk, normal, high-risk, or production-sensitive. Ask only blocking questions; otherwise state assumptions.

## 2. Investigate
Read relevant instructions and nearby implementation. Trace the end-to-end workflow and dependencies. Inspect tests, schemas, API contracts, permissions, feature flags, and UI patterns. Prefer official documentation and maintained references. Do not infer unseen files, runtime behavior, or environment state.

## 3. Design
For non-trivial work, state approach, material alternatives, affected areas, and failure modes. Define invariants, states, data ownership, authorization, idempotency, concurrency, observability, and rollback/migration needs where relevant. Identify UX states, accessibility, and responsive behavior for user-facing changes. Avoid broad unrelated refactors.

## 4. Implement
Make the smallest coherent change that delivers complete behavior. Follow existing conventions unless demonstrably deficient. Keep responsibilities clear and avoid duplicated business rules. Add/update tests. Do not swallow errors or introduce insecure defaults to make a happy path pass.

## 5. Verify
Run the narrowest relevant tests first, then broader checks as warranted. Inspect outputs; distinguish test failures from environment failures. Review the diff for accidental changes, secrets, debug code, unsafe migrations, and incomplete flows. For UI work, verify key states and responsiveness with available browser tooling when practical. Report exactly what was and was not verified.

## 6. Review
Ask: What could break? What is missing? What happens with invalid, duplicated, stale, unauthorized, concurrent, or unavailable inputs? Is this overbuilt or underbuilt? Does it match the actual user workflow?

## 7. Improve
Record recurring defects or process gaps with evidence, impact, and a proposed correction. Prefer adding a test or deterministic check over adding a vague instruction. Do not change canonical standards during ordinary feature work without explicit review.
