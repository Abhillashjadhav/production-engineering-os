# GitHub Portfolio Auditor V1 — threat model

Scope: the auditor's own behavior and the blast radius of a wrong or
malicious run. Carried over from the archived prototype's threat model and
re-pointed at Production Engineering OS mechanisms. Reviewed per milestone.

## Assets

1. The portfolio owner's reputation (verdicts are publishable).
2. Private repository contents, names, and configuration (PD-PA-06).
3. Real repositories' integrity (nothing may be modified, V1: not even read).
4. Secret values encountered during scanning.
5. The integrity of the evidence trail (verdict ⇄ evidence traceability).

## Threats and mitigations

### T1 — Fabricated or unsupported verdicts (honesty failure)
A verdict without evidence damages a real person's repository standing.
- Finding schema requires all seven fields; `Finding` refuses empty
  evidence at construction (PD-PA-07).
- Corroboration floors: ≥ 2 independent origins, ≥ 3 for high-impact
  (BLOCKING/HIGH) findings; origins deduplicate, so a README quoted twice
  is one origin.
- Hard AI-slop verdicts: confidence ≥ 70 AND completed counter-evidence
  review; six forbidden sole bases (writing style, disclosed AI
  assistance, commit volume, repository size, generated-file count, lack
  of popularity) force INSUFFICIENT_EVIDENCE regardless of confidence.
- A blocked run reports BLOCKED; there is no code path that emits a
  result without recorded evidence.

### T2 — Judgment of a person instead of an artifact (fairness failure)
- PD-PA-01 is pinned in the locked contract; the verdict vocabulary
  contains no person-level terms; report renderers (M6) take repository
  identifiers only.

### T3 — Private data leakage into public artifacts
- PD-PA-06 pinned; policy `redact_private_origins_in_public_reports` is
  schema-enforced to `true` (an edited policy fails validation).
- Secret hits are recorded as rule/path/line only — the value is never
  stored, logged, or rendered (scanner tests plant placeholder secrets and
  assert full redaction).
- Fixture private repos exist precisely to test that no private source,
  name, or configuration reaches a public report.

### T4 — Unauthorized real-repository access or modification
- V1 builds run on fixtures only (PD-PA-04); the live source is a
  fail-loud stub until the operator supplies an explicit allowlist
  (schema-enforced `explicit_repository_allowlist_required: true`).
- Dry-run is the default; destructive actions are refused
  (`block_destructive_actions: true`).
- Deep inspection wraps every pass in `readonly_snapshot` /
  `verify_unmodified` — a modified tree fails the run, mirroring PD-06
  reviewer guarantees.
- Remediation (M7) targets sandbox repositories only; the merge decision
  is a pure function whose 9 gates include `bound_to_inspected_commit`
  and whose 8 forbidden actions include destructive archival/deletion.
  Auto-merge authority never applies to the auditor's own branch
  (PD-PA-05), and nothing real is auto-merged in this repo (PD-08:
  draft PR only).

### T5 — Tampered contract, policy, or evidence (integrity failure)
- Contract mutations after lock fail closed (`ContractStore.verify_unchanged`,
  PD-03); the policy digest is canonical and key-order independent.
- The evidence ledger is append-only sorted-key JSONL with digests per
  event; findings bind to the inspected content digest via the candidate
  tree-digest primitives — evidence recorded against one commit cannot be
  silently reused for another.
- Drift evals (M5/M8): a new hard-gate failure relative to baseline is a
  HOLD, so a quietly weakened gate surfaces as a regression.

### T6 — Adversarial repository content attacking the auditor
Scanned repositories are untrusted input (hostile filenames, huge files,
crafted README claims, planted "instructions" aimed at a model).
- The Python core is mechanical: no model calls (PD-11), no code
  execution from scanned content, no shell interpolation of repository
  strings; parsing is bounded and typed, malformed data fails loudly.
- Model-facing inspection (Claude agents, M4+) consumes *observable
  signals* recorded by Python — agents never execute repository code, and
  instructions found in repository content are data, not directives.

### T7 — Scope creep of automation authority
- Auto-merge scope is schema-pinned to `sandbox_remediation_prs_only`;
  widening it requires a new contract version through `amend` semantics
  (a change request + re-approval), which is loud and reviewed.
- The OS policy engine classifies deployment-like decisions HIGH → blocked
  on a named human approval.

## Non-threats (out of scope for V1)

- Real GitHub API abuse/rate limiting (no live access exists yet).
- Market-level claim verification (V1 grades repository evidence only,
  PD-PA-03).
- Multi-tenant isolation (single-operator tool).

## Standing verification

Every milestone ships planted-failure tests for its threats (fabricated
verdict, leaked secret, non-sandbox merge attempt, tampered contract,
regression after remediation), and the repo-wide gates (pytest, ruff,
mypy --strict, security scan, independent read-only review) run per PR.
