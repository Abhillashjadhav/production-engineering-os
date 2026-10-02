"""Proposed acceptance observer. It runs CLI commands and returns observations.

Install these exact approved bytes as tests/acceptance/task_tracker.py in the
template. Expected outcomes live in the contract. This is evaluation source,
not a generated task tracker, and has not yet been exercised against a product.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def _call(store: Path, arguments: list[str]) -> dict:
    product = Path(__file__).resolve().parents[2] / "product.py"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(product),
                "--store",
                str(store),
                *arguments,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": "timeout", "output": None}
    try:
        output = json.loads(completed.stdout)
    except (ValueError, UnicodeError):
        output = {"invalid_json": True}
    return {"exit_code": completed.returncode, "output": output}


def _state_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observe(
    steps: list[list[str]], fixture: str = "empty", setup: list[list[str]] | None = None
) -> dict:
    """Each command runs in a new process against one shared persistent store."""
    with tempfile.TemporaryDirectory(prefix="task-tracker-acceptance-") as temporary:
        root = Path(temporary)
        store = root / "tasks.json"
        if fixture == "corrupt":
            store.write_bytes(b"{invalid storage\n")
        elif fixture == "unwritable":
            # A file cannot be a parent directory, including for UID 0.
            blocker = root / "parent-is-a-file"
            blocker.write_text("fixture\n")
            store = blocker / "tasks.json"
        elif fixture != "empty":
            raise ValueError("unsupported acceptance fixture")
        setup_observations = [_call(store, arguments) for arguments in (setup or [])]
        before = _state_digest(store)
        observations = [_call(store, arguments) for arguments in steps]
        return {
            "setup_observations": setup_observations,
            "observations": observations,
            "store_unchanged": before == _state_digest(store),
            "process_count": len(setup_observations) + len(observations),
        }


def missing_acknowledged_records() -> dict:
    """Count missing records after ten strictly sequential creator processes.

    Each process exits before the next starts; concurrent creation is out of scope.
    The blocking _call below preserves this order. No parallel writers are tested.
    The approved workload is ten records. sample_size counts distinct valid creation
    acknowledgements, preventing an implementation that creates nothing from passing.
    This is a deterministic record-count measurement, not a statistical quality score.
    """
    with tempfile.TemporaryDirectory(prefix="task-tracker-measure-") as temporary:
        store = Path(temporary) / "tasks.json"
        nonce = uuid.uuid4().hex
        acknowledged = {}
        for index in range(10):
            title = f"measurement-{nonce}-{index}"
            response = _call(store, ["create", title])
            output = response["output"]
            task = output.get("task") if isinstance(output, dict) else None
            if (
                response["exit_code"] == 0
                and isinstance(task, dict)
                and type(task.get("id")) is int
                and task["id"] > 0
                and task.get("title") == title
                and task.get("status") == "open"
            ):
                acknowledged[task["id"]] = title
        response = _call(store, ["list", "--status", "all"])
        output = response["output"]
        tasks = output.get("tasks") if isinstance(output, dict) else None
        observed = {}
        if response["exit_code"] == 0 and isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and type(task.get("id")) is int:
                    observed[task["id"]] = task.get("title")
        missing = [
            identifier
            for identifier, title in acknowledged.items()
            if observed.get(identifier) != title
        ]
        return {
            "sample_size": len(acknowledged),
            "value": len(missing),
            "units": "records",
            "missing_ids": sorted(missing),
            "workload_size": 10,
        }
