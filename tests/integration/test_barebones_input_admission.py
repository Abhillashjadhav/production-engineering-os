from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import ContractInvalidError
from pmpe.cli import barebones_cmd, build_options, main

_REPOSITORY = Path(__file__).parents[2]


@pytest.mark.parametrize("kind", ["contract", "receipt", "core", "graph"])
def test_input_paths_reject_symlinks(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "valid.json"
    target.write_text("{}")
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(target)

    def load() -> None:
        if kind == "contract":
            barebones_cmd._load_contract(symlink)
        elif kind == "core":
            barebones_cmd._load_core_harness_mapping(str(symlink))
        elif kind == "graph":
            build_options.load_task_graph(str(symlink))
        else:
            build_options.read_input_bytes(symlink, "approval receipt")

    with pytest.raises(ContractInvalidError):
        load()


def test_real_fifo_is_rejected_without_waiting_for_writer(tmp_path: Path) -> None:
    fifo = tmp_path / "contract.fifo"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(ContractInvalidError, match="regular file"):
        build_options.read_input_bytes(fifo, "contract")
    assert time.monotonic() - started < 1.0


def test_oversized_input_is_rejected_from_stat_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = tmp_path / "large.json"
    with oversized.open("wb") as stream:
        stream.seek(1_000_001)
        stream.write(b"x")

    def unexpected_read(_fd: int, _size: int) -> bytes:
        raise AssertionError("oversized file must not be read")

    monkeypatch.setattr(build_options.os, "read", unexpected_read)
    with pytest.raises(ContractInvalidError, match="size limit"):
        build_options.read_input_bytes(oversized, "contract")


def test_regular_approved_input_preserves_exact_receipt_bytes(tmp_path: Path) -> None:
    contract_path = _REPOSITORY / "examples/barebones/e1-contract.json"
    receipt_path = _REPOSITORY / "examples/barebones/e1-approval-receipt.json"
    receipt_source = receipt_path.read_bytes()
    assert build_options.read_input_bytes(receipt_path, "approval receipt") == receipt_source
    assert barebones_cmd._load_contract(contract_path)["contract_status"] == "APPROVED"

    core_path = tmp_path / "core.json"
    core_path.write_text(json.dumps({"marker": "core"}))
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps({"marker": "graph"}))
    assert barebones_cmd._load_core_harness_mapping(str(core_path)) == {"marker": "core"}
    assert build_options.load_task_graph(str(graph_path)) == {"marker": "graph"}


def test_run_rejects_symlink_receipt_before_provider(tmp_path: Path, capsys: Any) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.symlink_to(_REPOSITORY / "examples/barebones/e1-approval-receipt.json")
    code = main(
        [
            "barebones",
            "run",
            str(_REPOSITORY / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "receipt-symlink",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(receipt),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "must-not-run",
        ]
    )
    assert code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert not (tmp_path / "candidate").exists()
