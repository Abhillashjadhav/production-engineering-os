#!/usr/bin/env python3
"""Launch the repository's real ChatGPT-authenticated drift evidence matrix."""

from __future__ import annotations

import sys
from pathlib import Path


def _main() -> int:
    source_root = Path(__file__).resolve().parents[2] / "src"
    sys.path.insert(0, str(source_root))
    from pmpe.evals.real_behavior_drift_eval import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
