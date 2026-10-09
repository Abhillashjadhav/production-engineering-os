#!/usr/bin/env python3
"""Repeatable regression report over the frozen task-tracker entry; adds no new checks.

It runs the existing ``contract-file.py verify`` once, classifies the outcome from the
files that entry already writes, and compares the result with a previous report so
what changed since the last run is explicit. Classification:

* ``PASS``    - result.json present, every criterion PASS, no findings.
* ``FAIL``    - result.json present with at least one FAIL or finding.
* ``BLOCKED`` - no result.json; failure.json names the refusal (for example
  ``APPROVAL_BOUND_ARTIFACT_CHANGED`` or ``INCOMPATIBLE``). Blocked is never PASS.

The report is data for a human; it is not an approval, a release verdict, or a
substitute for the owner's freeze decision.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ENTRY = Path(__file__).with_name("contract-file.py")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def git_head(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def classify(output: Path, exit_code: int | None) -> dict[str, Any]:
    """Derive the outcome from the entry's own artifacts; never from the exit code alone."""
    result_path = output / "result.json"
    failure_path = output / "failure.json"
    if result_path.is_file():
        result = read_json(result_path)
        criteria = dict(result.get("criteria", {}))
        findings = list(result.get("findings", []))
        failed = sorted(k for k, v in criteria.items() if v != "PASS")
        outcome = "PASS" if criteria and not failed and not findings else "FAIL"
        return {
            "outcome": outcome,
            "criteria": criteria,
            "failed_criteria": failed,
            "finding_count": len(findings),
            "blocker": None,
            "exit_code": exit_code,
        }
    blocker = (
        read_json(failure_path)
        if failure_path.is_file()
        else {
            "error": "NO_RESULT",
            "detail": "the entry wrote neither result.json nor failure.json",
        }
    )
    return {
        "outcome": "BLOCKED",
        "criteria": {},
        "failed_criteria": [],
        "finding_count": 0,
        "blocker": blocker,
        "exit_code": exit_code,
    }


def compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return {"previous_report": None, "outcome_changed": None, "criteria_changed": {}}
    before = previous.get("criteria", {})
    after = current.get("criteria", {})
    changed = {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }
    return {
        "previous_report": previous.get("run_at"),
        "previous_outcome": previous.get("outcome"),
        "outcome_changed": previous.get("outcome") != current.get("outcome"),
        "criteria_changed": changed,
        "blocker_changed": previous.get("blocker") != current.get("blocker"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--freeze-digest", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="fresh directory for this run")
    parser.add_argument("--report", type=Path, required=True, help="where to write report.json")
    parser.add_argument("--previous", type=Path, help="an earlier report.json to diff against")
    parser.add_argument("--authorized-host-fallback", action="store_true")
    args = parser.parse_args()

    command = [
        sys.executable,
        str(ENTRY),
        "verify",
        "--packet",
        str(args.packet),
        *[arg for root in args.root for arg in ("--root", root)],
        "--freeze-digest",
        args.freeze_digest,
        "--candidate",
        str(args.candidate),
        "--output",
        str(args.output),
    ]
    if args.authorized_host_fallback:
        command.append("--authorized-host-fallback")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    roots = dict(item.split("=", 1) for item in args.root)
    report: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(),
        "entry": str(ENTRY),
        "freeze_digest": args.freeze_digest,
        "roots": {
            name: {"path": path, "head": git_head(Path(path))} for name, path in roots.items()
        },
        "candidate": str(args.candidate),
        "output": str(args.output),
        "stderr_tail": completed.stderr[-2000:],
        "mode": "retained-candidate replay; no model call; host fallback"
        if args.authorized_host_fallback
        else "retained-candidate replay; no model call",
    }
    report.update(classify(args.output, completed.returncode))
    previous = read_json(args.previous) if args.previous and args.previous.is_file() else None
    report["since_previous"] = compare(previous, report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "outcome": report["outcome"],
        "failed_criteria": report["failed_criteria"],
        "blocker": (report["blocker"] or {}).get("error") if report["blocker"] else None,
        "outcome_changed": report["since_previous"]["outcome_changed"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
