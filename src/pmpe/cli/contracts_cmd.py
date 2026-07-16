"""CLI commands for ProductDecisionContracts and ProductChangeRequests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.contracts import canonical_digest, diff_contracts, load_contract
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.domain.serialize import jsonable


def _cmd_contract_validate(args: argparse.Namespace) -> int:
    contract = load_contract(Path(args.path))
    digest = canonical_digest(contract.raw)
    for blocker in contract.blockers:
        print(f"BLOCKER: {blocker}")
    if not contract.runnable:
        return 3
    print(
        f"contract OK: {contract.contract_id} v{contract.contract_version} "
        f"({len(contract.functional_requirements)} requirements) {digest}"
    )
    return 0


def _cmd_contract_digest(args: argparse.Namespace) -> int:
    contract = load_contract(Path(args.path))
    print(canonical_digest(contract.raw))
    return 0


def _cmd_contract_diff(args: argparse.Namespace) -> int:
    delta = diff_contracts(Path(args.old), Path(args.new))
    print(f"old: {delta.old_digest}")
    print(f"new: {delta.new_digest}")
    for label, entries in (
        ("added", delta.added),
        ("removed", delta.removed),
        ("changed", delta.changed),
    ):
        for entry in entries:
            print(f"{label}: {entry}")
    return 0


def _cmd_pcr_create(args: argparse.Namespace) -> int:
    store = ChangeRequestStore(Path(args.run_dir))
    pcr = store.create(
        source_contract_id=args.contract_id,
        source_contract_version=args.contract_version,
        affected_requirement_ids=args.requirements.split(",") if args.requirements else [],
        engineering_finding=args.finding,
        reason=args.reason,
        options=args.option,
        engineering_consequences=args.consequences,
        recommended_technical_default=args.default,
        decision_owner=args.owner,
    )
    print(json.dumps(jsonable(pcr)))
    return 0


def _cmd_pcr_list(args: argparse.Namespace) -> int:
    for pcr in ChangeRequestStore(Path(args.run_dir)).list():
        print(
            f"{pcr.request_id} [{pcr.status}] {pcr.source_contract_id} "
            f"v{pcr.source_contract_version} -> {pcr.engineering_finding[:80]}"
        )
    return 0


def _cmd_pcr_decide(args: argparse.Namespace) -> int:
    pcr = ChangeRequestStore(Path(args.run_dir)).decide(
        args.request_id,
        status=args.status,
        resulting_contract_version=args.resulting_version,
    )
    print(json.dumps(jsonable(pcr)))
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p_contract = sub.add_parser("contract", help="ProductDecisionContract operations")
    contract_sub = p_contract.add_subparsers(dest="contract_command", required=True)

    p = contract_sub.add_parser("validate", help="validate a contract and report blockers")
    p.add_argument("path")
    p.set_defaults(fn=_cmd_contract_validate)

    p = contract_sub.add_parser("digest", help="print the canonical contract digest")
    p.add_argument("path")
    p.set_defaults(fn=_cmd_contract_digest)

    p = contract_sub.add_parser("diff", help="requirement-level diff of two contract versions")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(fn=_cmd_contract_diff)

    p_pcr = sub.add_parser("change-request", help="ProductChangeRequest operations")
    pcr_sub = p_pcr.add_subparsers(dest="pcr_command", required=True)

    p = pcr_sub.add_parser("create", help="record a product decision engineering cannot make")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--contract-id", required=True)
    p.add_argument("--contract-version", type=int, required=True)
    p.add_argument("--requirements", default="", help="comma-separated FR ids")
    p.add_argument("--finding", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--option", action="append", required=True, help="repeatable")
    p.add_argument("--consequences", required=True)
    p.add_argument("--default", required=True, dest="default")
    p.add_argument("--owner", required=True)
    p.set_defaults(fn=_cmd_pcr_create)

    p = pcr_sub.add_parser("list", help="list change requests for a run")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(fn=_cmd_pcr_list)

    p = pcr_sub.add_parser("decide", help="record the owner's decision")
    p.add_argument("request_id")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--status", required=True, choices=["APPROVED", "REJECTED"])
    p.add_argument("--resulting-version", type=int, default=None)
    p.set_defaults(fn=_cmd_pcr_decide)
