---
name: implementation-quality
description: Use while implementing a feature or bug fix and before handing off a code change for review.
---

# Implementation Quality

1. Confirm acceptance criteria and relevant existing conventions.
2. Make a cohesive, bounded change; avoid unrelated refactors.
3. Cover validation, errors, permissions, retries, empty states, and edge cases appropriate to the task.
4. Add or update automated tests at the correct layer.
5. Run actual project checks; inspect results rather than assuming success.
6. Review the diff for accidental scope, duplicated rules, security issues, secrets, debug code, and missing documentation.
7. Report behavior changed, checks run, results, and residual risks.
