import json
from pathlib import Path
W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
c1 = json.loads((W / "logs/chain-e8a929d.json").read_text())
c2 = json.loads((W / "logs/chain-f7669c2.json").read_text())
x1 = json.loads((W / "logs/chain-extra.json").read_text())
x2 = json.loads((W / "logs/chain-extra2.json").read_text())
chain = {
 "contract_id": "PMOS-TASK-TRACKER-001",
 "classification_key": {"a": "machine-verified now by W1", "b": "historical evidence only (quoted/asserted, cannot be re-derived)", "c": "still manual / not verifiable here"},
 "transitions": [
  {"step": "0. original request / intent",
   "artifacts": {
     "PMOS reviews/task-tracker-v1/publisher-input.json": "raw sha256:37303040df5b8dc6a9d3ae8182654872e629b59e1212dca736586693ecd50c40; canonical = contract source_digest sha256:80446afd29bec2cfa984dd7a2564a74d57b39d257d9f2f093c27446854f22f75 (reproduced via build_contract_draft equality)",
     "PMOS reviews/task-tracker-v1/ACCEPTANCE.md": "raw sha256:7788286762d679c26769e4abc05406597829cdb89da57a0425d4353d79c5e7a8 (agent-written; paraphrases owner decisions APD-001..APD-008)",
     "contract approved_product_decisions": "APD-001 'Owner approved a local task tracker with create, complete, status filtering and persistence across restart; CLI is sufficient.' ... APD-008",
     "external pointer": "PMOS issue #56 (commit 408ee21 'Refs #56'; reviews/pmos-workflow-20260925/RECONCILIATION.md) - NOT retrieved (outside repos)",
     "PRD search": "no task-tracker PRD in PMOS prds/ (2 files) or PEOS prds/ (3 files); git grep PMOS-TASK-TRACKER-001 hits only the packet + PEOS evidence"},
   "verification": "b", "note": "No owner-authored request record exists in either repo; intent is the agent-prepared publisher input."},
  {"step": "1. publisher input -> DRAFT (contract.draft.json)",
   "artifacts": {"contract.draft.json": "raw sha256:141fce81ce3b7ff25408df72bd0d4d3a6520b3ec70aab75a5d1821cf605ead74; canonical sha256:0684ae3efbc62aef686e36b9acc871e92451c458ed0a53bb951cebc44748fe89"},
   "recomputed": {"e8a929d": c1["rebuild_draft"], "f7669c2": c2["rebuild_draft"]},
   "verification": "a", "note": "build_contract_draft(publisher-input) == contract.draft.json exactly; draft bytes identical at PMOS 00ccd29 (owner-amendment commit, README showed this draft digest) and 3fa07a8 (freeze)."},
  {"step": "2. owner approval",
   "artifacts": {"freeze-manifest.json owner_approval_quote": "Confirmed — freeze the amended grid and proceed.",
                 "README.md 'Approval source'": "same quote",
                 "commit sequence (PMOS, PR #58 refs, unsigned %G?=N, author/committer 'Abhillash Jadhav')": "408ee21 proposal (review bundle sha256:4ae47ef2..., PROPOSED_NOT_APPROVED) -> 00ccd29 owner amendments (bundle sha256:4eaa1d95..., PROPOSED_NOT_APPROVED) -> 3fa07a8 freeze (bundle sha256:fbfe7363..., OWNER_CONFIRMED_FROZEN, freeze sha256:1dd281e5...) -> 9d55bf6"},
   "verification": "b", "note": "Approval is a quoted conversation recorded by the agent in two files; the quote names no digest; not in the receipt; no signature anywhere (receipt has no sig/key field; commits unsigned). Any new approval (re-freeze) is manual (c)."},
  {"step": "3. approved contract + approval-receipt.json",
   "artifacts": {"contract.approved.json": "raw sha256:41f93f23ca57cef1...; canonical sha256:501e0fd5eae05bceffeef928d1b731173dd8be87c988340f2761575d29b7e80e",
                 "approval-receipt.json": "raw sha256:856ef2b3257a54c3...; receipt_digest sha256:4b1f17711268f9bceca6d7b4fd4082bc35a65ddee383c6eb7eee28b5a64609ef; keys " + ", ".join(c1["receipt_keys"])},
   "recomputed": {"reapprove_e8a929d": c1["reapprove"], "verify_contract_approval(expected_approver='Abhillash Jadhav')": c1["verify_contract_approval_expected_owner"],
                  "_require_approved_contract as entry calls it": c1["require_approved_contract_as_entry_calls_it"],
                  "planted tamper (no re-hash)": c1["planted_tamper_unrehashed"],
                  "forgery (tamper + recomputed public hashes)": c1["forged_receipt_with_public_hashes"],
                  "forgery editing existing AC-001 field": x1["forgery_existing_field_verify_contract_approval"],
                  "forgery of non-plan fields (problem, GATE-001 description)": "ACCEPTED by verify_contract_approval -> " + x2["nonplan_forgery_verify_contract_approval"],
                  "entry compatibility() on forged packet copies": [x1["forged_entry_compatibility_reasons"], x2["nonplan_forgery_entry_compatibility"]["reasons"]]},
   "verification": "a (internal consistency) / b (authority)", "note": "receipt_digest = canonical_digest(receipt minus receipt_digest): public, keyless, forgeable. contract-file.py passes expected_approver=contract['approved_by'] (self-referential). Forged contracts are caught at the entry only by PLAN_CHANGED (compiled-plan.json embeds contract_digest) and by the raw-byte freeze guard; both anchors are unsigned repo files, ultimately anchored by the operator-supplied --freeze-digest."},
  {"step": "4. bindings.json / execution-profile.json",
   "artifacts": {"bindings.json": "raw sha256:3414ac07671405b6d69a41af91b1e96b8324d1c4455b0e262f5e04123540dac0 (version task-tracker-acceptance-v1)",
                 "execution-profile.json": "raw sha256:4a46f594d269e130b8933cd032fa7fb400c0a510553f77140efa2a1fab683120 (= compatibility.json profile_digest)"},
   "verification": "a", "note": "Both in the 218 inventory, unchanged since 00ccd29; load_template() (contract-file.py) admits bindings.json at e8a929d and f7669c2."},
  {"step": "5. compiled-plan.json",
   "artifacts": {"compiled-plan.json": "raw sha256:e729e28f53833400...; canonical sha256:4d552932f8907d770ecb01827d6b2a218b62fcd2002abb808ecd83d430072ab7; plan_digest field sha256:1dad520ebc6ac6973aeb23d80fe5c98d67e3d8a5fa20d902f56d45a180777b28"},
   "recomputed": {"e8a929d": c1["plan"], "f7669c2 (active-freeze-era code)": c2["plan"], "json_roundtrip_equal": x1["plan_json_roundtrip_equals_frozen"]},
   "verification": "a", "note": "Identical plan at both code eras; 14 criteria = 13 given_when_then + 1 measure (AC-013); compile raised no AcceptanceCompileError (zero diagnostics)."},
  {"step": "6. freeze manifest / review bundle",
   "artifacts": {"freeze-manifest.json": "raw sha256:bb7bc83e...; canonical sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 (= freeze-bundle.sha256)",
                 "review-manifest.json": "raw sha256:f3ad347c...; canonical sha256:fbfe73637ec326330d3107aac1d43b023fc7c5473fe3ef7dfcede7e4d07af711 (= review-bundle.sha256); peos_source_commit 1abfbd47061a947e8ce077523a60516a0b6cdcb0; pmos_policy_base_commit 5d79b20cc16703cb8fd6fa98040659db8881c579; binds 212 artifacts incl. OLD digests of the 5 drifted files"},
   "recomputed": c1["freeze_fields_vs_recomputed"],
   "verification": "a", "note": "Active manifest matches PEOS 1abfbd4..f7669c2 (204/204) and PMOS 9d55bf6/5aefeb5 (14/14); at bound/head/worktree 213/218 (5 drift)."},
  {"step": "7. PEOS entry examples/barebones/contract-file.py",
   "artifacts": {"contract-file.py": "raw sha256:08d590186663d48a1ecfd34cb169240d07c9d65e132e4791c6816171f7ccf387 at f7669c2/e8a929d/4b1558f/worktree; ABSENT at PEOS main 1a431b2; OUTSIDE the 218 inventory (created 54df3c0 2026-09-18T15:32:47Z, after recorded_at 15:22:13Z; last changed 0295973)"},
   "checks_before_execution": ["output dir must not exist", "canonical_digest(freeze-manifest.json) == --freeze-digest else FREEZE_DIGEST_MISMATCH", "all manifest artifacts + manifest file + own file (self-hash taken at start) raw-hashed before/after (220 checks)", "load_template: only version/files/actions/measures/context; targets module:function inside frozen tests/ files with __init__.py", "--authorized-host-fallback present", "CPython 3.12", "prlimit present", "profile.candidate_dependencies empty", "load_contract(contract.approved.json).runnable", "_require_approved_contract(contract, receipt, contract['approved_by'])", "compile_barebones_plan; only given_when_then/measure forms", "canonical plan == compiled-plan.json else PLAN_CHANGED"],
   "observed_runs_by_W1": {"check, active packet, real trees": "exit 2 TamperDetectedError APPROVAL_BOUND_ARTIFACT_CHANGED (5 files), 220 checked",
                           "check, DISPOSABLE packet copy with candidate manifest, real trees, --freeze-digest 82f6...": "exit 0 compatible, plan sha256:1dad520e..., 220 checked before+after, 0 mismatches (dry run on a copy, NOT approval)",
                           "DigestGuard(active, wrong digest 82f6...)": x1["digestguard_wrong_digest"]},
   "verification": "a (checks exercised) / c (entry bytes not approval-bound)"}
 ],
 "counts": {"acceptance_criteria": c1["acceptance_criteria_count"], "acceptance_criteria_ids": c1["acceptance_criteria_ids"],
            "binary_release_gates": c1["binary_release_gates_count"], "gate_ids": c1["binary_release_gate_ids"],
            "gate_keys": c1["binary_release_gate_keys_union"], "gates_with_acceptance_criterion_refs": c1["gates_with_acceptance_criterion_refs"]}
}
(W / "chain.json").write_text(json.dumps(chain, indent=2, ensure_ascii=False))
print("ok", len(chain["transitions"]))
