"""Small reusable local setup, connection check, and delivery commands."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .adapter import load_adapter_settings, load_normalized_run, map_normalized_run
from .integration import bind_baseline, connection_report
from .models import RunEnvelope, canonical_run_line
from .outbox import canonical_outbox_identity, enqueue, flush_resilient, http_post_sender


def load_envelope(path: Path, settings: Path | None) -> RunEnvelope:
    if settings is not None:
        return map_normalized_run(load_adapter_settings(settings), load_normalized_run(path))
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("run exceeds the 5 MB limit")
    return RunEnvelope.model_validate_json(path.read_bytes())


def queue_run(root: Path, run: RunEnvelope) -> Path:
    return enqueue(
        root,
        route="/api/monitoring/runs",
        identity=canonical_outbox_identity(
            "run", run.product.id, run.product.environment, run.run_id
        ),
        payload=run.model_dump(mode="json"),
    )


def write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("xb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pm-evals",
        description="Install, inspect, and connect product evaluations without changing product behavior.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "init", help="Create a labeled example and private queue; no production connection"
    )
    setup.add_argument("--directory", type=Path, required=True)
    for name in ("check", "submit"):
        command = commands.add_parser(name)
        command.add_argument("--run", type=Path, required=True)
        command.add_argument("--settings", type=Path)
        command.add_argument(
            "--baseline", type=Path, help="Explicitly selected canonical baseline envelope"
        )
        command.add_argument(
            "--baseline-digest",
            help="Verified server receipt digest for a previously stored baseline",
        )
        if name == "submit":
            command.add_argument("--outbox", type=Path, required=True)
    flush = commands.add_parser(
        "flush", help="Deliver queued evidence; failures cannot affect generation"
    )
    flush.add_argument("--outbox", type=Path, required=True)
    flush.add_argument("--url", required=True)
    flush.add_argument("--token-env", default="PM_EVALS_INGEST_TOKEN")
    flush.add_argument("--allow-delivery", action="store_true")
    watch = commands.add_parser(
        "watch", help="Watch explicitly selected normalized exports outside the product process"
    )
    watch.add_argument("--directory", type=Path, required=True)
    watch.add_argument("--settings", type=Path)
    watch.add_argument("--outbox", type=Path, required=True)
    watch.add_argument("--url", required=True)
    watch.add_argument("--token-env", default="PM_EVALS_INGEST_TOKEN")
    watch.add_argument("--allow-delivery", action="store_true")
    watch.add_argument("--interval", type=int, default=30)
    watch.add_argument("--once", action="store_true")
    linkedin = commands.add_parser(
        "linkedin", help="Export completed native dashboards without rerunning LinkedIn"
    )
    linkedin.add_argument("--repo", type=Path, required=True)
    linkedin.add_argument("--context", type=Path, required=True)
    linkedin.add_argument("--settings", type=Path, required=True)
    linkedin.add_argument("--outbox", type=Path, required=True)
    linkedin.add_argument("--url", required=True)
    linkedin.add_argument("--token-env", default="PM_EVALS_INGEST_TOKEN")
    linkedin.add_argument("--allow-delivery", action="store_true")
    linkedin.add_argument("--allow-monitoring-export", action="store_true")
    linkedin.add_argument("--interval", type=int, default=30)
    linkedin.add_argument("--once", action="store_true")
    serve = commands.add_parser(
        "serve", help="Run a local dashboard, without connecting any product"
    )
    serve.add_argument("--data-dir", type=Path)
    serve.add_argument("--demo", action="store_true")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--frontend-dir", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init":
            from .demo import build_demo_runs

            root = args.directory
            if root.exists():
                raise ValueError("choose a new directory; setup never overwrites existing files")
            root.mkdir(parents=True, mode=0o700)
            examples = build_demo_runs()
            write_private(root / "sample-run.json", canonical_run_line(examples[0]))
            write_private(
                root / "README.txt",
                b"Synthetic example only. Run pm-evals serve --demo to inspect the dashboard. Product connection and failure coverage are not verified.\n",
            )
            print(
                "Example installed. No real product connected. Start with: pm-evals serve --demo"
            )
            return 0
        if args.command == "serve":
            import uvicorn

            from pm_evals_api.app import create_app

            if not args.demo and args.data_dir is None:
                raise ValueError("select --demo or provide --data-dir")
            frontend = args.frontend_dir or Path(__file__).parents[3] / "frontend" / "dist"
            if not frontend.is_dir():
                frontend = Path(__file__).parent / "web"
            if frontend.is_dir():
                os.environ["PM_EVALS_FRONTEND_DIST"] = str(frontend)
            app = create_app(
                monitoring_data_dir=args.data_dir,
                monitoring_demo_mode=args.demo,
                monitoring_ingest_token=os.environ.get("PM_EVALS_INGEST_TOKEN"),
                monitoring_adjudication_token=os.environ.get("PM_EVALS_ADJUDICATION_TOKEN"),
                monitoring_viewer_token=os.environ.get("PM_EVALS_VIEWER_TOKEN"),
            )
            print(f"Local dashboard: http://127.0.0.1:{args.port}")
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            return 0
        if args.command in {"check", "submit"}:
            run = load_envelope(args.run, args.settings)
            if args.baseline:
                run = bind_baseline(
                    run, load_envelope(args.baseline, None), stored_digest=args.baseline_digest
                )
            report = connection_report(run)
            if args.command == "submit":
                queue_run(args.outbox, run)
                report["queued"] = True
                report["delivered"] = False
            print(json.dumps(report, indent=2))
            return 0
        if not args.allow_delivery:
            raise ValueError("network delivery requires --allow-delivery")
        token = os.environ.get(args.token_env, "")
        if not token:
            raise ValueError("the selected credential environment variable is empty")
        sender = http_post_sender(args.url, token)
        if args.command == "flush":
            result = flush_resilient(args.outbox, sender=sender)
            print(json.dumps(result))
            return 1 if result["pending"] or result["quarantined"] else 0
        if args.interval < 5:
            raise ValueError("worker interval must be at least five seconds")
        from .worker import collect_exports, collect_linkedin

        if args.command == "linkedin" and not args.allow_monitoring_export:
            raise ValueError("LinkedIn local export requires --allow-monitoring-export")
        while True:
            if args.command == "linkedin":
                collection = collect_linkedin(args.repo, args.context, args.settings, args.outbox)
            else:
                collection = collect_exports(args.directory, args.settings, args.outbox)
            result = flush_resilient(args.outbox, sender=sender)
            print(json.dumps({"collection": collection, "delivery": result}), flush=True)
            if args.once:
                return (
                    1 if collection["invalid"] or result["pending"] or result["quarantined"] else 0
                )
            time.sleep(args.interval)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        # Validation errors can contain input values. Keep private payloads and
        # credentials out of worker logs; the operator retains source artifacts.
        print(
            f"Connection stopped ({type(exc).__name__}). Check local inputs and configuration; product generation is unaffected."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
