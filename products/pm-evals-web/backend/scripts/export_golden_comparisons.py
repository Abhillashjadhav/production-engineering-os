"""Regenerate the frontend's golden comparison fixtures from the REAL engine.

The dashboard's component tests render these files (plan PR 8: "component
tests over golden fixture render"). They must never be hand-edited: this
script derives them deterministically from the committed product fixtures,
and a backend test pins the committed files byte-for-byte against fresh
engine output — hand-drift fails CI.

Usage: python scripts/export_golden_comparisons.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pm_evals_compare import CompareConfig, compare_runs, parse_run

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND.parent / "fixtures"
OUT = BACKEND.parent / "frontend" / "tests" / "fixtures"


def _run(name: str) -> tuple[object, str]:
    raw = (FIXTURES / name).read_bytes()
    result = parse_run(raw, source_name=name)
    assert result.run is not None, f"{name} must parse: {result.issues}"
    return result.run, "sha256:" + hashlib.sha256(raw).hexdigest()


def golden_comparisons() -> dict[str, str]:
    """Filename -> canonical JSON text for every golden fixture."""
    baseline, baseline_digest = _run("baseline.json")
    improved, improved_digest = _run("candidate_improved.json")
    regression, regression_digest = _run("candidate_regression.json")
    cases = {
        "comparison_improved.json": compare_runs(
            baseline,  # type: ignore[arg-type]
            improved,  # type: ignore[arg-type]
            baseline_digest=baseline_digest,
            candidate_digest=improved_digest,
        ),
        "comparison_regression.json": compare_runs(
            baseline,  # type: ignore[arg-type]
            regression,  # type: ignore[arg-type]
            baseline_digest=baseline_digest,
            candidate_digest=regression_digest,
        ),
        # the committed pair has 8 matched traces; requiring 20 yields the
        # genuine INSUFFICIENT_EVIDENCE verdict from the genuine engine
        "comparison_insufficient.json": compare_runs(
            baseline,  # type: ignore[arg-type]
            improved,  # type: ignore[arg-type]
            config=CompareConfig(min_matched_traces=20),
            baseline_digest=baseline_digest,
            candidate_digest=improved_digest,
        ),
    }
    return {
        name: json.dumps(comparison.model_dump(), indent=2, sort_keys=True) + "\n"
        for name, comparison in cases.items()
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in golden_comparisons().items():
        (OUT / name).write_text(text)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
