"""CLI entry point for the frozen bare-bones core."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import shlex
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.barebones import ContractInvalidError, compile_barebones_plan, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.domain.errors import ContractViolation
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger

_PROVIDER_OUTPUT_LIMIT_BYTES = 1_000_000


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
            "status": "VALIDATED",
            "coverage": {
                "structured": structured,
                "human_test": human,
                "total": len(plan.criteria),
            },
            "plan": plan.as_dict(),
        }
    )
    return 0


def _terminate_provider(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _run_provider_command(
    argv: tuple[str, ...],
    payload: bytes,
    timeout_seconds: int,
    output_limit_bytes: int = _PROVIDER_OUTPUT_LIMIT_BYTES,
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
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            _terminate_provider(process)
            raise RuntimeError("MODEL_PROVIDER_TIMEOUT") from exc
        except RuntimeError:
            _terminate_provider(process)
            raise
        finally:
            selector.close()
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
        completed = _run_provider_command(
            self.argv,
            json.dumps({"purpose": purpose, "request": request}).encode(),
            self.timeout_seconds,
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


def _verified_events(
    args: argparse.Namespace,
) -> tuple[EvidenceLedger, tuple[Mapping[str, Any], ...]]:
    ledger = EvidenceLedger.open_existing(Path(args.repository_root).resolve(), args.run_id)
    events = tuple(ledger.verify())
    if not events:
        raise EvidenceIntegrityError("evidence ledger is empty")
    return ledger, events


def _evidence_invalid(exc: EvidenceIntegrityError) -> int:
    _json({"state": "HALTED", "cause": "EVIDENCE_INVALID", "detail": str(exc)})
    return 3


def _status(args: argparse.Namespace) -> int:
    try:
        _, events = _verified_events(args)
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
        }
    )
    return 0


def _evidence(args: argparse.Namespace) -> int:
    try:
        ledger, events = _verified_events(args)
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
    try:
        for path in sorted(workspace.rglob("*")):
            relative = path.relative_to(workspace).as_posix()
            if path.is_symlink():
                symlinks.append(relative)
            elif path.is_file():
                observed[relative] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
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
        "symlinks": symlinks,
    }


def _inspect(args: argparse.Namespace) -> int:
    try:
        ledger, events = _verified_events(args)
        candidate_digest, manifest = _candidate_manifest(ledger, events[-1])
        output: dict[str, Any] = {
            "run_id": args.run_id,
            "state": "RELEASE_READY",
            "candidate_digest": candidate_digest,
            "files": manifest,
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
        if args.workspace is not None:
            comparison = _workspace_comparison(Path(args.workspace).resolve(), manifest)
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
    run_parser.add_argument("--provider-timeout", type=int, default=120)
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
