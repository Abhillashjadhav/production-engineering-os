"""The CLI is the primary interface: exit codes are part of the contract."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from pmpe.cli import main
from pmpe.config import PipelineConfig
from tests.conftest import mutate_contradictory
from tests.legacy_v1.workflow import WorkflowEngine

pytestmark = pytest.mark.e2e


def test_validate_golden_spec_exits_zero(golden_spec_path: Path) -> None:
    assert main(["validate", str(golden_spec_path)]) == 0


def test_validate_malformed_spec_exits_two(fixtures_dir: Path) -> None:
    assert main(["validate", str(fixtures_dir / "malformed_spec.yaml")]) == 2


def test_validate_contradictory_spec_exits_three(
    make_spec_file: Callable[..., Path],
) -> None:
    assert main(["validate", str(make_spec_file(mutate_contradictory))]) == 3


def test_historical_run_status_and_report_remain_read_only_cli_commands(
    golden_spec_path: Path, pipeline_workdir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = WorkflowEngine(
        PipelineConfig(
            runs_dir=pipeline_workdir,
            schema_path=repo_root / "schemas" / "mvp_spec.schema.json",
        )
    ).run(golden_spec_path)
    assert result.status == "success"

    assert main(["status", result.run_id, "--runs-dir", str(pipeline_workdir)]) == 0
    status_out = capsys.readouterr().out
    assert "report" in status_out and "done" in status_out

    assert main(["report", result.run_id, "--runs-dir", str(pipeline_workdir)]) == 0
    report_out = capsys.readouterr().out
    assert "FR-001" in report_out


def test_missing_file_exits_two(tmp_path: Path) -> None:
    assert main(["validate", str(tmp_path / "nope.yaml")]) == 2
