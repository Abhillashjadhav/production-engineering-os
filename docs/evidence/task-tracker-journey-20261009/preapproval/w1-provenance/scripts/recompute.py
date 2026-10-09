#!/usr/bin/env python3
"""W1 recompute: raw SHA-256 of every bound artifact from git object bytes and worktree bytes.

Read-only with respect to /home/user/*: uses only isolated clones for git reads and
plain file reads (open(..., 'rb')) for the real working trees.
"""
import hashlib, json, os, subprocess, sys
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
CLONE = {"production-engineering-os": f"{W}/peos", "PM-agent-OS": f"{W}/pmos"}
REAL = {"production-engineering-os": "/home/user/production-engineering-os", "PM-agent-OS": "/home/user/PM-agent-OS"}
COMMITS = {
    "bound": {"production-engineering-os": "e8a929df0feca124005dfc84f1b5bebdd207eab9", "PM-agent-OS": "0652843f02b5fbd5734331ffe5c00675a7b40b6b"},
    "head": {"production-engineering-os": "4b1558fd5bedd04e7beacb28ffb9f41ddaa7b577", "PM-agent-OS": "cafe8b4011d35653cc343175e0acd43d0b65e416"},
    "main": {"production-engineering-os": "1a431b23f837b04237c99ab7b924a234def10171", "PM-agent-OS": "2acc3fa0c81f1237f8ab7b5681b478630c530931"},
}

def git_blob(repo, rev, path):
    """Return (sha256:hex | 'ABSENT', mode) from the git object bytes at rev:path."""
    ls = subprocess.run(["git", "-C", CLONE[repo], "ls-tree", rev, "--", path], capture_output=True, text=True, check=True).stdout.strip()
    if not ls:
        return "ABSENT", None
    meta, _ = ls.split("\t", 1)
    mode, typ, obj = meta.split()
    if typ != "blob":
        return f"NOT_A_BLOB({typ})", mode
    data = subprocess.run(["git", "-C", CLONE[repo], "cat-file", "blob", obj], capture_output=True, check=True).stdout
    return "sha256:" + hashlib.sha256(data).hexdigest(), mode

def worktree(repo, path):
    full = os.path.join(REAL[repo], path)
    if os.path.islink(full):
        return "SYMLINK"
    try:
        with open(full, "rb") as fh:
            return "sha256:" + hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return "MISSING"
    except OSError as e:
        return "UNREADABLE:" + type(e).__name__

def main():
    active = json.load(open(f"{W}/files/active.freeze-manifest.json"))
    candB = json.load(open(f"{W}/files/candidateB.pmos-cafe8b4.json"))
    candA = json.load(open(f"{W}/files/candidateA.pmos-0652843.json"))
    pa = [(a["repository"], a["path"]) for a in active["artifacts"]]
    pb = [(a["repository"], a["path"]) for a in candB["artifacts"]]
    pA = [(a["repository"], a["path"]) for a in candA["artifacts"]]
    inv = {
        "active_count": len(pa), "candidateB_count": len(pb), "candidateA_count": len(pA),
        "active_unique_pairs": len(set(pa)), "candidateB_unique_pairs": len(set(pb)),
        "same_pairs_same_order_active_vs_candidateB": pa == pb,
        "same_pairs_same_order_active_vs_candidateA": pa == pA,
        "only_in_active_vs_candidateB": sorted(set(pa) - set(pb)),
        "only_in_candidateB_vs_active": sorted(set(pb) - set(pa)),
        "only_in_active_vs_candidateA": sorted(set(pa) - set(pA)),
        "only_in_candidateA_vs_active": sorted(set(pA) - set(pa)),
        "by_repository_active": {r: sum(1 for x, _ in pa if x == r) for r in sorted({x for x, _ in pa})},
        "first_order_difference_index_vs_B": next((i for i, (x, y) in enumerate(zip(pa, pb)) if x != y), None),
    }
    cb = {(a["repository"], a["path"]): a["sha256"] for a in candB["artifacts"]}
    cA = {(a["repository"], a["path"]): a["sha256"] for a in candA["artifacts"]}
    rows = []
    for a in active["artifacts"]:
        repo, path = a["repository"], a["path"]
        row = {"repository": repo, "path": path, "active_sha": a["sha256"],
               "candidate_sha": cb.get((repo, path), "NOT_IN_CANDIDATE"),
               "candidateA_sha_pmos_0652843": cA.get((repo, path), "NOT_IN_CANDIDATE_A")}
        for label, key in (("bound", "bound_commit_sha"), ("head", "head_sha"), ("main", "main_sha")):
            sha, mode = git_blob(repo, COMMITS[label][repo], path)
            row[key] = sha
            row[key.replace("_sha", "_mode")] = mode
        row["worktree_sha"] = worktree(repo, path)
        rows.append(row)
    # also any path present only in candidate (none expected) gets a row
    for (repo, path), sha in cb.items():
        if (repo, path) not in {(r["repository"], r["path"]) for r in rows}:
            rows.append({"repository": repo, "path": path, "active_sha": "NOT_IN_ACTIVE", "candidate_sha": sha})
    json.dump({"commits": COMMITS, "inventory": inv, "rows": rows}, open(f"{W}/recompute.full.json", "w"), indent=2)
    # compact deliverable
    keep = ["repository", "path", "active_sha", "candidate_sha", "bound_commit_sha", "head_sha", "main_sha", "worktree_sha"]
    json.dump([{k: r.get(k) for k in keep} for r in rows], open(f"{W}/recompute.json", "w"), indent=2)
    print(json.dumps(inv, indent=1))

if __name__ == "__main__":
    main()
