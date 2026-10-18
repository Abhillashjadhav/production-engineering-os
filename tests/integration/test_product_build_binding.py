"""Canonical runtime joins protected profile, dependency context and evidence."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import ContractInvalidError, default_template, run_to_release_ready
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.product_profile import compile_product_profile

ROOT = Path(__file__).parents[2]


class Provider:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, Any]] = []

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requests.append(request)
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": "def health():\n    return {'status': 'ok'}\n"},
        }


class LogicSandbox:
    """Only tests supervisor wiring; supplies no isolation evidence."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls += 1
        status = "not_ready" if self.calls == 1 else "ok"
        return subprocess.CompletedProcess([], 0, json.dumps({"status": status}), "")


def _contract() -> dict[str, Any]:
    return dict(json.loads((ROOT / "examples/barebones/e1-contract.json").read_text()))


def test_runtime_binds_profile_graph_and_complete_checks_without_claiming_delivery(
    tmp_path: Path,
) -> None:
    provider = Provider()
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="bound",
        provider=provider,
        candidate_sandbox=LogicSandbox(),
        product_profile=compile_product_profile(
            "auto", contract=_contract(), template=default_template(), harness_plan=None
        ),
    )
    graph = provider.requests[0]["task_graph"]
    assert graph["execution_mode"] == "whole_candidate_with_dependency_context"
    assert graph["tasks"][0]["task_id"] == "WHOLE-CANDIDATE"
    assert graph["plan_digest"] == provider.requests[0]["plan"]["plan_digest"]
    events = list(EvidenceLedger.open_existing(tmp_path, "bound").verify())
    admitted = events[0]["payload"]
    assert admitted["product_profile"]["profile_id"] == "barebones-health-v1"
    assert admitted["task_graph_digest"] == graph["graph_digest"]
    report = next(e["payload"] for e in events if e["event_type"] == "required_checks_evaluated")
    assert report["binding"]["candidate_digest"] == result.annotation["candidate_digest"]
    assert report["binding"]["plan_digest"] == graph["plan_digest"]
    assert report["candidate_qualified"] is True
    assert report["delivery_qualified"] is False
    ledger = EvidenceLedger.open_existing(tmp_path, "bound")
    for check in report["results"]:
        if check["evidence_digest"] is not None:
            assert ledger.read_blob(check["evidence_digest"])
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"


def test_forged_profile_is_rejected_before_workspace_or_provider(tmp_path: Path) -> None:
    profile = compile_product_profile(
        "auto", contract=_contract(), template=default_template(), harness_plan=None
    )
    profile = replace(profile, criterion_ids=())
    provider = Provider()
    with pytest.raises(ContractInvalidError, match="profile"):
        run_to_release_ready(
            contract=_contract(),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="forged",
            provider=provider,
            product_profile=profile,
        )
    assert provider.requests == []
    assert not (tmp_path / ".pmpe").exists()


def test_graph_mismatch_is_rejected_before_workspace_or_provider(tmp_path: Path) -> None:
    provider = Provider()
    with pytest.raises(ContractInvalidError, match="task graph"):
        run_to_release_ready(
            contract=_contract(),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="graph",
            provider=provider,
            task_graph_mapping={"plan_digest": canonical_digest({}), "tasks": []},
        )
    assert provider.requests == []
    assert not (tmp_path / ".pmpe").exists()


def test_unicode_contract_remains_readable_after_actual_runtime(
    tmp_path: Path, capsys: Any
) -> None:
    from pmpe.cli import main

    contract = _contract()
    contract["functional_requirements"]["FR-001"]["statement"] += " café"
    profile = compile_product_profile(
        "auto", contract=contract, template=default_template(), harness_plan=None
    )
    run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="unicode",
        provider=Provider(),
        candidate_sandbox=LogicSandbox(),
        product_profile=profile,
    )
    assert main(["barebones", "status", "unicode", "--repository-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["cause"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
