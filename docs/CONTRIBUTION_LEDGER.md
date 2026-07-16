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
| 2 | TBD | Specification ingestion | `pmpe validate` loads JSON/YAML MVP specs, enforces the schema, normalizes to typed MvpSpec, rejects malformed input with exit 2 | TRD ingestion requirements; PRD spec-input contract | 16 unit tests (schema + normalizer) passed; CLI smoke on golden + malformed fixtures | pending | pending | Structural validation only — semantic requirement validation lands in PR 3 |
