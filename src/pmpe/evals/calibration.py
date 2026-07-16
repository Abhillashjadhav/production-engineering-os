"""Judge calibration: agreement with human labels, and the queue of verdicts
still awaiting a human label. Judges never self-calibrate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def agreement_report(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """pairs: [{case_id, judge, human}] with pass/fail verdicts (human may be None)."""
    labeled = [p for p in pairs if p.get("human") is not None]
    agree = sum(1 for p in labeled if p["judge"] == p["human"])
    judge_higher = sum(1 for p in labeled if p["judge"] == "pass" and p["human"] == "fail")
    judge_lower = sum(1 for p in labeled if p["judge"] == "fail" and p["human"] == "pass")
    return {
        "labeled": len(labeled),
        "unlabeled": len(pairs) - len(labeled),
        "agreement_rate": round(agree / len(labeled), 4) if labeled else None,
        "judge_higher": judge_higher,  # judge more lenient than humans
        "judge_lower": judge_lower,  # judge harsher than humans
    }


def queue_uncalibrated(pairs: list[dict[str, Any]], queue_path: Path) -> int:
    """Append every judge verdict lacking a human label to the calibration queue."""
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queued = 0
    with queue_path.open("a") as fh:
        for pair in pairs:
            if pair.get("human") is None:
                fh.write(json.dumps(pair, sort_keys=True) + "\n")
                queued += 1
    return queued
