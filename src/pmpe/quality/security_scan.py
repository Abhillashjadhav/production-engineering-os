"""Built-in deterministic security scanner.

Runs on every build regardless of environment; bandit (when installed) covers the
OS's own source in CI. Each rule is a named regex over source lines so every
finding is explainable and reproducible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pmpe.domain.models import Finding, Severity


@dataclass(frozen=True)
class _Rule:
    id: str
    pattern: re.Pattern[str]
    message: str
    skip_tests: bool = False  # test files legitimately contain fake credentials


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "SEC_HARDCODED_SECRET",
        re.compile(r"""(?i)\b(password|passwd|secret|api_key|apikey|token)\s*=\s*["'][^"']+["']"""),
        "possible hardcoded secret — inject via environment instead",
        skip_tests=True,
    ),
    _Rule(
        "SEC_EVAL",
        re.compile(r"\beval\s*\("),
        "eval() on dynamic input enables code injection",
    ),
    _Rule(
        "SEC_EXEC",
        re.compile(r"\bexec\s*\("),
        "exec() on dynamic input enables code injection",
    ),
    _Rule(
        "SEC_SHELL_TRUE",
        re.compile(r"shell\s*=\s*True"),
        "subprocess with shell=True enables shell injection",
    ),
    _Rule(
        "SEC_PICKLE",
        re.compile(r"\bpickle\.loads?\s*\("),
        "unpickling untrusted data executes arbitrary code",
    ),
    _Rule(
        "SEC_SQL_FORMAT",
        re.compile(r"""execute\s*\(\s*f["']|execute\s*\([^)]*\.format\("""),
        "SQL built with interpolation — use parameterized queries",
    ),
)

_SKIP_DIRS = {".git", "__pycache__", ".venv", "deploy"}


def _is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    is_test = _is_test_path(path)
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        for rule in _RULES:
            if rule.skip_tests and is_test:
                continue
            if rule.pattern.search(line):
                findings.append(
                    Finding(
                        id=f"SEC-{len(findings) + 1:03d}",
                        category="security",
                        severity=Severity.CRITICAL,
                        blocking=True,
                        safe_to_autofix=False,
                        file=str(path),
                        line=lineno,
                        message=rule.message,
                        rule=rule.id,
                    )
                )
    return findings


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        findings.extend(scan_file(path))
    # re-number across the whole tree for stable ids
    return [
        Finding(
            id=f"SEC-{i:03d}",
            category=f.category,
            severity=f.severity,
            blocking=f.blocking,
            safe_to_autofix=f.safe_to_autofix,
            file=f.file,
            line=f.line,
            message=f.message,
            rule=f.rule,
        )
        for i, f in enumerate(findings, start=1)
    ]
