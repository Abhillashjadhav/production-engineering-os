"""Immutable TestPlan persistence and trusted pre-implementation authorization."""

from __future__ import annotations

import json
import os
import secrets
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pmpe.admission import (
    AdmissionReceipt,
    FileArtifactAdmissionAuthority,
    FileArtifactAdmissionVerifier,
)
from pmpe.architecture.models import ArchitecturePack
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence import (
    ORACLE_ARTIFACT_KIND,
    EvidenceAdapterRegistry,
    EvidenceExpectation,
    EvidenceSubmission,
    MeaningfulRedGate,
    NodeExpectation,
    default_adapter_registry,
    evidence_plan_digest,
    oracle_artifact_digest,
    oracle_subject_bindings,
)
from pmpe.execution import (
    CommandOutcome,
    ExecutionCommand,
    ExecutionError,
    ExecutionPolicy,
    IsolatedExecutionKernel,
    SandboxRunner,
)
from pmpe.repository.models import RepositorySnapshot

from .compiler import ContractAdmission, TestPlanCompiler
from .models import RepositoryTestCapability, TestPlan


class TestPlanConflictError(RuntimeError):
    pass


class TestPlanNotAdmittedError(RuntimeError):
    pass


TestPlanConflict = TestPlanConflictError
TestPlanNotAdmitted = TestPlanNotAdmittedError

_PLAN_NAME = "test-plan.json"
_RECEIPT_NAME = "test-plan.receipt.json"
_MAX_PLAN_BYTES = 4 * 1024 * 1024
_MAX_RECEIPT_BYTES = 64 * 1024


@dataclass(frozen=True)
class TestPlanReceipt:
    plan_digest: str
    artifact_path: str
    admission_receipt: AdmissionReceipt


@dataclass(frozen=True)
class ImplementationAuthorization:
    plan_digest: str
    red_run_digest: str
    commit_sha: str


class _CapturingSandbox:
    """Keep authenticated raw output beside the kernel-produced digests."""

    def __init__(self, delegate: SandboxRunner) -> None:
        self.delegate = delegate
        self.identity = delegate.identity
        self.last_outcome: CommandOutcome | None = None

    def run(
        self,
        workspace: Path,
        command: ExecutionCommand,
        policy: ExecutionPolicy,
    ) -> CommandOutcome:
        self.last_outcome = None
        outcome = self.delegate.run(workspace, command, policy)
        self.last_outcome = outcome
        return outcome


class TestPlanStore:
    def __init__(
        self,
        run_dir: Path,
        *,
        authority: FileArtifactAdmissionAuthority | None = None,
        verifier: FileArtifactAdmissionVerifier | None = None,
        sandbox: SandboxRunner | None = None,
        policy: ExecutionPolicy | None = None,
        registry: EvidenceAdapterRegistry | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / _PLAN_NAME
        self.authority = authority
        self.verifier = verifier
        self.sandbox = sandbox
        self.policy = policy or ExecutionPolicy()
        self.registry = registry or default_adapter_registry()

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
    def _read_existing(
        directory_descriptor: int,
        name: str,
        maximum_bytes: int,
    ) -> bytes | None:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=directory_descriptor)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise TestPlanNotAdmitted(
                "persisted TestPlan artifact could not be opened without following symlinks"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > maximum_bytes
            ):
                raise TestPlanNotAdmitted(
                    "persisted TestPlan artifact is not a bounded regular file"
                )
            chunks: list[bytes] = []
            remaining = maximum_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > maximum_bytes:
                raise TestPlanNotAdmitted("persisted TestPlan artifact exceeds its safe limit")
            return payload
        finally:
            os.close(descriptor)

    @staticmethod
    def _persist(directory_descriptor: int, name: str, payload: bytes) -> bytes:
        temporary = f".{name}.{secrets.token_hex(16)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_descriptor)
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise OSError("TestPlan write made no progress")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                limit = _MAX_PLAN_BYTES if name == _PLAN_NAME else _MAX_RECEIPT_BYTES
                existing = TestPlanStore._read_existing(directory_descriptor, name, limit)
                if existing != payload:
                    raise TestPlanConflict(
                        "an immutable different TestPlan artifact already exists for this run"
                    ) from None
                return existing
            os.fsync(directory_descriptor)
            return payload
        except (TestPlanConflict, TestPlanNotAdmitted):
            raise
        except OSError as exc:
            raise TestPlanNotAdmitted("TestPlan artifact could not be persisted safely") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise TestPlanNotAdmitted(
                    "temporary TestPlan artifact cleanup could not be proven"
                ) from exc

    @staticmethod
    def _receipt_bindings(plan: TestPlan, input_digest: str) -> dict[str, str]:
        return {
            "architecture_pack_digest": plan.architecture_pack_digest,
            "compiler_version": plan.compiler_version,
            "contract_digest": plan.contract_digest,
            "input_digest": input_digest,
            "repository_commit": plan.repository_commit,
            "repository_snapshot_digest": plan.repository_snapshot_digest,
            "toolchain_digest": plan.toolchain_digest,
        }

    def admit(
        self,
        *,
        contract_bundle: Mapping[str, Any],
        contract_validation: ContractAdmission,
        repository_snapshot: RepositorySnapshot,
        architecture_pack: ArchitecturePack,
        capabilities: Sequence[RepositoryTestCapability],
    ) -> TestPlanReceipt:
        if self.authority is None:
            raise TestPlanNotAdmitted("TestPlan admission authority is not configured")
        compilation = TestPlanCompiler(self.registry).compile(
            contract_bundle,
            contract_validation,
            repository_snapshot,
            architecture_pack,
            capabilities,
        )
        plan = compilation.plan
        if (
            plan is None
            or compilation.disposition.value != "ADMITTED"
            or compilation.diagnostics
            or plan.disposition != "ADMITTED"
            or not plan.digest_is_valid()
        ):
            raise TestPlanNotAdmitted(
                "only a compiler-produced, diagnostic-free ADMITTED TestPlan can be persisted"
            )
        admission_receipt = self.authority.admit(
            artifact_kind="TEST_PLAN",
            artifact_digest=plan.plan_digest,
            subject_bindings=self._receipt_bindings(plan, compilation.input_digest),
        )
        plan_payload = plan.canonical_bytes()
        receipt_payload = canonical_json_bytes(admission_receipt.as_dict()) + b"\n"
        directory_descriptor = self._open_run_dir(create=True)
        try:
            existing_plan = self._read_existing(directory_descriptor, _PLAN_NAME, _MAX_PLAN_BYTES)
            existing_receipt = self._read_existing(
                directory_descriptor, _RECEIPT_NAME, _MAX_RECEIPT_BYTES
            )
            if existing_plan is not None and existing_plan != plan_payload:
                raise TestPlanConflict(
                    "an immutable different TestPlan already exists for this run"
                )
            if existing_receipt is not None and existing_receipt != receipt_payload:
                raise TestPlanConflict(
                    "an immutable different TestPlan receipt already exists for this run"
                )
            if existing_plan is None:
                self._persist(directory_descriptor, _PLAN_NAME, plan_payload)
            if existing_receipt is None:
                self._persist(directory_descriptor, _RECEIPT_NAME, receipt_payload)
        finally:
            os.close(directory_descriptor)
        return TestPlanReceipt(plan.plan_digest, str(self.path), admission_receipt)

    def _load_admitted(self, plan: TestPlan) -> AdmissionReceipt:
        directory_descriptor = self._open_run_dir(create=False)
        try:
            plan_payload = self._read_existing(directory_descriptor, _PLAN_NAME, _MAX_PLAN_BYTES)
            receipt_payload = self._read_existing(
                directory_descriptor, _RECEIPT_NAME, _MAX_RECEIPT_BYTES
            )
        finally:
            os.close(directory_descriptor)
        if plan_payload is None or receipt_payload is None:
            raise TestPlanNotAdmitted("implementation refused: admitted TestPlan is not persisted")
        try:
            persisted = json.loads(plan_payload)
            receipt_value = json.loads(receipt_payload)
            receipt = AdmissionReceipt.from_dict(receipt_value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TestPlanNotAdmitted("persisted TestPlan admission is unreadable") from exc
        if (
            plan_payload != plan.canonical_bytes()
            or persisted != plan.as_dict()
            or not plan.digest_is_valid()
            or plan.disposition != "ADMITTED"
        ):
            raise TestPlanNotAdmitted("implementation refused: persisted TestPlan does not match")
        if receipt_payload != canonical_json_bytes(receipt.as_dict()) + b"\n":
            raise TestPlanNotAdmitted(
                "implementation refused: compiler admission receipt does not match"
            )
        return receipt

    @staticmethod
    def _draft_expectations(
        plan: TestPlan,
        *,
        subject_digest: str,
    ) -> tuple[EvidenceExpectation, ...]:
        by_command: dict[tuple[str, ...], list[Any]] = {}
        for node in plan.nodes:
            if (
                node.status == "PLANNED"
                and node.execution_mode == "AUTOMATED"
                and node.meaningful_red_required
                and node.command
            ):
                by_command.setdefault(node.command, []).append(node)
        expectations: list[EvidenceExpectation] = []
        for index, command in enumerate(sorted(by_command), start=1):
            nodes = sorted(by_command[command], key=lambda item: item.node_id)
            toolchains = {(item.toolchain_refs[0], item.toolchain_refs[1]) for item in nodes}
            if len(toolchains) != 1 or any(not item.expected_test_node for item in nodes):
                raise TestPlanNotAdmitted(
                    "implementation refused: plan command has ambiguous evidence bindings"
                )
            tool, evidence_format = next(iter(toolchains))
            expectations.append(
                EvidenceExpectation(
                    command_id=f"CMD-{index:04d}",
                    tool=tool,
                    evidence_format=evidence_format,
                    plan_digest="sha256:" + "0" * 64,
                    commit_sha=plan.repository_commit,
                    subject_digest=subject_digest,
                    command=ExecutionCommand(command),
                    nodes=tuple(
                        NodeExpectation(item.expected_test_node, item.assertion_id)
                        for item in nodes
                    ),
                )
            )
        if not expectations:
            raise TestPlanNotAdmitted(
                "implementation refused: TestPlan has no runner-backed meaningful-red command"
            )
        plan_digest = evidence_plan_digest(expectations)
        return tuple(replace(item, plan_digest=plan_digest) for item in expectations)

    def authorize_implementation(
        self,
        plan: TestPlan,
        *,
        workspace: Path,
        expected_commit_sha: str,
    ) -> ImplementationAuthorization:
        receipt = self._load_admitted(plan)
        if expected_commit_sha != plan.repository_commit:
            raise TestPlanNotAdmitted(
                "implementation refused: expected repository commit does not match TestPlan"
            )
        if self.authority is None or self.verifier is None or self.sandbox is None:
            raise TestPlanNotAdmitted(
                "implementation refused: trusted execution boundary is not configured"
            )
        bindings = dict(receipt.subject_bindings)
        if not self.verifier.verify(
            receipt,
            artifact_kind="TEST_PLAN",
            artifact_digest=plan.plan_digest,
            subject_bindings=bindings,
        ) or bindings != self._receipt_bindings(plan, bindings.get("input_digest", "")):
            raise TestPlanNotAdmitted(
                "implementation refused: compiler admission receipt is not verified"
            )

        capturing = _CapturingSandbox(self.sandbox)
        kernel = IsolatedExecutionKernel(
            authority=self.authority,
            sandbox=capturing,
            policy=self.policy,
        )
        commands = sorted(
            {
                node.command
                for node in plan.nodes
                if node.status == "PLANNED"
                and node.execution_mode == "AUTOMATED"
                and node.meaningful_red_required
                and node.command
            }
        )
        if not commands:
            raise TestPlanNotAdmitted(
                "implementation refused: TestPlan has no runner-backed meaningful-red command"
            )
        try:
            provisional = kernel.execute(
                repository=Path(workspace),
                commit_sha=expected_commit_sha,
                plan_digest=plan.plan_digest,
                command=ExecutionCommand(commands[0]),
            )
            expectations = self._draft_expectations(
                plan,
                subject_digest=provisional.subject_digest_before,
            )
            submissions: list[EvidenceSubmission] = []
            execution_digests: list[str] = []
            for expectation in expectations:
                oracle_receipt = self.authority.admit(
                    artifact_kind=ORACLE_ARTIFACT_KIND,
                    artifact_digest=oracle_artifact_digest(expectation),
                    subject_bindings=oracle_subject_bindings(expectation),
                )
                execution = kernel.execute(
                    repository=Path(workspace),
                    commit_sha=expected_commit_sha,
                    plan_digest=expectation.plan_digest,
                    command=expectation.command,
                )
                outcome = capturing.last_outcome
                if outcome is None:
                    raise ExecutionError("sandbox output was not captured")
                submissions.append(
                    EvidenceSubmission(
                        expectation.command_id,
                        execution,
                        outcome.stdout,
                        outcome.stderr,
                        oracle_receipt,
                    )
                )
                execution_digests.append(execution.execution_digest)
        except (OSError, TypeError, ValueError, ExecutionError) as exc:
            raise TestPlanNotAdmitted(
                "implementation refused: isolated meaningful-red execution failed"
            ) from exc

        decision = MeaningfulRedGate(verifier=self.verifier, registry=self.registry).evaluate(
            expectations=expectations,
            submissions=tuple(submissions),
        )
        if not decision.authorized:
            raise TestPlanNotAdmitted(
                "implementation refused: meaningful-red failed ("
                + "; ".join(decision.reasons)
                + ")"
            )
        required_red = {
            (node.node_id, node.assertion_id)
            for expectation in expectations
            for node in expectation.nodes
        }
        observed_red = {
            (node.node_id, node.assertion_id)
            for node in decision.nodes
            if node.outcome == "failed" and node.failure_kind == "assertion"
        }
        if observed_red != required_red:
            missing = sorted(node_id for node_id, assertion_id in required_red - observed_red)
            raise TestPlanNotAdmitted(
                "implementation refused: meaningful-red failed because every plan-bound "
                "node must fail through its admitted assertion; missing: " + ", ".join(missing)
            )
        red_run_digest = canonical_digest(
            {
                "evidence_plan_digest": expectations[0].plan_digest,
                "execution_digests": execution_digests,
                "nodes": [
                    {
                        "assertion_id": item.assertion_id,
                        "failure_kind": item.failure_kind,
                        "node_id": item.node_id,
                        "outcome": item.outcome,
                        "raw_output_digest": item.raw_output_digest,
                    }
                    for item in decision.nodes
                ],
                "test_plan_digest": plan.plan_digest,
            }
        )
        return ImplementationAuthorization(plan.plan_digest, red_run_digest, expected_commit_sha)
