"""Extra checks with bound code: plan JSON round-trip, realistic receipt forgery, entry compatibility on packet copies."""
import copy, hashlib, importlib.util, json, shutil, sys, tempfile
from pathlib import Path
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.model import load_contract
from pmpe.barebones import compile_barebones_plan
W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
P = W / "files" / "packet"
spec = importlib.util.spec_from_file_location("cfe", W / "peos/examples/barebones/contract-file.py")
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)
R = {}
rj = lambda p: strict_loads(Path(p).read_bytes(), "application/json")
approved, receipt = rj(P / "contract.approved.json"), rj(P / "approval-receipt.json")
tmpl = cf.load_template(P / "bindings.json")
with tempfile.TemporaryDirectory(dir=str(W / "tmp")) as td:
    plan = compile_barebones_plan(contract=approved, repository_root=Path(td), template=tmpl)
pd = plan.as_dict()
R["plan_json_roundtrip_equals_frozen"] = json.loads(json.dumps(pd)) == rj(P / "compiled-plan.json")
# realistic forgery: edit an existing field value (AC-001 'then' first expectation value), recompute public hashes
f = copy.deepcopy(approved)
ac = f["acceptance_criteria"][0]
R["AC-001_then_before"] = json.dumps(ac.get("then"))[:300]
if isinstance(ac.get("then"), list) and ac["then"]:
    ac["then"][0]["value"] = "FORGED"
elif isinstance(ac.get("then"), str):
    ac["then"] = ac["then"] + " (FORGED)"
fd = copy.deepcopy(f); fd.update({"contract_status": "DRAFT", "approved_by": "", "approved_at": ""})
forged = {k: v for k, v in receipt.items() if k != "receipt_digest"}
forged.update({"approved_contract_digest": canonical_digest(f), "draft_digest": canonical_digest(fd)})
forged["receipt_digest"] = canonical_digest(forged)
try:
    R["forgery_existing_field_verify_contract_approval"] = "ACCEPTED " + verify_contract_approval(copy.deepcopy(f), copy.deepcopy(forged), expected_approver="Abhillash Jadhav")
except Exception as e:
    R["forgery_existing_field_verify_contract_approval"] = f"REFUSED {type(e).__name__}: {e}"
# entry-level compatibility() on a disposable packet copy carrying the forged contract+receipt
with tempfile.TemporaryDirectory(dir=str(W / "tmp")) as td:
    pk = Path(td) / "packet"; shutil.copytree(P, pk)
    (pk / "contract.approved.json").write_text(json.dumps(f))
    (pk / "approval-receipt.json").write_text(json.dumps(forged))
    try:
        R["forged_load_contract_runnable"] = bool(load_contract(pk / "contract.approved.json").runnable)
    except Exception as e:
        R["forged_load_contract_runnable"] = f"ERROR {type(e).__name__}: {e}"
    try:
        rep, *_ = cf.compatibility(pk, cf.load_template(pk / "bindings.json"), rj(pk / "execution-profile.json"), Path(td) / "out", True)
        R["forged_entry_compatibility_reasons"] = rep["reasons"]
        R["forged_entry_compatibility_plan_digest"] = rep["plan_digest"]
    except Exception as e:
        R["forged_entry_compatibility"] = f"RAISED {type(e).__name__}: {e}"
    # same packet copy, original contract/receipt -> baseline compatibility
    shutil.copy(P / "contract.approved.json", pk / "contract.approved.json"); shutil.copy(P / "approval-receipt.json", pk / "approval-receipt.json")
    try:
        rep, *_ = cf.compatibility(pk, cf.load_template(pk / "bindings.json"), rj(pk / "execution-profile.json"), Path(td) / "out2", True)
        R["original_entry_compatibility_reasons"] = rep["reasons"]
        R["original_entry_compatible"] = rep["compatible"]
        R["original_entry_plan_digest"] = rep["plan_digest"]
    except Exception as e:
        R["original_entry_compatibility"] = f"RAISED {type(e).__name__}: {e}"
# DigestGuard with the active manifest and the bound trees (git-object copies are not needed: read-only roots)
try:
    g = cf.DigestGuard(P / "freeze-manifest.json", {"PM-agent-OS": "/home/user/PM-agent-OS", "production-engineering-os": "/home/user/production-engineering-os"},
                       "sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2", Path(W / "tmp" / "guard-active.jsonl"))
    try:
        g.check("w1-readonly-probe")
        R["digestguard_active_vs_real_worktrees"] = "PASS"
    except Exception as e:
        R["digestguard_active_vs_real_worktrees"] = f"{type(e).__name__}: {str(e)[:600]}"
except Exception as e:
    R["digestguard_active_init"] = f"{type(e).__name__}: {e}"
try:
    cf.DigestGuard(P / "freeze-manifest.json", {"PM-agent-OS": ".", "production-engineering-os": "."}, "sha256:82f6365cd895892c4cb9fadd279f82e2755cc62bed2c60d95f49233d4c1c7f42", Path(W / "tmp" / "guard-wrong.jsonl"))
    R["digestguard_wrong_digest"] = "ACCEPTED (unexpected)"
except Exception as e:
    R["digestguard_wrong_digest"] = f"REFUSED {type(e).__name__}: {e}"
(W / "logs" / "chain-extra.json").write_text(json.dumps(R, indent=2, default=str))
print(json.dumps(R, indent=1, default=str))
