"""V2 CLI contract: contract and change-request commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.cli import main

pytestmark = pytest.mark.e2e

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v2" / "contract_approved.json"


@pytest.fixture()
def contract_path(tmp_path: Path) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(FIXTURE.read_text())
    return path


def test_contract_validate_approved_exits_zero(
    contract_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["contract", "validate", str(contract_path)]) == 0
    assert "PDC-TEST-001" in capsys.readouterr().out


def test_contract_validate_draft_exits_three(tmp_path: Path, contract_path: Path) -> None:
    data: dict[str, Any] = json.loads(contract_path.read_text())
    data["contract_status"] = "DRAFT"
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(data))
    assert main(["contract", "validate", str(draft)]) == 3


def test_contract_validate_malformed_exits_two(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"contract_id": "X"}')
    assert main(["contract", "validate", str(bad)]) == 2


def test_contract_digest_and_diff(
    tmp_path: Path, contract_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["contract", "digest", str(contract_path)]) == 0
    digest = capsys.readouterr().out.strip()
    assert digest.startswith("sha256:")

    data: dict[str, Any] = json.loads(contract_path.read_text())
    data["contract_version"] = 2
    data["functional_requirements"].append({"id": "FR-002", "title": "History"})
    new = tmp_path / "v2.json"
    new.write_text(json.dumps(data))
    assert main(["contract", "diff", str(contract_path), str(new)]) == 0
    out = capsys.readouterr().out
    assert "FR-002" in out and "contract_version" in out


def test_change_request_cli_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = str(tmp_path / "run")
    code = main(
        [
            "change-request",
            "create",
            "--run-dir",
            run_dir,
            "--contract-id",
            "PDC-TEST-001",
            "--contract-version",
            "1",
            "--requirements",
            "FR-001",
            "--finding",
            "AC wording conflict",
            "--reason",
            "cannot proceed safely",
            "--option",
            "status only",
            "--option",
            "status + uptime",
            "--consequences",
            "journey differs",
            "--default",
            "status only",
            "--owner",
            "abhillash",
        ]
    )
    assert code == 0
    created = json.loads(capsys.readouterr().out)
    assert created["request_id"] == "PCR-001"

    assert main(["change-request", "list", "--run-dir", run_dir]) == 0
    assert "PCR-001 [OPEN]" in capsys.readouterr().out

    assert (
        main(
            [
                "change-request",
                "decide",
                "PCR-001",
                "--run-dir",
                run_dir,
                "--status",
                "APPROVED",
                "--resulting-version",
                "2",
            ]
        )
        == 0
    )
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "APPROVED"
    assert decided["resulting_contract_version"] == 2
