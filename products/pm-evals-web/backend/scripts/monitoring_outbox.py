"""Enqueue and deliver monitoring evidence without losing failed sends."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from pm_evals_monitoring import (
    RunReceipt,
    load_adapter_settings,
    load_normalized_run,
    map_normalized_run,
)
from pm_evals_monitoring.outbox import (
    canonical_outbox_identity,
    enqueue,
    flush,
    http_post_sender,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outbox-dir", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    receipt = commands.add_parser("enqueue-receipt")
    receipt.add_argument("--receipt", type=Path, required=True)
    run = commands.add_parser("enqueue-run")
    run.add_argument("--settings", type=Path, required=True)
    run.add_argument("--run", type=Path, required=True)
    deliver = commands.add_parser("flush")
    deliver.add_argument("--base-url", required=True)
    deliver.add_argument("--token-env", default="PM_EVALS_INGEST_TOKEN")
    args = parser.parse_args()
    if args.command == "enqueue-receipt":
        model = RunReceipt.model_validate_json(args.receipt.read_bytes())
        enqueue(
            args.outbox_dir,
            route="/api/monitoring/receipts",
            identity=canonical_outbox_identity("receipt", model.receipt_id),
            payload=model.model_dump(mode="json"),
        )
        return 0
    if args.command == "enqueue-run":
        envelope = map_normalized_run(
            load_adapter_settings(args.settings), load_normalized_run(args.run)
        )
        enqueue(
            args.outbox_dir,
            route="/api/monitoring/runs",
            identity=canonical_outbox_identity(
                "run",
                envelope.product.id,
                envelope.product.environment,
                envelope.run_id,
            ),
            payload=envelope.model_dump(mode="json"),
        )
        return 0
    token = os.environ.get(args.token_env, "")
    if not token:
        raise RuntimeError(f"monitoring credential environment variable {args.token_env} is empty")
    print(flush(args.outbox_dir, sender=http_post_sender(args.base_url, token)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
