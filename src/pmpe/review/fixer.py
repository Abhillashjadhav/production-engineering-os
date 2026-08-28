"""Fix agent: applies ONLY allow-listed, formatting-level fixes.

Everything else is escalated (blocking) or left for humans (non-blocking).
The fixer never touches architecture, product behavior, or security findings —
that boundary is the point of the allow-list.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pmpe.domain.models import Finding, FixResult, ReviewReport


def _fix_trailing_whitespace(path: Path) -> None:
    lines = path.read_text().splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n")


def _fix_missing_eof_newline(path: Path) -> None:
    text = path.read_text()
    if text and not text.endswith("\n"):
        path.write_text(text + "\n")


_FIXERS: dict[str, Callable[[Path], None]] = {
    "REV_TRAILING_WHITESPACE": _fix_trailing_whitespace,
    "REV_MISSING_EOF_NEWLINE": _fix_missing_eof_newline,
}


class FixAgent:
    def apply(self, workspace: Path, report: ReviewReport) -> FixResult:
        fixed: list[Finding] = []
        escalated: list[Finding] = []
        skipped: list[Finding] = []
        for finding in report.findings:
            fixer = _FIXERS.get(finding.rule)
            if finding.safe_to_autofix and fixer is not None:
                target = workspace / finding.file
                if target.exists():
                    fixer(target)
                    fixed.append(finding)
                    continue
            if finding.blocking:
                escalated.append(finding)
            else:
                skipped.append(finding)
        return FixResult(fixed=fixed, escalated=escalated, skipped=skipped)
