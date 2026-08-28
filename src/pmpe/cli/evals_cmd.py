"""CLI commands for agent/trajectory evals and drift comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from pmpe.agents.registry import AgentRegistry
from pmpe.domain.serialize import atomic_write_json
from pmpe.evals.drift import compare
from pmpe.evals.registry import load_eval_suite, run_agent_evals
from pmpe.evals.trajectory import evaluate_trajectory


def _cmd_evals_run(args: argparse.Namespace) -> int:
    failures = 0
    if args.suite in ("agents", "all"):
        registry = AgentRegistry(Path(args.agents_dir))
        suite = load_eval_suite(Path(args.evals_dir) / "agents")
        results = run_agent_evals(suite, registry)
        for rate_agent, rate in results.pass_rate_by_agent.items():
            print(f"agent {rate_agent}: pass rate {rate:.2f}")
        for failure in results.hard_gate_failures:
            print(f"HARD-GATE FAILURE: {failure}")
        failed = [r for r in results.results if not r.passed]
        for result in failed:
            print(f"FAIL {result.agent}:{result.case_id} — {result.detail}")
        failures += len(failed)
        if args.out:
            atomic_write_json(Path(args.out), results.to_dict())
            print(f"results written to {args.out}")
    if args.suite in ("trajectory", "all"):
        if not args.ledger:
            print("trajectory suite requires --ledger <ledger.jsonl>")
            return 2
        events = [
            json.loads(line) for line in Path(args.ledger).read_text().splitlines() if line.strip()
        ]
        violations = evaluate_trajectory(events)
        for violation in violations:
            print(
                f"TRAJECTORY VIOLATION {violation.check_id}: {violation.description} "
                f"({violation.evidence})"
            )
        failures += len(violations)
        if not violations:
            print("trajectory: no violations")
    print(f"eval run complete: {failures} failure(s)")
    return 0 if failures == 0 else 1


def _cmd_drift_compare(args: argparse.Namespace) -> int:
    baseline: dict[str, Any] = json.loads(Path(args.baseline).read_text())
    current: dict[str, Any] = json.loads(Path(args.current).read_text())
    thresholds: dict[str, Any] = yaml.safe_load(Path(args.thresholds).read_text())
    report = compare(baseline, current, thresholds)
    print(f"drift status: {report.status}")
    for item in report.items:
        marker = "HOLD" if item.hold else item.severity.upper()
        print(f"[{marker}] {item.category}: {item.description}")
    if args.out:
        atomic_write_json(Path(args.out), report)  # jsonable() handles the dataclass tree
    return 3 if report.status == "HOLD" else 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p_evals = sub.add_parser("evals", help="run agent/trajectory evals")
    evals_sub = p_evals.add_subparsers(dest="evals_command", required=True)

    p = evals_sub.add_parser("run", help="run an eval suite")
    p.add_argument("--suite", choices=["agents", "trajectory", "all"], default="agents")
    p.add_argument("--evals-dir", default="evals")
    p.add_argument("--agents-dir", default=".claude/agents")
    p.add_argument("--ledger", default=None, help="ledger.jsonl for the trajectory suite")
    p.add_argument("--out", default=None, help="write results JSON here")
    p.set_defaults(fn=_cmd_evals_run)

    p_drift = sub.add_parser("drift", help="drift measurement")
    drift_sub = p_drift.add_subparsers(dest="drift_command", required=True)

    p = drift_sub.add_parser("compare", help="compare current results against a baseline")
    p.add_argument("--baseline", required=True)
    p.add_argument("--current", required=True)
    p.add_argument("--thresholds", default="evals/thresholds.yaml")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=_cmd_drift_compare)
