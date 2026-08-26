from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_capability_evidence_does_not_claim_stale_exact_head_links() -> None:
    readme = (ROOT / "README.md").read_text()

    assert "exact-head" not in readme.lower()
    assert re.search(
        r"github\.com/Abhillashjadhav/production-engineering-os/blob/[0-9a-f]{40}/",
        readme,
    ) is None


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
