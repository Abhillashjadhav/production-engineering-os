"""TEST ONLY: the supported approved-bundle path supplies the same process-gate inputs.

Bundles here are built from the approved-packet test fixture; no user approval is
created. The provider is an offline replay; no model is called.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BudgetCaps, default_template, run_to_release_ready
from pmpe.cli import main
from pmpe.process_sources import raw_digest
from tests.integration.test_process_gate_approval import approved_fixture
from tests.integration.test_process_gate_r4 import gates_for
from tests.integration.test_process_gate_runtime import LocalSandbox, ReplayProvider

ROOT = Path(__file__).resolve().parents[2]
REPLAY = """
import json, sys
request = json.load(sys.stdin)
marker = {marker!r}
open(marker, "a").write("called\\n")
json.dump({{"request_digest": request["request_digest"],
           "files": {{"product.py": "def health():\\n    return {{'status': 'ok'}}\\n"}}}},
          sys.stdout)
"""


def write_bundle(tmp_path: Path) -> tuple[Path, str, Any, dict[str, Any], bytes]:
    """Lay the fixture's approved packet out as a bundle directory."""
    inputs, approved, receipt_bytes = approved_fixture(tmp_path / "fixture")
    bundle = tmp_path / "bundle"
    approval: dict[str, str] = {}
    for key, source in inputs.approval_paths.items():
        relative = "approval/" + key + ".json"
        (bundle / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, bundle / relative)
        approval[key] = relative
    (bundle / "approval-freeze.json").write_bytes(inputs.approval_freeze)
    bindings = {k: v for k, v in asdict(default_template()).items() if k != "proofs"}
    (bundle / "bindings.json").write_text(json.dumps(bindings))
    (bundle / "execution-profile.json").write_bytes(inputs.execution_profile)
    controls: dict[str, str] = {}
    for identifier, snapshot in inputs.negative_controls.items():
        for relative, content in snapshot.items():
            target = bundle / "controls" / identifier / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        controls[identifier] = "controls/" + identifier
    source_paths = {
        name: {"root": "repository", "path": str(path.relative_to(ROOT))}
        for name, path in inputs.source_paths.items()
    }
    manifest = {
        "schema_version": "1",
        "approval": approval,
        "approval_freeze": "approval-freeze.json",
        "bindings": "bindings.json",
        "execution_profile": "execution-profile.json",
        "source_paths": source_paths,
        "negative_controls": controls,
        "generation": {
            "mode": inputs.generation_mode,
            "provider_attestation": dict(inputs.provider_attestation),
        },
        "real_sandbox_leg": dict(inputs.real_sandbox_leg),
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest, indent=2))
    return bundle, raw_digest(inputs.approval_freeze), inputs, approved, receipt_bytes


def load(bundle: Path, digest: str) -> Any:
    from pmpe.approved_bundle import load_approved_bundle

    return load_approved_bundle(bundle, freeze_digest=digest, roots={"repository": ROOT})


def test_bundle_reconstructs_the_exact_process_inputs(tmp_path: Path) -> None:
    bundle, digest, inputs, approved, receipt_bytes = write_bundle(tmp_path)
    loaded = load(bundle, digest)
    assert loaded.contract == approved
    assert loaded.receipt_bytes == receipt_bytes
    assert loaded.template == default_template()
    assert loaded.inputs.approval_freeze == inputs.approval_freeze
    assert loaded.inputs.approval_freeze_expected_digest == digest
    assert loaded.inputs.source_manifest == inputs.source_manifest
    assert loaded.inputs.execution_profile == inputs.execution_profile
    assert loaded.inputs.negative_controls == inputs.negative_controls
    assert loaded.inputs.generation_mode == inputs.generation_mode
    assert loaded.inputs.provider_attestation == inputs.provider_attestation
    assert loaded.inputs.real_sandbox_leg == inputs.real_sandbox_leg
    assert {k: p.resolve() for k, p in loaded.inputs.source_paths.items()} == {
        k: p.resolve() for k, p in inputs.source_paths.items()
    }


def test_bundle_run_matches_direct_library_verdicts(tmp_path: Path) -> None:
    bundle, digest, inputs, approved, receipt_bytes = write_bundle(tmp_path)
    loaded = load(bundle, digest)
    common = {
        "provider": None,
        "candidate_sandbox": None,
        "budget": BudgetCaps(max_attempts=1),
        "approval_receipt": json.loads(receipt_bytes),
        "approval_authority": "TEST-ONLY-fixture",
        "approval_receipt_bytes": receipt_bytes,
    }
    verdicts = {}
    for label, contract, gate_inputs in (
        ("direct", approved, inputs),
        ("bundle", loaded.contract, loaded.inputs),
    ):
        root = tmp_path / label
        result = run_to_release_ready(
            **{**common, "provider": ReplayProvider(), "candidate_sandbox": LocalSandbox()},
            contract=contract,
            repository_root=root,
            workspace=root / "candidate",
            run_id="bundle-equivalence",
            process_gate_inputs=gate_inputs,
        )
        verdicts[label] = (
            result.state,
            [(gate["gate_id"], gate["status"]) for gate in gates_for(root, result.run_id)],
        )
    assert verdicts["bundle"] == verdicts["direct"]
    assert ("GATE-003", "PASS") in verdicts["bundle"][1]


def run_cli(
    tmp_path: Path, bundle: Path, digest: str, *, approver: str = "TEST-ONLY-fixture"
) -> tuple[int, Path]:
    marker = tmp_path / "provider-called"
    script = tmp_path / "replay_provider.py"
    script.write_text(REPLAY.format(marker=str(marker)))
    code = main(
        [
            "barebones",
            "run-bundle",
            str(bundle),
            "--freeze-digest",
            digest,
            "--root",
            f"repository={ROOT}",
            "--run-id",
            "bundle-cli",
            "--workspace",
            str(tmp_path / "candidate"),
            "--repository-root",
            str(tmp_path / "evidence"),
            "--expected-approver",
            approver,
            "--provider-command",
            f"{sys.executable} {script}",
        ]
    )
    return code, marker


def refused_before_side_effects(
    tmp_path: Path, code: int, marker: Path, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    output: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert code == 3
    assert output["state"] == "HALTED" and output["cause"] == "CONTRACT_INVALID"
    assert not marker.exists()
    assert not (tmp_path / "candidate").exists()
    return output


@pytest.mark.parametrize(
    "artifact",
    ["approval/contract.json", "approval/receipt.json", "approval/mutant/broken.json"],
)
def test_tampered_bundle_artifact_is_refused_before_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], artifact: str
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    path = bundle / artifact
    path.write_bytes(path.read_bytes() + b"\n")
    code, marker = run_cli(tmp_path, bundle, digest)
    output = refused_before_side_effects(tmp_path, code, marker, capsys)
    assert "digest" in output["detail"]


def test_wrong_external_freeze_digest_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, _digest, *_ = write_bundle(tmp_path)
    code, marker = run_cli(tmp_path, bundle, "sha256:" + "0" * 64)
    output = refused_before_side_effects(tmp_path, code, marker, capsys)
    assert "freeze" in output["detail"]


def test_symlinked_or_escaping_bundle_paths_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    manifest = json.loads((bundle / "bundle.json").read_text())
    manifest["bindings"] = "../outside.json"
    (bundle / "bundle.json").write_text(json.dumps(manifest))
    code, marker = run_cli(tmp_path, bundle, digest)
    refused_before_side_effects(tmp_path, code, marker, capsys)

    bundle2, digest2, *_ = write_bundle(tmp_path / "second")
    target = bundle2 / "execution-profile.json"
    real = bundle2 / "profile-real.json"
    target.rename(real)
    os.symlink(real, target)
    code, marker = run_cli(tmp_path / "second", bundle2, digest2)
    refused_before_side_effects(tmp_path / "second", code, marker, capsys)


@pytest.mark.parametrize("field", ["negative_controls", "generation", "real_sandbox_leg"])
def test_missing_process_input_is_refused_before_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    manifest = json.loads((bundle / "bundle.json").read_text())
    del manifest[field]
    (bundle / "bundle.json").write_text(json.dumps(manifest))
    code, marker = run_cli(tmp_path, bundle, digest)
    refused_before_side_effects(tmp_path, code, marker, capsys)


def test_unknown_bundle_field_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    manifest = json.loads((bundle / "bundle.json").read_text())
    manifest["default_duration_minutes"] = 30
    (bundle / "bundle.json").write_text(json.dumps(manifest))
    code, marker = run_cli(tmp_path, bundle, digest)
    refused_before_side_effects(tmp_path, code, marker, capsys)


def test_approver_mismatch_is_refused_before_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    code, marker = run_cli(tmp_path, bundle, digest, approver="someone-else")
    refused_before_side_effects(tmp_path, code, marker, capsys)


def test_unprepared_interpreter_relaunches_source_only(tmp_path: Path) -> None:
    """The console entry point may start without -B; the command relaunches itself."""
    bundle, _digest, *_ = write_bundle(tmp_path)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}
    }
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; from pmpe.cli import main; raise SystemExit(main(sys.argv[1:]))",
            "barebones",
            "run-bundle",
            str(bundle),
            "--freeze-digest",
            "sha256:" + "0" * 64,
            "--root",
            f"repository={ROOT}",
            "--run-id",
            "relaunch",
            "--workspace",
            str(tmp_path / "candidate"),
            "--repository-root",
            str(tmp_path / "evidence"),
            "--expected-approver",
            "TEST-ONLY-fixture",
            "--provider-command",
            "false",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = json.loads(completed.stdout)
    # Reaching freeze verification proves the relaunched interpreter was admitted.
    assert completed.returncode == 3, completed.stderr
    assert "freeze" in output["detail"], output
    assert "source-only" not in output["detail"]


@pytest.mark.parametrize(
    ("measures", "files"),
    [
        ({"score": "product:health"}, {}),
        ({"score": "tests.judge:score"}, {"tests/judge.py": "def score(): ...\n"}),
    ],
    ids=["evaluator-in-product-code", "missing-package-initializer"],
)
def test_bindings_keep_evaluators_frozen_and_explicit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], measures: Any, files: Any
) -> None:
    bundle, digest, *_ = write_bundle(tmp_path)
    bindings = json.loads((bundle / "bindings.json").read_text())
    bindings["measures"] = measures
    bindings["files"].update(files)
    (bundle / "bindings.json").write_text(json.dumps(bindings))
    code, marker = run_cli(tmp_path, bundle, digest)
    output = refused_before_side_effects(tmp_path, code, marker, capsys)
    assert "bundle" in output["detail"]
