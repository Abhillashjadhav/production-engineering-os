from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pmpe.barebones import RunState, run_to_release_ready
from pmpe.cli import barebones_cmd, build_parser
from pmpe.cli.barebones_cmd import CommandModelProvider


def test_barebones_cli_runs_a_contract_without_cloud_services(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "cli-e1",
            "--repository-root",
            str(tmp_path),
            "--provider-command",
            f"{sys.executable} {repository / 'examples/barebones/e1-provider.py'}",
        ]
    )

    assert args.fn(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "RELEASE_READY"
    assert output["model_calls"] == 2


def test_provider_timeout_is_a_classified_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_run = barebones_cmd.subprocess.run

    def timeout(args: object, **kwargs: object) -> object:
        if args == ("provider",):
            raise barebones_cmd.subprocess.TimeoutExpired("provider", 1)
        return original_run(args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(barebones_cmd.subprocess, "run", timeout)
    repository = Path(__file__).parents[2]
    contract = json.loads((repository / "examples/barebones/e1-contract.json").read_text())
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="provider-timeout",
        provider=CommandModelProvider("provider", 1),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_PROVIDER_TIMEOUT"
    event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    assert event["event_type"] == "halted"
    assert event["payload"]["cause"] == "MODEL_PROVIDER_TIMEOUT"


def test_malformed_contract_is_reported_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = tmp_path / "malformed.json"
    contract.write_text("{not-json")
    args = build_parser().parse_args(
        [
            "barebones",
            str(contract),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "malformed-contract",
            "--repository-root",
            str(tmp_path),
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["diagnostics"][0]["code"] == "MALFORMED_SOURCE"


def test_non_empty_workspace_is_rejected_before_evidence_is_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "previous.txt").write_text("occupied")
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(workspace),
            "--run-id",
            "occupied-workspace",
            "--repository-root",
            str(tmp_path),
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["detail"] == "candidate workspace must be empty"
    assert not (tmp_path / ".pmpe" / "runs" / "occupied-workspace").exists()


def test_workspace_cannot_overlap_evidence_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(workspace),
            "--run-id",
            "overlapping-roots",
            "--repository-root",
            str(workspace),
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["detail"] == "candidate workspace must not overlap evidence storage"
    assert not (workspace / ".pmpe").exists()


def test_command_provider_rejects_non_json_numeric_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 0
        stdout = '{"request_digest":"bound","score":NaN}'
        stderr = ""

    monkeypatch.setattr(barebones_cmd.subprocess, "run", lambda *args, **kwargs: Completed())

    with pytest.raises(RuntimeError, match="malformed JSON"):
        CommandModelProvider("provider", 1).invoke(
            purpose="advisory_review", request={"request_digest": "bound"}
        )
