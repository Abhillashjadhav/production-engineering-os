"""Map product-normalized facts into the shared monitoring envelope."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pm_evals_monitoring import (
    load_adapter_settings,
    load_normalized_run,
    map_normalized_run,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    envelope = map_normalized_run(
        load_adapter_settings(args.settings), load_normalized_run(args.run)
    )
    args.output.write_text(
        json.dumps(envelope.model_dump(mode="json"), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
