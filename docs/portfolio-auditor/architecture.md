# GitHub Portfolio Auditor V1 — architecture

Status: ACTIVE (M1). Contract: `products/portfolio-auditor/contract.json`
(`PDC-PORTFOLIO-AUDITOR-V1`, APPROVED, digest-locked). Policy:
`products/portfolio-auditor/policy.json` (digest-bound, schema-validated).

Provenance: reimplements the product decisions of the archived
loop-engineering prototype (`Abhillashjadhav/loop-engineering`, branch
`archive/portfolio-auditor-loop-prototype`, commit `5d09b27`) against
Production Engineering OS mechanisms. The prototype is reference-only;
`src/pmpe/portfolio/` never imports from it (test-enforced) and the
contract's `source_digest` pins the archived contract we reimplemented.

## What it is

A deterministic, fixture-first auditor that turns a repository portfolio
into evidence-backed scorecards, an explicit AI-slop verdict per deeply
inspected repository, a recommendation (FIX / SHOWCASE / CONSOLIDATE /
REBUILD / KEEP_AS_IS), and a prioritized remediation backlog — then
verifies remediation by re-audit. V1 builds and verifies entirely on
planted fixtures, mocked GitHub data, and sandbox PRs (PD-PA-04); no real
repository is read or modified.

## Mechanism reuse (PD-PA-08 — no new infrastructure)

| Concern | OS mechanism |
|---|---|
| Product contract | `pmpe.contracts` — `load_contract`, `ContractStore.lock_for_run` / `verify_unchanged` (PD-03 immutability), `canonical_digest` |
| Auditor vocabulary | policy config validated by `pmpe.ingestion.schema.SchemaValidator` against `schemas/portfolio_policy.schema.json`; range rules in the typed loader |
| Evidence of record | `pmpe.engineering.ledger.EvidenceLedger` (append-only sorted-key JSONL, digests per event) |
| Subject binding | `pmpe.engineering.candidate` tree digests — findings bind to the inspected commit/content digest |
| Read-only inspection proof | `pmpe.assurance.readonly_guard.readonly_snapshot` / `verify_unmodified` around every inspection pass |
| Merge decisions | `pmpe.review.merge_gate` pattern: gates ∧ zero blocking findings ∧ traceability ∧ approvals; an approval never overrides a failing gate |
| Security scanning | `pmpe.quality.security_scan.scan_tree` (redacting, rule-based) |
| Stability / regression | `pmpe.evals.drift.compare` (OK / WATCH / HOLD; a new hard-gate failure is HOLD) |
| Risky-action policy | `pmpe.policies.engine.PolicyEngine` (HIGH-risk decisions block on a named human approval) |

## Module map (target layout across M1–M9)

```
src/pmpe/portfolio/
  __init__.py       M1  public surface
  models.py         M1  vocabulary enums, EvidenceRef (origin = independence
                        key), Finding (7 contract-required fields), scoring
                        guards, slop gate
  policy.py         M1  typed, fail-closed policy loader + finding validation
  contract.py       M1  AuditorBundle: (contract digest, policy digest)
  datasource.py     M2  RepositorySource protocol; fixture source; fail-loud
                        live stub (no network until operator allowlist)
  scanner.py        M2  broad mechanical signal extraction (deterministic)
  selection.py      M3  strategic config, risk ranking, deep-scan selection
  inspection.py     M4  deep technical/architecture/security/business passes
  slop.py           M5  classifier + counter-evidence review + stability evals
  reporting.py      M6  dashboard, scorecards, remediation backlog (pure fns)
  remediation.py    M7  sandbox PR generation + gated merge decision
  reaudit.py        M8  baseline comparison, regression detection (HOLD)
src/pmpe/cli/portfolio_cmd.py   M2+  `pmpe portfolio ...` (additive register)
src/pmpe/schemas/portfolio_policy.schema.json    M1
src/pmpe/schemas/portfolio_finding.schema.json   M1
products/portfolio-auditor/{contract,policy}.json M1
evals/fixtures/portfolio_auditor/demo-portfolio/  M2  planted fixture portfolio
```

## Data flow (one audit run)

1. **Bind** — `load_auditor_bundle()` loads the APPROVED contract + policy,
   computes both digests; `ContractStore.lock_for_run` locks the contract
   into the run dir; every artifact carries the digest pair.
2. **Inventory** — the repository source (fixtures in V1) yields the
   configured inventory; the strategic list comes from operator config
   (PD-PA-02), never source code.
3. **Broad scan** — mechanical signals per repository, injected clock,
   byte-identical re-runs; secret hits recorded as rule/path/line only.
4. **Select** — deterministic risk ranking chooses the deep-inspection set.
5. **Deep inspect** — read-only passes (snapshot/verify around each);
   findings with origin-independent corroboration (2 normal / 3
   high-impact); business claims graded on the five-point scale.
6. **Classify** — AI-slop verdict through the gate: hard verdicts need
   confidence ≥ 70 AND a counter-evidence review; forbidden sole bases
   force INSUFFICIENT_EVIDENCE (PD-PA-01: never about the person).
7. **Report** — dashboard + scorecards + backlog rendered as pure
   functions; a numeric score never overrides a material high-confidence
   finding.
8. **Remediate (sandbox)** — generated PRs against sandbox repos; the merge
   decision enforces all 9 gates and refuses the 8 forbidden actions,
   bound to the inspected commit.
9. **Re-audit** — compare against the frozen baseline; regressions → HOLD.

Every step appends to the run's `EvidenceLedger`; a run that cannot proceed
writes an explicit BLOCKED report (PD-PA-07) — never invented results.

## Determinism rules

- Clocks, run ids, and inventories are parameters; no wall-clock reads in
  scoring, ranking, selection, or rendering.
- All serialization is sorted-key canonical JSON; digests via
  `canonical_digest`.
- Fixtures encode planted cases (healthy, slop-wrapper, stale-fork,
  private-with-secret); if a formula changes, planted expectations are
  re-derived, never loosened.

## Audit modes without schedulers (PD-10)

`quarterly`, `on_demand`, and `post_remediation` are labels on explicit
CLI invocations. There is no daemon, no cron, no self-prompting loop in
this repository.
