---
name: architecture-review
description: Use for cross-module features, data model changes, integrations, architectural decisions, performance concerns, or recurring design problems.
---

# Architecture Review

1. Read the AES engineering charter, workflow, and verification standards.
2. Map affected components, dependencies, data ownership, public contracts, and deployment constraints.
3. Identify invariants, permissions, state transitions, concurrency, idempotency, failure propagation, observability, and recovery requirements where relevant.
4. Compare at least two viable approaches for material decisions; include complexity and migration cost.
5. Prefer the least complex design that meets real requirements. Explicitly reject speculative abstractions.
6. Document significant decisions as an ADR with context, decision, alternatives, and consequences.
7. Define how the design will be verified before implementation is considered complete.
