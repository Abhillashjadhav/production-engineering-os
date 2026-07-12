"""Deterministic PR reviewer.

Reviews the workspace against the spec and plan across the required dimensions:
correctness signals, architecture alignment, test sufficiency (traceability
markers), security, maintainability, and complexity. Every finding names its
rule; blocking findings stop the merge gate later.

Backward compatibility: V1 builds are greenfield (fresh workspace per run), so
compatibility review is recorded as not-applicable in the summary rather than
silently omitted.
"""

from __future__ import annotations

import re
from pathlib import Path

from pmpe.domain.models import (
    EngineeringPlan,
    Finding,
    MvpSpec,
    ReviewReport,
    Severity,
)
from pmpe.quality.security_scan import scan_tree

_ALLOWED_ROOTS = {"app", "tests", "deploy", "README.md", ".gitignore"}
_SKIP_PARTS = {".git", "__pycache__"}
_MAX_FILE_LINES = 400
_COVERS_RE = re.compile(r"Covers:\s*([A-Z]+-\d+(?:\s*,\s*[A-Z]+-\d+)*)")


class PrReviewer:
    def review(self, workspace: Path, spec: MvpSpec, plan: EngineeringPlan) -> ReviewReport:
        raw: list[Finding] = []
        raw.extend(scan_tree(workspace))
        raw.extend(self._unplanned_files(workspace))
        raw.extend(self._missing_components(workspace, plan))
        raw.extend(self._requirement_coverage(workspace, spec))
        raw.extend(self._maintainability(workspace))

        findings = [
            Finding(
                id=f"F-{i:03d}",
                category=f.category,
                severity=f.severity,
                blocking=f.blocking,
                safe_to_autofix=f.safe_to_autofix,
                file=f.file,
                line=f.line,
                message=f.message,
                rule=f.rule,
            )
            for i, f in enumerate(
                sorted(raw, key=lambda f: (f.rule, f.file, f.line)), start=1
            )
        ]
        blocking = sum(1 for f in findings if f.blocking)
        summary = (
            f"{len(findings)} finding(s), {blocking} blocking. "
            "Backward compatibility: not applicable (greenfield workspace)."
        )
        return ReviewReport(findings=findings, summary=summary)

    # --- checks -----------------------------------------------------------------

    def _iter_files(self, workspace: Path) -> list[Path]:
        return [
            p
            for p in sorted(workspace.rglob("*"))
            if p.is_file()
            and not any(part in _SKIP_PARTS for part in p.relative_to(workspace).parts)
        ]

    def _unplanned_files(self, workspace: Path) -> list[Finding]:
        findings = []
        for path in self._iter_files(workspace):
            rel = path.relative_to(workspace)
            root = rel.parts[0]
            if root in _ALLOWED_ROOTS or rel.suffix == ".db":
                continue
            findings.append(
                _finding(
                    rule="REV_UNPLANNED_FILE",
                    category="architecture",
                    severity=Severity.MAJOR,
                    blocking=True,
                    file=str(rel),
                    line=1,
                    message=(
                        f"'{rel}' is outside the planned layout "
                        f"({', '.join(sorted(_ALLOWED_ROOTS))}) — architecture drift"
                    ),
                )
            )
        return findings

    def _missing_components(self, workspace: Path, plan: EngineeringPlan) -> list[Finding]:
        expected = {
            "storage": "app/storage.py",
            "auth": "app/auth.py",
            "api": "app/api.py",
            "server": "app/server.py",
        }
        findings = []
        for task in plan.tasks:
            path = expected.get(task.component)
            if task.kind == "feature" and path and not (workspace / path).exists():
                findings.append(
                    _finding(
                        rule="REV_MISSING_COMPONENT",
                        category="architecture",
                        severity=Severity.CRITICAL,
                        blocking=True,
                        file=path,
                        line=1,
                        message=f"planned component '{task.component}' ({task.id}) missing",
                    )
                )
        return findings

    def _requirement_coverage(self, workspace: Path, spec: MvpSpec) -> list[Finding]:
        covered: set[str] = set()
        tests_dir = workspace / "tests"
        if tests_dir.is_dir():
            for path in sorted(tests_dir.rglob("*.py")):
                for match in _COVERS_RE.finditer(path.read_text()):
                    for rid in re.split(r"\s*,\s*", match.group(1)):
                        covered.add(rid.strip())
        findings = []
        for fr in spec.functional_requirements:
            if fr.id not in covered:
                findings.append(
                    _finding(
                        rule="REV_UNCOVERED_REQUIREMENT",
                        category="test-sufficiency",
                        severity=Severity.MAJOR,
                        blocking=True,
                        file="tests/",
                        line=1,
                        message=f"{fr.id} ('{fr.title}') has no test carrying a Covers marker",
                    )
                )
        return findings

    def _maintainability(self, workspace: Path) -> list[Finding]:
        findings = []
        for path in self._iter_files(workspace):
            if path.suffix != ".py":
                continue
            rel = str(path.relative_to(workspace))
            text = path.read_text()
            lines = text.splitlines()
            in_app = rel.startswith("app/")
            for lineno, line in enumerate(lines, start=1):
                if "TODO" in line or "FIXME" in line:
                    findings.append(
                        _finding(
                            rule="REV_TODO",
                            category="maintainability",
                            severity=Severity.MINOR,
                            blocking=False,
                            file=rel,
                            line=lineno,
                            message="TODO/FIXME left in delivered code",
                        )
                    )
                if in_app and re.search(r"^\s*print\(", line):
                    findings.append(
                        _finding(
                            rule="REV_DEBUG_PRINT",
                            category="maintainability",
                            severity=Severity.MINOR,
                            blocking=False,
                            file=rel,
                            line=lineno,
                            message="print() in product code — use logging",
                        )
                    )
                if line != line.rstrip() and line.strip():
                    findings.append(
                        _finding(
                            rule="REV_TRAILING_WHITESPACE",
                            category="maintainability",
                            severity=Severity.MINOR,
                            blocking=False,
                            safe_to_autofix=True,
                            file=rel,
                            line=lineno,
                            message="trailing whitespace",
                        )
                    )
            if text and not text.endswith("\n"):
                findings.append(
                    _finding(
                        rule="REV_MISSING_EOF_NEWLINE",
                        category="maintainability",
                        severity=Severity.MINOR,
                        blocking=False,
                        safe_to_autofix=True,
                        file=rel,
                        line=len(lines),
                        message="file does not end with a newline",
                    )
                )
            if len(lines) > _MAX_FILE_LINES:
                findings.append(
                    _finding(
                        rule="REV_LONG_FILE",
                        category="complexity",
                        severity=Severity.MAJOR,
                        blocking=False,
                        file=rel,
                        line=len(lines),
                        message=f"{len(lines)} lines exceeds the {_MAX_FILE_LINES}-line budget",
                    )
                )
        return findings


def _finding(
    *,
    rule: str,
    category: str,
    severity: Severity,
    blocking: bool,
    file: str,
    line: int,
    message: str,
    safe_to_autofix: bool = False,
) -> Finding:
    return Finding(
        id="",  # assigned after sorting
        category=category,
        severity=severity,
        blocking=blocking,
        safe_to_autofix=safe_to_autofix,
        file=file,
        line=line,
        message=message,
        rule=rule,
    )
