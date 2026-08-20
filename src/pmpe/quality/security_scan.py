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

_SHELL_RULES: tuple[_Rule, ...] = (
    _Rule(
        "SEC_SHELL_RECURSIVE_DELETE",
        re.compile(
            r"\brm\b"
            r"(?=[^;&|\n]*(?:--recursive|-[A-Za-z]*[rR][A-Za-z]*))"
            r"(?=[^;&|\n]*(?:--force|-[A-Za-z]*f[A-Za-z]*))"
        ),
        "recursive forced deletion in an executable deployment script",
    ),
    _Rule(
        "SEC_SHELL_REMOTE_PIPE",
        re.compile(
            r"\b(?:curl|wget)\b[^\n|]*\|\s*"
            r"(?:(?:/usr/bin/)?env\s+)?(?:(?:/[\w.-]+)*/)?(?:ba)?sh\b"
        ),
        "remote content piped directly to a shell",
    ),
)

_SKIP_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache", ".pytest_cache"}


def _shell_logical_lines(text: str) -> list[tuple[int, str]]:
    logical: list[tuple[int, str]] = []
    buffered = ""
    start = 1
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not buffered:
            start = lineno
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffered += stripped[:-1] + " "
            continue
        logical.append((start, buffered + line))
        buffered = ""
    if buffered:
        logical.append((start, buffered))
    return logical


def scan_file(path: Path, root: Path | None = None) -> list[Finding]:
    """Scan one file. Test-file detection uses the path RELATIVE to ``root`` when
    given — absolute ancestors named 'tests' (e.g. a runs dir under /home/x/tests/)
    must never exempt product code from the secret rule."""
    rel_parts = path.relative_to(root).parts if root is not None else (path.name,)
    is_test = "tests" in rel_parts or path.name.startswith("test_")
    is_shell_like = path.suffix == ".sh" or path.name.startswith("Dockerfile")
    findings: list[Finding] = []
    rules = _RULES + (_SHELL_RULES if is_shell_like else ())
    text = path.read_text()
    lines = (
        _shell_logical_lines(text) if is_shell_like else list(enumerate(text.splitlines(), start=1))
    )
    for lineno, line in lines:
        for rule in rules:
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
    for path in sorted(
        candidate
        for candidate in root.rglob("*")
        if candidate.suffix in {".py", ".sh"} or candidate.name.startswith("Dockerfile")
    ):
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        findings.extend(scan_file(path, root=root))
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
