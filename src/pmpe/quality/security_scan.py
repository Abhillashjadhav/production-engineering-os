"""Built-in deterministic security scanner.

Runs on every build regardless of environment; bandit (when installed) covers the
OS's own source in CI. Each rule is a named regex over source lines so every
finding is explainable and reproducible.
"""

from __future__ import annotations

import re
import shlex
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

_SKIP_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache", ".pytest_cache"}
_SHELL_SEPARATORS = {";", "&&", "||", "|"}


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


def _shell_basename(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def _shell_tokens(line: str) -> list[str]:
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return []


def _env_command_index(tokens: list[str], command: int) -> int:
    options_with_separate_argument = {
        "-C",
        "-S",
        "-u",
        "--chdir",
        "--split-string",
        "--unset",
    }
    while command < len(tokens):
        token = tokens[command]
        if token == "--":
            command += 1
            break
        if token in options_with_separate_argument:
            command += 2
            continue
        if token.startswith("-"):
            command += 1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) is not None:
            command += 1
            continue
        break
    return command


def _shell_rule_matches(line: str) -> list[tuple[str, str]]:
    tokens = _shell_tokens(line)
    matches: list[tuple[str, str]] = []
    for index, token in enumerate(tokens):
        if _shell_basename(token) != "rm":
            continue
        recursive = False
        force = False
        for option in tokens[index + 1 :]:
            if option in _SHELL_SEPARATORS:
                break
            if option == "--":
                break
            if option == "--recursive":
                recursive = True
            elif option == "--force":
                force = True
            elif option.startswith("-") and not option.startswith("--"):
                recursive = recursive or "r" in option[1:] or "R" in option[1:]
                force = force or "f" in option[1:]
        if recursive and force:
            matches.append(
                (
                    "SEC_SHELL_RECURSIVE_DELETE",
                    "recursive forced deletion in an executable deployment script",
                )
            )
            break

    for index, token in enumerate(tokens):
        if token != "|":
            continue
        pipeline_start = 0
        for candidate_index in range(index - 1, -1, -1):
            if tokens[candidate_index] in {";", "&&", "||"}:
                pipeline_start = candidate_index + 1
                break
        if not any(
            _shell_basename(candidate) in {"curl", "wget"}
            for candidate in tokens[pipeline_start:index]
        ):
            continue
        command = index + 1
        if command >= len(tokens):
            continue
        if _shell_basename(tokens[command]) == "env":
            command = _env_command_index(tokens, command + 1)
        if command < len(tokens) and _shell_basename(tokens[command]) in {"sh", "bash"}:
            matches.append(("SEC_SHELL_REMOTE_PIPE", "remote content piped directly to a shell"))
            break
    return matches


def scan_file(path: Path, root: Path | None = None) -> list[Finding]:
    """Scan one file. Test-file detection uses the path RELATIVE to ``root`` when
    given — absolute ancestors named 'tests' (e.g. a runs dir under /home/x/tests/)
    must never exempt product code from the secret rule."""
    rel_parts = path.relative_to(root).parts if root is not None else (path.name,)
    is_test = "tests" in rel_parts or path.name.startswith("test_")
    is_shell_like = path.suffix == ".sh" or path.name.startswith("Dockerfile")
    findings: list[Finding] = []
    rules = _RULES
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
        if is_shell_like:
            for rule_id, message in _shell_rule_matches(line):
                findings.append(
                    Finding(
                        id=f"SEC-{len(findings) + 1:03d}",
                        category="security",
                        severity=Severity.CRITICAL,
                        blocking=True,
                        safe_to_autofix=False,
                        file=str(path),
                        line=lineno,
                        message=message,
                        rule=rule_id,
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
