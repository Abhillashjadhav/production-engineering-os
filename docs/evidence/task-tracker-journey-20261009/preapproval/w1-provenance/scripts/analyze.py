import json, collections
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
d = json.load(open(f"{W}/recompute.full.json"))
rows = d["rows"]
out = {}
for ref in ("active_sha", "candidate_sha", "candidateA_sha_pmos_0652843"):
    for obs in ("bound_commit_sha", "head_sha", "main_sha", "worktree_sha"):
        mism = [{"repository": r["repository"], "path": r["path"], "expected": r[ref], "actual": r[obs]} for r in rows if r[ref] != r[obs]]
        out[f"{ref} vs {obs}"] = {"match": len(rows) - len(mism), "mismatch": len(mism), "mismatches": mism}
# candidate vs active differences
diffAB = [{"repository": r["repository"], "path": r["path"], "active": r["active_sha"], "candidate": r["candidate_sha"]} for r in rows if r["active_sha"] != r["candidate_sha"]]
diffAA = [{"repository": r["repository"], "path": r["path"], "active": r["active_sha"], "candidateA": r["candidateA_sha_pmos_0652843"]} for r in rows if r["active_sha"] != r["candidateA_sha_pmos_0652843"]]
diffBA = [{"repository": r["repository"], "path": r["path"], "candidateB": r["candidate_sha"], "candidateA": r["candidateA_sha_pmos_0652843"]} for r in rows if r["candidate_sha"] != r["candidateA_sha_pmos_0652843"]]
out["active_vs_candidateB_records"] = diffAB
out["active_vs_candidateA_records"] = diffAA
out["candidateB_vs_candidateA_records"] = diffBA
modes = collections.Counter((r.get("bound_commit_mode"), r.get("head_mode"), r.get("main_mode")) for r in rows)
out["modes"] = {str(k): v for k, v in modes.items()}
out["absent"] = {k: [ (r["repository"], r["path"]) for r in rows if r.get(k) in ("ABSENT", "MISSING")] for k in ("bound_commit_sha", "head_sha", "main_sha", "worktree_sha")}
json.dump(out, open(f"{W}/logs/compare.json", "w"), indent=2)
for k, v in out.items():
    if isinstance(v, dict) and "match" in v:
        print(f"{k:55s} match={v['match']:3d} mismatch={v['mismatch']:3d}")
        for m in v["mismatches"]:
            print("    ", m["repository"], m["path"], "\n        expected", m["expected"], "\n        actual  ", m["actual"])
print("active vs candidateB differing records:", len(diffAB))
for m in diffAB: print("   ", m)
print("active vs candidateA differing records:", len(diffAA))
print("candidateB vs candidateA differing records:", len(diffBA))
for m in diffBA: print("   ", m)
print("modes", out["modes"])
print("absent", out["absent"])
