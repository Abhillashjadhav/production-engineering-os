"""GitHub rejects a workflow whose job-level env uses the runner context.

The runner context exists only inside steps, so a job-level ``${{ runner.* }}``
invalidates the whole workflow and no check runs at all.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github/workflows").glob("*.yml"))
RUNNER_CONTEXT = re.compile(r"\$\{\{[^}]*\brunner\.")


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_job_level_env_uses_only_contexts_github_allows(workflow: Path) -> None:
    document: dict[str, Any] = yaml.safe_load(workflow.read_text())
    offenders = [
        f"{job_id}.env.{name}"
        for job_id, job in (document.get("jobs") or {}).items()
        for name, value in (job.get("env") or {}).items()
        if RUNNER_CONTEXT.search(str(value))
    ]
    assert offenders == [], offenders
