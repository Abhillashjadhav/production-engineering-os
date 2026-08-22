"""CLI entry point for the frozen bare-bones core."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pmpe.barebones import ContractInvalidError, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.canonical import strict_loads


class CommandModelProvider:
    """ModelProvider that exchanges one JSON object with a local command."""

    def __init__(self, command: str, timeout_seconds: int) -> None:
        self.argv = tuple(shlex.split(command))
        if not self.argv:
            raise ValueError("provider command cannot be empty")
        self.timeout_seconds = timeout_seconds

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            completed = subprocess.run(
                self.argv,
                input=json.dumps({"purpose": purpose, "request": request}),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("MODEL_PROVIDER_TIMEOUT") from exc
        if completed.returncode != 0:
            raise RuntimeError("model provider failed: " + completed.stderr.strip())
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("model provider returned malformed JSON") from exc
        if not isinstance(response, dict):
            raise RuntimeError("model provider response must be an object")
        return response


def _run(args: argparse.Namespace) -> int:
    contract_path = Path(args.contract)
    content_type = (
        "application/yaml"
        if contract_path.suffix.lower() in {".yaml", ".yml"}
        else "application/json"
    )
    contract = strict_loads(contract_path.read_bytes(), content_type)
    try:
        result = run_to_release_ready(
            contract=contract,
            repository_root=Path(args.repository_root).resolve(),
            workspace=Path(args.workspace).resolve(),
            run_id=args.run_id,
            provider=CommandModelProvider(args.provider_command, args.provider_timeout),
        )
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
    parser.add_argument(
        "--provider-command",
        required=True,
        help="local ModelProvider command; receives and returns JSON over stdio",
    )
    parser.add_argument("--provider-timeout", type=int, default=120)
    parser.set_defaults(fn=_run)
