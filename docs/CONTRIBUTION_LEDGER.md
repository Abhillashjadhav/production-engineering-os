# Contribution ledger — atomic PR series

The monolithic V1/V2 deliveries (closed PRs #1 and #2, preserved immutably as
`backup/v1-monolith` and `backup/v2-monolith`) are re-delivered as a sequence of
atomic, independently reviewed PRs. Each row is completed (merge commit filled in)
by the next PR in the series; the final report closes the last row.

Legend — outcome: what the PR makes usable on `main`. reviewer verdict: from the
independent read-only review recorded on the PR before merge.

| # | PR | Title | Outcome | Requirements | Tests (result) | Reviewer verdict | Merge commit | Limitations / deferred |
|---|----|-------|---------|--------------|----------------|------------------|--------------|------------------------|
| 1 | #3 | Repository foundation | Installable `pmpe` package skeleton, CI (format/lint, strict types, security scan, build+import smoke), PR template, contribution rules, architecture boundary and design docs | PRD §repo foundation; docs/technical-requirements.md SYS-setup | no product tests yet (foundation); CI jobs green | APPROVE (2 rounds, 6 scope-purity findings fixed) | 89599f9 | No functional pipeline yet — ingestion arrives in PR 2 |
| 2 | #4 | Specification ingestion | `pmpe validate` loads JSON/YAML MVP specs, enforces the schema, normalizes to typed MvpSpec, rejects malformed input with exit 2 | TRD ingestion requirements; PRD spec-input contract | 18 unit tests (schema + normalizer + packaged-schema sync guard) passed; CLI smoke on golden + malformed fixtures | APPROVE (2 rounds, 3 findings fixed) | 2a41462 | Structural validation only — semantic requirement validation lands in PR 3 |
| 3 | TBD | Requirement validation | `pmpe validate` now runs semantic checks: missing fields/decisions, contradictions, untestable acceptance criteria, activity-only NSM, undeclared dependencies; errors/questions exit 3 | TRD validation requirements; PRD verification-first principle | planted-failure unit tests (validator) passed | pending | pending | Heuristic pattern-based checks — catch common failure shapes, not all (documented) |
