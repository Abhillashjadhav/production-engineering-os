"""A product package follows the exact sealed candidate, without claiming delivery."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from pmpe.cli import main
from pmpe.contracts.canonical import canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.product_package import (
    ProductPackageError,
    _read_bundle_files,
    assemble_product_package,
    verify_product_package,
)


def test_package_credential_scan_does_not_reject_task_tracker_paths() -> None:
    from pmpe import product_package

    assert (
        product_package._CREDENTIAL.search(b"/tmp/task-tracker-acceptance-7e4af/tasks.json") is None
    )
    for value in (b"sk-" + b"A" * 24, b"AKIA" + b"D" * 16, b"-----BEGIN PRIVATE KEY-----"):
        assert product_package._CREDENTIAL.search(value)


def _sealed_run(
    root: Path,
    *,
    candidate_path: str = "product.py",
    content: bytes = b"def health():\n    return {'status': 'ok'}\n",
) -> tuple[str, str]:
    ledger = EvidenceLedger(root, "run")
    file_digest = ledger.put_blob(content)
    manifest_digest = ledger.put_blob(canonical_json_bytes({candidate_path: file_digest}))
    terminal = ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest="sha256:" + "1" * 64,
        blob_digests=(file_digest, manifest_digest),
        payload={"candidate_digest": manifest_digest},
    )
    return str(terminal["event_digest"]), manifest_digest


def test_product_package_requires_bound_profile_and_clean_evidence(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path)
    result = assemble_product_package(tmp_path, "run", head, tmp_path / "package")

    assert result.status == "BLOCKED"
    assert "PROFILE_NOT_BOUND" in result.blockers
    manifest = json.loads((result.bundle / "product-package.json").read_text())
    assert manifest["source"]["candidate_digest"].startswith("sha256:")
    assert manifest["source"]["files"]["product.py"].startswith("sha256:")
    assert (
        result.bundle / "source" / "product.py"
    ).read_bytes() == b"def health():\n    return {'status': 'ok'}\n"
    assert manifest["claims"] == {
        "package_verified": False,
        "customer_delivery_verified": False,
    }
    checked = verify_product_package(result.bundle, tmp_path, "run", head, result.manifest_digest)
    assert checked.status == "BLOCKED"


def test_product_package_rejects_unsafe_candidate_paths(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path, candidate_path="../secret")
    with pytest.raises(ProductPackageError, match="candidate path"):
        assemble_product_package(tmp_path, "run", head, tmp_path / "package")
    assert not (tmp_path / "package").exists()


def test_product_package_rejects_stale_head_and_source_tampering(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path)
    with pytest.raises(ProductPackageError, match="head"):
        assemble_product_package(tmp_path, "run", "sha256:" + "f" * 64, tmp_path / "package")

    result = assemble_product_package(tmp_path, "run", head, tmp_path / "package")
    (result.bundle / "source" / "product.py").write_text("tampered")
    with pytest.raises(ProductPackageError, match="source"):
        verify_product_package(result.bundle, tmp_path, "run", head, result.manifest_digest)


def test_product_package_rejects_user_supplied_verdict_and_wrong_ledger(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path)
    result = assemble_product_package(tmp_path, "run", head, tmp_path / "package")
    manifest_path = result.bundle / "product-package.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["claims"]["package_verified"] = True
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(ProductPackageError, match="manifest"):
        verify_product_package(result.bundle, tmp_path, "run", head, result.manifest_digest)

    with pytest.raises(ProductPackageError):
        verify_product_package(
            result.bundle, tmp_path / "other", "run", head, result.manifest_digest
        )


def test_product_package_does_not_export_obvious_credentials(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path, content=b"token = 'sk-abcdefghijklmnopqrstuvwxyz'\n")
    with pytest.raises(ProductPackageError, match="credential"):
        assemble_product_package(tmp_path, "run", head, tmp_path / "package")
    assert not (tmp_path / "package").exists()


class _FakeSandbox:
    def __init__(self, *, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.workspaces: list[Path] = []

    def run(self, workspace: Path, argv, *, timeout_seconds, environment):  # type: ignore[no-untyped-def]
        assert (workspace / "product.py").is_file()
        assert not (workspace / "product-package.json").exists()
        assert timeout_seconds <= 20
        assert "-I" in argv
        assert "SECRET" not in environment
        self.workspaces.append(workspace)
        return subprocess.CompletedProcess(argv, self.exit_code, "", "")


def test_clean_check_uses_separate_workspace_but_fake_cannot_verify(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path)
    fake = _FakeSandbox()
    result = assemble_product_package(tmp_path, "run", head, tmp_path / "package", sandbox=fake)
    assert len(fake.workspaces) == 1
    assert fake.workspaces[0] != result.bundle
    assert not fake.workspaces[0].exists()
    manifest = json.loads((result.bundle / "product-package.json").read_text())
    assert manifest["required_clean_checks"][0]["status"] == "BLOCKED"
    assert manifest["required_clean_checks"][0]["reason"] == "TEST_ADAPTER_NOT_TRUSTED"
    assert manifest["claims"]["package_verified"] is False


def test_clean_check_failure_is_recorded_without_package_claim(tmp_path: Path) -> None:
    head, _ = _sealed_run(tmp_path)
    result = assemble_product_package(
        tmp_path, "run", head, tmp_path / "package", sandbox=_FakeSandbox(exit_code=1)
    )
    manifest = json.loads((result.bundle / "product-package.json").read_text())
    check = manifest["required_clean_checks"][0]
    assert check["id"] == "python-syntax"
    assert check["status"] == "FAIL"
    assert check["reason"] == "PYTHON_SYNTAX_FAILED"
    assert check["tool_identity_digest"].startswith("sha256:")
    assert "PYTHON_SYNTAX_FAILED" in result.blockers
    assert manifest["claims"]["package_verified"] is False


def test_candidate_only_halted_run_cannot_be_packaged(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, "run")
    file_digest = ledger.put_blob(b"print('candidate')\n")
    candidate_digest = ledger.put_blob(canonical_json_bytes({"product.py": file_digest}))
    halted = ledger.append(
        event_type="halted",
        state="HALTED",
        subject_digest="sha256:" + "1" * 64,
        blob_digests=(file_digest, candidate_digest),
        payload={
            "candidate_digest": candidate_digest,
            "cause": "PROVIDER_WRITE_ISOLATION_UNVERIFIED",
        },
    )
    with pytest.raises(ProductPackageError, match="RELEASE_READY"):
        assemble_product_package(tmp_path, "run", str(halted["event_digest"]), tmp_path / "package")


def test_product_subcommand_reports_blocked_separately_from_input_error(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    head, _ = _sealed_run(tmp_path)
    bundle = tmp_path / "package"
    assert (
        main(
            [
                "barebones",
                "package",
                "product-build",
                "--repository-root",
                str(tmp_path),
                "--run-id",
                "run",
                "--expected-head-digest",
                head,
                "--output",
                str(bundle),
            ]
        )
        == 3
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "BLOCKED"
    assert output["bundle"] == str(bundle)
    assert (
        main(
            [
                "barebones",
                "package",
                "product-verify",
                "--repository-root",
                str(tmp_path),
                "--run-id",
                "run",
                "--expected-head-digest",
                head,
                "--expected-manifest-digest",
                output["manifest_digest"],
                "--bundle",
                str(bundle),
            ]
        )
        == 3
    )
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"


def test_fifo_manifest_is_rejected_by_nonblocking_reader(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    os.mkfifo(bundle / "product-package.json")
    with pytest.raises(ProductPackageError, match="regular|unsupported"):
        _read_bundle_files(bundle)


def test_oversized_manifest_and_source_are_rejected_before_read(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "source").mkdir(parents=True)
    manifest = bundle / "product-package.json"
    manifest.write_bytes(b"x" * (512 * 1024 + 1))
    source = bundle / "source" / "product.py"
    source.write_bytes(b"print('safe')\n")
    with pytest.raises(ProductPackageError, match="size limit"):
        _read_bundle_files(bundle)
    manifest.write_bytes(b"{}")
    with source.open("wb") as stream:
        stream.truncate(4 * 1024 * 1024 + 1)
    with pytest.raises(ProductPackageError, match="size limit"):
        _read_bundle_files(bundle)


def test_bundle_reader_rejects_symlinked_source_directory(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "product-package.json").write_bytes(b"{}")
    external = tmp_path / "external"
    external.mkdir()
    (bundle / "source").symlink_to(external, target_is_directory=True)
    with pytest.raises(ProductPackageError, match="unsupported"):
        _read_bundle_files(bundle)


def test_bundle_reader_limits_cumulative_source_bytes(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    source = bundle / "source"
    source.mkdir(parents=True)
    (bundle / "product-package.json").write_bytes(b"{}")
    for number in range(7):
        with (source / f"module-{number}.py").open("wb") as stream:
            stream.truncate(4 * 1024 * 1024)
    with pytest.raises(ProductPackageError, match="size limit"):
        _read_bundle_files(bundle)
