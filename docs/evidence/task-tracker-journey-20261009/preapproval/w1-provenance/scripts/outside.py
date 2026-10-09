import hashlib, json, os, subprocess
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
FILES = ["examples/barebones/contract-file.py", "examples/barebones/task-tracker-regression.py",
         "examples/barebones/session-file-provider.py", "docs/evidence/task-tracker-live-20260918/clean-install/journey.py",
         "examples/barebones/contract-file.md", "docs/evidence/task-tracker-live-20260918/REPRODUCE.md"]
REVS = {"bound_e8a929d": "e8a929df0feca124005dfc84f1b5bebdd207eab9", "head_4b1558f": "4b1558fd5bedd04e7beacb28ffb9f41ddaa7b577",
        "main_1a431b2": "1a431b23f837b04237c99ab7b924a234def10171", "frozen_era_f7669c2": "f7669c2cd1bb9600b0fe7bd26e621b95a3402fb1"}
active = json.load(open(f"{W}/files/active.freeze-manifest.json"))
cand = json.load(open(f"{W}/files/candidateB.pmos-cafe8b4.json"))
ainv = {(a["repository"], a["path"]): a["sha256"] for a in active["artifacts"]}
cinv = {(a["repository"], a["path"]): a["sha256"] for a in cand["artifacts"]}
rows = []
for f in FILES:
    row = {"repository": "production-engineering-os", "path": f}
    for k, r in REVS.items():
        p = subprocess.run(["git", "-C", f"{W}/peos", "ls-tree", r, "--", f], capture_output=True, text=True, check=True).stdout.strip()
        if not p:
            row[k] = "ABSENT"; continue
        oid = p.split()[2]
        data = subprocess.run(["git", "-C", f"{W}/peos", "cat-file", "blob", oid], capture_output=True, check=True).stdout
        row[k] = "sha256:" + hashlib.sha256(data).hexdigest()
    real = f"/home/user/production-engineering-os/{f}"
    row["worktree"] = ("sha256:" + hashlib.sha256(open(real, "rb").read()).hexdigest()) if os.path.isfile(real) else "MISSING"
    row["in_active_inventory"] = ("production-engineering-os", f) in ainv
    row["in_candidate_inventory"] = ("production-engineering-os", f) in cinv
    row["active_inventory_sha"] = ainv.get(("production-engineering-os", f))
    rows.append(row)
# any examples/ or docs/ entries in inventory at all?
row_ex = sorted(p for (r, p) in ainv if r == "production-engineering-os" and not p.startswith("src/"))
out = {"files": rows, "non_src_PEOS_entries_in_inventory": row_ex}
json.dump(out, open(f"{W}/hashes-outside-inventory.json", "w"), indent=2)
for r in rows:
    print(r["path"], "| in active:", r["in_active_inventory"], "| in candidate:", r["in_candidate_inventory"])
    for k in list(REVS) + ["worktree"]:
        print(f"    {k:20s} {r[k]}")
print("non-src PEOS entries in inventory:", row_ex)
