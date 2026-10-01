"""Fixed reference registry for PMOS's approved local task-tracker cases.

This registry is deliberately one named example, not an arbitrary adapter
loader. The historical observer bytes are unchanged; the new wrapper is
separately versioned and both identities must match the mapped contract.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pmpe.barebones import Template

REGISTRY_NAME = "pmos-task-tracker-v1"
REGISTRY_VERSION = "1"
EVALUATOR_SHA256 = "sha256:7a5a3064d8ec07ae1d941aaa2145330076c8acf62bbbc7cc65e158b9f9cf4d66"
ACTION_TARGET = "pmpe_task_tracker:observe"
MEASURE_TARGET = "pmpe_task_tracker:missing_acknowledged_records"
BASELINE_SOURCE = (
    '"""Protocol-valid meaningful-RED task-tracker skeleton."""\n'
    "import json\n"
    "import sys\n"
    "print(json.dumps({'error': 'NOT_IMPLEMENTED'}))\n"
    "raise SystemExit(2)\n"
)


def _source_bytes(name: str) -> bytes:
    return files("pmpe").joinpath(name).read_bytes()


def runner_source() -> str:
    evaluator = _source_bytes("task_tracker_evaluator_source.txt")
    if "sha256:" + hashlib.sha256(evaluator).hexdigest() != EVALUATOR_SHA256:
        raise RuntimeError("fixed task-tracker evaluator source changed")
    wrapper = _source_bytes("task_tracker_wrapper_source.txt")
    return evaluator.decode("utf-8") + "\n" + wrapper.decode("utf-8")


def registry_identity() -> dict[str, Any]:
    wrapper = _source_bytes("task_tracker_wrapper_source.txt")
    return {
        "name": REGISTRY_NAME,
        "version": REGISTRY_VERSION,
        "evaluator_digest": EVALUATOR_SHA256,
        "wrapper_digest": "sha256:" + hashlib.sha256(wrapper).hexdigest(),
        "baseline_digest": "sha256:" + hashlib.sha256(BASELINE_SOURCE.encode()).hexdigest(),
        "action_target": ACTION_TARGET,
        "measure_target": MEASURE_TARGET,
    }


def fixed_template() -> Template:
    """Return the one packaged binding through the existing Template API."""

    from pmpe.barebones import Template

    return Template(
        version=REGISTRY_NAME,
        files={"product.py": BASELINE_SOURCE},
        actions={"task_tracker.observe": ACTION_TARGET},
        context={"acceptance": {"ready": True}},
        measures={"task_tracker.missing_acknowledged_records": MEASURE_TARGET},
    )
