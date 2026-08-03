"""Legacy input validation and read-only run inspection commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from pmpe.config import PipelineConfig, packaged_schema_path
from pmpe.ingestion import ingest
from pmpe.orchestration import decoders
from pmpe.validation.validator import RequirementValidator


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


def _cmd_report(args: argparse.Namespace) -> int:
    config = _config(args)
    path = config.runs_dir / args.run_id / "artifacts" / "final_report.md"
    if not path.exists():
        print(f"no final report yet for {args.run_id} (run still in progress or blocked)")
        return 1
    print(path.read_text())
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Register non-mutating compatibility commands only."""
    p_validate = sub.add_parser("validate", help="validate a specification only")
    p_validate.add_argument("spec")
    p_validate.add_argument("--schema", default=None)
    p_validate.set_defaults(fn=_cmd_validate)

    for name, fn in (("status", _cmd_status), ("report", _cmd_report)):
        p = sub.add_parser(name, help=f"show run {name}")
        p.add_argument("run_id")
        p.add_argument("--runs-dir", default=None)
        p.add_argument("--config", default=None)
        p.set_defaults(fn=fn)
