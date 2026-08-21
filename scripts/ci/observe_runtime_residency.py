#!/usr/bin/env python3
"""Execute a storage probe and emit residency evidence without reading privacy policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest

_SHA = re.compile(r"^[0-9a-f]{40}$")


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _observe(
    *,
    candidate_sha: str,
    runtime_config_path: Path,
    storage_root: Path,
) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("residency observer candidate SHA is malformed")
    value = json.loads(runtime_config_path.read_text())
    if not isinstance(value, dict):
        raise ValueError("runtime residency configuration is malformed")
    if value.get("authority") != "runtime-storage-observer/v1":
        raise ValueError("runtime residency authority is not trusted")
    observed_residency = value.get("storage_region")
    environment_id = value.get("environment_id")
    if not isinstance(observed_residency, str) or not observed_residency.strip():
        raise ValueError("runtime storage region is unavailable")
    if not isinstance(environment_id, str) or not environment_id.strip():
        raise ValueError("runtime environment identity is unavailable")

    storage_root = storage_root.resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    probe = storage_root / f"residency-probe-{os.urandom(8).hex()}"
    payload = os.urandom(32)
    probe.write_bytes(payload)
    storage_probe_passed = probe.read_bytes() == payload
    probe.unlink()
    shell = {
        "authority": "runtime-storage-observer/v1",
        "candidate_sha": candidate_sha,
        "environment_id": environment_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "observed_residency": observed_residency,
        "observer_file_digest": _file_digest(Path(__file__)),
        "runtime_config_digest": _file_digest(runtime_config_path),
        "storage_probe_passed": storage_probe_passed,
        "storage_root_digest": canonical_digest(str(storage_root)),
    }
    return {**shell, "evidence_digest": canonical_digest(shell)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = _observe(
        candidate_sha=args.candidate_sha,
        runtime_config_path=args.runtime_config,
        storage_root=args.storage_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
