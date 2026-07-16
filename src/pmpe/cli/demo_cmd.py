"""``pmpe demo`` — run the labeled synthetic end-to-end demonstration."""

from __future__ import annotations

import argparse
from pathlib import Path

from pmpe.demo.synthetic import run_demo


def _cmd_demo(args: argparse.Namespace) -> int:
    report = run_demo(
        Path(args.base_dir),
        contract=Path(args.contract),
        agents_dir=Path(args.agents_dir),
        evals_dir=Path(args.evals_dir),
    )
    print(report["label"])
    print(f"run {report['run_id']} -> {report['run_dir']}")
    print(f"code defect detected:      {report['detected']['code_defect']}")
    print(f"after fix:                 {report['detected']['code_defect_after_fix']}")
    print(
        f"traceability before/after: {report['traceability_before']} -> "
        f"{report['traceability_after']}"
    )
    print(f"complexity finding:        {report['detected']['complexity']}")
    print(f"planted trajectory:        {report['detected']['planted_trajectory']}")
    print(f"drift verdict:             {report['drift_status']}")
    print(f"reconciliation:            {report['reconciliation']}")
    print(f"retest:                    {report['retest']}")
    print(f"deployments:               {report['deployments']}")
    print(f"production blocked:        {report['production_blocked_reason']}")
    print(f"release verdict:           {report['release_verdict']}")
    print(f"report: {Path(args.base_dir) / 'demo-report.json'}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("demo", help="run the synthetic end-to-end demonstration")
    p.add_argument("--base-dir", required=True)
    p.add_argument("--contract", default="examples/v2-demo/contract.json")
    p.add_argument("--agents-dir", default=".claude/agents")
    p.add_argument("--evals-dir", default="evals")
    p.set_defaults(fn=_cmd_demo)
