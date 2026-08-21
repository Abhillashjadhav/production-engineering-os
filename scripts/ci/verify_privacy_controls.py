#!/usr/bin/env python3
"""Execute deletion, retention, and telemetry privacy checks for CI evidence."""

from __future__ import annotations

import argparse
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
from pmpe.privacy.retention import RetentionController
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


def _verify(candidate_sha: str, policy_path: Path) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("privacy verifier candidate SHA is malformed")
    privacy = _load_policy(policy_path)
    retention_days = int(privacy["retention_days"])
    telemetry_allowlist = tuple(str(item) for item in privacy["telemetry_allowlist"])
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

        retention_root = root / "retention"
        retention_root.mkdir()
        expired = retention_root / "expired.json"
        current = retention_root / "current.json"
        expired.write_text("{}")
        current.write_text("{}")
        old_time = (now - timedelta(days=retention_days + 1)).timestamp()
        current_time = now.timestamp()
        os.utime(expired, (old_time, old_time))
        os.utime(current, (current_time, current_time))
        retention = RetentionController(retention_days=retention_days).purge(
            retention_root, now=now
        )
        retention_test_passed = retention.deleted == ("expired.json",) and retention.retained == (
            "current.json",
        )

        event_log = EventLog(root / "telemetry")
        event_log.emit(
            "privacy_verification",
            run_id="synthetic-run",
            latency_ms=1,
            outcome="pass",
        )
        records = event_log.read_all()
        emitted_telemetry = tuple(
            sorted(set(records[0]) - {"ts", "type"}) if len(records) == 1 else ()
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
