"""CLI entry point for the frozen bare-bones core."""

from __future__ import annotations

import argparse
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
from pathlib import Path
from typing import Any

from pmpe.barebones import ContractInvalidError, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.domain.errors import ContractViolation
from pmpe.evidence.ledger import EvidenceIntegrityError

_PROVIDER_OUTPUT_LIMIT_BYTES = 1_000_000


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
        verify_contract_approval(
            dict(contract), dict(receipt), expected_approver=expected_approver
        )
    except ContractViolation as exc:
        raise ContractInvalidError(str(exc)) from exc


def _run(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    try:
        content_type = (
            "application/yaml"
            if contract_path.suffix.lower() in {".yaml", ".yml"}
            else "application/json"
        )
        contract = strict_loads(contract_path.read_bytes(), content_type)
        receipt = strict_loads(Path(args.approval_receipt).read_bytes(), "application/json")
        _require_approved_contract(contract, receipt, args.expected_approver)
        result = run_to_release_ready(
            contract=contract,
            repository_root=Path(args.repository_root).resolve(),
            workspace=Path(args.workspace).resolve(),
            run_id=args.run_id,
            provider=CommandModelProvider(args.provider_command, args.provider_timeout),
        )
    except CanonicalInputError as exc:
        print(
            json.dumps(
                {
                    "state": "HALTED",
                    "cause": "CONTRACT_INVALID",
                    "diagnostics": [{"code": exc.code, "message": str(exc)}],
                },
                sort_keys=True,
            )
        )
        return 3
    except AcceptanceCompileError as exc:
        print(
            json.dumps(
                {
                    "state": "HALTED",
                    "cause": "CONTRACT_INVALID",
                    "diagnostics": [item.__dict__ for item in exc.diagnostics],
                },
                sort_keys=True,
            )
        )
        return 3
    except ContractInvalidError as exc:
        print(json.dumps({"state": "HALTED", "cause": "CONTRACT_INVALID", "detail": str(exc)}))
        return 3
    except EvidenceIntegrityError as exc:
        print(json.dumps({"state": "HALTED", "cause": "EVIDENCE_INVALID", "detail": str(exc)}))
        return 3
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "state": result.state,
                "cause": result.cause,
                "attempts": result.attempts,
                "model_calls": result.model_calls,
                "elapsed_ms": result.elapsed_ms,
                "evidence": str(result.evidence_path),
                "annotation": result.annotation,
                "telemetry": result.telemetry,
            },
            sort_keys=True,
        )
    )
    return 0 if result.state == "RELEASE_READY" else 3


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = sub.add_parser(
        "barebones",
        help="compile a PMOS contract and stop at RELEASE_READY",
    )
    parser.add_argument("contract")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--approval-receipt", required=True)
    parser.add_argument(
        "--expected-approver",
        required=True,
        help="human identity that must exactly match contract approved_by",
    )
    parser.add_argument(
        "--provider-command",
        required=True,
        help="local ModelProvider command; receives and returns JSON over stdio",
    )
    parser.add_argument("--provider-timeout", type=int, default=120)
    parser.set_defaults(fn=_run)
