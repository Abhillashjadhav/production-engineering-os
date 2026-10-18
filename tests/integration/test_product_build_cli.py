"""Supported build configuration reaches the ordinary CLI runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.cli import barebones_cmd, main

ROOT = Path(__file__).parents[2]


def test_cli_passes_explicit_resource_caps_without_starting_a_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def capture(**kwargs: Any) -> Any:
        captured.update(kwargs)
        raise RuntimeError("TEST_RUNTIME_STOP")

    monkeypatch.setattr(barebones_cmd, "run_to_release_ready", capture)
    assert (
        main(
            [
                "barebones",
                "run",
                str(ROOT / "examples/barebones/e1-contract.json"),
                "--approval-receipt",
                str(ROOT / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                "never-executed",
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                "bounded-cli",
                "--max-wall-time",
                "12.5",
                "--max-input-tokens",
                "25",
                "--max-output-tokens",
                "10",
                "--max-attempts",
                "2",
                "--max-model-calls",
                "3",
                "--max-model-output-bytes",
                "500",
            ]
        )
        == 3
    )
    budget = captured["budget"]
    assert (budget.max_wall_time_seconds, budget.max_input_tokens, budget.max_output_tokens) == (
        12.5,
        25,
        10,
    )
    assert (budget.max_attempts, budget.max_model_calls, budget.max_model_output_bytes) == (
        2,
        3,
        500,
    )
    assert captured["enforce_quality"] is True
    assert json.loads(capsys.readouterr().out)["detail"] == "TEST_RUNTIME_STOP"


def test_compile_rejects_unbound_graph_as_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = tmp_path / "graph.json"
    graph.write_text('{"plan_digest":"sha256:wrong","tasks":[]}')
    assert (
        main(
            [
                "barebones",
                "compile",
                str(ROOT / "examples/barebones/e1-contract.json"),
                "--task-graph",
                str(graph),
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["cause"] == "CONTRACT_INVALID"
