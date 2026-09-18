"""Re-run the production sandbox command with the owner's network-only amendment.

The mock only captures command construction. The amended command is then actually
executed by subprocess.run. This is a diagnostic, not a second sandbox or a
product build. Production defaults are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from pmpe.barebones import BubblewrapCandidateSandbox

ROOT = Path(__file__).resolve().parents[3]
NAMESPACES = ("user", "pid", "mnt", "ipc", "uts", "cgroup", "net")


def main() -> None:
    captured = []

    def capture(argv, **kwargs):
        captured.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, 0)

    probe = """
import json,os,resource
from pathlib import Path
def writable(path):
    try:
        fd=os.open(path,os.O_WRONLY)
    except OSError as error:
        return {'opened_for_write':False,'errno':error.errno}
    else:
        os.close(fd)
        return {'opened_for_write':True}
print(json.dumps({
    'namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in
        ('user','pid','mnt','ipc','uts','cgroup','net')},
    'limits':{n:resource.getrlimit(getattr(resource,n)) for n in
        ('RLIMIT_AS','RLIMIT_CPU','RLIMIT_FSIZE','RLIMIT_NOFILE','RLIMIT_NPROC')},
    'candidate_mount':writable('/workspace/marker.txt'),
    'runtime_mount':writable('/usr/bin/true'),
    'mountinfo':Path('/proc/self/mountinfo').read_text(),
    'environment':dict(os.environ),
}))
"""
    with tempfile.TemporaryDirectory(prefix="pmpe-network-amendment-") as temporary:
        workspace = Path(temporary)
        (workspace / "marker.txt").write_text("diagnostic only\n")
        with patch("pmpe.barebones.subprocess.run", capture):
            BubblewrapCandidateSandbox().run(
                workspace, [sys.executable, "-I", "-B", "-c", probe],
                timeout_seconds=5, environment={"PATH": "/usr/bin:/bin"},
            )
        original, _ = captured[0]
        position = original.index("--unshare-all")
        # Explicit strict flags retain every requested namespace except network.
        replacement = [
            "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--unshare-cgroup",
        ]
        if sys.argv[1:] == ["--exact-share-net"]:
            # Bubblewrap advertises this as the network-only override. Retain
            # --unshare-all itself, including its supported-namespace policy.
            replacement = ["--unshare-all", "--share-net"]
        amended = original[:position] + replacement + original[position + 1:]
        assert amended[:position] == original[:position]
        assert amended[position + len(replacement):] == original[position + 1:]
        started = time.monotonic()
        completed = subprocess.run(
            amended, cwd=workspace, capture_output=True, text=True, check=False,
            timeout=5, env={"LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        result = {
            "owner_authorized_change": "remove network unsharing only",
            "namespace_selection": replacement,
            "production_command": original,
            "executed_command": amended,
            "other_command_arguments_unchanged": True,
            "network_namespace_shared_with_host": True,
            "mount_namespace": "created by Bubblewrap's mount setup",
            "host_namespaces": {n: os.readlink('/proc/self/ns/' + n) for n in NAMESPACES},
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "production_sandbox_source_digest": "sha256:" + hashlib.sha256(
                (ROOT / "src/pmpe/barebones.py").read_bytes()
            ).hexdigest(),
            "production_defaults_modified": False,
            "product_generated": False,
        }
        if completed.returncode == 0:
            observations = json.loads(completed.stdout)
            result["observations"] = observations
            result["namespace_changes"] = {
                n: observations["namespaces"][n] != result["host_namespaces"][n]
                for n in NAMESPACES
            }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
