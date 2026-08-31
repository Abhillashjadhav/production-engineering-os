from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_recorded_agent_runs_in_a_scrubbed_linux_process(tmp_path: Path) -> None:
    output_root = tmp_path / "recorded-agent-output"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/recorded-tool-agent/run.py"),
            str(output_root),
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src")},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "cause": "PASS",
        "deployment_authority": False,
        "evidence_path": str(output_root / ".pmpe/runs/recorded-agent-example/events.jsonl"),
        "output": "Customers can request a refund within 30 calendar days of purchase.",
        "run_id": "recorded-agent-example",
        "state": "RELEASE_READY",
    }
    assert Path(result["evidence_path"]).is_file()
