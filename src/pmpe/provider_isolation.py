"""Offline, no-credential launcher for a whole untrusted provider adapter.

This is an executable containment path for fake/local providers, not a grant
of release eligibility or an authenticated Codex CLI configuration. Network
and ambient credentials remain unavailable inside the Bubblewrap namespace.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pmpe.barebones import BubblewrapCandidateSandbox, ContractInvalidError
from pmpe.contracts.canonical import CanonicalInputError, canonical_json_bytes, strict_loads

_ENTRY = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_REQUEST_LIMIT_BYTES = 1_000_000
_SYSTEM_PYTHON = Path("/usr/bin/python3")


class _OfflineProviderSandbox(BubblewrapCandidateSandbox):
    """Mount only OS runtime roots, never the active verifier virtualenv."""

    @staticmethod
    def _runtime_roots() -> tuple[Path, ...]:
        return tuple(
            path
            for path in (Path("/usr"), Path("/bin"), Path("/sbin"), Path("/lib"), Path("/lib64"))
            if path.exists()
        )


def _protected_system_python() -> str:
    try:
        executable = _SYSTEM_PYTHON.resolve(strict=True)
        locations = (executable, *executable.parents)
        if not executable.is_file() or not executable.is_relative_to(Path("/usr")):
            raise OSError("system Python is outside /usr")
        if any(
            path.stat().st_uid == os.geteuid()
            or path.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            for path in locations
        ):
            raise OSError("system Python or its parent is writable by the provider user")
    except OSError as exc:
        raise ContractInvalidError("protected system Python is unavailable") from exc
    return str(_SYSTEM_PYTHON)


class OfflineConfinedProvider:
    """Invoke one bundled Python provider with no host paths, network or secrets."""

    def __init__(
        self,
        *,
        bundle: Path,
        entry: str,
        protected_roots: Sequence[Path],
        timeout_seconds: int,
        sandbox: BubblewrapCandidateSandbox | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ContractInvalidError("provider timeout must be positive")
        if _ENTRY.fullmatch(entry) is None or any(part in {".", ".."} for part in entry.split("/")):
            raise ContractInvalidError("offline provider entry must be a safe relative path")
        if not bundle.is_dir() or bundle.is_symlink():
            raise ContractInvalidError("offline provider bundle is unavailable")
        resolved_bundle = bundle.resolve(strict=True)
        visible_host_paths = tuple(
            path.resolve(strict=False)
            for path in (
                *_OfflineProviderSandbox._runtime_roots(),
                *_OfflineProviderSandbox._host_read_only_paths(),
            )
            if path.exists()
        )
        for protected in protected_roots:
            resolved = protected.resolve(strict=False)
            if resolved_bundle.is_relative_to(resolved) or resolved.is_relative_to(resolved_bundle):
                raise ContractInvalidError("offline provider bundle overlaps protected host input")
            if any(
                resolved.is_relative_to(visible) or visible.is_relative_to(resolved)
                for visible in visible_host_paths
            ):
                raise ContractInvalidError(
                    "protected host input overlaps offline provider runtime mount"
                )
        for item in resolved_bundle.rglob("*"):
            if item.is_symlink() or not (item.is_dir() or item.is_file()):
                raise ContractInvalidError("offline provider bundle contains an unsafe entry")
        target = resolved_bundle / entry
        if not target.is_file() or target.is_symlink() or target.suffix != ".py":
            raise ContractInvalidError("offline provider entry must be a regular Python file")
        self.bundle = resolved_bundle
        self.entry = entry
        self.timeout_seconds = timeout_seconds
        self.python_executable = _protected_system_python()
        self.sandbox = sandbox or _OfflineProviderSandbox()

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        payload = canonical_json_bytes({"purpose": purpose, "request": dict(request)})
        if len(payload) > _REQUEST_LIMIT_BYTES:
            raise RuntimeError("MODEL_PROVIDER_REQUEST_LIMIT")
        try:
            completed = self.sandbox.run_with_input(
                self.bundle,
                (self.python_executable, "-I", "-B", f"/workspace/{self.entry}"),
                timeout_seconds=self.timeout_seconds,
                environment={
                    "HOME": "/tmp/home",
                    "LC_ALL": "C",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONNOUSERSITE": "1",
                    "TMPDIR": "/tmp",
                },
                input_data=payload,
            )
        except ContractInvalidError as exc:
            raise RuntimeError("MODEL_PROVIDER_SANDBOX_UNAVAILABLE") from exc
        if completed.returncode != 0:
            raise RuntimeError("MODEL_PROVIDER_FAILED")
        try:
            return strict_loads(completed.stdout.encode("utf-8"), "application/json")
        except (CanonicalInputError, UnicodeError) as exc:
            raise RuntimeError("MODEL_PROVIDER_RESPONSE_INVALID") from exc


__all__ = ["OfflineConfinedProvider"]
