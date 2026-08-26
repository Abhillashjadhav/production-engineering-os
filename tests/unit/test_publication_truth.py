from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pmpe.evidence.ledger import EvidenceLedger

ROOT = Path(__file__).resolve().parents[2]
E1 = ROOT / "docs" / "evidence" / "e1-real-provider-20260826"
E1_RUN_ID = "codex-e1-live-20260826T100659Z"


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
