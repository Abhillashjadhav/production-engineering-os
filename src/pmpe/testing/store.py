"""Immutable TestPlan persistence and pre-implementation authorization."""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from .evidence import MeaningfulRedGate, MeaningfulRedRun
from .models import TestPlan


class TestPlanConflictError(RuntimeError):
    pass


class TestPlanNotAdmittedError(RuntimeError):
    pass


TestPlanConflict = TestPlanConflictError
TestPlanNotAdmitted = TestPlanNotAdmittedError

_PLAN_NAME = "test-plan.json"
_MAX_PLAN_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class TestPlanReceipt:
    plan_digest: str
    artifact_path: str


@dataclass(frozen=True)
class ImplementationAuthorization:
    plan_digest: str
    red_run_digest: str
    commit_sha: str


class TestPlanStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / _PLAN_NAME

    def _open_run_dir(self, *, create: bool) -> int:
        """Open every directory component without following a symlink."""

        absolute = Path(os.path.abspath(self.run_dir))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(absolute.anchor, flags)
            for component in absolute.parts[1:]:
                child: int | None = None
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    child = os.open(component, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            pinned = os.fstat(descriptor)
            if not stat.S_ISDIR(pinned.st_mode):
                raise OSError("run path is not a directory")
            return descriptor
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            raise TestPlanNotAdmitted(
                "TestPlan run directory could not be opened without following symlinks"
            ) from exc

    @staticmethod
    def _read_existing(directory_descriptor: int) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(_PLAN_NAME, flags, dir_fd=directory_descriptor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise TestPlanNotAdmitted(
                "persisted TestPlan could not be opened without following symlinks"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > _MAX_PLAN_BYTES
            ):
                raise TestPlanNotAdmitted("persisted TestPlan is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = _MAX_PLAN_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > _MAX_PLAN_BYTES:
                raise TestPlanNotAdmitted("persisted TestPlan exceeds the safe size limit")
            return payload
        finally:
            os.close(descriptor)

    @staticmethod
    def _persist(directory_descriptor: int, payload: bytes) -> bytes:
        temporary = f".test-plan.{secrets.token_hex(16)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_descriptor)
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary,
                    _PLAN_NAME,
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                existing = TestPlanStore._read_existing(directory_descriptor)
                if existing != payload:
                    raise TestPlanConflict(
                        "an immutable different TestPlan already exists for this run"
                    ) from None
                return existing
            os.fsync(directory_descriptor)
            return payload
        except (TestPlanConflict, TestPlanNotAdmitted):
            raise
        except OSError as exc:
            raise TestPlanNotAdmitted("TestPlan could not be persisted safely") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise TestPlanNotAdmitted("temporary TestPlan cleanup could not be proven") from exc

    def admit(self, plan: TestPlan) -> TestPlanReceipt:
        payload = plan.canonical_bytes()
        directory_descriptor = self._open_run_dir(create=True)
        try:
            existing = self._read_existing(directory_descriptor)
            if existing is not None:
                if existing != payload:
                    raise TestPlanConflict(
                        "an immutable different TestPlan already exists for this run"
                    )
                if not plan.digest_is_valid() or plan.disposition != "ADMITTED":
                    raise TestPlanNotAdmitted("persisted TestPlan is not digest-valid and ADMITTED")
            elif not plan.digest_is_valid() or plan.disposition != "ADMITTED":
                raise TestPlanNotAdmitted("only a digest-valid ADMITTED TestPlan can be persisted")
            else:
                self._persist(directory_descriptor, payload)
        finally:
            os.close(directory_descriptor)
        return TestPlanReceipt(plan.plan_digest, str(self.path))

    def authorize_implementation(
        self,
        plan: TestPlan,
        red_run: MeaningfulRedRun,
        *,
        expected_commit_sha: str,
    ) -> ImplementationAuthorization:
        directory_descriptor = self._open_run_dir(create=False)
        try:
            payload = self._read_existing(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        if payload is None:
            raise TestPlanNotAdmitted("implementation refused: TestPlan is not persisted")
        try:
            persisted = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TestPlanNotAdmitted("persisted TestPlan is unreadable") from exc
        if (
            persisted != plan.as_dict()
            or not plan.digest_is_valid()
            or plan.disposition != "ADMITTED"
        ):
            raise TestPlanNotAdmitted("implementation refused: persisted TestPlan does not match")
        admission = MeaningfulRedGate().validate(
            plan, red_run, expected_commit_sha=expected_commit_sha
        )
        if not admission.admitted:
            rules = ", ".join(item.rule_id for item in admission.diagnostics)
            raise TestPlanNotAdmitted(f"implementation refused: meaningful-red failed ({rules})")
        return ImplementationAuthorization(
            plan_digest=plan.plan_digest,
            red_run_digest=red_run.run_digest(),
            commit_sha=red_run.commit_sha,
        )
