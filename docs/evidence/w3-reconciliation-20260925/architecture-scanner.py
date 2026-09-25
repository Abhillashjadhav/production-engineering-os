"""Run the unchanged text-only architecture scanner with the reviewed policy on a checkout.

Usage (from the checkout root, source-only interpreter):
    PYTHONPATH=src:. python -B docs/evidence/w3-reconciliation-20260925/architecture-scanner.py

Prints the JSON recorded in architecture-scanner.json; exits 1 if any edge is unapproved.
This is the scanner's edge check only, not the composed CI security job.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.ci.evaluate_security_profile import (
    _observed_architecture_edges,
    _reviewed_policy_config,
)

BASE = "ccabeecc7346dffa7354e88c1deec53b1674428a"
PROTECTED = (
    "scripts/ci/evaluate_security_profile.py",
    "security/security-profile-policy.json",
    "security/secret-allowlist.json",
)

root = Path.cwd()
config = _reviewed_policy_config(
    json.loads((root / "security/security-profile-policy.json").read_bytes())
)
allowlist = tuple(
    (str(i["path"]), int(i["line"]), str(i["line_fingerprint"]), str(i["file_digest"]))
    for i in config["dynamic_import_allowlist"]
)
observed = _observed_architecture_edges(root, dynamic_import_allowlist=allowlist)
unapproved = sorted(set(observed) - set(map(tuple, config["allowed_architecture_edges"])))
files = {}
for name in PROTECTED:
    current = (root / name).read_bytes()
    files[name] = {
        "sha256": hashlib.sha256(current).hexdigest(),
        "same_as_ccabeecc": current == subprocess.check_output(["git", "show", f"{BASE}:{name}"]),
    }
head = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
print(
    json.dumps(
        {
            "head": head,
            "scope": "unchanged text-only architecture scanner with the reviewed policy; "
            "not the composed CI job",
            "unapproved_edges": unapproved,
            "protected_files": files,
        },
        indent=2,
    )
)
sys.exit(1 if unapproved else 0)
