"""Quality gate runner for a generated workspace.

Gates are deterministic subprocess/scan checks; each returns a typed GateResult.
format/lint use ruff when available and are recorded as skipped (never silently
omitted) when it is not — required gates are all stdlib-only so a build can be
verified on any machine.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from pmpe.domain.models import GateResult
from pmpe.quality.security_scan import scan_tree

DEFAULT_REQUIRED_GATES = ("compile", "unit", "integration", "security")
SUBPROCESS_TIMEOUT_S = 180


def tail_output(text: str, lines: int = 15) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def normalize_format(workspace: Path) -> bool:
    """Format generated code with the same tool the format gate checks with.

    Returns True if formatting ran. When ruff is absent this is a no-op and the
    format gate reports itself skipped — consistent either way.
    """
    if shutil.which("ruff") is None:
        return False
    targets = [d for d in ("app", "tests") if (workspace / d).is_dir()]
    if not targets:
        return False
    subprocess.run(
        ["ruff", "format", "--quiet", *targets],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_S,
        check=False,
    )
    return True


class QualityGateRunner:
    def __init__(self, workspace: Path, required: tuple[str, ...] = DEFAULT_REQUIRED_GATES) -> None:
        self.workspace = workspace
        self.required = set(required)

    # --- individual gates -------------------------------------------------------

    def _run_cmd(self, args: list[str]) -> tuple[bool, str]:
        proc = subprocess.run(
            args,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_S,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return proc.returncode == 0, tail_output(output)

    def _gate_compile(self) -> tuple[bool, str, bool]:
        ok, out = self._run_cmd([sys.executable, "-m", "compileall", "-q", "app", "tests"])
        return ok, out or "all sources compile", False

    def _gate_format(self) -> tuple[bool, str, bool]:
        if shutil.which("ruff") is None:
            return True, "ruff not available — gate skipped (recorded, not hidden)", True
        ok, out = self._run_cmd(["ruff", "format", "--check", "app", "tests"])
        return ok, out or "formatting clean", False

    def _gate_lint(self) -> tuple[bool, str, bool]:
        if shutil.which("ruff") is None:
            return True, "ruff not available — gate skipped (recorded, not hidden)", True
        ok, out = self._run_cmd(["ruff", "check", "app", "tests"])
        return ok, out or "lint clean", False

    def _gate_unit(self) -> tuple[bool, str, bool]:
        if not (self.workspace / "tests" / "unit").is_dir():
            return True, "no unit tests present", True
        ok, out = self._run_cmd(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-t", "."]
        )
        return ok, out, False

    def _gate_integration(self) -> tuple[bool, str, bool]:
        if not (self.workspace / "tests" / "integration").is_dir():
            return True, "no integration tests present", True
        ok, out = self._run_cmd(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests/integration", "-t", "."]
        )
        return ok, out, False

    def _gate_security(self) -> tuple[bool, str, bool]:
        findings = scan_tree(self.workspace)
        if not findings:
            return True, "no security findings", False
        details = "; ".join(f"{f.rule} at {f.file}:{f.line}" for f in findings)
        return False, details, False

    # --- runner -----------------------------------------------------------------

    def run(self) -> list[GateResult]:
        gates: dict[str, Callable[[], tuple[bool, str, bool]]] = {
            "compile": self._gate_compile,
            "format": self._gate_format,
            "lint": self._gate_lint,
            "unit": self._gate_unit,
            "integration": self._gate_integration,
            "security": self._gate_security,
        }
        results: list[GateResult] = []
        for name in gates:
            fn = gates[name]
            started = time.monotonic()
            passed, details, skipped = fn()
            results.append(
                GateResult(
                    gate=name,
                    passed=passed,
                    required=name in self.required,
                    details=details,
                    duration_s=round(time.monotonic() - started, 3),
                    skipped=skipped,
                )
            )
        return results
