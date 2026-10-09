"""W1 chain verification: request -> draft -> approval -> receipt -> bindings -> plan -> entry.

Run with the PEOS venv python. argv[1] = label, argv[2] = path to contract-file.py to import
load_template from, argv[3] = output json path. pmpe is taken from whatever sys.path resolves
(editable install = $W/peos at e8a929d, or PYTHONPATH=<worktree>/src for other eras).
Only reads packet bytes previously extracted from git objects into $W/files/packet.
"""
import copy, hashlib, importlib.util, json, sys, tempfile
from pathlib import Path
import pmpe
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.contracts.authoring import build_contract_draft, approve_contract_draft, verify_contract_approval
from pmpe.contracts.model import load_contract
from pmpe.barebones import compile_barebones_plan
from pmpe.cli.barebones_cmd import _require_approved_contract
from pmpe.domain.errors import ContractViolation

W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
P = W / "files" / "packet"
label, entry_path, out_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("contract_file_entry", entry_path)
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)

def rj(name): return strict_loads((P / name).read_bytes(), "application/json")
def raw(name): return "sha256:" + hashlib.sha256((P / name).read_bytes()).hexdigest()
R = {"label": label, "pmpe_file": pmpe.__file__, "entry_imported_from": str(entry_path),
     "entry_raw_sha256": "sha256:" + hashlib.sha256(entry_path.read_bytes()).hexdigest()}

answers = rj("publisher-input.json")
R["publisher_input_top_keys"] = sorted(answers) if isinstance(answers, dict) else type(answers).__name__
draft_file = rj("contract.draft.json")
approved = rj("contract.approved.json")
receipt = rj("approval-receipt.json")
R["draft_file_canonical_digest"] = canonical_digest(draft_file)
R["approved_file_canonical_digest"] = canonical_digest(approved)
# 1. publisher input -> draft
try:
    inp = answers.get("answers", answers) if isinstance(answers, dict) else answers
    res = build_contract_draft(copy.deepcopy(inp))
    R["rebuild_draft"] = {"status": res.status, "draft_digest": res.draft_digest,
                          "equals_contract_draft_json": res.draft == draft_file,
                          "blocking_questions": [getattr(q, "__dict__", str(q)) for q in res.blocking_questions][:5]}
except Exception as e:
    R["rebuild_draft"] = {"error": f"{type(e).__name__}: {e}"}
# 2. draft -> approved + receipt (re-run publisher approval with recorded approver/time)
try:
    ap = approve_contract_draft(copy.deepcopy(draft_file), expected_draft_digest=receipt["draft_digest"],
                                approver=receipt["approved_by"], approved_at=receipt["approved_at"])
    R["reapprove"] = {"contract_equals_file": ap.contract == approved, "receipt_equals_file": ap.receipt == receipt,
                      "receipt_digest": ap.receipt["receipt_digest"]}
except Exception as e:
    R["reapprove"] = {"error": f"{type(e).__name__}: {e}"}
# 3. receipt verification (external authority supplied explicitly) and the entry's own call
try:
    R["verify_contract_approval_expected_owner"] = verify_contract_approval(copy.deepcopy(approved), copy.deepcopy(receipt), expected_approver="Abhillash Jadhav")
except Exception as e:
    R["verify_contract_approval_expected_owner"] = f"FAIL {type(e).__name__}: {e}"
try:
    _require_approved_contract(approved, receipt, approved["approved_by"])
    R["require_approved_contract_as_entry_calls_it"] = "PASS (expected_approver taken from contract['approved_by'])"
except Exception as e:
    R["require_approved_contract_as_entry_calls_it"] = f"FAIL {type(e).__name__}: {e}"
# 3b. planted failure: tamper one severity without re-hashing -> must fail
t = copy.deepcopy(approved)
t["acceptance_criteria"][0]["severity"] = "minor" if t["acceptance_criteria"][0].get("severity") != "minor" else "major"
try:
    _require_approved_contract(t, receipt, t["approved_by"]); R["planted_tamper_unrehashed"] = "ACCEPTED (unexpected)"
except Exception as e:
    R["planted_tamper_unrehashed"] = f"REFUSED {type(e).__name__}: {e}"
# 3c. forgery: tamper + recompute public hashes (no secret needed) -> shows receipts are forgeable
f = copy.deepcopy(t)
fd = copy.deepcopy(f); fd["contract_status"] = "DRAFT"; fd["approved_by"] = ""; fd["approved_at"] = ""
forged = {k: receipt[k] for k in receipt if k != "receipt_digest"}
forged["approved_contract_digest"] = canonical_digest(f)
forged["draft_digest"] = canonical_digest(fd)
forged["receipt_digest"] = canonical_digest(forged)
try:
    got = verify_contract_approval(copy.deepcopy(f), copy.deepcopy(forged), expected_approver="Abhillash Jadhav")
    _require_approved_contract(f, forged, f["approved_by"])
    R["forged_receipt_with_public_hashes"] = f"ACCEPTED by verify_contract_approval and _require_approved_contract (forged receipt digest {got})"
except Exception as e:
    R["forged_receipt_with_public_hashes"] = f"REFUSED {type(e).__name__}: {e}"
R["receipt_keys"] = sorted(receipt)
R["receipt_has_signature_or_key_field"] = any(k for k in receipt if any(s in k.lower() for s in ("sig", "key", "cert", "mac")))
# 4. load_contract runnable
try:
    m = load_contract(P / "contract.approved.json")
    R["load_contract_runnable"] = bool(m.runnable)
except Exception as e:
    R["load_contract_runnable"] = f"ERROR {type(e).__name__}: {e}"
try:
    m2 = load_contract(P / "contract.draft.json")
    R["load_contract_draft_runnable"] = bool(m2.runnable)
except Exception as e:
    R["load_contract_draft_runnable"] = f"ERROR {type(e).__name__}: {e}"
# 5. criteria and gates
acs = approved["acceptance_criteria"]; gates = approved["binary_release_gates"]
R["acceptance_criteria_count"] = len(acs)
R["acceptance_criteria_ids"] = [a.get("id") or a.get("criterion_id") for a in acs]
R["acceptance_criteria_keys_union"] = sorted({k for a in acs for k in a})
R["binary_release_gates_count"] = len(gates)
R["binary_release_gate_ids"] = [g.get("id") or g.get("gate_id") for g in gates]
R["binary_release_gate_keys_union"] = sorted({k for g in gates for k in g})
R["gates_with_acceptance_criterion_refs"] = [g.get("id") for g in gates if "acceptance_criterion_refs" in g]
# 6. bindings -> template -> compiled plan
tmpl = cf.load_template(P / "bindings.json")
with tempfile.TemporaryDirectory(dir=str(W / "tmp")) as td:
    plan = compile_barebones_plan(contract=approved, repository_root=Path(td), template=tmpl)
    pd = plan.as_dict()
frozen_plan = rj("compiled-plan.json")
R["plan"] = {"plan.plan_digest": plan.plan_digest,
             "canonical_digest(plan.as_dict())": canonical_digest(pd),
             "canonical_digest(compiled-plan.json)": canonical_digest(frozen_plan),
             "plan_equals_frozen_compiled_plan": pd == frozen_plan,
             "PLAN_CHANGED_check_would_pass": canonical_digest(pd) == canonical_digest(frozen_plan),
             "criteria_count": len(plan.criteria),
             "criteria_forms": sorted({c.form for c in plan.criteria}),
             "criteria_ids": [c.criterion_id for c in plan.criteria],
             "frozen_compiled_plan_keys": sorted(frozen_plan) if isinstance(frozen_plan, dict) else None,
             "frozen_plan_digest_field": frozen_plan.get("plan_digest") if isinstance(frozen_plan, dict) else None}
# 7. review bundle and freeze manifest anchors
rm = rj("review-manifest.json")
R["review_manifest_canonical_digest"] = canonical_digest(rm)
R["review_bundle_sha256_file"] = (P / "review-bundle.sha256").read_text().strip()
fm = rj("freeze-manifest.json")
R["freeze_manifest_canonical_digest"] = canonical_digest(fm)
R["freeze_bundle_sha256_file"] = (P / "freeze-bundle.sha256").read_text().strip()
R["freeze_fields_vs_recomputed"] = {
    "approved_contract_digest": [fm["approved_contract_digest"], canonical_digest(approved)],
    "plan_digest": [fm["plan_digest"], plan.plan_digest],
    "review_bundle_digest": [fm["review_bundle_digest"], canonical_digest(rm)],
    "receipt.approved_contract_digest": [receipt["approved_contract_digest"], canonical_digest(approved)],
    "receipt.draft_digest": [receipt["draft_digest"], canonical_digest(draft_file)],
}
out_path.write_text(json.dumps(R, indent=2, default=str))
print(json.dumps(R, indent=1, default=str))
