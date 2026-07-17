# pm-evals Web — dogfood verification report

**Candidate:** CAND-001, commit `243eddf72005f6f23ed70142053adbd27f7ae3c3`,
tree digest `sha256:3af7832792afa78c12aa88efab6030ebfeafdd45eb75f45c3d9a943470c03bcb`,
contract digest `sha256:f01af9c278d32e5c3c953f151662958c8580f109938e44016ac802dc563bad6f`.

This is a **verification-only** pass over the frozen candidate with the corrected
read-only guard and three-dimension release report (this PR). It reuses the six
lens reports (`lens-reviews/`) and the frozen phase-1 evidence; it does not
re-freeze the candidate or re-run the reviewers. Executed proof is in
`readonly-proof.txt`; the machine-readable result is `verification-report.json`;
the clean verification ledger is `verification-ledger.jsonl`.

The three dimensions are reported **separately**, as the fixed `release_report`
requires.

---

## 1. Product verdict: **HOLD**

The candidate carries confirmed, blocking defects. The reviewers found real
FAILs, so PROCEED is not honest; the product is held.

| # | Defect | Lens(es) | Disposition |
|---|--------|----------|-------------|
| P-1 | **S-3 Trace Detail does not deliver its contracted purpose** — it renders only *flipped* criteria, not per-criterion baseline-vs-candidate results or the trace's evidence fields; the `Comparison` payload does not even carry them. | ux-journey (J-7 FAIL), product-conformance (FAIL) | **ProductChangeRequest** — requires an API/payload change to approved behaviour. Separate follow-up PR. |
| P-2 | **S-3 `loading` state declared but unimplemented** — the explorer renders synchronously; the state is unreachable. | ux-journey, product-conformance | **ProductChangeRequest** — implement the state or amend the contract. Separate follow-up PR. |
| P-3 | **GATE-4: reports were not byte-identical for identical inputs** — `/api/report` injected `datetime.now()`. | product-conformance (FAIL), backend-api-security | **Fixed in this PR** for future candidates (deterministic `/api/report`; regression test added). Remains FAIL for the *frozen* CAND-001; a re-frozen candidate clears it. |
| P-4 | **Committed OpenAPI 422 schema ≠ wire shape** — documented as a bare `ValidationProblem[]`; the app emits `{"detail": [...]}` (plus two more shapes). A generated client mis-parses every 422. | backend-api-security (FAIL) | Separate follow-up product PR (schema + typed-client). |
| P-5 | **Size cap enforced after multipart parsing**, not before; **duplicate-key and `NaN`/`Infinity` parser differentials** accepted silently; **no backend lockfile / audit gate**. | backend-api-security (FAIL) | Separate follow-up product PRs. |

Numerous items are **NOT_PROVEN** (the 375px mobile requirement was exercised at
390px; unit suites are not candidate-bound; only `local_preview` ran, not the
contracted `containerized_preview`; egress/persistence have no executed test).
These independently preclude PROCEED and reinforce HOLD.

## 2. Reviewer findings

All six lenses reviewed the frozen candidate and returned findings (full reports
in `lens-reviews/`, verbatim as produced). Every lens verified the candidate
manifest first (CAND-001, commit `243eddf`). The reconciliation above is drawn
from those reports; the product defects are tracked as the follow-up backlog,
not retrofitted into the frozen candidate.

## 3. Verification integrity: **valid and auditable**

- The reviewer read-only proof is drawn at the **git-tracked boundary**. Over
  the frozen candidate tree (464 tracked files), the corrected guard is **clean**
  — including the exact prior false positive: a `.claude/scheduled_tasks.lock`
  present at snapshot time then deleted mid-review no longer reads as a write.
  A real tracked-file modification is still caught. (`readonly-proof.txt`.)
- The six v3 reviewers are **read-only by tool configuration** at `243eddf`
  (Read/Grep/Glob only), asserted fail-closed.
- Driving `begin_review`/`end_review` over the frozen candidate worktree yields
  **six clean read-only proofs**; `release_report` emits **HOLD** with
  `verification_integrity = valid`. (`verification-ledger.jsonl`.)
- The complete verification ledger (reused phase-1 evidence + the six
  re-established reviews + the HOLD release) is **clean under both rule sets** —
  `evaluate_fullstack_trajectory` (TRAJ-FS) and `evaluate_trajectory` (V2) both
  return no violations. TRAJ-FS-06 was aligned with `release_report` in this PR
  so the trajectory auditor and the orchestrator agree about the same run
  (an `infrastructure_invalid` proof is acceptable for HOLD, never for PROCEED).

The original run's failed read-only proof (`readonly_check: modified`) was a
harness-lock **false positive**, not a reviewer write. It is preserved verbatim
in `audit/` and is superseded — not erased — by the clean proof here.

### Candidate binding note (honest scope)

The candidate is bound by its **immutable commit** `243eddf`, and the read-only
proofs are re-run over that commit's tracked tree. The frozen manifest's
`tree_digest` (`3af783…`) was produced by the freeze content-map, which walks the
whole working tree (including untracked `.venv`/caches present at freeze time)
and is therefore not reproducible from a clean checkout. Migrating the *freeze*
digest to the same git-tracked boundary is a separate follow-up (it would move
already-frozen candidate digests and is out of scope for this PR, which must not
touch `243eddf`).

---

## Outcome

- **Product release verdict:** HOLD.
- **Verification infrastructure:** valid and auditable.
- **Product defects:** tracked as separate follow-up PRs (P-1, P-2, P-4, P-5);
  the report-determinism defect (P-3) is fixed in this PR for future candidates.
