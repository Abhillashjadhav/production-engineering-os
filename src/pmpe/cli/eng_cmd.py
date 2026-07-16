"""``pmpe eng`` — drive an engineering run from the command line.

Thin argparse wrappers over :class:`pmpe.engineering.engine.EngineeringRun`;
every command loads the run from its directory (verifying the locked contract)
and returns the CLI's standard exit codes: 0 success, 1 pipeline error,
2 rejected/malformed input, 3 blocked on a human gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pmpe.assurance.reconcile import OwnerDecision
from pmpe.domain.errors import ContractViolation, SpecError
from pmpe.engineering.engine import DeploymentBlocked, EngineeringRun
from pmpe.evals.registry import STAGE_AGENTS
from pmpe.quality.test_evidence import run_tests_with_evidence


def _load(args: argparse.Namespace) -> EngineeringRun:
    return EngineeringRun.load(Path(args.run_dir))


def _read_json(path: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(Path(path).read_text())
    return loaded


def _cmd_start(args: argparse.Namespace) -> int:
    try:
        run = EngineeringRun.start(
            Path(args.contract), Path(args.run_dir), agents_dir=Path(args.agents_dir)
        )
    except ContractViolation as exc:
        print(str(exc))
        return 3  # blocked on a human gate: the contract is not runnable
    print(f"run {run.status()['run_id']} started at stage '{run.stage}'")
    print(f"contract locked: {run.contract_digest}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(_load(args).status(), indent=2))
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    run = _load(args)
    expected = ", ".join(STAGE_AGENTS.get(run.stage, ())) or "an engine-owned action"
    print(f"run resumed at stage '{run.stage}' (contract verified unchanged)")
    print(f"next: {expected}")
    return 0


def _cmd_assess(args: argparse.Namespace) -> int:
    _load(args).record_assessment(_read_json(args.artifact))
    return 0


def _cmd_submit(args: argparse.Namespace) -> int:
    run = _load(args)
    run.submit(args.agent, _read_json(args.artifact))
    print(f"'{args.agent}' artifact admitted; stage is now '{run.stage}'")
    return 0


def _cmd_freeze(args: argparse.Namespace) -> int:
    candidate = _load(args).freeze(Path(args.repo))
    print(f"candidate {candidate.candidate_id} frozen: {candidate.tree_digest}")
    return 0


def _cmd_review_begin(args: argparse.Namespace) -> int:
    _load(args).begin_review(args.agent, Path(args.repo))
    print(f"pre-review snapshot recorded for '{args.agent}'")
    return 0


def _cmd_review_end(args: argparse.Namespace) -> int:
    _load(args).end_review(args.agent, Path(args.repo))
    print(f"read-only check clean for '{args.agent}'")
    return 0


def _cmd_reconcile(args: argparse.Namespace) -> int:
    run = _load(args)
    decisions: dict[str, OwnerDecision] = {}
    if args.decisions:
        for finding_id, raw in _read_json(args.decisions).items():
            decisions[finding_id] = OwnerDecision(
                status=str(raw["status"]), owner=str(raw["owner"]), reason=str(raw["reason"])
            )
    result = run.reconcile_findings(decisions, owner=args.owner)
    if result.undecided:
        print("reconciliation blocked — undecided finding(s) require an owner decision:")
        for finding_id in result.undecided:
            print(f"  {finding_id}")
        return 3
    print(
        f"reconciled: accepted={result.accepted} rejected={result.rejected} "
        f"duplicates={result.duplicates} product_decisions={result.product_decisions}"
    )
    return 0


def _cmd_gates(args: argparse.Namespace) -> int:
    run = _load(args)
    workspace = Path(args.workspace)
    evidence = run_tests_with_evidence(workspace)
    executed = len(evidence.executions)
    passed_count = sum(1 for e in evidence.executions if e.outcome == "passed")
    detail = f"{passed_count}/{executed} executed tests passed"
    run.record_gates(repo=workspace, passed=evidence.all_passed, detail=detail)
    print(f"gates: {detail} -> {'pass' if evidence.all_passed else 'fail'}")
    return 0 if evidence.all_passed else 1


def _cmd_verify_fix(args: argparse.Namespace) -> int:
    _load(args).record_fix_verification(args.finding, verifier=args.verifier)
    print(f"{args.finding} verified by {args.verifier}")
    return 0


def _cmd_draft_pr(args: argparse.Namespace) -> int:
    _load(args).record_draft_pr(args.reference)
    return 0


def _cmd_approve_production(args: argparse.Namespace) -> int:
    approval = _load(args).approve_production(owner=args.owner, reason=args.reason)
    print(f"production approval recorded for candidate {approval.candidate_digest}")
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    run = _load(args)
    try:
        outcome = run.deploy(
            args.environment,
            repo=Path(args.repo),
            canary_healthy=not args.canary_fail,
            health_verified=args.health_verified,
            journey_verified=args.journey_verified,
        )
    except DeploymentBlocked as exc:
        print(str(exc))
        return 3
    report_line = getattr(outcome, "report_line", "")
    print(report_line or f"deployment to {args.environment} authorized")
    return 0


def _parse_gate_results(pairs: list[str]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for pair in pairs:
        gate_id, sep, value = pair.partition("=")
        if not sep or value.lower() not in ("pass", "fail"):
            raise SpecError(f"--gate expects ID=pass|fail, got '{pair}'")
        results[gate_id] = value.lower() == "pass"
    return results


def _cmd_report(args: argparse.Namespace) -> int:
    gate_results = _parse_gate_results(args.gate or [])
    _load(args).record_release_report(args.verdict, gate_results=gate_results)
    print(f"release report recorded: {args.verdict}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p_eng = sub.add_parser("eng", help="drive an engineering run (V2)")
    eng = p_eng.add_subparsers(dest="eng_command", required=True)

    def command(name: str, fn: Any, help_text: str) -> argparse.ArgumentParser:
        p: argparse.ArgumentParser = eng.add_parser(name, help=help_text)
        if name != "start":
            p.add_argument("--run-dir", required=True)
        p.set_defaults(fn=fn)
        return p

    p = command("start", _cmd_start, "lock a contract and open a run")
    p.add_argument("--contract", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--agents-dir", default=".claude/agents")

    command("status", _cmd_status, "print the run state as JSON")
    command("resume", _cmd_resume, "verify the run and print the next expected action")

    p = command("assess", _cmd_assess, "record the current-state assessment")
    p.add_argument("--artifact", required=True)

    p = command("submit", _cmd_submit, "submit an agent artifact for admission")
    p.add_argument("--agent", required=True)
    p.add_argument("--artifact", required=True)

    p = command("freeze", _cmd_freeze, "freeze the review candidate from a workspace")
    p.add_argument("--repo", required=True)

    p = command("review-begin", _cmd_review_begin, "snapshot the workspace before a review")
    p.add_argument("--agent", required=True)
    p.add_argument("--repo", required=True)

    p = command("review-end", _cmd_review_end, "verify the reviewer wrote nothing")
    p.add_argument("--agent", required=True)
    p.add_argument("--repo", required=True)

    p = command("reconcile", _cmd_reconcile, "reconcile review findings")
    p.add_argument("--owner", required=True)
    p.add_argument("--decisions", default=None, help="JSON: finding id -> {status,owner,reason}")

    p = command("gates", _cmd_gates, "run the workspace test suite as the retest gate")
    p.add_argument("--workspace", required=True)

    p = command("verify-fix", _cmd_verify_fix, "record independent fix verification")
    p.add_argument("--finding", required=True)
    p.add_argument("--verifier", required=True)

    p = command("draft-pr", _cmd_draft_pr, "record the draft PR reference")
    p.add_argument("--reference", required=True)

    p = command("approve-production", _cmd_approve_production, "record a named production approval")
    p.add_argument("--owner", required=True)
    p.add_argument("--reason", required=True)

    p = command("deploy", _cmd_deploy, "deploy up the environment ladder")
    p.add_argument("--environment", required=True)
    p.add_argument(
        "--repo", required=True, help="workspace to re-verify against the frozen candidate"
    )
    p.add_argument("--canary-fail", action="store_true", help="simulate a failing canary")
    p.add_argument(
        "--health-verified",
        action="store_true",
        help="attest the health check was verified (production readiness)",
    )
    p.add_argument(
        "--journey-verified",
        action="store_true",
        help="attest the user journey was verified (production readiness)",
    )

    p = command("report", _cmd_report, "record the release report and complete the run")
    p.add_argument("--verdict", required=True)
    p.add_argument(
        "--gate",
        action="append",
        metavar="ID=pass|fail",
        help="evaluation of one contract binary release gate (repeat per gate)",
    )
