#!/usr/bin/env python3
"""Execute a storage probe and emit residency evidence without reading privacy policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest

_SHA = re.compile(r"^[0-9a-f]{40}$")
_S3_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_MUMBAI_REGION = "ap-south-1"
_AWS_REGION_RESIDENCY = {_MUMBAI_REGION: "IN"}

AwsCommand = Callable[[tuple[str, ...]], str]


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _run_aws(command: tuple[str, ...]) -> str:
    environment = dict(os.environ)
    environment["AWS_PAGER"] = ""
    completed = subprocess.run(  # noqa: S603 - exact argv, never a shell command
        ("aws", *command),
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return completed.stdout.strip()


def _required_string(value: dict[str, Any], key: str) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError(f"runtime residency {key} is unavailable")
    return candidate.strip()


def _provider_identity(aws_command: AwsCommand) -> tuple[str, str]:
    raw = aws_command(("sts", "get-caller-identity", "--output", "json"))
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("AWS OIDC identity metadata is malformed")
    account = value.get("Account")
    arn = value.get("Arn")
    if not isinstance(account, str) or not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("AWS OIDC account identity is malformed")
    if not isinstance(arn, str) or not arn.startswith("arn:aws:sts::"):
        raise ValueError("AWS OIDC role identity is malformed")
    return account, arn


def _bucket_region(bucket: str, account: str, aws_command: AwsCommand) -> str:
    raw = aws_command(
        (
            "s3api",
            "get-bucket-location",
            "--bucket",
            bucket,
            "--expected-bucket-owner",
            account,
            "--query",
            "LocationConstraint",
            "--output",
            "text",
        )
    ).strip()
    return "us-east-1" if raw in {"", "None", "null"} else raw


def _observe(
    *,
    candidate_sha: str,
    runtime_config_path: Path,
    bucket: str,
    aws_command: AwsCommand = _run_aws,
) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("residency observer candidate SHA is malformed")
    if not _S3_BUCKET.fullmatch(bucket):
        raise ValueError("AWS residency bucket name is malformed")
    value = json.loads(runtime_config_path.read_text())
    if not isinstance(value, dict):
        raise ValueError("runtime residency configuration is malformed")
    if value.get("authority") != "aws-s3-runtime-storage-observer/v1":
        raise ValueError("runtime residency authority is not trusted")
    if value.get("provider") != "aws" or value.get("service") != "s3":
        raise ValueError("runtime residency provider is not the approved AWS S3 backend")
    environment_id = _required_string(value, "environment_id")
    expected_region = _required_string(value, "expected_provider_region")
    if expected_region != _MUMBAI_REGION:
        raise ValueError("runtime residency configuration is not pinned to AWS Mumbai")

    account, role_arn = _provider_identity(aws_command)
    observed_region = _bucket_region(bucket, account, aws_command)
    if observed_region != expected_region or observed_region not in _AWS_REGION_RESIDENCY:
        raise ValueError(
            "authenticated AWS bucket region does not match the approved Mumbai region"
        )

    endpoint = {"provider": "aws", "service": "s3", "bucket": bucket}
    endpoint_digest = canonical_digest(endpoint)
    key = f"residency-probes/{candidate_sha}/{os.urandom(16).hex()}"
    payload = os.urandom(32)
    put_completed = False
    with tempfile.TemporaryDirectory(prefix="pmpe-aws-residency-") as temporary:
        upload = Path(temporary) / "probe-upload.bin"
        download = Path(temporary) / "probe-download.bin"
        upload.write_bytes(payload)
        try:
            aws_command(
                (
                    "s3api",
                    "put-object",
                    "--bucket",
                    bucket,
                    "--key",
                    key,
                    "--body",
                    str(upload),
                    "--expected-bucket-owner",
                    account,
                    "--output",
                    "json",
                )
            )
            put_completed = True
            aws_command(
                (
                    "s3api",
                    "get-object",
                    "--bucket",
                    bucket,
                    "--key",
                    key,
                    "--expected-bucket-owner",
                    account,
                    "--output",
                    "json",
                    str(download),
                )
            )
            if download.read_bytes() != payload:
                raise ValueError("AWS S3 storage probe readback failed")
        finally:
            if put_completed:
                aws_command(
                    (
                        "s3api",
                        "delete-object",
                        "--bucket",
                        bucket,
                        "--key",
                        key,
                        "--expected-bucket-owner",
                        account,
                        "--output",
                        "json",
                    )
                )

    identity_digest = canonical_digest({"account": account, "role_arn": role_arn})
    metadata_digest = canonical_digest(
        {
            "account": account,
            "bucket_endpoint_digest": endpoint_digest,
            "provider_region": observed_region,
        }
    )
    shell = {
        "authority": "aws-s3-runtime-storage-observer/v1",
        "authenticated_metadata_digest": metadata_digest,
        "candidate_sha": candidate_sha,
        "environment_id": environment_id,
        "observed_at": datetime.now(UTC).isoformat(),
        "observed_provider_region": observed_region,
        "observed_residency": _AWS_REGION_RESIDENCY[observed_region],
        "observer_file_digest": _file_digest(Path(__file__)),
        "provider": "aws",
        "provider_identity_digest": identity_digest,
        "probe_object_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "runtime_config_digest": _file_digest(runtime_config_path),
        "storage_endpoint_digest": endpoint_digest,
        "storage_probe_passed": True,
        "storage_service": "s3",
    }
    return {**shell, "evidence_digest": canonical_digest(shell)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = _observe(
        candidate_sha=args.candidate_sha,
        runtime_config_path=args.runtime_config,
        bucket=args.bucket,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
