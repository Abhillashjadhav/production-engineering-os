import hashlib, json, subprocess, sys
W = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1"
repo_dir = {"production-engineering-os": "peos", "PM-agent-OS": "pmos"}
man = json.load(open(sys.argv[1]))
rev = {"production-engineering-os": sys.argv[2], "PM-agent-OS": sys.argv[3]}
res = {"match": 0, "mismatch": []}
for a in man["artifacts"]:
    r = a["repository"]
    if rev[r] == "-":
        continue
    p = subprocess.run(["git", "-C", f"{W}/{repo_dir[r]}", "cat-file", "blob", f"{rev[r]}:{a['path']}"], capture_output=True)
    sha = "sha256:" + hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 else "ABSENT"
    if sha == a["sha256"]:
        res["match"] += 1
    else:
        res["mismatch"].append((r, a["path"], a["sha256"][:23], sha[:23]))
print(sys.argv[2:], "match", res["match"], "mismatch", len(res["mismatch"]))
for m in res["mismatch"]: print("   ", m)
