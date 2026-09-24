"""Receipt-verified PMOS-to-PEOS engineering handoff."""

from __future__ import annotations

from pathlib import Path

from pmpe.engineering.engine import EngineeringRun


def start_approved_run(
    *,
    contract_path: Path,
    receipt_path: Path,
    expected_approver: str,
    run_dir: Path,
    agents_dir: Path,
) -> EngineeringRun:
    """Start PEOS only after the exact contract approval receipt verifies."""

    return EngineeringRun.start(
        contract_path,
        run_dir,
        agents_dir=agents_dir,
        approval_receipt_path=receipt_path,
        expected_approver=expected_approver,
    )
