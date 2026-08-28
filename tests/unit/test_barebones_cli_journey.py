from __future__ import annotations

import json
import os
from pathlib import Path

from pmpe.cli import main
from pmpe.evidence.ledger import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]


def _sealed_run(
    repository_root: Path,
    run_id: str = "sealed",
    *,
    approval: dict[str, str] | None = None,
) -> tuple[str, str]:
    ledger = EvidenceLedger(repository_root, run_id)
    if approval is not None:
        contract_digest = ledger.put_blob(b'{"contract_status":"APPROVED"}')
        plan_digest = ledger.put_blob(b'{"criteria":[]}')
        ledger.append(
            event_type="contract_validated",
            state="VALIDATED",
            subject_digest="sha256:" + "1" * 64,
            blob_digests=(contract_digest, plan_digest),
            payload={
                "approval": approval,
                "contract_digest": contract_digest,
                "plan_digest": plan_digest,
            },
        )
    content = b"def health():\n    return {'status': 'ok'}\n"
    file_digest = ledger.put_blob(content)
    manifest_digest = ledger.put_blob(
        json.dumps({"product.py": file_digest}, sort_keys=True, separators=(",", ":")).encode()
    )
    ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest="sha256:" + "1" * 64,
        blob_digests=(manifest_digest, file_digest),
        payload={
            "candidate_digest": manifest_digest,
            "telemetry": {"model_calls": 2, "elapsed_ms": 10},
        },
    )
    return manifest_digest, file_digest


def test_compile_reports_the_deterministic_plan_without_starting_a_run(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    result = main(
        [
            "barebones",
            "compile",
            str(ROOT / "examples" / "barebones" / "e1-contract.json"),
            "--repository-root",
            str(ROOT),
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "COMPILES"
    assert output["contract_status"] == "APPROVED"
    assert output["plan"]["plan_digest"].startswith("sha256:")
    assert output["coverage"] == {
        "human_test": 0,
        "structured": 1,
        "total": 1,
    }
    assert not (tmp_path / ".pmpe").exists()


def test_compile_reports_a_draft_as_compilable_without_claiming_validation(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    contract = json.loads((ROOT / "examples" / "barebones" / "e1-contract.json").read_text())
    contract["contract_status"] = "DRAFT"
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(contract))

    assert (
        main(
            [
                "barebones",
                "compile",
                str(draft),
                "--repository-root",
                str(ROOT),
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "COMPILES"
    assert output["contract_status"] == "DRAFT"


def test_status_and_evidence_verify_the_sealed_chain(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _sealed_run(tmp_path)

    assert main(["barebones", "status", "sealed", "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "RELEASE_READY"
    assert status["cause"] == "PASS"
    assert status["events"] == 1

    assert main(["barebones", "evidence", "sealed", "--repository-root", str(tmp_path)]) == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["integrity"] == "PASS"
    assert evidence["events"] == 1
    assert evidence["referenced_blobs"] == 2
    assert evidence["head_event_digest"].startswith("sha256:")


def test_inspection_commands_surface_verified_approval_authority(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    receipt_digest = "sha256:" + "9" * 64
    approval = {
        "status": "VERIFIED",
        "authority": "pmos-owner",
        "receipt_digest": receipt_digest,
    }
    _sealed_run(tmp_path, "approved", approval=approval)

    for command in ("status", "evidence", "inspect"):
        assert (
            main(
                [
                    "barebones",
                    command,
                    "approved",
                    "--repository-root",
                    str(tmp_path),
                ]
            )
            == 0
        )
        output = json.loads(capsys.readouterr().out)
        assert output["approval"] == approval


def test_inspect_refuses_to_publish_an_unverified_direct_call(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _sealed_run(
        tmp_path,
        "unverified",
        approval={"status": "UNVERIFIED_DIRECT_CALL"},
    )

    result = main(
        [
            "barebones",
            "inspect",
            "unverified",
            "--repository-root",
            str(tmp_path),
        ]
    )

    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "RELEASE_READY"
    assert output["approval"] == {"status": "UNVERIFIED_DIRECT_CALL"}
    assert output["release_eligible"] is False


def test_inspect_reads_only_the_sealed_candidate_and_checks_workspace_drift(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    manifest_digest, file_digest = _sealed_run(tmp_path)
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    content = "def health():\n    return {'status': 'ok'}\n"
    (workspace / "product.py").write_text(content)

    result = main(
        [
            "barebones",
            "inspect",
            "sealed",
            "--repository-root",
            str(tmp_path),
            "--workspace",
            str(workspace),
            "--file",
            "product.py",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["candidate_digest"] == manifest_digest
    assert output["files"] == {"product.py": file_digest}
    assert output["workspace"] == {
        "changed": [],
        "missing": [],
        "symlinks": [],
        "status": "MATCH",
        "untracked": [],
    }
    assert output["selected_file"] == {
        "content": content,
        "digest": file_digest,
        "path": "product.py",
    }

    (workspace / "product.py").write_text("changed\n")
    assert (
        main(
            [
                "barebones",
                "inspect",
                "sealed",
                "--repository-root",
                str(tmp_path),
                "--workspace",
                str(workspace),
            ]
        )
        == 3
    )
    drift = json.loads(capsys.readouterr().out)
    assert drift["workspace"]["status"] == "DRIFT"
    assert drift["workspace"]["changed"] == ["product.py"]


def test_inspect_rejects_a_symlinked_workspace_root(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _sealed_run(tmp_path)
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "product.py").write_text("def health():\n    return {'status': 'ok'}\n")
    workspace_link = tmp_path / "candidate-link"
    workspace_link.symlink_to(workspace, target_is_directory=True)

    result = main(
        [
            "barebones",
            "inspect",
            "sealed",
            "--repository-root",
            str(tmp_path),
            "--workspace",
            str(workspace_link),
        ]
    )

    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output["workspace"] == {
        "changed": [],
        "missing": ["product.py"],
        "symlinks": ["."],
        "status": "DRIFT",
        "untracked": [],
    }


def test_inspect_fails_closed_when_a_workspace_subtree_cannot_be_scanned(
    tmp_path: Path, capsys, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    _sealed_run(tmp_path)
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "product.py").write_text("def health():\n    return {'status': 'ok'}\n")
    blocked = workspace / "blocked"
    blocked.mkdir()
    (blocked / "untracked.py").write_text("hidden = True\n")
    original_scandir = os.scandir

    def guarded_scandir(path):  # type: ignore[no-untyped-def]
        if Path(path) == blocked:
            raise PermissionError("denied")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded_scandir)

    result = main(
        [
            "barebones",
            "inspect",
            "sealed",
            "--repository-root",
            str(tmp_path),
            "--workspace",
            str(workspace),
        ]
    )

    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "cause": "EVIDENCE_INVALID",
        "detail": "candidate workspace cannot be inspected",
        "state": "HALTED",
    }


def test_inspection_commands_report_invalid_run_ids_as_json(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    for command in ("status", "evidence", "inspect"):
        result = main(
            [
                "barebones",
                command,
                "../bad",
                "--repository-root",
                str(tmp_path),
            ]
        )

        assert result == 3
        captured = capsys.readouterr()
        assert captured.err == ""
        assert json.loads(captured.out) == {
            "cause": "EVIDENCE_INVALID",
            "detail": "run_id must be a bounded filesystem-safe identifier",
            "state": "HALTED",
        }


def test_status_rejects_adversarial_event_json_as_a_controlled_error(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    depth = 10_000
    hostile_sources = (
        '{"nested":' * depth + "null" + "}" * depth,
        '{"integer":' + "1" * 5_000 + "}",
        '{"number":NaN}',
    )
    for index, source in enumerate(hostile_sources):
        run_id = f"hostile-{index}"
        ledger = EvidenceLedger(tmp_path, run_id)
        ledger.events_path.write_text(source)

        result = main(
            [
                "barebones",
                "status",
                run_id,
                "--repository-root",
                str(tmp_path),
            ]
        )

        assert result == 3
        assert json.loads(capsys.readouterr().out) == {
            "cause": "EVIDENCE_INVALID",
            "detail": "event is not canonical JSON",
            "state": "HALTED",
        }


def test_inspection_fails_closed_when_evidence_is_mutated(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    _, file_digest = _sealed_run(tmp_path)
    blob = tmp_path / ".pmpe" / "blobs" / file_digest.removeprefix("sha256:")
    blob.write_bytes(b"mutated")

    result = main(["barebones", "evidence", "sealed", "--repository-root", str(tmp_path)])

    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "EVIDENCE_INVALID"


def test_inspection_rejects_duplicate_candidate_manifest_members(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    ledger = EvidenceLedger(tmp_path, "duplicate-manifest")
    file_digest = ledger.put_blob(b"first")
    manifest_digest = ledger.put_blob(
        ('{"product.py":"' + file_digest + '","product.py":"' + file_digest + '"}').encode()
    )
    ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest="sha256:" + "2" * 64,
        blob_digests=(manifest_digest, file_digest),
        payload={"candidate_digest": manifest_digest},
    )

    result = main(
        [
            "barebones",
            "inspect",
            "duplicate-manifest",
            "--repository-root",
            str(tmp_path),
        ]
    )

    assert result == 3
    output = json.loads(capsys.readouterr().out)
    assert output["cause"] == "EVIDENCE_INVALID"
    assert output["detail"] == "candidate manifest is malformed"
