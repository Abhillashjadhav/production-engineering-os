import copy, importlib.util, json, shutil, tempfile
from pathlib import Path
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.contracts.authoring import verify_contract_approval
W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
P = W / "files" / "packet"
spec = importlib.util.spec_from_file_location("cfe", W / "peos/examples/barebones/contract-file.py")
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)
rj = lambda p: strict_loads(Path(p).read_bytes(), "application/json")
approved, receipt = rj(P / "contract.approved.json"), rj(P / "approval-receipt.json")
R = {}
# non-plan forgery: change a release-gate description and the problem statement, recompute public hashes
f = copy.deepcopy(approved)
f["binary_release_gates"][0]["description"] = "FORGED: " + f["binary_release_gates"][0]["description"]
f["problem"] = "FORGED problem statement"
fd = copy.deepcopy(f); fd.update({"contract_status": "DRAFT", "approved_by": "", "approved_at": ""})
forged = {k: v for k, v in receipt.items() if k != "receipt_digest"}
forged.update({"approved_contract_digest": canonical_digest(f), "draft_digest": canonical_digest(fd)})
forged["receipt_digest"] = canonical_digest(forged)
R["nonplan_forgery_verify_contract_approval"] = verify_contract_approval(copy.deepcopy(f), copy.deepcopy(forged), expected_approver="Abhillash Jadhav")
with tempfile.TemporaryDirectory(dir=str(W / "tmp")) as td:
    pk = Path(td) / "packet"; shutil.copytree(P, pk)
    (pk / "contract.approved.json").write_text(json.dumps(f)); (pk / "approval-receipt.json").write_text(json.dumps(forged))
    rep, *_ = cf.compatibility(pk, cf.load_template(pk / "bindings.json"), rj(pk / "execution-profile.json"), Path(td) / "out", True)
    R["nonplan_forgery_entry_compatibility"] = {"compatible": rep["compatible"], "reasons": rep["reasons"], "plan_digest": rep["plan_digest"]}
    # the raw-byte freeze layer still catches it (contract.approved.json is a bound artifact)
    try:
        g = cf.DigestGuard(P / "freeze-manifest.json", {"PM-agent-OS": str(Path(td) / "pmosroot"), "production-engineering-os": "/home/user/production-engineering-os"},
                           "sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2", Path(td) / "g.jsonl")
        R["note"] = "guard constructed (check needs a full PMOS root; contract file byte change would be reported as mismatch)"
    except Exception as e:
        R["guard_init"] = f"{type(e).__name__}: {e}"
# candidate manifest under DigestGuard against the real worktrees (read-only)
cand_path = W / "files" / "candidateB.pmos-cafe8b4.json"
roots = {"PM-agent-OS": "/home/user/PM-agent-OS", "production-engineering-os": "/home/user/production-engineering-os"}
try:
    g = cf.DigestGuard(cand_path, roots, "sha256:82f6365cd895892c4cb9fadd279f82e2755cc62bed2c60d95f49233d4c1c7f42", W / "logs" / "digestguard-candidate-vs-real-worktrees.jsonl")
    g.check("w1-readonly-probe-candidate")
    R["digestguard_candidate_vs_real_worktrees"] = f"PASS ({len(g.entries)} entries incl. manifest anchor)"
except Exception as e:
    R["digestguard_candidate_vs_real_worktrees"] = f"{type(e).__name__}: {str(e)[:400]}"
(W / "logs" / "chain-extra2.json").write_text(json.dumps(R, indent=2, default=str))
print(json.dumps(R, indent=1, default=str))
