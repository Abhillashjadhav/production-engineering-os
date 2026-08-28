#!/usr/bin/env python3
"""Admit only a protected or exact-manifest security verifier runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess  # nosec B404 - fixed git argv authenticates local checkouts
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DECLARED_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9._,-]+\])?==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)\Z"
)
_LOCKED_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"==(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)\s*\\?\Z"
)
_SCHEMA = "trusted-security-bootstrap/v1"
_BOOTSTRAP_PR = 133
_ENTRYPOINTS = (
    "scripts/ci/evaluate_security_profile.py",
    "scripts/ci/verify_privacy_controls.py",
    "scripts/ci/verify_repository_secrets.py",
)
_PROTECTED_RUNTIME = (*_ENTRYPOINTS, "src/pmpe/quality/security_profiles.py")
_TOOLCHAIN_FILES = ("pyproject.toml", "requirements.lock")
_SOURCE_ROOT = "src"
_MANIFEST_FIELDS = {
    "approved_by",
    "approved_candidate_sha",
    "approved_pr_number",
    "expires_at",
    "files",
    "justification",
    "manifest_digest",
    "schema_version",
}


class BootstrapVerificationError(RuntimeError):
    """The security runner has no independently authenticated execution root."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    try:
        return subprocess.run(  # nosec B603 - fixed git argv; no shell
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BootstrapVerificationError("repository identity cannot be authenticated") from exc


def _verify_repository(root: Path, expected_sha: str, *, label: str) -> Path:
    if not _SHA.fullmatch(expected_sha):
        raise BootstrapVerificationError(f"{label} SHA is malformed")
    resolved = root.resolve()
    if (
        not root.is_dir()
        or Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != resolved
        or _git(root, "rev-parse", "HEAD") != expected_sha
        or _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    ):
        raise BootstrapVerificationError(f"{label} checkout is not the clean exact commit")
    return resolved


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise BootstrapVerificationError("bootstrap manifest expiration is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BootstrapVerificationError("bootstrap manifest expiration is malformed") from exc
    if parsed.tzinfo is None:
        raise BootstrapVerificationError("bootstrap manifest expiration is not timezone-aware")
    return parsed


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise BootstrapVerificationError("bootstrap manifest path is malformed")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise BootstrapVerificationError("bootstrap manifest path escapes its execution root")
    return path.as_posix()


def _manifest_files(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise BootstrapVerificationError("bootstrap manifest has no file inventory")
    files: dict[str, str] = {}
    for raw_path, raw_digest in value.items():
        path = _safe_relative_path(raw_path)
        if not isinstance(raw_digest, str) or not _DIGEST.fullmatch(raw_digest):
            raise BootstrapVerificationError("bootstrap manifest file digest is malformed")
        if path in files:
            raise BootstrapVerificationError("bootstrap manifest path is duplicated")
        files[path] = raw_digest
    return files


def _load_manifest(
    path: Path,
    *,
    candidate_sha: str,
    pr_number: int,
    now: datetime,
) -> tuple[dict[str, str], str]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapVerificationError("protected bootstrap manifest is unavailable") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_FIELDS:
        raise BootstrapVerificationError("bootstrap manifest has an unexpected shape")
    claimed_digest = value.get("manifest_digest")
    unsigned = dict(value)
    unsigned.pop("manifest_digest", None)
    if (
        not isinstance(claimed_digest, str)
        or not _DIGEST.fullmatch(claimed_digest)
        or _digest_bytes(_canonical_bytes(unsigned)) != claimed_digest
    ):
        raise BootstrapVerificationError("bootstrap manifest digest is invalid")
    if (
        value.get("schema_version") != _SCHEMA
        or value.get("approved_pr_number") != _BOOTSTRAP_PR
        or value.get("approved_candidate_sha") != candidate_sha
        or pr_number != _BOOTSTRAP_PR
    ):
        raise BootstrapVerificationError("bootstrap manifest is not authorized for this PR")
    if any(
        not isinstance(value.get(field), str) or not str(value[field]).strip()
        for field in ("approved_by", "justification")
    ):
        raise BootstrapVerificationError("bootstrap manifest lacks reviewed ownership")
    if _timestamp(value.get("expires_at")) <= now:
        raise BootstrapVerificationError("bootstrap manifest approval has expired")
    return _manifest_files(value.get("files")), claimed_digest


def _execution_inventory(root: Path) -> dict[str, str]:
    paths: list[Path] = [root / item for item in (*_ENTRYPOINTS, *_TOOLCHAIN_FILES)]
    source = root / _SOURCE_ROOT
    if not source.is_dir() or source.is_symlink():
        raise BootstrapVerificationError("bootstrap source root is missing or symlinked")
    paths.extend(sorted(source.rglob("*")))
    inventory: dict[str, str] = {}
    for path in paths:
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise BootstrapVerificationError("bootstrap execution inventory is not regular")
        relative = path.relative_to(root).as_posix()
        inventory[relative] = _digest_bytes(path.read_bytes())
    return inventory


def _verify_bootstrap_files(root: Path, expected: Mapping[str, str]) -> int:
    actual = _execution_inventory(root)
    if set(actual) != set(expected) or any(actual[path] != expected[path] for path in actual):
        raise BootstrapVerificationError("candidate execution inventory differs from manifest")
    return len(actual)


def _report_digest(value: Mapping[str, Any]) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _normalized_requirement(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise BootstrapVerificationError("project dependency declaration is malformed")
    match = _DECLARED_REQUIREMENT.fullmatch(value)
    if match is None:
        raise BootstrapVerificationError("project dependencies must use exact version pins")
    name = re.sub(r"[-_.]+", "-", match.group("name")).lower()
    return name, match.group("version")


def _declared_dependencies(payload: Mapping[str, Any]) -> set[tuple[str, str]]:
    build = payload.get("build-system")
    project = payload.get("project")
    if not isinstance(build, Mapping) or not isinstance(project, Mapping):
        raise BootstrapVerificationError("candidate dependency metadata is malformed")
    groups: list[object] = [build.get("requires"), project.get("dependencies")]
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, Mapping):
        raise BootstrapVerificationError("candidate optional dependencies are malformed")
    groups.extend(optional.values())
    declared: set[tuple[str, str]] = set()
    for group in groups:
        if not isinstance(group, list) or not group:
            raise BootstrapVerificationError("candidate dependency group is malformed")
        declared.update(_normalized_requirement(item) for item in group)
    return declared


def _locked_dependencies(payload: str) -> set[tuple[str, str]]:
    locked: set[tuple[str, str]] = set()
    current: tuple[str, str] | None = None
    hashed = False

    def finish() -> None:
        nonlocal current, hashed
        if current is not None:
            if not hashed:
                raise BootstrapVerificationError("requirements lock contains an unhashed entry")
            locked.add(current)
        current = None
        hashed = False

    for line in payload.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            finish()
            match = _LOCKED_REQUIREMENT.fullmatch(line)
            if match is None:
                raise BootstrapVerificationError("requirements lock entry is malformed")
            current = (
                re.sub(r"[-_.]+", "-", match.group("name")).lower(),
                match.group("version"),
            )
        elif current is not None and "--hash=sha256:" in line:
            hashed = True
    finish()
    if not locked:
        raise BootstrapVerificationError("requirements lock has no authenticated entries")
    return locked


def verify_locked_dependency_coverage(
    *,
    candidate_root: Path,
    candidate_sha: str,
) -> dict[str, Any]:
    """Bind every declared build/runtime/extra dependency to one hashed exact lock entry."""

    if not _SHA.fullmatch(candidate_sha):
        raise BootstrapVerificationError("candidate SHA is malformed")
    root = candidate_root.resolve()
    pyproject_path = root / "pyproject.toml"
    lock_path = root / "requirements.lock"
    if any(path.is_symlink() or not path.is_file() for path in (pyproject_path, lock_path)):
        raise BootstrapVerificationError("candidate dependency metadata is unavailable")
    try:
        pyproject_bytes = pyproject_path.read_bytes()
        lock_bytes = lock_path.read_bytes()
        pyproject = tomllib.loads(pyproject_bytes.decode())
        lock_text = lock_bytes.decode()
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapVerificationError("candidate dependency metadata is malformed") from exc
    declared = _declared_dependencies(pyproject)
    locked = _locked_dependencies(lock_text)
    if not declared <= locked:
        raise BootstrapVerificationError("a declared dependency is absent from the hash lock")
    shell: dict[str, Any] = {
        "candidate_sha": candidate_sha,
        "coverage_passed": True,
        "declared_dependency_count": len(declared),
        "lock_digest": _digest_bytes(lock_bytes),
        "pyproject_digest": _digest_bytes(pyproject_bytes),
        "schema_version": "trusted-dependency-coverage/v1",
    }
    return {**shell, "report_digest": _report_digest(shell)}


def verify_trusted_security(
    *,
    trusted_root: Path,
    candidate_root: Path,
    manifest_path: Path,
    base_sha: str,
    candidate_sha: str,
    pr_number: int,
    trusted_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Return the only admitted runner root for an exact pull-request subject."""

    trusted = _verify_repository(trusted_root, base_sha, label="protected base")
    candidate = _verify_repository(candidate_root, candidate_sha, label="candidate")
    for relative in (
        "security/security-profile-policy.json",
        "security/secret-allowlist.json",
    ):
        path = trusted / relative
        if path.is_symlink() or not path.is_file():
            raise BootstrapVerificationError("protected security policy root is incomplete")
    protected_presence = [(trusted / relative).is_file() for relative in _PROTECTED_RUNTIME]
    if any(protected_presence) and not all(protected_presence):
        raise BootstrapVerificationError(
            "protected verifier is partial; bootstrap fallback is forbidden"
        )
    if all(protected_presence):
        if any(not (trusted / relative).is_file() for relative in _TOOLCHAIN_FILES):
            raise BootstrapVerificationError("protected verifier toolchain is incomplete")
        mode = "PROTECTED_BASE"
        runner = trusted
        manifest_digest: str | None = None
        file_count: int | None = None
    else:
        now = trusted_clock()
        if now.tzinfo is None:
            raise BootstrapVerificationError("trusted clock is not timezone-aware")
        try:
            resolved_manifest = manifest_path.resolve(strict=True)
        except OSError as exc:
            raise BootstrapVerificationError("protected bootstrap manifest is unavailable") from exc
        if (
            manifest_path.is_symlink()
            or not resolved_manifest.is_file()
            or not resolved_manifest.is_relative_to(trusted)
        ):
            raise BootstrapVerificationError(
                "bootstrap manifest is not a regular protected-base file"
            )
        expected, manifest_digest = _load_manifest(
            resolved_manifest,
            candidate_sha=candidate_sha,
            pr_number=pr_number,
            now=now,
        )
        file_count = _verify_bootstrap_files(candidate, expected)
        mode = "BOOTSTRAP_PINNED_CANDIDATE"
        runner = candidate
    shell: dict[str, Any] = {
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "manifest_digest": manifest_digest,
        "manifest_file_count": file_count,
        "mode": mode,
        "pr_number": pr_number,
        "requirements_path": str((runner / "requirements.lock").resolve()),
        "runner_root": str(runner),
        "schema_version": "trusted-security-admission/v1",
    }
    return {**shell, "report_digest": _report_digest(shell)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-dependency-coverage", action="store_true")
    parser.add_argument("--trusted-root", type=Path)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--base-sha")
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    if args.verify_dependency_coverage:
        report = verify_locked_dependency_coverage(
            candidate_root=args.candidate_root,
            candidate_sha=args.candidate_sha,
        )
    else:
        if any(
            value is None
            for value in (args.trusted_root, args.manifest, args.base_sha, args.pr_number)
        ):
            parser.error("admission mode requires trusted root, manifest, base SHA, and PR number")
        assert args.trusted_root is not None
        assert args.manifest is not None
        assert args.base_sha is not None
        assert args.pr_number is not None
        report = verify_trusted_security(
            trusted_root=args.trusted_root,
            candidate_root=args.candidate_root,
            manifest_path=args.manifest,
            base_sha=args.base_sha,
            candidate_sha=args.candidate_sha,
            pr_number=args.pr_number,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.github_output is not None and not args.verify_dependency_coverage:
        with args.github_output.open("a") as stream:
            for field in ("mode", "requirements_path", "runner_root"):
                stream.write(f"{field}={report[field]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
