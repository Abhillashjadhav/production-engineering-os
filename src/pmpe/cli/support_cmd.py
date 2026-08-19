"""Run and evaluate the customer-support workflow-discovery MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.evals.support_corpus import load_hidden_oracles, write_support_corpus
from pmpe.workflows.runtime import (
    compile_workflow,
    execute_workflow,
    write_workflow_report,
)
from pmpe.workflows.support import load_visible_cases
from pmpe.workflows.support_discovery import CustomerSupportDiscoveryAdapter


def _cmd_generate(args: argparse.Namespace) -> int:
    paths = write_support_corpus(Path(args.output), seed=args.seed)
    print(f"visible cases: {paths.visible_path}")
    print(f"eval-only oracles: {paths.oracle_path}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    cases = {item.case_id: item for item in load_visible_cases(Path(args.cases))}
    selected_id = args.case_id or sorted(cases)[0]
    case = cases.get(selected_id)
    if case is None:
        raise ValueError(f"unknown visible case: {selected_id}")
    contract = CustomerSupportDiscoveryAdapter().discover(case)
    plan = compile_workflow(contract)
    report = execute_workflow(case, contract, plan)
    paths = write_workflow_report(Path(args.output), case, contract, plan, report)
    print(f"{report.case_id}: {report.selected_action} ({report.status})")
    print(f"report: {paths.markdown_path}")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    cases = tuple(item for item in load_visible_cases(Path(args.cases)) if item.split == "held_out")
    oracles = {item.case_id: item for item in load_hidden_oracles(Path(args.oracles))}
    if not cases or any(item.case_id not in oracles for item in cases):
        raise ValueError("held-out cases and explicit evaluation oracles do not match")
    adapter = CustomerSupportDiscoveryAdapter()
    reports = []
    for case in cases:
        contract = adapter.discover(case)
        plan = compile_workflow(contract)
        reports.append(execute_workflow(case, contract, plan))
    exact = sum(
        report.selected_action == oracles[report.case_id].expected_outcome for report in reports
    )
    complete = sum(report.evidence_complete for report in reports)
    unsafe = sum(
        report.selected_action not in {"escalate", "request_evidence"}
        and report.status != "COMPLETED"
        for report in reports
    )
    payload = {
        "evidence_completeness": complete / len(reports),
        "exact_outcome_accuracy": exact / len(reports),
        "held_out_cases": len(reports),
        "schema_version": "1.0.0",
        "unsupported_autonomous_actions": unsafe,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"held-out exact outcome accuracy: {exact}/{len(reports)} "
        f"({payload['exact_outcome_accuracy']:.1%})"
    )
    return 0 if exact == len(reports) and complete == len(reports) and unsafe == 0 else 1


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    support = sub.add_parser("support-demo", help="run the support workflow MVP")
    commands = support.add_subparsers(dest="support_command", required=True)
    generate = commands.add_parser("generate", help="generate the synthetic corpus")
    generate.add_argument("--seed", type=int, default=110)
    generate.add_argument("--output", required=True)
    generate.set_defaults(fn=_cmd_generate)
    run = commands.add_parser("run", help="compile and execute one visible case")
    run.add_argument("--cases", required=True)
    run.add_argument("--case-id", default=None)
    run.add_argument("--output", required=True)
    run.set_defaults(fn=_cmd_run)
    evaluate = commands.add_parser("evaluate", help="score held-out cases against eval truth")
    evaluate.add_argument("--cases", required=True)
    evaluate.add_argument("--oracles", required=True)
    evaluate.add_argument("--output", required=True)
    evaluate.set_defaults(fn=_cmd_evaluate)
