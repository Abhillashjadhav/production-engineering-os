# R4 retained-inspection BAR

1. **Does this already exist? Yes.** Reuse and strengthen `validate_release_gate_evidence` and the existing barebones reader; the alternative-engine approach is stopped.
2. **Approved criterion or reproduced blocker? Yes.** R4 N1–3/N5, C4-F1/F2/F4, and F-C3-2/3/4 identify inconsistent retained evidence accepted by these readers.
3. **Existing behavior affected? Yes.** Gated and ungated retained inspection/status, synthetic packet fixtures, support-package reading, and PMOS callers may reject packets lacking coherent attempts or genuine receipt bindings; this isolated inspection branch owns the change.
4. **Executable RED-before/GREEN-after check? Yes.** `reviews/r4-inspection/red.txt` records 45 failing new mutation/anchor cases and 44 passing existing controls on unchanged source; source implementation may proceed.
5. **Revert as one unit? Yes.** Reader/CLI changes and direct regression/control fixtures form one logical inspection repair; the shared process validator is a separate integration dependency.
6. **Unrequested setting/dependency/extension? No.** Preserve the public validator signature; `head_anchor` explains the existing optional head argument and adds no authority.

No frozen source, trusted policy, scanner, allowlist, model, deployment, merge, or publication changes. A self-consistent unsigned rewrite remains unauthenticated without an independently retained head.

## Distinct support-package caller unit

1. **Existing path? Yes.** Extend the package reader's current contract/receipt/candidate checks; do not synthesize a barebones plan or add another engine.
2. **Reproduced blocker? Yes.** The real package sealer has a separate two-event format; strict barebones validation would reject it, while its old reader accepted an interposed unknown event.
3. **Existing behavior affected? Yes.** Package sealing, reuse, and assembly consume this reader; the coordinator explicitly extended this branch's boundary to its call site.
4. **Executable RED/GREEN? Yes.** The archived baseline gives one failure and three preserving controls in `package-red.txt`; the changed reader and full support file give 88 passes in `package-green.txt`.
5. **Single-unit revert? Yes.** A pure sequence guard, one import/call substitution, and four direct tests form a separate commit.
6. **Unrequested setting/dependency? No.** The existing package schema and caller distinguish this format. No marker, policy, scanner, or settings change is added.

## W1a — malformed human-test bindings on the R4 process line (2026-09-25)

1. **Already exists? Yes.** PR #205 (`bd3e081`) fixed this against `main`; this unit reuses its exact test and source change on `ccabeecc` instead of writing a parallel fix.
2. **Reproduced blocker? Yes.** Handoff W1 / review P1: `human_test: null` compiles to zero criteria and still counts as requirement coverage. `reviews/w1-consolidation-20260925/human-test-binding-red.txt` records 21 failing / 44 passing on unchanged `ccabeecc` source.
3. **Changes behaviour with callers/tests? Yes.** `compile_acceptance_plan` now raises for malformed bindings that were previously dropped silently; contracts that relied on that silent drop will be refused before any provider or sandbox call.
4. **Failing check first? Yes.** Test commit precedes the fix commit.
5. **Revert as one unit? Yes.** Two commits, one test file and one source function.
6. **New setting/dependency/extension? No.**

## W1b — setup/teardown failures counted as meaningful RED on the R4 process line (2026-09-25)

1. **Already exists? Yes.** PR #204 (`12fa805`, `c061e21`) fixed this against `main`; this unit reuses its tests (including the allowlisted-fixture position) and source change on top of W1a.
2. **Reproduced blocker? Yes.** Handoff W1 / review P1: a fixture failing before the test body was classified as an assertion failure. `reviews/w1-consolidation-20260925/call-phase-red-red.txt` records 4 failing / 44 passing on unchanged W1a source.
3. **Changes behaviour with callers/tests? Yes.** `_run_pytest_node` now raises `ContractInvalidError` for setup/teardown failures and non-assertion exceptions that previously counted as RED; intentional `pytest.fail` and assertion failures keep their meaning.
4. **Failing check first? Yes.** Test commit precedes the fix commit.
5. **Revert as one unit? Yes.** One source function and one test file.
6. **New setting/dependency/extension? No.**
