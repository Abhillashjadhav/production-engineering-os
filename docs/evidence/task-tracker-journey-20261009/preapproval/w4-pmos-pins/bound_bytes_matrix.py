"""For each PEOS commit, count how many PEOS-bound freeze entries match git blob bytes.

Usage: python bound_bytes_matrix.py <peos-repo> <manifest.json> [<manifest.json> ...] -- <commit> [<commit> ...]
Reads blobs with one `git cat-file --batch` process per commit. Writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys

argv = sys.argv[1:]
repo = argv[0]
split = argv.index("--")
manifests = argv[1:split]
commits = argv[split + 1 :]


def blob_digests(commit: str, paths: list[str]) -> dict[str, str]:
    proc = subprocess.Popen(
        ["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert proc.stdin and proc.stdout
    out: dict[str, str] = {}
    for path in paths:
        proc.stdin.write(f"{commit}:{path}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().decode().rstrip("\n")
        if header.endswith(" missing") or header.endswith("ambiguous"):
            out[path] = "MISSING"
            continue
        size = int(header.split()[2])
        data = proc.stdout.read(size)
        proc.stdout.read(1)
        out[path] = "sha256:" + hashlib.sha256(data).hexdigest()
    proc.stdin.close()
    proc.wait()
    return out


result = {}
for manifest_path in manifests:
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    entries = [e for e in manifest["artifacts"] if e["repository"] == "production-engineering-os"]
    paths = [e["path"] for e in entries]
    per_commit = {}
    for commit in commits:
        digests = blob_digests(commit, paths)
        mismatched = [e["path"] for e in entries if digests[e["path"]] != e["sha256"]]
        missing = [p for p in paths if digests[p] == "MISSING"]
        per_commit[commit[:9]] = {
            "bound": len(entries),
            "match": len(entries) - len(mismatched),
            "mismatch": len(mismatched) - len(missing),
            "missing": len(missing),
            "mismatched_paths": mismatched[:12],
        }
    result[manifest_path.rsplit("/", 1)[-1] + f" (status={manifest.get('status')})"] = per_commit
print(json.dumps(result, indent=1))
