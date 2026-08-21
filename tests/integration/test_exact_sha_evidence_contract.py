"""Planning-red contract for issue #69's evidence authority."""

from __future__ import annotations

import importlib.util


def test_exact_sha_evidence_authority_exists() -> None:
    """A missing authority cannot govern readiness or prevent false DONE."""

    assert importlib.util.find_spec("pmpe.audit.evidence") is not None
