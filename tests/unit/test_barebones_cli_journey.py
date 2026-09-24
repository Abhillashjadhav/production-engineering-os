from __future__ import annotations

import json
import os
from pathlib import Path

from pmpe.barebones import compile_barebones_plan
from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.evidence.ledger import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]


def _sealed_run(
    repository_root: Path,
    run_id: str = "sealed",
    *,
    approval: dict[str, str] | None = None,
) -> tuple[str, str]:
    ledger = EvidenceLedger(repository_root, run_id)
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    authority = (approval or {}).get("authority", "fixture-human")
    contract["approved_by"] = authority
    subject = canonical_digest(contract)
    plan = compile_barebones_plan(contract=contract, repository_root=repository_root).as_dict()
    contract_blob = ledger.put_blob(canonical_json_bytes(contract))
    plan_blob = ledger.put_blob(canonical_json_bytes(plan))
    validation_blobs = [contract_blob, plan_blob]
    if approval == {"status": "UNVERIFIED_DIRECT_CALL"}:
        approval_record = dict(approval)
    else:
        draft = {**contract, "contract_status": "DRAFT", "approved_by": "", "approved_at": ""}
        receipt = {
            "schema_version": "1.0.0",
            "decision": "APPROVED",
            "approved_by": authority,
            "approved_at": contract["approved_at"],
            "approved_contract_digest": subject,
            "contract_id": contract["contract_id"],
            "contract_version": contract["contract_version"],
            "draft_digest": canonical_digest(draft),
        }
        receipt["receipt_digest"] = canonical_digest(receipt)
        receipt_blob = ledger.put_blob(canonical_json_bytes(receipt))
        validation_blobs.append(receipt_blob)
        approval_record = {
            "status": "VERIFIED",
            "authority": authority,
            "receipt_digest": receipt["receipt_digest"],
            "receipt_blob_digest": receipt_blob,
        }
    ledger.append(
        event_type="contract_validated",
        state="VALIDATED",
        subject_digest=subject,
        blob_digests=validation_blobs,
        payload={
            "approval": approval_record,
            "contract_digest": contract_blob,
            "plan_digest": plan["plan_digest"],
        },
    )
    ledger.append(
        event_type="coder_completed",
        state="BUILDING",
        subject_digest=subject,
        payload={"attempt": 1},
    )
    ledger.append(
        event_type="verification_started",
        state="VERIFYING",
        subject_digest=subject,
        payload={"attempt": 1},
    )
    content = b"def health():\n    return {'status': 'ok'}\n"
    file_digest = ledger.put_blob(content)
    manifest_digest = ledger.put_blob(
        json.dumps({"product.py": file_digest}, sort_keys=True, separators=(",", ":")).encode()
    )
    ledger.append(
        event_type="release_ready",
        state="RELEASE_READY",
        subject_digest=subject,
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
    assert status["events"] == 4

    assert main(["barebones", "evidence", "sealed", "--repository-root", str(tmp_path)]) == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["integrity"] == "PASS"
    assert evidence["events"] == 4
    assert evidence["referenced_blobs"] == 5
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
        assert output["approval"]["status"] == "VERIFIED"
        assert output["approval"]["authority"] == "pmos-owner"
        assert output["approval"]["receipt_digest"].startswith("sha256:")


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
        if not isinstance(path, int) and Path(path) == blocked:
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
    _sealed_run(tmp_path, "duplicate-manifest")
    ledger = EvidenceLedger.open_existing(tmp_path, "duplicate-manifest")
    events = [dict(event) for event in ledger.verify()]
    terminal = events[-1]
    file_digest = next(
        blob for blob in terminal["blob_digests"] if blob != terminal["payload"]["candidate_digest"]
    )
    malformed = ('{"product.py":"' + file_digest + '","product.py":"' + file_digest + '"}').encode()
    import hashlib

    manifest_digest = "sha256:" + hashlib.sha256(malformed).hexdigest()
    (ledger.blobs_directory / manifest_digest.removeprefix("sha256:")).write_bytes(malformed)
    terminal["blob_digests"] = sorted([manifest_digest, file_digest])
    terminal["payload"]["candidate_digest"] = manifest_digest
    terminal.pop("event_digest")
    terminal["event_digest"] = canonical_digest(terminal)
    ledger.events_path.write_bytes(
        b"".join(canonical_json_bytes(event) + b"\n" for event in events)
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
    assert output["detail"] == "release gate evidence blob is malformed"
