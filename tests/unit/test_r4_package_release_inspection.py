"""The package producer keeps its distinct, exact two-event release protocol."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from pmpe.evidence.ledger import EvidenceLedger
from pmpe.support_package import (
    PackageContractError,
    _load_release_candidate,
    assemble_support_package,
    load_support_package_contract,
    seal_support_release,
)
from tests.unit.test_r4_release_gate_inspection import _rechain

CONTRACT = Path("examples/support-package/contract.json")
RECEIPT = Path("examples/support-package/approval-receipt.json")


def test_r4_real_package_seal_and_assembly_remain_valid(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    sealed = seal_support_release(CONTRACT, RECEIPT, root, "package", "fixture-human")
    result = assemble_support_package(
        CONTRACT,
        RECEIPT,
        root,
        "package",
        sealed["head_event_digest"],
        "fixture-human",
        tmp_path / "bundle",
    )
    assert result.state == "PACKAGE_READY"


@pytest.mark.parametrize("mutation", ["interposed-event", "gate-event", "contract-subject"])
def test_r4_package_reader_rejects_order_or_identity_mutations(
    tmp_path: Path, mutation: str
) -> None:
    sealed = seal_support_release(CONTRACT, RECEIPT, tmp_path, "package", "fixture-human")
    assert sealed["state"] == "RELEASE_READY"
    ledger = EvidenceLedger.open_existing(tmp_path, "package")
    events = [dict(event) for event in ledger.verify()]
    if mutation == "contract-subject":
        events[0]["subject_digest"] = "sha256:" + "f" * 64
    else:
        extra = copy.deepcopy(events[0])
        extra.update(
            event_type="release_gates_evaluated" if mutation == "gate-event" else "unknown_event",
            state="VERIFYING",
            payload={},
            blob_digests=[],
        )
        events.insert(1, extra)
    _rechain(ledger, events)
    with pytest.raises(PackageContractError):
        _load_release_candidate(tmp_path, "package", load_support_package_contract(CONTRACT))
