"""CLI entry point for the frozen bare-bones core."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, cast

from pmpe.barebones import ContractInvalidError, compile_barebones_plan, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.canonical import CanonicalInputError, canonical_digest, strict_loads
from pmpe.domain.errors import ContractViolation
from pmpe.evals.barebones_drift import (
    ProviderBehavior,
    compare_provider_behavior,
    observe_provider_behavior,
)
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

_PROVIDER_OUTPUT_LIMIT_BYTES = 1_000_000
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _load_contract(path: Path) -> Mapping[str, Any]:
    content_type = (
        "application/yaml" if path.suffix.lower() in {".yaml", ".yml"} else "application/json"
    )
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise ContractInvalidError("cannot read contract") from exc
    contract = strict_loads(source, content_type)
    if not isinstance(contract, Mapping):
        raise ContractInvalidError("contract must be an object")
    return contract


def _compile(args: argparse.Namespace) -> int:
    try:
        contract = _load_contract(Path(args.contract))
        plan = compile_barebones_plan(
            contract=contract,
            repository_root=Path(args.repository_root).resolve(),
        )
    except CanonicalInputError as exc:
        _json(
            {
                "state": "HALTED",
                "cause": "CONTRACT_INVALID",
                "diagnostics": [{"code": exc.code, "message": str(exc)}],
            }
        )
        return 3
    except AcceptanceCompileError as exc:
        _json(
            {
                "state": "HALTED",
                "cause": "CONTRACT_INVALID",
                "diagnostics": [item.__dict__ for item in exc.diagnostics],
            }
        )
        return 3
    except ContractInvalidError as exc:
        _json({"state": "HALTED", "cause": "CONTRACT_INVALID", "detail": str(exc)})
        return 3
    structured = sum(item.form != "human_test" for item in plan.criteria)
    human = sum(item.form == "human_test" for item in plan.criteria)
    _json(
        {
            "status": "COMPILES",
            "contract_status": contract.get("contract_status"),
            "coverage": {
                "structured": structured,
                "human_test": human,
                "total": len(plan.criteria),
            },
            "plan": plan.as_dict(),
        }
    )
    return 0


def _fence_provider_group(process: subprocess.Popen[bytes]) -> int:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    return process.wait()


def _terminate_provider(process: subprocess.Popen[bytes]) -> None:
    _fence_provider_group(process)


def _wait_for_provider_exit_without_reaping(
    process: subprocess.Popen[bytes], timeout_seconds: float
) -> bool:
    """Observe provider exit while retaining its PID until its group is fenced."""

    if not all(hasattr(os, name) for name in ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT")):
        raise RuntimeError("MODEL_PROVIDER_PROCESS_GROUP_UNAVAILABLE")
    waitid = cast(
        Callable[[int, int, int], object | None],
        vars(os)["waitid"],
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            result = waitid(
                os.P_PID,
                process.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError as exc:
            raise RuntimeError("MODEL_PROVIDER_PROCESS_REAPED") from exc
        if result is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _run_provider_command(
    argv: tuple[str, ...],
    payload: bytes,
    timeout_seconds: int,
    output_limit_bytes: int = _PROVIDER_OUTPUT_LIMIT_BYTES,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryFile() as stdin_file:
        stdin_file.write(payload)
        stdin_file.seek(0)
        process = subprocess.Popen(
            argv,
            stdin=stdin_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env=dict(environment) if environment is not None else None,
        )
        if process.stdout is None or process.stderr is None:
            _terminate_provider(process)
            raise RuntimeError("MODEL_PROVIDER_IO_UNAVAILABLE")
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout_seconds
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("MODEL_PROVIDER_TIMEOUT")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output = streams[key.data]
                    output.extend(chunk)
                    if len(output) > output_limit_bytes:
                        raise RuntimeError("MODEL_PROVIDER_OUTPUT_LIMIT")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("MODEL_PROVIDER_TIMEOUT")
            if not _wait_for_provider_exit_without_reaping(process, remaining):
                raise RuntimeError("MODEL_PROVIDER_TIMEOUT")
            returncode = _fence_provider_group(process)
        except subprocess.TimeoutExpired as exc:
            _terminate_provider(process)
            raise RuntimeError("MODEL_PROVIDER_TIMEOUT") from exc
        except RuntimeError:
            _terminate_provider(process)
            raise
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
        return subprocess.CompletedProcess(
            argv,
            returncode,
            bytes(streams["stdout"]),
            bytes(streams["stderr"]),
        )


class CommandModelProvider:
    """ModelProvider that exchanges one JSON object with a local command."""

    def __init__(self, command: str, timeout_seconds: int) -> None:
        self.argv = tuple(shlex.split(command))
        if not self.argv:
            raise ValueError("provider command cannot be empty")
        self.timeout_seconds = timeout_seconds

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        environment = dict(os.environ)
        environment["PMPE_PROVIDER_TIMEOUT_SECONDS"] = str(self.timeout_seconds)
        completed = _run_provider_command(
            self.argv,
            json.dumps({"purpose": purpose, "request": request}).encode(),
            self.timeout_seconds,
            environment=environment,
        )
        if completed.returncode != 0:
            raise RuntimeError("MODEL_PROVIDER_FAILED")
        try:
            response = strict_loads(completed.stdout, "application/json")
        except CanonicalInputError as exc:
            raise RuntimeError("model provider returned malformed JSON") from exc
        return response


def _require_approved_contract(
    contract: Mapping[str, Any], receipt: Mapping[str, Any], expected_approver: str
) -> None:
    status = contract.get("contract_status")
    approved_by = contract.get("approved_by")
    if status != "APPROVED":
        raise ContractInvalidError("contract_status must be APPROVED")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ContractInvalidError("approved_by is required")
    if approved_by != expected_approver:
        raise ContractInvalidError("approved_by does not match --expected-approver")
    try:
        verify_contract_approval(dict(contract), dict(receipt), expected_approver=expected_approver)
    except ContractViolation as exc:
        raise ContractInvalidError(str(exc)) from exc


def _run(args: argparse.Namespace) -> int:
    try:
        EvidenceLedger.validate_run_id(args.run_id)
    except ValueError as exc:
        return _evidence_invalid(EvidenceIntegrityError(str(exc)))
    contract_path = Path(args.contract)
    try:
        contract = _load_contract(contract_path)
        try:
            receipt_source = Path(args.approval_receipt).read_bytes()
        except OSError as exc:
            raise ContractInvalidError("cannot read approval receipt") from exc
        receipt = strict_loads(receipt_source, "application/json")
        _require_approved_contract(contract, receipt, args.expected_approver)
        result = run_to_release_ready(
            contract=contract,
            repository_root=Path(args.repository_root).resolve(),
            workspace=Path(args.workspace).resolve(),
            run_id=args.run_id,
            provider=CommandModelProvider(args.provider_command, args.provider_timeout),
            approval_receipt=receipt,
            approval_authority=args.expected_approver,
            approval_receipt_bytes=receipt_source,
        )
    except CanonicalInputError as exc:
        _json(
            {
                "state": "HALTED",
                "cause": "CONTRACT_INVALID",
                "diagnostics": [{"code": exc.code, "message": str(exc)}],
            }
        )
        return 3
    except AcceptanceCompileError as exc:
        _json(
            {
                "state": "HALTED",
                "cause": "CONTRACT_INVALID",
                "diagnostics": [item.__dict__ for item in exc.diagnostics],
            }
        )
        return 3
    except ContractInvalidError as exc:
        _json({"state": "HALTED", "cause": "CONTRACT_INVALID", "detail": str(exc)})
        return 3
    except EvidenceIntegrityError as exc:
        _json({"state": "HALTED", "cause": "EVIDENCE_INVALID", "detail": str(exc)})
        return 3
    _json(
        {
            "run_id": result.run_id,
            "state": result.state,
            "cause": result.cause,
            "attempts": result.attempts,
            "model_calls": result.model_calls,
            "elapsed_ms": result.elapsed_ms,
            "workspace": str(Path(args.workspace).resolve()),
            "evidence": str(result.evidence_path),
            "annotation": result.annotation,
            "telemetry": result.telemetry,
        }
    )
    return 0 if result.state == "RELEASE_READY" else 3


def _open_verified_events(
    repository_root: Path, run_id: str
) -> tuple[EvidenceLedger, tuple[Mapping[str, Any], ...]]:
    try:
        ledger = EvidenceLedger.open_existing(repository_root.resolve(), run_id)
    except ValueError as exc:
        raise EvidenceIntegrityError(str(exc)) from exc
    events = tuple(ledger.verify())
    if not events:
        raise EvidenceIntegrityError("evidence ledger is empty")
    return ledger, events


def _verified_events(
    args: argparse.Namespace,
) -> tuple[EvidenceLedger, tuple[Mapping[str, Any], ...]]:
    return _open_verified_events(Path(args.repository_root), args.run_id)


def _evidence_invalid(exc: EvidenceIntegrityError) -> int:
    _json({"state": "HALTED", "cause": "EVIDENCE_INVALID", "detail": str(exc)})
    return 3


def _approval_summary(events: tuple[Mapping[str, Any], ...]) -> dict[str, str]:
    for event in events:
        if event.get("event_type") != "contract_validated":
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise EvidenceIntegrityError("approval evidence is malformed")
        approval = payload.get("approval")
        if not isinstance(approval, Mapping):
            raise EvidenceIntegrityError("approval evidence is malformed")
        status = approval.get("status")
        if status == "UNVERIFIED_DIRECT_CALL":
            return {"status": status}
        if status != "VERIFIED":
            raise EvidenceIntegrityError("approval evidence is malformed")
        authority = approval.get("authority")
        receipt_digest = approval.get("receipt_digest")
        if not isinstance(authority, str) or not isinstance(receipt_digest, str):
            raise EvidenceIntegrityError("approval evidence is malformed")
        return {
            "status": status,
            "authority": authority,
            "receipt_digest": receipt_digest,
        }
    return {"status": "NOT_RECORDED"}


def _status(args: argparse.Namespace) -> int:
    try:
        _, events = _verified_events(args)
        approval = _approval_summary(events)
    except EvidenceIntegrityError as exc:
        return _evidence_invalid(exc)
    terminal = events[-1]
    payload = terminal.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    event_type = terminal.get("event_type")
    cause = payload.get("cause")
    if not isinstance(cause, str):
        cause = "PASS" if event_type == "release_ready" else "IN_PROGRESS"
    telemetry = payload.get("telemetry")
    _json(
        {
            "run_id": args.run_id,
            "state": terminal.get("state"),
            "cause": cause,
            "events": len(events),
            "head_event_digest": terminal.get("event_digest"),
            "telemetry": dict(telemetry) if isinstance(telemetry, Mapping) else {},
            "approval": approval,
        }
    )
    return 0


def _evidence(args: argparse.Namespace) -> int:
    try:
        ledger, events = _verified_events(args)
        approval = _approval_summary(events)
    except EvidenceIntegrityError as exc:
        return _evidence_invalid(exc)
    referenced = {
        digest
        for event in events
        for digest in event.get("blob_digests", [])
        if isinstance(digest, str)
    }
    _json(
        {
            "run_id": args.run_id,
            "integrity": "PASS",
            "events": len(events),
            "referenced_blobs": len(referenced),
            "head_event_digest": events[-1].get("event_digest"),
            "events_path": str(ledger.events_path),
            "blobs_directory": str(ledger.blobs_directory),
            "approval": approval,
        }
    )
    return 0


def _comparison_observation(
    evidence_root: Path,
    run_id: str,
    *,
    expected_approver: str,
    compiler_root: Path,
) -> dict[str, Any]:
    ledger, events = _open_verified_events(evidence_root, run_id)
    validation_events = [
        event for event in events if event.get("event_type") == "contract_validated"
    ]
    if len(validation_events) != 1:
        raise EvidenceIntegrityError("run does not contain one contract validation event")
    validation = validation_events[0]
    validation_payload = validation.get("payload")
    if not isinstance(validation_payload, Mapping):
        raise EvidenceIntegrityError("contract validation evidence is malformed")
    contract_digest = validation_payload.get("contract_digest")
    plan_digest = validation_payload.get("plan_digest")
    approval = validation_payload.get("approval")
    validation_blobs = validation.get("blob_digests")
    if (
        not isinstance(contract_digest, str)
        or not isinstance(plan_digest, str)
        or not isinstance(approval, Mapping)
        or not isinstance(validation_blobs, list)
        or contract_digest not in validation_blobs
        or _SHA256.fullmatch(contract_digest) is None
        or _SHA256.fullmatch(plan_digest) is None
        or validation.get("subject_digest") != contract_digest
    ):
        raise EvidenceIntegrityError("contract or plan identity is malformed")
    authority = approval.get("authority")
    receipt_digest = approval.get("receipt_digest")
    receipt_blob_digest = approval.get("receipt_blob_digest")
    if (
        approval.get("status") != "VERIFIED"
        or not isinstance(authority, str)
        or not authority
        or not isinstance(receipt_digest, str)
        or _SHA256.fullmatch(receipt_digest) is None
        or not isinstance(receipt_blob_digest, str)
        or _SHA256.fullmatch(receipt_blob_digest) is None
        or receipt_blob_digest not in validation_blobs
    ):
        raise EvidenceIntegrityError("behavior comparison requires verified approval evidence")
    if authority != expected_approver:
        raise EvidenceIntegrityError("approval authority does not match --expected-approver")
    plan_blob_digests = [
        digest
        for digest in validation_blobs
        if digest not in {contract_digest, receipt_blob_digest}
    ]
    if (
        len(plan_blob_digests) != 1
        or not isinstance(plan_blob_digests[0], str)
        or _SHA256.fullmatch(plan_blob_digests[0]) is None
    ):
        raise EvidenceIntegrityError("contract or plan identity is malformed")
    try:
        contract = strict_loads(ledger.read_blob(contract_digest), "application/json")
        plan = strict_loads(ledger.read_blob(plan_blob_digests[0]), "application/json")
        receipt = strict_loads(ledger.read_blob(receipt_blob_digest), "application/json")
    except CanonicalInputError as exc:
        raise EvidenceIntegrityError("contract, plan, or approval evidence is malformed") from exc
    if (
        not isinstance(contract, dict)
        or not isinstance(plan, dict)
        or not isinstance(receipt, dict)
    ):
        raise EvidenceIntegrityError("contract, plan, or approval evidence is malformed")
    if canonical_digest(contract) != contract_digest:
        raise EvidenceIntegrityError("contract evidence is not digest-bound")
    try:
        expected_plan = compile_barebones_plan(
            contract=contract,
            repository_root=compiler_root,
        ).as_dict()
    except (AcceptanceCompileError, ContractInvalidError, OSError) as exc:
        raise EvidenceIntegrityError(
            "recorded contract cannot be deterministically recompiled"
        ) from exc
    if (
        canonical_digest(plan) != canonical_digest(expected_plan)
        or plan.get("plan_digest") != plan_digest
    ):
        raise EvidenceIntegrityError("recorded plan does not match deterministic compilation")
    try:
        verified_receipt_digest = verify_contract_approval(
            contract,
            receipt,
            expected_approver=expected_approver,
        )
    except ContractViolation as exc:
        raise EvidenceIntegrityError("approval evidence is not bound to the contract") from exc
    if verified_receipt_digest != receipt_digest:
        raise EvidenceIntegrityError("approval receipt identity is inconsistent")

    coder_events = [event for event in events if event.get("event_type") == "coder_completed"]
    if not coder_events:
        raise EvidenceIntegrityError("run has no recorded Coder behavior")
    coder_event = coder_events[-1]
    if coder_event.get("subject_digest") != contract_digest:
        raise EvidenceIntegrityError("Coder behavior is not bound to the approved contract")
    coder_blobs = coder_event.get("blob_digests")
    if not isinstance(coder_blobs, list) or len(coder_blobs) != 1:
        raise EvidenceIntegrityError("Coder response evidence is malformed")
    try:
        response = strict_loads(ledger.read_blob(coder_blobs[0]), "application/json")
    except CanonicalInputError as exc:
        raise EvidenceIntegrityError("Coder response evidence is malformed") from exc
    if not isinstance(response, Mapping):
        raise EvidenceIntegrityError("Coder response evidence is malformed")
    try:
        behavior = observe_provider_behavior(purpose="code", response=response)
    except ValueError as exc:
        raise EvidenceIntegrityError("Coder behavior evidence is malformed") from exc
    coder_payload = coder_event.get("payload")
    recorded_behavior = (
        coder_payload.get("provider_behavior") if isinstance(coder_payload, Mapping) else None
    )
    observed_behavior = asdict(behavior)
    required_behavior_fields = {
        "purpose",
        "request_digest",
        "output_digest",
        "provider",
        "model",
        "prompt_version",
    }
    if (
        not isinstance(recorded_behavior, Mapping)
        or not required_behavior_fields.issubset(recorded_behavior)
        or any(
            key not in observed_behavior or observed_behavior[key] != value
            for key, value in recorded_behavior.items()
        )
    ):
        raise EvidenceIntegrityError("normalized Coder behavior does not match its response")

    terminal = events[-1]
    if terminal.get("subject_digest") != contract_digest:
        raise EvidenceIntegrityError("release candidate is not bound to the approved contract")
    candidate_digest, _ = _candidate_manifest(ledger, terminal)
    return {
        "run_id": run_id,
        "contract_digest": contract_digest,
        "plan_digest": plan_digest,
        "candidate_digest": candidate_digest,
        "provider_behavior": observed_behavior,
        "events": len(events),
        "head_event_digest": events[-1].get("event_digest"),
    }


def _compare(args: argparse.Namespace) -> int:
    try:
        compiler_root = Path(args.compiler_root).resolve()
        baseline = _comparison_observation(
            Path(args.baseline_root),
            args.baseline_run_id,
            expected_approver=args.expected_approver,
            compiler_root=compiler_root,
        )
        current = _comparison_observation(
            Path(args.current_root),
            args.current_run_id,
            expected_approver=args.expected_approver,
            compiler_root=compiler_root,
        )
    except EvidenceIntegrityError as exc:
        return _evidence_invalid(exc)
    common: dict[str, Any] = {"baseline": baseline, "current": current}
    for field, cause in (
        ("contract_digest", "CONTRACT_CHANGED"),
        ("plan_digest", "PLAN_CHANGED"),
    ):
        if baseline[field] != current[field]:
            _json({"status": "NOT_COMPARABLE", "cause": cause, **common})
            return 3
    try:
        baseline_behavior = ProviderBehavior(
            **{
                key: baseline["provider_behavior"][key]
                for key in (
                    "purpose",
                    "request_digest",
                    "output_digest",
                    "provider",
                    "model",
                    "prompt_version",
                    "cli_version",
                )
            }
        )
        current_behavior = ProviderBehavior(
            **{
                key: current["provider_behavior"][key]
                for key in (
                    "purpose",
                    "request_digest",
                    "output_digest",
                    "provider",
                    "model",
                    "prompt_version",
                    "cli_version",
                )
            }
        )
        drift = compare_provider_behavior(baseline_behavior, current_behavior)
    except (KeyError, TypeError, ValueError):
        _json({"status": "NOT_COMPARABLE", "cause": "PROVIDER_REQUEST_CHANGED", **common})
        return 3
    _json(
        {
            "status": "COMPARABLE",
            "plan_repeatable": True,
            "candidate_variation": {
                "detected": baseline["candidate_digest"] != current["candidate_digest"],
                "baseline_digest": baseline["candidate_digest"],
                "current_digest": current["candidate_digest"],
            },
            "behavior_drift": asdict(drift),
            **common,
        }
    )
    return 0


def _safe_manifest_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _candidate_manifest(
    ledger: EvidenceLedger, terminal: Mapping[str, Any]
) -> tuple[str, dict[str, str]]:
    if terminal.get("event_type") != "release_ready" or terminal.get("state") != "RELEASE_READY":
        raise EvidenceIntegrityError("run has no sealed RELEASE_READY candidate")
    payload = terminal.get("payload")
    if not isinstance(payload, Mapping):
        raise EvidenceIntegrityError("release event payload is malformed")
    candidate_digest = payload.get("candidate_digest")
    blob_digests = terminal.get("blob_digests")
    if (
        not isinstance(candidate_digest, str)
        or not isinstance(blob_digests, list)
        or candidate_digest not in blob_digests
    ):
        raise EvidenceIntegrityError("release event does not bind a candidate manifest")
    try:
        decoded = strict_loads(ledger.read_blob(candidate_digest), "application/json")
    except CanonicalInputError as exc:
        raise EvidenceIntegrityError("candidate manifest is malformed") from exc
    if not isinstance(decoded, dict):
        raise EvidenceIntegrityError("candidate manifest must be an object")
    manifest: dict[str, str] = {}
    for path, digest in decoded.items():
        if (
            not isinstance(path, str)
            or not _safe_manifest_path(path)
            or not isinstance(digest, str)
        ):
            raise EvidenceIntegrityError("candidate manifest entry is malformed")
        ledger.read_blob(digest)
        if digest not in blob_digests:
            raise EvidenceIntegrityError("release event does not bind every candidate file")
        manifest[path] = digest
    return candidate_digest, manifest


def _workspace_comparison(workspace: Path, manifest: Mapping[str, str]) -> dict[str, Any]:
    if workspace.is_symlink():
        return {
            "status": "DRIFT",
            "missing": sorted(manifest),
            "changed": [],
            "untracked": [],
            "symlinks": ["."],
        }
    if not workspace.is_dir():
        return {
            "status": "DRIFT",
            "missing": sorted(manifest),
            "changed": [],
            "untracked": [],
            "symlinks": [],
        }
    observed: dict[str, str] = {}
    symlinks: list[str] = []

    def fail_scan(exc: OSError) -> None:
        raise EvidenceIntegrityError("candidate workspace cannot be inspected") from exc

    try:
        for directory, directory_names, file_names in os.walk(
            workspace,
            topdown=True,
            onerror=fail_scan,
            followlinks=False,
        ):
            directory_names.sort()
            file_names.sort()
            root = Path(directory)
            for name in tuple(directory_names):
                path = root / name
                if path.is_symlink():
                    symlinks.append(path.relative_to(workspace).as_posix())
                    directory_names.remove(name)
            for name in file_names:
                path = root / name
                relative = path.relative_to(workspace).as_posix()
                if path.is_symlink():
                    symlinks.append(relative)
                elif path.is_file():
                    observed[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    raise EvidenceIntegrityError(
                        "candidate workspace contains an unsupported filesystem entry"
                    )
    except OSError as exc:
        raise EvidenceIntegrityError("candidate workspace cannot be inspected") from exc
    missing = sorted(set(manifest) - set(observed))
    untracked = sorted(set(observed) - set(manifest))
    changed = sorted(
        path for path in set(manifest) & set(observed) if manifest[path] != observed[path]
    )
    return {
        "status": "MATCH" if not (missing or changed or untracked or symlinks) else "DRIFT",
        "missing": missing,
        "changed": changed,
        "untracked": untracked,
        "symlinks": sorted(symlinks),
    }


def _inspect(args: argparse.Namespace) -> int:
    try:
        ledger, events = _verified_events(args)
        approval = _approval_summary(events)
        candidate_digest, manifest = _candidate_manifest(ledger, events[-1])
        output: dict[str, Any] = {
            "run_id": args.run_id,
            "state": "RELEASE_READY",
            "candidate_digest": candidate_digest,
            "files": manifest,
            "approval": approval,
        }
        if args.file is not None:
            digest = manifest.get(args.file)
            if digest is None:
                raise EvidenceIntegrityError("selected file is not in the sealed candidate")
            try:
                content = ledger.read_blob(digest).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise EvidenceIntegrityError("selected candidate file is not UTF-8") from exc
            output["selected_file"] = {
                "path": args.file,
                "digest": digest,
                "content": content,
            }
        exit_code = 0
        if approval["status"] == "UNVERIFIED_DIRECT_CALL":
            output["release_eligible"] = False
            exit_code = 3
        elif approval["status"] == "VERIFIED":
            output["release_eligible"] = True
        if args.workspace is not None:
            comparison = _workspace_comparison(Path(args.workspace), manifest)
            output["workspace"] = comparison
            if comparison["status"] != "MATCH":
                exit_code = 3
        _json(output)
        return exit_code
    except EvidenceIntegrityError as exc:
        return _evidence_invalid(exc)


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = sub.add_parser(
        "barebones",
        help="compile, run, and inspect the six-state contract-to-RELEASE_READY journey",
    )
    commands = parser.add_subparsers(dest="barebones_command", required=True)

    compile_parser = commands.add_parser(
        "compile", help="compile a contract and report deterministic coverage"
    )
    compile_parser.add_argument("contract")
    compile_parser.add_argument("--repository-root", default=".")
    compile_parser.set_defaults(fn=_compile)

    run_parser = commands.add_parser("run", help="run one approved contract")
    run_parser.add_argument("contract")
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--repository-root", default=".")
    run_parser.add_argument("--approval-receipt", required=True)
    run_parser.add_argument(
        "--expected-approver",
        required=True,
        help="human identity that must exactly match contract approved_by",
    )
    run_parser.add_argument(
        "--provider-command",
        required=True,
        help="local ModelProvider command; receives and returns JSON over stdio",
    )
    run_parser.add_argument("--provider-timeout", type=int, default=960)
    run_parser.set_defaults(fn=_run)

    for name, function, help_text in (
        ("status", _status, "show the verified state of an existing run"),
        ("evidence", _evidence, "verify and locate an existing evidence chain"),
    ):
        inspection = commands.add_parser(name, help=help_text)
        inspection.add_argument("run_id")
        inspection.add_argument("--repository-root", default=".")
        inspection.set_defaults(fn=function)

    inspect_parser = commands.add_parser(
        "inspect", help="inspect the sealed candidate and optionally detect workspace drift"
    )
    inspect_parser.add_argument("run_id")
    inspect_parser.add_argument("--repository-root", default=".")
    inspect_parser.add_argument("--workspace")
    inspect_parser.add_argument("--file")
    inspect_parser.set_defaults(fn=_inspect)

    compare_parser = commands.add_parser(
        "compare", help="compare two verified RELEASE_READY provider runs"
    )
    compare_parser.add_argument("baseline_run_id")
    compare_parser.add_argument("current_run_id")
    compare_parser.add_argument("--baseline-root", default=".")
    compare_parser.add_argument("--current-root", default=".")
    compare_parser.add_argument(
        "--expected-approver",
        required=True,
        help="trusted human identity that both recorded approvals must match",
    )
    compare_parser.add_argument(
        "--compiler-root",
        default=".",
        help="trusted repository root used to deterministically recompile each contract",
    )
    compare_parser.set_defaults(fn=_compare)
