import hashlib, json, subprocess, sys
from pmpe.contracts.canonical import canonical_digest, strict_loads
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
def blob(repo, rev, path):
    return subprocess.run(["git", "-C", f"{W}/{repo}", "show", f"{rev}:{path}"], capture_output=True, check=True).stdout
targets = [
 ("active freeze-manifest.json @PMOS 0652843", "pmos", "0652843", "reviews/task-tracker-v1/freeze-manifest.json"),
 ("active freeze-manifest.json @PMOS cafe8b4", "pmos", "cafe8b4", "reviews/task-tracker-v1/freeze-manifest.json"),
 ("active freeze-manifest.json @PMOS 2acc3fa (main)", "pmos", "2acc3fa", "reviews/task-tracker-v1/freeze-manifest.json"),
 ("candidate (refreeze-candidate-20261009) @PMOS cafe8b4 [B]", "pmos", "cafe8b4", "reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json"),
 ("candidate (refreeze-candidate-20261009) @PMOS 0652843 [A]", "pmos", "0652843", "reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json"),
 ("PEOS stage-a copy @PEOS 4b1558f", "peos", "4b1558f", "docs/evidence/task-tracker-completion-20261009/stage-a/freeze-manifest.candidate.json"),
 ("PEOS refreeze-candidate copy @PEOS e8a929d", "peos", "e8a929d", "docs/evidence/task-tracker-completion-20261009/refreeze-candidate/freeze-manifest.candidate.json"),
 ("PEOS refreeze-candidate copy @PEOS 4b1558f", "peos", "4b1558f", "docs/evidence/task-tracker-completion-20261009/refreeze-candidate/freeze-manifest.candidate.json"),
]
res = []
for label, repo, rev, path in targets:
    raw = blob(repo, rev, path)
    v = strict_loads(raw, "application/json")
    v2 = json.loads(raw)
    res.append({"label": label, "repo": repo, "rev": rev, "path": path,
                "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "canonical_digest_strict_loads": canonical_digest(v),
                "canonical_digest_json_loads": canonical_digest(v2)})
claims = {
 "freeze-bundle.sha256 @PMOS 0652843": blob("pmos", "0652843", "reviews/task-tracker-v1/freeze-bundle.sha256").decode().strip(),
 "freeze-bundle.sha256 @PMOS cafe8b4": blob("pmos", "cafe8b4", "reviews/task-tracker-v1/freeze-bundle.sha256").decode().strip(),
 "candidate-freeze-digest.txt @PMOS cafe8b4": blob("pmos", "cafe8b4", "reviews/task-tracker-v1/refreeze-candidate-20261009/candidate-freeze-digest.txt").decode().strip(),
 "candidate-freeze-digest.txt @PMOS 0652843": blob("pmos", "0652843", "reviews/task-tracker-v1/refreeze-candidate-20261009/candidate-freeze-digest.txt").decode().strip(),
 "stage-a/candidate-digest.txt @PEOS 4b1558f": blob("peos", "4b1558f", "docs/evidence/task-tracker-completion-20261009/stage-a/candidate-digest.txt").decode().strip(),
 "refreeze-candidate/candidate-freeze-digest.txt @PEOS e8a929d": blob("peos", "e8a929d", "docs/evidence/task-tracker-completion-20261009/refreeze-candidate/candidate-freeze-digest.txt").decode().strip(),
}
# worktree copies
for label, p in [("worktree PMOS active", "/home/user/PM-agent-OS/reviews/task-tracker-v1/freeze-manifest.json"),
                 ("worktree PMOS candidate", "/home/user/PM-agent-OS/reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json"),
                 ("worktree PEOS stage-a copy", "/home/user/production-engineering-os/docs/evidence/task-tracker-completion-20261009/stage-a/freeze-manifest.candidate.json")]:
    raw = open(p, "rb").read()
    res.append({"label": label, "path": p, "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(), "canonical_digest_strict_loads": canonical_digest(strict_loads(raw, "application/json"))})
out = {"pmpe_file": __import__("pmpe").__file__, "results": res, "claimed": claims}
json.dump(out, open(f"{W}/logs/canonical-digests.json", "w"), indent=2)
for r in res: print(f"{r['label']:60s} raw={r['raw_sha256'][:23]}… canon={r['canonical_digest_strict_loads']}" + ("" if r.get('canonical_digest_json_loads', r['canonical_digest_strict_loads']) == r['canonical_digest_strict_loads'] else " JSONLOADS-DIFFERS"))
for k, v in claims.items(): print(f"CLAIM {k:60s} {v}")
