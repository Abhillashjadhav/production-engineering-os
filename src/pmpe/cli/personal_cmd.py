"""CLI for governed Personal Execution OS workflow packs."""

from __future__ import annotations

import argparse
from pathlib import Path

from pmpe.domain.errors import SpecError
from pmpe.personal.executor import (
    PersonalExecutionError,
    load_personal_context,
    run_personal_execution,
    write_personal_execution,
)
from pmpe.personal.planner import WORKFLOW_ORDER
from pmpe.personal.runtime.demo import run_runtime_demo
from pmpe.personal.synthetic import write_synthetic_personal_context


def _cmd_generate(args: argparse.Namespace) -> int:
    path = write_synthetic_personal_context(Path(args.output), args.seed)
    print(f"synthetic governed workflow request: {path}")
    return 0


def _cmd_starter(args: argparse.Namespace) -> int:
    path = write_synthetic_personal_context(Path(args.output), args.seed, workflow_ids=(args.pack,))
    print(f"synthetic {args.pack} starter: {path}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    context = load_personal_context(Path(args.input))
    print(f"workflow request OK: {context['request_id']} ({len(context['workflow_ids'])} packs)")
    return 0


def _run(context_path: Path, output: Path) -> int:
    try:
        context = load_personal_context(context_path)
        execution = run_personal_execution(context)
        paths = write_personal_execution(output, execution)
    except PersonalExecutionError as exc:
        raise SpecError(str(exc)) from exc
    print(f"{len(execution.results)} workflow packs completed in parallel")
    print(f"status: {execution.report.status}")
    print(f"pending approvals: {len(execution.approvals)}")
    print(f"unauthorized external actions: {execution.report.unauthorized_external_actions}")
    print(f"report: {paths['report']}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    return _run(Path(args.context), Path(args.output))


def _cmd_quickstart(args: argparse.Namespace) -> int:
    output = Path(args.output)
    context = write_synthetic_personal_context(output, args.seed)
    return _run(context, output)


def _cmd_runtime_quickstart(args: argparse.Namespace) -> int:
    paths = run_runtime_demo(Path(args.output))
    print("governed personal runtime demo completed with local fakes")
    print("external writes: 0")
    print(f"report: {paths['report']}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    personal = sub.add_parser(
        "personal-workflows",
        aliases=["personal-demo"],
        help="run 21 evidence-led workflow packs in parallel",
    )
    commands = personal.add_subparsers(dest="personal_command", required=True)
    generate = commands.add_parser("generate", help="generate synthetic personal context")
    generate.add_argument("--seed", type=int, default=2026)
    generate.add_argument("--output", required=True)
    generate.set_defaults(fn=_cmd_generate)
    starter = commands.add_parser("starter", help="generate one pack-specific starter")
    starter.add_argument("--pack", required=True, choices=WORKFLOW_ORDER)
    starter.add_argument("--seed", type=int, default=2026)
    starter.add_argument("--output", required=True)
    starter.set_defaults(fn=_cmd_starter)
    validate = commands.add_parser("validate", help="validate a user workflow request")
    validate.add_argument("--input", required=True)
    validate.set_defaults(fn=_cmd_validate)
    run = commands.add_parser("run", help="run all personal workflows")
    run.add_argument("--context", required=True)
    run.add_argument("--output", required=True)
    run.set_defaults(fn=_cmd_run)
    quickstart = commands.add_parser("quickstart", help="generate and run the complete demo")
    quickstart.add_argument("--seed", type=int, default=2026)
    quickstart.add_argument("--output", required=True)
    quickstart.set_defaults(fn=_cmd_quickstart)

    runtime = sub.add_parser(
        "personal-runtime", help="exercise governed runtime adapters with local fakes"
    )
    runtime_commands = runtime.add_subparsers(dest="personal_runtime_command", required=True)
    runtime_quickstart = runtime_commands.add_parser(
        "quickstart", help="run calendar, worker, registry, recovery, and learning controls"
    )
    runtime_quickstart.add_argument("--output", required=True)
    runtime_quickstart.set_defaults(fn=_cmd_runtime_quickstart)
