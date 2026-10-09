# Approval request: re-freeze PMOS-TASK-TRACKER-001 (candidate r2), status UNAPPROVED

Nothing in this file is approval. Approval can only come from the owner's written reply.

## What would be approved

- **Candidate:** PMOS `reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json`,
  committed at PMOS `b146337`.
- **Candidate canonical digest (RFC 8785):**
  `sha256:5f3ea231fb7148f99d2005264fd36747c2ed72a8e30d59d519e539e2742e710a`. PEOS `canonical_digest` and
  the stdlib form compute the same value.
- **Baseline for the bound bytes (full commits):**
  - PEOS `e8a929df0feca124005dfc84f1b5bebdd207eab9`: 204 entries
  - PMOS `0652843f02b5fbd5734331ffe5c00675a7b40b6b`: 14 entries
  - 218/218 recomputed from git bytes at those commits and from the current working trees.
- **Superseded, never approved:** `82f6365c…` (it silently rewrote `previous_review_bundle_digest`),
  `20e67cca…`, and the scratch `123be9dd…`.

## Changed bound files (frozen → baseline)

| File | Change | Effect |
| --- | --- | --- |
| PMOS `.claude/skills/decision-to-contract/SKILL.md` (PR #68, 33ba7ec) | Prose: new verification gate asks release gates to carry `acceptance_criterion_refs`; tighter approval wording | No contract, plan, evaluator or authority mechanism change |
| PEOS `src/pmpe/barebones.py` (PR #243) | A provider `OSError` now ends `HALTED/MODEL_PROVIDER_FAILED` | Execution path only |
| PEOS `src/pmpe/cli/barebones_cmd.py` (PR #243) | Provider is built after the approval check; child is terminated on stream `OSError` | Execution path only |
| PEOS `src/pmpe/contracts/acceptance.py` (PR #244) | Stricter compiler: invalid assertions are not counted, and a non-mapping `human_test` is rejected | Frozen contract compiles to the identical plan |
| PEOS `src/pmpe/evals/real_behavior_drift_eval.py` (PR #233) | Sealed memfd bwrap image | Not on the run path; changes bundle identity only |

The complete diffs (458 lines) are in `docs/evidence/task-tracker-completion-20261009/stage-a/w1/diff-1..5.patch`.

## Unchanged and verified

- Approved contract: `sha256:501e0fd5…`. It reproduces byte-for-byte from the publisher.
- Receipt: bytes unchanged; it verifies to `sha256:4b1f1771…09ef`.
- Compiled plan: `plan_digest` `sha256:1dad520e…`; canonical form `sha256:4d552932…`, identical at e8a929d.
- Criteria and gates: 14 criteria (AC-001 to AC-014) and 5 gates (GATE-001 to GATE-005, no criterion references).
- Evaluator, bindings and profile: identical.
- Manifest fields: `previous_review_bundle_digest` keeps the historical `4eaa1d95…`, and `review_bundle_digest` keeps `fbfe7363…`.

## The mechanical transition (only after the owner's matching approval and permission)

`refreeze_transition.py apply` changes exactly four fields:

| Field | Becomes |
| --- | --- |
| `status` | `OWNER_CONFIRMED_FROZEN` |
| `owner_approval_quote` | the owner's exact reply |
| `recorded_at` | the UTC time Claude processes that reply |
| `approval_context` | a statement that the owner approved candidate `sha256:5f3ea231…` in session `session_01KHtyZ9U4aq3hxRTXkBKMb2` and that Claude recorded it with the owner's permission |

The tool refuses any other change.

It writes `refreeze-20261009/transition.json` and `superseded-freeze-manifest.json`.
`verify` then proves that reverting those four fields reproduces `5f3ea231…`.

The active digest will differ from the candidate digest. Both will be reported.

## Decisions folded into the approval

1. **Review manifest.** Its `future_source_rule` says to regenerate the review manifest when bound source changes.
   - Recommended: waive regeneration for this re-freeze and keep the September review bundle as history.
   - Alternative: regenerate first. That produces a new candidate and a new question.
2. **Support-package proof flake.**
   - Root cause: the empty-read cache in the documented-port loop. The exact message was reproduced on the real test path; the fix is a one-line production change.
   - Recommended: do not include the fix in this re-freeze. The file is off the task-tracker run path. Approve it separately later.
   - Alternative: include it, which needs a new baseline and a new candidate.
3. **Pin.**
   - Recommended: keep `297a11d7` for the generic current-authoring job (7/7) and record `e8a929d` as the task-tracker baseline.
   - Reason: at `e8a929d` the generic job scores 5/7, with two `AcceptanceCompileError not raised` failures. At `297a11d7` the frozen contract is rejected with `RELEASE_GATE_UNBOUND`. No single pin satisfies both jobs.

## Remaining failures and limitations

- **Support-package flake:** fix not applied. Full suite on compliant Git: 2911 passed, 4 skipped (bwrap), 0 failed, twice.
- **Refusal tests:** 4/4 pass locally, but all four skip in PEOS CI, which does not check out PMOS.
- **Process cleanup:** the provider shim escapes the killed process group. The tests reap it.
- **Missing `failure.json`:** a wrong freeze digest and a reused output directory exit 1 with no `failure.json`. They are still classified as BLOCKED, never PASS.
- **Timeout:** the provider timeout is fixed at 600 s, with a shim deadline of 540 s.
- **Unknown product command:** it gets argparse usage text rather than JSON. No criterion covers it.
- **Approval authority:** receipts are public-hash and forgeable; the expected approver in the entry is self-referential; root can alter evidence. There is no Bubblewrap leg.
- **CI:** no CI runs on branch pushes. Getting required checks to run needs draft PRs, which requires separate permission.
- **Merge state:** nothing is merged. PEOS `main` lacks `session-file-provider.py` and the entry.
