import json
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
act = json.load(open(f"{W}/files/active.freeze-manifest.json"))
B = json.load(open(f"{W}/files/candidateB.pmos-cafe8b4.json"))
A = json.load(open(f"{W}/files/candidateA.pmos-0652843.json"))
EXPECTED_MAY_DIFFER = {"status", "owner_approval_quote", "recorded_at", "approval_context", "refreeze_basis"}
def diff(old, new, old_label, new_label):
    keys_old, keys_new = set(old), set(new)
    top_diff = {}
    for k in sorted(keys_old & keys_new):
        if k == "artifacts":
            continue
        if old[k] != new[k]:
            top_diff[k] = {old_label: old[k], new_label: new[k]}
    only_old = {k: old[k] for k in sorted(keys_old - keys_new)}
    only_new = {k: new[k] for k in sorted(keys_new - keys_old)}
    rec = []
    oa, na = old["artifacts"], new["artifacts"]
    for i, (x, y) in enumerate(zip(oa, na)):
        if x != y:
            rec.append({"index": i, old_label: x, new_label: y,
                        "fields_differing": sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))})
    if len(oa) != len(na):
        rec.append({"length_mismatch": [len(oa), len(na)]})
    identical = sorted(k for k in keys_old & keys_new if k != "artifacts" and old[k] == new[k])
    # protected-field check: anything differing beyond sha256 of artifact records and the expected-to-differ metadata
    unexpected_top = sorted(k for k in list(top_diff) + list(only_old) + list(only_new) if k not in EXPECTED_MAY_DIFFER)
    unexpected_rec = [r for r in rec if r.get("fields_differing") not in (["sha256"],)]
    return {"compare": f"{old_label} -> {new_label}", "top_level_differing": top_diff,
            "keys_only_in_" + old_label: only_old, "keys_only_in_" + new_label: only_new,
            "artifact_records_differing": rec, "artifact_records_differing_count": len([r for r in rec if 'index' in r]),
            "identical_top_level_fields": identical,
            "unexpected_protected_top_level_differences": unexpected_top,
            "unexpected_artifact_field_differences": unexpected_rec}
out = {
  "sources": {"active": "PMOS 0652843 (identical bytes at cafe8b4 and 2acc3fa) reviews/task-tracker-v1/freeze-manifest.json",
              "candidate": "PMOS cafe8b4 reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json (byte-identical to PEOS 4b1558f docs/evidence/task-tracker-completion-20261009/stage-a/freeze-manifest.candidate.json)",
              "candidateA": "PMOS 0652843 reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json (byte-identical to PEOS e8a929d/4b1558f docs/evidence/task-tracker-completion-20261009/refreeze-candidate/freeze-manifest.candidate.json)"},
  "expected_may_differ": sorted(EXPECTED_MAY_DIFFER),
  "active_vs_candidate": diff(act, B, "active", "candidate"),
  "active_vs_candidateA": diff(act, A, "active", "candidateA"),
  "candidateA_vs_candidate": diff(A, B, "candidateA", "candidate"),
}
json.dump(out, open(f"{W}/manifest-diff.json", "w"), indent=2, ensure_ascii=False)
for k in ("active_vs_candidate", "active_vs_candidateA", "candidateA_vs_candidate"):
    d = out[k]
    print("=====", d["compare"])
    for kk, vv in d["top_level_differing"].items():
        print("  DIFF", kk); [print("     ", lab, json.dumps(val, ensure_ascii=False)[:2000]) for lab, val in vv.items()]
    for kk in [x for x in d if x.startswith("keys_only_in_")]:
        print("  ", kk, json.dumps(d[kk], ensure_ascii=False)[:3000])
    print("  artifact records differing:", d["artifact_records_differing_count"], [ (r.get('index'), r.get('fields_differing')) for r in d["artifact_records_differing"]])
    print("  identical top-level:", d["identical_top_level_fields"])
    print("  UNEXPECTED protected top-level diffs:", d["unexpected_protected_top_level_differences"])
    print("  UNEXPECTED artifact field diffs:", d["unexpected_artifact_field_differences"])
