from __future__ import annotations

import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

from pmpe.evidence.ledger import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
E1 = ROOT / "docs" / "evidence" / "e1-real-provider-20260826"
E1_RUN_ID = "codex-e1-live-20260826T100659Z"
DRIFT = ROOT / "docs" / "evidence" / "real-behavior-drift-20260827"
DRIFT_ARCHIVE = DRIFT / "pmpe-real-drift-20260827T141651Z.tgz"
DRIFT_ROOT = "pmpe-real-drift-20260827T141651Z"
DRIFT_ARCHIVE_DIGEST = "877bf87b6fdfb305e28ba68468f5f8f5d1c03ca65fcb51351ae63f32df8f32c1"


def test_readme_capability_evidence_does_not_claim_stale_exact_head_links() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "exact-head" not in readme.lower()
    assert (
        re.search(
            r"github\.com/Abhillashjadhav/production-engineering-os/blob/[0-9a-f]{40}/",
            readme,
        )
        is None
    )


def test_legacy_architecture_and_plan_surfaces_are_marked_historical() -> None:
    historical = (
        ROOT / "ARCHITECTURE.md",
        ROOT / "ROADMAP.md",
        ROOT / "docs" / "TARGET-ARCHITECTURE.md",
        ROOT / "docs" / "implementation-plan.md",
        ROOT / "docs" / "v2-implementation-plan.md",
        ROOT / "docs" / "v3" / "implementation-plan.md",
    )

    for path in historical:
        opening = "\n".join(path.read_text().splitlines()[:8]).lower()
        assert "historical / superseded" in opening, path
        assert "readme.md" in opening, path


def test_published_real_provider_e1_chain_verifies() -> None:
    ledger = EvidenceLedger.open_existing(E1 / "evidence", E1_RUN_ID)
    events = tuple(ledger.verify())

    assert len(events) == 5
    assert events[-1]["state"] == "RELEASE_READY"
    assert events[-1]["event_digest"] == (
        "sha256:8c8da110bfc89c6cd0095c798817383e0328743a9b0d3da9739ba6bf14655b69"
    )


def test_published_real_provider_e1_candidate_matches_sealed_digest() -> None:
    candidate = (E1 / "candidate" / "product.py").read_bytes()
    digest = "sha256:" + hashlib.sha256(candidate).hexdigest()
    events_path = E1 / "evidence" / ".pmpe" / "runs" / E1_RUN_ID / "events.jsonl"
    terminal = json.loads(events_path.read_text().splitlines()[-1])

    assert digest == "sha256:2cc37ee3852c332874496816ca9fff5fa7aa3ad7bb5534f74420c1b584be0b36"
    assert terminal["payload"]["candidate_digest"] == (
        "sha256:4a0888572b4b546aeb1c6cff09532fb17bdaa587a0d03b152dce4f4e3a2ee4d0"
    )


def test_published_real_behavior_drift_archive_matches_outer_digest() -> None:
    assert hashlib.sha256(DRIFT_ARCHIVE.read_bytes()).hexdigest() == DRIFT_ARCHIVE_DIGEST
    assert (DRIFT / "SHA256SUMS").read_text() == (f"{DRIFT_ARCHIVE_DIGEST}  {DRIFT_ARCHIVE.name}\n")


def test_published_real_behavior_drift_archive_is_safe_and_complete() -> None:
    with tarfile.open(DRIFT_ARCHIVE, "r:gz") as bundle:
        members = bundle.getmembers()
        by_name = {member.name: member for member in members}

        for member in members:
            path = PurePosixPath(member.name)
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert not member.issym()
            assert not member.islnk()

        manifest_member = by_name[f"{DRIFT_ROOT}/SHA256SUMS"]
        manifest_file = bundle.extractfile(manifest_member)
        assert manifest_file is not None
        manifest = manifest_file.read().decode().splitlines()
        assert len(manifest) == 831

        for entry in manifest:
            expected, relative = entry.split("  ", 1)
            member = by_name[f"{DRIFT_ROOT}/{relative}"]
            content = bundle.extractfile(member)
            assert content is not None
            assert hashlib.sha256(content.read()).hexdigest() == expected

        summary_file = bundle.extractfile(by_name[f"{DRIFT_ROOT}/summary.json"])
        assert summary_file is not None
        summary = json.load(summary_file)

    assert summary["gate"] == "PASS"
    assert len(summary["runs"]) == 7
    assert all(
        run["exit_code"] == 0
        and run["result"]["state"] == "RELEASE_READY"
        and run["result"]["cause"] == "PASS"
        for run in summary["runs"]
    )
