import hashlib, json, subprocess, sys
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
FILES = [
 ("pmos", "PM-agent-OS", ".claude/skills/decision-to-contract/SKILL.md", "0652843f02b5fbd5734331ffe5c00675a7b40b6b", "sha256:ad0978c8e3780f11ec40d06395653d2c45ce100449ca8c7edea56bac6593ee1f", 1),
 ("peos", "production-engineering-os", "src/pmpe/barebones.py", "e8a929df0feca124005dfc84f1b5bebdd207eab9", "sha256:9895b6cc792ab960a34761e9fda545d52be62772aa7a327dc8cf9da6768ac0b7", 2),
 ("peos", "production-engineering-os", "src/pmpe/cli/barebones_cmd.py", "e8a929df0feca124005dfc84f1b5bebdd207eab9", "sha256:09116350f8a69cd053688e4ac6c42ff8514b173d3c69c1af86cc1903f04739cb", 3),
 ("peos", "production-engineering-os", "src/pmpe/contracts/acceptance.py", "e8a929df0feca124005dfc84f1b5bebdd207eab9", "sha256:07204c0021fb2c5ea7e8ade41533979e5fbb259d0d65621fda1fe7247edc8e1c", 4),
 ("peos", "production-engineering-os", "src/pmpe/evals/real_behavior_drift_eval.py", "e8a929df0feca124005dfc84f1b5bebdd207eab9", "sha256:27c1d087abc02b6136fcebbe3552b7b4cc7c8522f276d2709c22f2b584fdc14c", 5),
]
def git(repo, *args, inp=None, text=True):
    return subprocess.run(["git", "-C", f"{W}/{repo}", *args], input=inp, capture_output=True, text=text, check=True).stdout
cache = {}
def blob_sha(repo, oid):
    if (repo, oid) not in cache:
        data = subprocess.run(["git", "-C", f"{W}/{repo}", "cat-file", "blob", oid], capture_output=True, check=True).stdout
        cache[(repo, oid)] = "sha256:" + hashlib.sha256(data).hexdigest()
    return cache[(repo, oid)]
out = []
for repo, rname, path, bound, frozen, n in FILES:
    # every commit reachable from the bound commit, newest first (topo order)
    commits = git(repo, "rev-list", "--topo-order", bound).split()
    # also all refs, to find frozen bytes on other branches
    allc = git(repo, "rev-list", "--topo-order", "--all").split()
    q = "".join(f"{c}:{path}\n" for c in allc)
    res = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)", inp=q).splitlines()
    oid_at = {}
    for c, line in zip(allc, res):
        parts = line.split()
        oid_at[c] = parts[0] if len(parts) == 2 and parts[1] == "blob" else None
    frozen_commits_in_bound = [c for c in commits if oid_at.get(c) and blob_sha(repo, oid_at[c]) == frozen]
    frozen_commits_any = [c for c in allc if oid_at.get(c) and blob_sha(repo, oid_at[c]) == frozen]
    frozen_oid = oid_at[frozen_commits_any[0]] if frozen_commits_any else None
    # last (most recent) ancestor-of-bound commit whose bytes equal frozen: first in topo order
    last = frozen_commits_in_bound[0] if frozen_commits_in_bound else None
    changed_after = []
    if last:
        log = git(repo, "log", "--format=%H%x09%ad%x09%an%x09%s", "--date=iso", f"{last}..{bound}", "--", path).splitlines()
        for l in log:
            h, d, a, s = l.split("\t", 3)
            # version after this commit
            changed_after.append({"commit": h, "date": d, "author": a, "subject": s,
                                  "sha256_after": blob_sha(repo, oid_at[h]) if oid_at.get(h) else "ABSENT"})
    # commits that introduced the frozen bytes (first appearance in bound history)
    intro = git(repo, "log", "--format=%H%x09%ad%x09%s", "--date=iso", bound, "--", path).splitlines()
    versions = []
    for l in intro:
        h, d, s = l.split("\t", 2)
        versions.append({"commit": h, "date": d, "subject": s, "sha256": blob_sha(repo, oid_at[h]) if oid_at.get(h) else "ABSENT",
                         "equals_frozen": bool(oid_at.get(h)) and blob_sha(repo, oid_at[h]) == frozen})
    # git diff and compare with patch
    patch_ok = None
    if last:
        d = subprocess.run(["git", "-C", f"{W}/{repo if repo=='peos' else 'pmos'}", "diff", f"{last}..{bound}", "--", path], capture_output=True, check=True).stdout
        open(f"{W}/logs/diff-{n}.recomputed.patch", "wb").write(d)
        pt = subprocess.run(["git", "-C", f"{W}/peos", "show", f"4b1558f:docs/evidence/task-tracker-completion-20261009/stage-a/w1/diff-{n}.patch"], capture_output=True, check=True).stdout
        patch_ok = {"recomputed_sha256": hashlib.sha256(d).hexdigest(), "evidence_patch_sha256": hashlib.sha256(pt).hexdigest(),
                    "byte_identical": d == pt, "recomputed_lines": d.count(b"\n"), "evidence_lines": pt.count(b"\n")}
    out.append({"n": n, "repository": rname, "path": path, "bound_commit": bound, "frozen_sha256": frozen,
                "frozen_blob_oid": frozen_oid,
                "bound_sha256": blob_sha(repo, oid_at[bound]),
                "last_commit_with_frozen_bytes_in_bound_ancestry": last,
                "last_commit_info": git(repo, "log", "-1", "--format=%H %ad %s", "--date=iso", last).strip() if last else None,
                "commits_with_frozen_bytes_any_ref_count": len(frozen_commits_any),
                "changed_after_frozen": changed_after, "history_in_bound_ancestry": versions, "patch_check": patch_ok})
json.dump(out, open(f"{W}/logs/drift-history.json", "w"), indent=2)
for o in out:
    print(f"== {o['n']} {o['repository']} {o['path']}")
    print("   frozen blob oid", o["frozen_blob_oid"], "| last frozen commit:", o["last_commit_info"])
    for c in o["changed_after_frozen"]:
        print("   changed by", c["commit"][:10], c["date"], c["subject"], "->", c["sha256_after"][:23])
    print("   patch:", o["patch_check"])
