"""Runtime-owned observations, with explicit criterion identity and exact blobs."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pmpe.contracts.canonical import canonical_digest
from pmpe.process_sources import raw_digest

if TYPE_CHECKING:
    from pmpe.barebones import CandidateSandbox
    from pmpe.evidence.ledger import EvidenceLedger


class RecordingSandbox:
    def __init__(
        self,
        delegate: CandidateSandbox,
        ledger: EvidenceLedger,
        paths: Mapping[str, Path],
        expected: Mapping[str, str],
    ) -> None:
        self.delegate, self.ledger = delegate, ledger
        self.paths, self.expected = dict(paths), dict(expected)
        self.records: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        self.phase = "baseline"
        self.attempt = 0
        self.criterion_id = ""
        self.protected: dict[str, bytes] = {}
        self.current_workspace: Path | None = None
        self.blobs: set[str] = set()
        self.integrity_failed = False

    def blob(self, payload: bytes) -> str:
        digest = self.ledger.put_blob(payload)
        self.blobs.add(digest)
        return digest

    @contextmanager
    def criterion(self, criterion_id: str, workspace: Path) -> Iterator[None]:
        self.criterion_id, self.current_workspace = criterion_id, workspace
        try:
            yield
        finally:
            self.criterion_id, self.current_workspace = "", None

    def boundary(self, stage: str, *, process_index: int | None = None) -> None:
        expected = dict(self.expected)
        observed: dict[str, str] = {}
        for name, path in self.paths.items():
            observed[name] = (
                "SYMLINK"
                if path.is_symlink()
                else raw_digest(path.read_bytes())
                if path.is_file()
                else "MISSING"
            )
        if self.current_workspace is not None:
            for relative, payload in self.protected.items():
                name = "protected/" + relative
                expected[name] = raw_digest(payload)
                path = self.current_workspace / relative
                observed[name] = (
                    "SYMLINK"
                    if path.is_symlink()
                    else raw_digest(path.read_bytes())
                    if path.is_file()
                    else "MISSING"
                )
        mismatches = sorted(name for name in expected if expected[name] != observed[name])
        self.observations.append(
            {
                "run_id": self.ledger.run_id,
                "stage": stage,
                "phase": self.phase,
                "attempt": self.attempt,
                "criterion_id": self.criterion_id,
                "process_index": process_index,
                "expected_inventory_digest": canonical_digest(expected),
                "observed_inventory_digest": canonical_digest(observed),
                "checked": len(expected),
                "mismatches": mismatches,
            }
        )
        if mismatches:
            self.integrity_failed = True
            from pmpe.barebones import ContractInvalidError

            raise ContractInvalidError("process gate integrity mismatch: " + ", ".join(mismatches))

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        if not self.criterion_id or self.current_workspace != workspace:
            raise ValueError("process gate requires explicit criterion context")
        index = len(self.records)
        record: dict[str, Any] = {
            "run_id": self.ledger.run_id,
            "process_index": index,
            "phase": self.phase,
            "attempt": self.attempt,
            "criterion_id": self.criterion_id,
            "requested_argv": list(argv),
            "timeout_seconds": timeout_seconds,
            "environment": dict(environment),
            "sandbox_class": type(self.delegate).__module__
            + "."
            + type(self.delegate).__qualname__,
            "output_encoding": "UTF-8 encoding of sandbox text observations",
        }
        self.boundary("before", process_index=index)
        try:
            completed = self.delegate.run(
                workspace, argv, timeout_seconds=timeout_seconds, environment=environment
            )
            record.update(
                {
                    "executed_argv": list(completed.args)
                    if not isinstance(completed.args, str)
                    else [completed.args],
                    "exit_code": completed.returncode,
                    "stdout_digest": self.blob(completed.stdout.encode()),
                    "stderr_digest": self.blob(completed.stderr.encode()),
                }
            )
            return completed
        except Exception as exc:
            record["error"] = type(exc).__name__ + ": " + str(exc)
            raise
        finally:
            self.records.append(record)
            self.boundary("after", process_index=index)

    def selected(self, values: list[dict[str, Any]], attempt: int) -> list[dict[str, Any]]:
        return [item for item in values if item["attempt"] in {0, attempt}]
