"""``pmpe barebones run-bundle``: one approved bundle, one engine call.

The command starts the run in a source-only interpreter (owner decision
2026-09-25), verifies the whole bundle, checks the approver, and calls
``run_to_release_ready`` once with the bundle's template and process-gate inputs.
It adds no engine, product rule or sandbox of its own.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from pmpe.approved_bundle import BundleError, load_approved_bundle
from pmpe.barebones import BudgetCaps, ContractInvalidError, run_to_release_ready
from pmpe.cli.barebones_cmd import CommandModelProvider, _json, _require_approved_contract
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.process_sources import require_source_only_interpreter

_RELAUNCHED = "PMPE_SOURCE_ONLY_RELAUNCHED"
_LAUNCH = "import sys; from pmpe.cli import main; raise SystemExit(main(sys.argv[1:]))"


def _argv(args: argparse.Namespace) -> list[str]:
    values = ["barebones", "run-bundle", str(args.bundle), "--freeze-digest", args.freeze_digest]
    for root in args.root:
        values += ["--root", root]
    return values + [
        "--run-id",
        args.run_id,
        "--workspace",
        str(args.workspace),
        "--repository-root",
        str(args.repository_root),
        "--expected-approver",
        args.expected_approver,
        "--provider-command",
        args.provider_command,
        "--provider-timeout",
        str(args.provider_timeout),
    ]


def _relaunch_source_only(args: argparse.Namespace) -> None:
    """Replace this process with a source-only one; at most once."""
    try:
        require_source_only_interpreter()
        return
    except ValueError:
        if os.environ.get(_RELAUNCHED) == "1":
            return  # admission below reports the refusal instead of looping
    prefix = tempfile.mkdtemp(prefix="pmpe-source-only-")
    os.environ[_RELAUNCHED] = "1"
    sys.stdout.flush()
    os.execv(
        sys.executable,
        [sys.executable, "-B", "-X", "pycache_prefix=" + prefix, "-c", _LAUNCH, *_argv(args)],
    )


def _halted(detail: str) -> int:
    _json({"state": "HALTED", "cause": "CONTRACT_INVALID", "detail": detail})
    return 3


def _run_bundle(args: argparse.Namespace) -> int:
    _relaunch_source_only(args)
    try:
        require_source_only_interpreter()
        EvidenceLedger.validate_run_id(args.run_id)
        roots = {}
        for item in args.root:
            name, separator, directory = item.partition("=")
            if not separator or not name or not directory:
                raise BundleError("--root must be NAME=DIRECTORY")
            roots[name] = Path(directory)
        bundle = load_approved_bundle(
            Path(args.bundle), freeze_digest=args.freeze_digest, roots=roots
        )
        _require_approved_contract(bundle.contract, bundle.receipt, args.expected_approver)
        profile = strict_loads(bundle.inputs.execution_profile, "application/json")
        budget = (
            BudgetCaps(**profile["build_budget"])
            if isinstance(profile, dict) and isinstance(profile.get("build_budget"), dict)
            else BudgetCaps()
        )
        result = run_to_release_ready(
            contract=bundle.contract,
            repository_root=Path(args.repository_root).resolve(),
            workspace=Path(args.workspace).resolve(),
            run_id=args.run_id,
            provider=CommandModelProvider(args.provider_command, args.provider_timeout),
            template=bundle.template,
            budget=budget,
            approval_receipt=bundle.receipt,
            approval_authority=args.expected_approver,
            approval_receipt_bytes=bundle.receipt_bytes,
            process_gate_inputs=bundle.inputs,
        )
    except AcceptanceCompileError as exc:
        _json(
            {
                "state": "HALTED",
                "cause": "CONTRACT_INVALID",
                "diagnostics": [item.__dict__ for item in exc.diagnostics],
            }
        )
        return 3
    except EvidenceIntegrityError as exc:
        _json({"state": "HALTED", "cause": "EVIDENCE_INVALID", "detail": str(exc)})
        return 3
    except (BundleError, ContractInvalidError, CanonicalInputError, ValueError, TypeError) as exc:
        return _halted(str(exc))
    _json(
        {
            "run_id": result.run_id,
            "state": result.state,
            "cause": result.cause,
            "attempts": result.attempts,
            "model_calls": result.model_calls,
            "workspace": str(Path(args.workspace).resolve()),
            "evidence": str(result.evidence_path),
        }
    )
    return 0 if result.state == "RELEASE_READY" else 3


def register(commands: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = commands.add_parser(
        "run-bundle", help="run one approved bundle with its process-gate inputs"
    )
    parser.add_argument("bundle")
    parser.add_argument(
        "--freeze-digest",
        required=True,
        help="sha256 of the bundle's approval freeze, retained outside the bundle",
    )
    parser.add_argument(
        "--root", action="append", default=[], help="NAME=DIRECTORY for bundle source roots"
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--repository-root", default=".")
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
    parser.add_argument("--provider-timeout", type=int, default=960)
    parser.set_defaults(fn=_run_bundle)
