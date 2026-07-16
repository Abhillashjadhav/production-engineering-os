"""The synthetic demonstration: every planted failure caught, fixed where
accepted, and honestly reported — with production correctly blocked.

The demo is the OS's known-answer fixture at system scale: a workspace with
four planted defects goes through one complete engineering run, and this test
asserts each defect was detected by the real machinery (not by assertion in
the demo script), that only ACCEPTED findings were fixed, and that the run's
own evidence ledger is trajectory-clean.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.demo.synthetic import run_demo

from pmpe.cli import main

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    base = tmp_path_factory.mktemp("v2-demo")
    run_demo(
        base,
        contract=ROOT / "examples" / "v2-demo" / "contract.json",
        agents_dir=ROOT / ".claude" / "agents",
        evals_dir=ROOT / "evals",
    )
    loaded: dict[str, object] = json.loads((base / "demo-report.json").read_text())
    return loaded


def test_report_is_labeled_synthetic(report: dict[str, object]) -> None:
    assert report["synthetic"] is True
    assert "SYNTHETIC" in str(report["label"]).upper()


def test_planted_code_defect_detected_and_gone_after_fix(report: dict[str, object]) -> None:
    detected = report["detected"]
    assert isinstance(detected, dict)
    assert "SEC_EVAL" in str(detected["code_defect"])
    assert detected["code_defect_after_fix"] == "clean"


def test_planted_conformance_failure_detected_then_verified(report: dict[str, object]) -> None:
    before = report["traceability_before"]
    after = report["traceability_after"]
    assert isinstance(before, dict) and isinstance(after, dict)
    assert before["FR-001"] == "VERIFIED"
    assert before["FR-002"] == "NOT_PROVEN"  # markers never prove coverage; execution does
    assert after["FR-001"] == "VERIFIED"
    assert after["FR-002"] == "VERIFIED"


def test_planted_complexity_finding_detected(report: dict[str, object]) -> None:
    detected = report["detected"]
    assert isinstance(detected, dict)
    assert "factory" in str(detected["complexity"]).lower()


def test_planted_trajectory_and_drift_failures_detected(report: dict[str, object]) -> None:
    detected = report["detected"]
    assert isinstance(detected, dict)
    assert "TRAJ-03" in str(detected["planted_trajectory"])
    assert report["drift_status"] == "HOLD"


def test_reconciliation_split_engineering_from_product(report: dict[str, object]) -> None:
    reconciliation = report["reconciliation"]
    assert isinstance(reconciliation, dict)
    assert reconciliation["accepted"] == ["RF-001", "RF-002", "RF-004"]
    assert reconciliation["product_decisions"] == ["RF-003"]
    assert reconciliation["open_change_requests"] == ["PCR-001"]


def test_fixes_verified_by_someone_other_than_the_fixer(report: dict[str, object]) -> None:
    fixes = report["fixes"]
    assert isinstance(fixes, list) and len(fixes) == 3
    for fix in fixes:
        assert isinstance(fix, dict)
        assert fix["status"] == "VERIFIED"
        assert fix["verified_by"] != fix["fixed_by"]


def test_own_run_ledger_is_trajectory_clean(report: dict[str, object]) -> None:
    assert report["own_run_trajectory_violations"] == []


def test_deploy_ladder_blocks_production_honestly(report: dict[str, object]) -> None:
    deployments = report["deployments"]
    assert isinstance(deployments, dict)
    assert deployments["local"] == "authorized"
    assert deployments["staging"] == "authorized"
    assert report["production_blocked"] is True
    assert "approval" in str(report["production_blocked_reason"])
    assert report["release_verdict"] == "READY_FOR_PRODUCTION_APPROVAL"


def test_demo_cli_runs_and_prints_synthetic_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        [
            "demo",
            "--base-dir",
            str(tmp_path / "demo"),
            "--contract",
            str(ROOT / "examples" / "v2-demo" / "contract.json"),
            "--agents-dir",
            str(ROOT / ".claude" / "agents"),
            "--evals-dir",
            str(ROOT / "evals"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "SYNTHETIC" in out
    assert "production" in out and "blocked" in out
    assert (tmp_path / "demo" / "demo-report.json").exists()
