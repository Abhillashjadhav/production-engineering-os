"""Candidate syntax must run behind bounded trusted compiler process."""

from __future__ import annotations

import json
import resource
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pmpe.barebones import default_template
from pmpe.contracts.canonical import canonical_digest
from pmpe.product_checks import candidate_manifest_digest, evaluate_required_checks
from pmpe.product_profile import (
    CompiledProductProfile,
    ProductProfileError,
    compile_product_profile,
)
from pmpe.product_syntax import check_python_syntax

ROOT = Path(__file__).resolve().parents[2]


def _profile() -> CompiledProductProfile:
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    return compile_product_profile(
        "barebones-health-v1", contract=contract, template=default_template(), harness_plan=None
    )


def test_deep_expression_fails_within_watchdog_without_supervisor_recursion() -> None:
    source = b"x=" + b"+1" * 10_000
    started = time.monotonic()
    status, reason = check_python_syntax({"product.py": source})
    assert (status, reason) == ("FAIL", "source syntax invalid")
    assert time.monotonic() - started < 7

    snapshot = {"product.py": source}
    report = evaluate_required_checks(
        _profile(),
        candidate_digest=candidate_manifest_digest(snapshot),
        source_files=snapshot,
        acceptance_observations={},
        security_findings=(),
    )
    check = next(item for item in report.results if item.check_id == "python-syntax")
    assert check.status == "FAIL"
    assert report.candidate_qualified is False


def test_syntax_budget_and_no_python_source_never_pass(tmp_path: Path) -> None:
    assert check_python_syntax({"README.md": b"no Python"})[0] == "BLOCKED"
    assert check_python_syntax({"product.py": b"x = 1\n"})[0] == "PASS"
    assert check_python_syntax({"product.py": b"x=\n"})[0] == "FAIL"
    marker = tmp_path / "candidate-executed"
    candidate = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode()
    assert check_python_syntax({"product.py": candidate})[0] == "PASS"
    assert not marker.exists()
    assert check_python_syntax({"product.py": b"a" * 1_000_001}) == (
        "BLOCKED",
        "source syntax resource limit",
    )


def test_nested_compiler_preserves_stricter_inherited_hard_limits() -> None:
    def lower_limits() -> None:
        resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_STACK, (4 * 1024 * 1024, 4 * 1024 * 1024))

    script = (
        f"import json,sys;sys.path.insert(0,{str(ROOT / 'src')!r});"
        "from pmpe.product_syntax import check_python_syntax;"
        "print(json.dumps([check_python_syntax({'product.py': b'x=1\\n'}),"
        "check_python_syntax({'product.py': b'x=\\n'})]))"
    )
    completed = subprocess.run(
        (sys.executable, "-I", "-S", "-c", script),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
        preexec_fn=lower_limits,
    )
    statuses = json.loads(completed.stdout)
    assert [item[0] for item in statuses] == ["PASS", "FAIL"]


def test_compiler_uses_only_its_interpreter_library_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted Pythons may need their own shared library to start under the wrapper."""

    monkeypatch.setenv("LD_LIBRARY_PATH", "/candidate-controlled-libraries")
    observed: list[str] = []

    def capture_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        library_path = environment.get("LD_LIBRARY_PATH")
        assert isinstance(library_path, str)
        observed.append(library_path)
        assert library_path == str(Path(sys.executable).resolve().parent.parent / "lib")
        return subprocess.CompletedProcess([], 0, b"0", b"")

    with patch("pmpe.product_syntax.subprocess.run", side_effect=capture_run):
        assert check_python_syntax({"product.py": b"x = 1\n"})[0] == "PASS"
    assert len(observed) == 1


def test_inc_1_nested_compiler_reports_bounded_child_failure() -> None:
    """A failed fixed child remains BLOCKED with enough safe detail to diagnose CI."""

    with patch(
        "pmpe.product_syntax.subprocess.run",
        return_value=subprocess.CompletedProcess([], 127, b"", b"private stderr"),
    ):
        assert check_python_syntax({"product.py": b"x = 1\n"}) == (
            "BLOCKED",
            "source syntax resource limit (child exit 127)",
        )
    with patch("pmpe.product_syntax.subprocess.run", side_effect=OSError(11, "private path")):
        assert check_python_syntax({"product.py": b"x = 1\n"}) == (
            "BLOCKED",
            "source syntax resource limit (child launch errno 11)",
        )
    with patch(
        "pmpe.product_syntax.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, b"private output", b""),
    ):
        assert check_python_syntax({"product.py": b"x = 1\n"}) == (
            "BLOCKED",
            "source syntax resource limit (child protocol)",
        )


def test_health_profile_accepts_list_criteria_but_rejects_duplicate_ids() -> None:
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    contract["acceptance_criteria"] = [
        {"id": criterion_id, **criterion}
        for criterion_id, criterion in contract["acceptance_criteria"].items()
    ]
    profile = compile_product_profile(
        "barebones-health-v1", contract=contract, template=default_template(), harness_plan=None
    )
    assert profile.criterion_ids == ("AC-001",)
    assert profile.contract_digest == canonical_digest(contract)
    contract["acceptance_criteria"].append(dict(contract["acceptance_criteria"][0]))
    with pytest.raises(ProductProfileError, match="criterion"):
        compile_product_profile(
            "barebones-health-v1",
            contract=contract,
            template=default_template(),
            harness_plan=None,
        )
