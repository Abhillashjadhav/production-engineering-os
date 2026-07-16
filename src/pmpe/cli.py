"""pmpe — the CLI of PM Production Engineering OS.

Exit codes (part of the contract): 0 success · 1 failure · 2 malformed specification ·
3 blocked on human gate / semantic errors
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pmpe.config import PipelineConfig, packaged_schema_path
from pmpe.domain.errors import PmpeError, SpecError
from pmpe.domain.serialize import jsonable
from pmpe.ingestion import ingest
from pmpe.orchestration import decoders
from pmpe.orchestration.workflow import WorkflowEngine
from pmpe.validation.validator import RequirementValidator

_EXIT_BY_OUTCOME = {"success": 0, "failed": 1, "blocked": 3}


def _config(args: argparse.Namespace) -> PipelineConfig:
    config = PipelineConfig.load(Path(args.config) if getattr(args, "config", None) else None)
    if getattr(args, "runs_dir", None):
        config.runs_dir = Path(args.runs_dir).resolve()
    return config


def _cmd_validate(args: argparse.Namespace) -> int:
    schema = Path(args.schema) if args.schema else packaged_schema_path()
    spec = ingest(Path(args.spec), schema)
    report = RequirementValidator().validate(spec)
    for issue in report.errors:
        print(f"ERROR   [{issue.code}] {issue.message}")
    for issue in report.questions:
        print(f"QUESTION[{issue.code}] {issue.message}")
    for issue in report.warnings:
        print(f"WARNING [{issue.code}] {issue.message}")
    if report.ok and not report.questions:
        print(
            f"specification OK: {spec.product_name} "
            f"({len(spec.functional_requirements)} requirements)"
        )
        return 0
    return 3


def _cmd_run(args: argparse.Namespace) -> int:
    result = WorkflowEngine(_config(args)).run(Path(args.spec))
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "status": result.status,
                "run_dir": str(result.run_dir),
            }
        )
    )
    return _EXIT_BY_OUTCOME.get(result.status, 1)


def _cmd_resume(args: argparse.Namespace) -> int:
    result = WorkflowEngine(_config(args)).resume(args.run_id)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "status": result.status,
                "run_dir": str(result.run_dir),
            }
        )
    )
    return _EXIT_BY_OUTCOME.get(result.status, 1)


def _cmd_approve(args: argparse.Namespace) -> int:
    approval = WorkflowEngine(_config(args)).approve(
        args.run_id,
        args.escalation_id,
        approver=args.approver,
        reason=args.reason,
        approved=not args.reject,
    )
    print(json.dumps(jsonable(approval)))
    print(f"recorded. resume with: pmpe resume {args.run_id}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    from pmpe.orchestration.state import RunState

    config = _config(args)
    state = RunState.load(config.runs_dir / args.run_id)
    print(f"run: {state.run_id}   outcome: {state.outcome or 'in progress'}")
    for name, record in state.steps.items():
        print(f"  {name:<16} {record.status.value:<8} {record.detail[:80]}")
    run_dir = config.runs_dir / args.run_id
    approvals = decoders.load_approvals(run_dir)
    for esc in decoders.load_escalations(run_dir):
        approval = approvals.get(esc.id)
        if approval is None:
            resolution = "OPEN"
        elif approval.approved:
            resolution = f"approved by {approval.approver}"
        else:
            resolution = f"REJECTED by {approval.approver}"
        print(f"  escalation {esc.id} [{esc.risk.value}] {resolution}: {esc.reason[:100]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmpe",
        description="Convert an approved PM OS MVP specification into tested, "
        "reviewed, deployable software.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a specification only")
    p_validate.add_argument("spec")
    p_validate.add_argument("--schema", default=None)
    p_validate.set_defaults(fn=_cmd_validate)

    for name, fn, needs_spec in (
        ("run", _cmd_run, True),
        ("resume", _cmd_resume, False),
    ):
        p = sub.add_parser(name, help=f"{name} the full pipeline")
        if needs_spec:
            p.add_argument("spec")
        else:
            p.add_argument("run_id")
        p.add_argument("--runs-dir", default=None)
        p.add_argument("--config", default=None)
        p.set_defaults(fn=fn)

    p_approve = sub.add_parser("approve", help="record a human decision on an escalation")
    p_approve.add_argument("run_id")
    p_approve.add_argument("escalation_id")
    p_approve.add_argument("--approver", required=True)
    p_approve.add_argument("--reason", required=True)
    p_approve.add_argument("--reject", action="store_true")
    p_approve.add_argument("--runs-dir", default=None)
    p_approve.add_argument("--config", default=None)
    p_approve.set_defaults(fn=_cmd_approve)

    p_status = sub.add_parser("status", help="show run status")
    p_status.add_argument("run_id")
    p_status.add_argument("--runs-dir", default=None)
    p_status.add_argument("--config", default=None)
    p_status.set_defaults(fn=_cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.fn(args)
    except SpecError as exc:
        print(f"specification rejected:\n{exc}", file=sys.stderr)
        return 2
    except PmpeError as exc:
        print(f"pipeline error: {exc}", file=sys.stderr)
        return 1
    return result


if __name__ == "__main__":
    sys.exit(main())
