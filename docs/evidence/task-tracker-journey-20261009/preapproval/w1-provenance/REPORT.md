# W1 — approval/provenance check, PMOS-TASK-TRACKER-001 (2026-10-09)
(Transcribed by the integration owner from W1's hand-back; machine-readable outputs: recompute.json, recompute.full.json,
hashes-outside-inventory.json, manifest-diff.json, chain.json, logs/, scripts/.)

Inventory: active and both candidates list the same 218 (repository, path) pairs in the same order — no inventory difference.
vs active manifest: bound/head/worktree 213 match, 5 mismatch; PEOS main 212 (+ session-file-provider.py ABSENT on main).
vs 82f6 candidate: 218/218 at bound commits/heads/worktree; main 217 (same absent file).
Five mismatches frozen→actual: SKILL.md ad0978c8→f14623cb; barebones.py 9895b6cc→ab3e4f4b; barebones_cmd.py 09116350→8917eb82;
acceptance.py 07204c00→4490079b; real_behavior_drift_eval.py 27c1d087→093448d6. Active manifest fully matches PEOS 1abfbd4…f7669c2 (204/204)
and PMOS 9d55bf6/3fa07a8/5aefeb5 (14/14). Entry `check` on real trees: exit 2 APPROVAL_BOUND_ARTIFACT_CHANGED on exactly 5 of 220 checks.
Disposable-packet dry run with 82f6 candidate: exit 0, compatible, plan 1dad520e, 0 mismatches (not approval).

Canonical digests (pmpe @ e8a929d): active 1dd281e5 = freeze-bundle.sha256; cafe8b4 candidate 82f6365c = candidate-freeze-digest.txt;
PEOS stage-a copy 82f6365c (byte-identical); 0652843 candidate and PEOS refreeze-candidate/ copy 20e67cca.

Contradictions with claimed facts:
1. 82f6 candidate file is not at PMOS 0652843 (there: earlier candidate 20e67cca); 82f6 exists at PMOS cafe8b4 and PEOS 4b1558f stage-a/.
2. Undisclosed protected-field change previous_review_bundle_digest 4eaa1d95→fbfe7363 in both candidates.
3. review_bundle_digest kept at fbfe7363 although review-manifest.json still binds old digests of the five drifted files and its
   future_source_rule says to regenerate it if bound source changes.
4. Execution entry outside inventory: contract-file.py 08d59018… (created 54df3c0 after recorded_at; changed at 0295973; self-hash only);
   task-tracker-regression.py 2d351051…; clean-install/journey.py 6194264f…; inside: session-file-provider.py ed265e03…. All four absent on PEOS main.
5. Entry calls _require_approved_contract(contract, receipt, contract["approved_by"]) — expected approver is self-referential.
6. Receipts forgeable (confirmed): 9 keys, no signature/key/MAC; forged contract + re-hashed receipt accepted by verify_contract_approval;
   the entry catches it only via PLAN_CHANGED and the raw-byte freeze guard (operator-supplied --freeze-digest).
7. Cited run evidence runs/01..09, runs/07, "run 10" not committed anywhere — unverifiable.
8. Neither manifest works on current mains (PEOS main lacks session-file-provider.py).
9. Only PMOS PR #68 (33ba7ec) changed the SKILL.md bytes (not "#67–#74").

Chain: intent publisher-input.json 37303040… (historical record; no PRD; issue #56 not retrieved) → draft reproduced by build_contract_draft
(0684ae3e ✓) → approval quote only in freeze-manifest/README, names no digest, unsigned commits; sequence 408ee21 (4ae47ef2) → 00ccd29
(4eaa1d95) → 3fa07a8 (fbfe7363 + freeze) → approve_contract_draft reproduces contract.approved.json (501e0fd5 ✓) and receipt byte-for-byte;
verify_contract_approval → 4b1f1771…09ef ✓ → bindings 3414ac07…, profile 4a46f594… → plan at e8a929d and f7669c2: plan_digest 1dad520e ✓,
canonical 4d552932… = compiled-plan.json ✓ (13 gwt + 1 measure, 0 diagnostics) → entry checks (chain.json).
Criteria AC-001..AC-014 (14); gates GATE-001..GATE-005 (5) with keys id/description only, no acceptance_criterion_refs.
Five drifted-file diffs (stage-a/w1/diff-1..5.patch) byte-identical to git diff last-frozen..bound (458 lines).
