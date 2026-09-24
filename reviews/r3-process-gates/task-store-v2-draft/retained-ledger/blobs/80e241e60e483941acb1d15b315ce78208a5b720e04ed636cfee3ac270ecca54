"""CLI commands for ProductDecisionContracts and ProductChangeRequests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.contracts import canonical_digest, diff_contracts, load_contract
from pmpe.contracts.authoring import (
    approve_contract_draft,
    build_contract_draft,
    load_json_object,
    write_json_atomic,
)
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.domain.serialize import jsonable
from pmpe.engineering.handoff import start_approved_run


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


def _cmd_contract_draft(args: argparse.Namespace) -> int:
    result = build_contract_draft(load_json_object(Path(args.answers)))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        output / "source-map.json",
        {"schema_version": "1.0.0", "source_map": result.source_map},
    )
    if result.draft is None:
        write_json_atomic(
            output / "blocking-questions.json",
            {
                "questions": [question.as_dict() for question in result.blocking_questions],
                "schema_version": "1.0.0",
                "status": result.status,
            },
        )
        print(f"product input required: {len(result.blocking_questions)} blocking question(s)")
        print(f"questions: {output / 'blocking-questions.json'}")
        return 3
    write_json_atomic(output / "contract-draft.json", result.draft)
    write_json_atomic(
        output / "draft-summary.json",
        {
            "contract_id": result.draft["contract_id"],
            "contract_version": result.draft["contract_version"],
            "draft_digest": result.draft_digest,
            "schema_version": "1.0.0",
            "status": result.status,
        },
    )
    print(f"draft ready: {output / 'contract-draft.json'}")
    print(f"approve exact digest: {result.draft_digest}")
    return 0


def _cmd_contract_approve(args: argparse.Namespace) -> int:
    result = approve_contract_draft(
        load_json_object(Path(args.draft)),
        expected_draft_digest=args.expected_digest,
        approver=args.approver,
        approved_at=args.approved_at,
    )
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    contract_path = output / "contract-approved.json"
    receipt_path = output / "approval-receipt.json"
    write_json_atomic(contract_path, result.contract)
    write_json_atomic(receipt_path, result.receipt)
    print(f"approved contract: {contract_path}")
    print(f"approval receipt: {receipt_path}")
    print(f"approved contract digest: {result.receipt['approved_contract_digest']}")
    return 0


def _cmd_contract_handoff(args: argparse.Namespace) -> int:
    run = start_approved_run(
        contract_path=Path(args.contract),
        receipt_path=Path(args.receipt),
        expected_approver=args.expected_approver,
        run_dir=Path(args.run_dir),
        agents_dir=Path(args.agents_dir),
    )
    print(f"engineering run started: {run.status()['run_id']}")
    print(f"contract locked: {run.contract_digest}")
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

    p = contract_sub.add_parser(
        "draft", help="compile guided product answers into a reviewable draft contract"
    )
    p.add_argument("--answers", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(fn=_cmd_contract_draft)

    p = contract_sub.add_parser(
        "approve", help="approve a draft bound to its exact reviewed digest"
    )
    p.add_argument("--draft", required=True)
    p.add_argument("--expected-digest", required=True)
    p.add_argument("--approver", required=True)
    p.add_argument("--approved-at", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(fn=_cmd_contract_approve)

    p = contract_sub.add_parser(
        "handoff", help="lock an approved contract and start the PEOS engineering run"
    )
    p.add_argument("--contract", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--expected-approver", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--agents-dir", default=".claude/agents")
    p.set_defaults(fn=_cmd_contract_handoff)

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
