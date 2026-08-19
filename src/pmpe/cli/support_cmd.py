"""Run and evaluate the customer-support workflow-discovery MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pmpe.domain.errors import SpecError
from pmpe.evals.support_corpus import (
    SupportCorpus,
    load_hidden_oracles,
    validate_support_corpus,
    write_support_corpus,
)
from pmpe.workflows.runtime import (
    compile_workflow,
    execute_workflow,
    write_workflow_report,
)
from pmpe.workflows.support import VisibleCorpusError, load_visible_cases
from pmpe.workflows.support_discovery import CustomerSupportDiscoveryAdapter


def _cmd_generate(args: argparse.Namespace) -> int:
    try:
        paths = write_support_corpus(Path(args.output), seed=args.seed)
    except VisibleCorpusError as exc:
        raise SpecError(str(exc)) from exc
    print(f"visible cases: {paths.visible_path}")
    print(f"eval-only oracles: {paths.oracle_path}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        cases = {item.case_id: item for item in load_visible_cases(Path(args.cases))}
    except VisibleCorpusError as exc:
        raise SpecError(str(exc)) from exc
    selected_id = args.case_id or sorted(cases)[0]
    case = cases.get(selected_id)
    if case is None:
        raise SpecError(f"unknown visible case: {selected_id}")
    adapter = CustomerSupportDiscoveryAdapter()
    contract = adapter.discover(case)
    plan = compile_workflow(contract)
    report = execute_workflow(case, contract, plan)
    paths = write_workflow_report(
        Path(args.output),
        case,
        contract,
        plan,
        report,
    )
    print(f"{report.case_id}: {report.selected_action} ({report.status})")
    print(f"report: {paths.markdown_path}")
    return 3 if report.status == "NEEDS_HUMAN_DECISION" else 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    try:
        all_cases = load_visible_cases(Path(args.cases))
        loaded_oracles = load_hidden_oracles(Path(args.oracles))
        validate_support_corpus(SupportCorpus(all_cases, loaded_oracles))
    except VisibleCorpusError as exc:
        raise SpecError(str(exc)) from exc
    oracles = {item.case_id: item for item in loaded_oracles}
    held_out_ids = {item.case_id for item in loaded_oracles if item.split == "held_out"}
    cases = tuple(item for item in all_cases if item.case_id in held_out_ids)
    adapter = CustomerSupportDiscoveryAdapter()
    evaluated = []
    for case in cases:
        contract = adapter.discover(case)
        plan = compile_workflow(contract)
        report = execute_workflow(case, contract, plan)
        evaluated.append((case, contract, report))
    exact = sum(
        report.selected_action == oracles[report.case_id].expected_outcome
        for _case, _contract, report in evaluated
    )
    complete = sum(
        report.evidence_complete
        and set(oracles[report.case_id].required_fact_ids) <= set(contract.action_fact_refs)
        and set(oracles[report.case_id].required_rule_ids) <= set(contract.action_rule_refs)
        for _case, contract, report in evaluated
    )
    unsafe = sum(
        report.status == "COMPLETED"
        and report.selected_action
        not in {
            policy.action
            for policy in case.policies
            if policy.rule_id in contract.action_rule_refs
            and policy.required_fact_id in contract.action_fact_refs
        }
        for case, contract, report in evaluated
    )
    total = len(evaluated)
    payload = {
        "evidence_completeness": complete / total,
        "exact_outcome_accuracy": exact / total,
        "held_out_cases": total,
        "schema_version": "1.0.0",
        "unsupported_autonomous_actions": unsafe,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        f"held-out exact outcome accuracy: {exact}/{total} "
        f"({payload['exact_outcome_accuracy']:.1%})"
    )
    return 0 if exact == total and complete == total and unsafe == 0 else 1


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
