from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.delivery import assemble_delivery, verify_delivery
from pmpe.quality.generated_python import check_python_candidate

SOURCE = {"product.py": b'def health() -> dict[str, str]:\n    return {"status": "ok"}\n'}


def delivery(tmp_path: Path) -> dict[str, str]:
    quality = check_python_candidate(SOURCE).as_dict()
    identity = {
        "candidate_digest": quality["candidate_digest"],
        "contract_digest": "sha256:" + "a" * 64,
        "plan_digest": "sha256:" + "b" * 64,
        "head_event_digest": "sha256:" + "c" * 64,
    }
    return assemble_delivery(SOURCE, quality=quality, identity=identity, output=tmp_path / "out")


def test_delivery_contains_exact_source_quality_and_use_guidance(tmp_path: Path) -> None:
    result = delivery(tmp_path)
    root = tmp_path / "out"
    assert (root / "product/product.py").read_bytes() == SOURCE["product.py"]
    assert (root / "QUALITY.json").is_file()
    assert "NOT_DEPLOYED" in (root / "README.md").read_text()
    assert verify_delivery(root, expected_manifest_digest=result["manifest_digest"]) == result


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra", "symlink", "manifest"])
def test_modified_delivery_fails(tmp_path: Path, mutation: str) -> None:
    result = delivery(tmp_path)
    root = tmp_path / "out"
    source = root / "product/product.py"
    if mutation == "changed":
        source.write_text("changed")
    elif mutation == "missing":
        source.unlink()
    elif mutation == "extra":
        (root / "unexpected.txt").write_text("extra")
    elif mutation == "symlink":
        source.unlink()
        source.symlink_to(tmp_path / "outside")
    else:
        (root / "DELIVERY.json").write_text("{}")
    with pytest.raises(ValueError):
        verify_delivery(root, expected_manifest_digest=result["manifest_digest"])


def test_delivery_refuses_unchecked_sources_and_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assemble_delivery(SOURCE, quality={"passed": True}, identity={}, output=tmp_path / "bad")
    delivery(tmp_path)
    with pytest.raises(ValueError, match="exist"):
        delivery(tmp_path)


def test_external_manifest_anchor_is_required(tmp_path: Path) -> None:
    delivery(tmp_path)
    with pytest.raises(ValueError, match="digest"):
        verify_delivery(tmp_path / "out", expected_manifest_digest="sha256:" + "0" * 64)
