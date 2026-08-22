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
