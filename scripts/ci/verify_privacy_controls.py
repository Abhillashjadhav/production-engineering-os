#!/usr/bin/env python3
"""Execute deletion, retention, and telemetry privacy checks for CI evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.intake import FileQuarantineStore
from pmpe.telemetry.events import EventLog

_SHA = re.compile(r"^[0-9a-f]{40}$")


class _EphemeralCipher:
    key_version = "privacy-verifier-ephemeral/v1"

    def __init__(self) -> None:
        self._material = os.urandom(32)

    def _transform(self, payload: bytes) -> bytes:
        return bytes(
            value ^ self._material[index % len(self._material)]
            for index, value in enumerate(payload)
        )

    def encrypt(self, payload: bytes) -> bytes:
        return self._transform(payload)

    def decrypt(self, payload: bytes) -> bytes:
        return self._transform(payload)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("privacy"), dict):
        raise ValueError("privacy policy is malformed")
    return dict(value["privacy"])


def _inventory_telemetry_fields(root: Path) -> tuple[str, ...]:
    fields: set[str] = set()
    for path in sorted((root / "src" / "pmpe").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "emit"
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg is None:
                    raise ValueError(
                        f"telemetry emission uses unresolved field expansion: {path}:{node.lineno}"
                    )
                fields.add(keyword.arg)
    if not fields:
        raise ValueError("no product telemetry emissions were observed")
    return tuple(sorted(fields))


def _verify(candidate_sha: str, policy_path: Path) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("privacy verifier candidate SHA is malformed")
    privacy = _load_policy(policy_path)
    retention_days = int(privacy["retention_days"])
    telemetry_allowlist = tuple(str(item) for item in privacy["telemetry_allowlist"])
    repository_root = policy_path.resolve().parents[1]
    emitted_telemetry = _inventory_telemetry_fields(repository_root)
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="pmpe-privacy-verifier-") as temporary:
        root = Path(temporary)
        quarantine = FileQuarantineStore(
            root / "quarantine",
            cipher=_EphemeralCipher(),
            max_bytes=1024,
        )
        handle = "PRIVACY-VERIFICATION-OBJECT"
        payload = b"synthetic-non-production-data"
        quarantine.put(handle, payload, {"content_type": "application/octet-stream"})
        deletion_test_passed = (
            quarantine.exists(handle)
            and quarantine.read(handle) == payload
            and quarantine.delete(handle)
            and not quarantine.exists(handle)
        )

        runs_root = root / "runs"
        expired = runs_root / "expired-run" / "events.jsonl"
        current_run = runs_root / "current-run"
        expired.parent.mkdir(parents=True)
        expired.write_text("{}")
        old_time = (now - timedelta(days=retention_days + 1)).timestamp()
        os.utime(expired, (old_time, old_time))
        event_log = EventLog(
            current_run,
            retention_days=retention_days,
            trusted_clock=lambda: now,
        )
        event_log.emit("privacy_verification", **dict.fromkeys(emitted_telemetry, "synthetic"))
        retention_test_passed = (
            not expired.exists() and event_log.path.exists() and len(event_log.read_all()) == 1
        )
        telemetry_test_passed = set(emitted_telemetry) <= set(telemetry_allowlist)

    shell = {
        "candidate_sha": candidate_sha,
        "classification": str(privacy["classification"]),
        "deletion_test_passed": deletion_test_passed,
        "emitted_telemetry": list(emitted_telemetry),
        "policy_file_digest": _file_digest(policy_path),
        "residency": str(privacy["residency"]),
        "retention_days": retention_days,
        "retention_test_passed": retention_test_passed,
        "telemetry_test_passed": telemetry_test_passed,
        "verifier_file_digest": _file_digest(Path(__file__)),
    }
    if not deletion_test_passed or not retention_test_passed or not telemetry_test_passed:
        raise ValueError("privacy control verification failed")
    return {**shell, "evidence_digest": canonical_digest(shell)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = _verify(args.candidate_sha, args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
