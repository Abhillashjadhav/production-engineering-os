# Option B probe (porting PR 209 commit 85358d5 "enforce executable release-gate bindings" onto e8a929d)

- cherry-pick: conflicts in 3 files (reviews prompt, test_release_gate_runtime.py, test_release_gate_compiler.py); 7 src/schema files apply, 293 insertions.
- Installed the conflicted-src tree: PMOS tests/decision-to-contract/test_current_authoring.py -> 7/7 OK.
- BUT compile_barebones_plan on the APPROVED PMOS-TASK-TRACKER-001 contract raises
  AcceptanceCompileError: RELEASE_GATE_UNBOUND:GATE-001..GATE-005
  because the approved contract's binary_release_gates carry no acceptance_criterion_refs.
- Conclusion: gate-enforcement lineage (PR 209 / pin 297a11d7) rejects the approved contract.
  It cannot be the baseline for this journey without changing the approved contract (a new approval).
