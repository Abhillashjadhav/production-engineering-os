from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.quality.generated_python import check_python_candidate, generation_policy

GOOD = b'def health() -> dict[str, str]:\n    return {"status": "ok"}\n'


def test_clean_candidate_has_all_required_checks_and_bound_identity() -> None:
    report = check_python_candidate({"product.py": GOOD})
    assert report.passed, report
    assert {item.name for item in report.checks} == {
        "syntax", "dependencies", "verification_integrity", "format", "lint", "types"
    }
    assert all(item.status == "PASS" for item in report.checks)
    assert report.candidate_digest != check_python_candidate({"other.py": GOOD}).candidate_digest
    assert generation_policy()["profile"] == report.profile


@pytest.mark.parametrize(
    ("source", "failed_check"),
    [
        (b"def broken(:\n", "syntax"),
        (b"def health():\n    return missing_name\n", "lint"),
        (b"def count() -> int:\n    return 'wrong'\n", "types"),
        (b"import requests\n", "dependencies"),
        (b"value = 1  # noqa\n", "verification_integrity"),
        (b"value = 1  # type: ignore\n", "verification_integrity"),
        (b"# mypy: ignore-errors\nvalue = 1\n", "verification_integrity"),
        (b"value=1\n", "format"),
    ],
)
def test_planted_defect_fails(source: bytes, failed_check: str) -> None:
    report = check_python_candidate({"product.py": source})
    assert not report.passed
    assert any(c.name == failed_check and c.status == "FAIL" for c in report.checks)


def test_local_module_imports_are_supported() -> None:
    report = check_python_candidate({
        "product.py": b"from helper import count\n\nresult = count()\n",
        "helper.py": b"def count() -> int:\n    return 1\n",
    })
    assert report.passed, report


def test_missing_checker_is_unavailable_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pmpe.quality.generated_python._tool_available", lambda name: False)
    report = check_python_candidate({"product.py": GOOD})
    assert not report.passed
    assert {c.status for c in report.checks if c.name in {"format", "lint", "types"}} == {
        "UNAVAILABLE"
    }


def test_candidate_config_cannot_disable_trusted_checks() -> None:
    report = check_python_candidate({
        "product.py": b"value = undefined\n",
        "pyproject.toml": b'[tool.ruff.lint]\nignore = ["F821"]\n[tool.mypy]\nignore_errors = true\n',
    })
    assert not report.passed
    assert any(c.name == "lint" and c.status == "FAIL" for c in report.checks)


def test_static_checks_never_execute_candidate(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    code = f'from pathlib import Path\n\nPath({str(marker)!r}).touch()\n'.encode()
    check_python_candidate({"product.py": code})
    assert not marker.exists()


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "nested/../../outside.py"])
def test_path_escape_is_rejected(path: str) -> None:
    with pytest.raises(ValueError, match="path"):
        check_python_candidate({path: GOOD})


def test_empty_or_unsupported_source_cannot_pass() -> None:
    assert not check_python_candidate({}).passed
    assert not check_python_candidate({"index.ts": b"export const value = 1;"}).passed
