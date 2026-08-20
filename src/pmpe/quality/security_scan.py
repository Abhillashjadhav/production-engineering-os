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


def _env_split_tokens(value: str) -> list[str] | None:
    """Conservatively split ``env -S`` values.

    GNU env gives backslashes and variable expansion semantics that differ from
    POSIX shell tokenization. Until those semantics are implemented exactly,
    values using either feature are unresolved and therefore blocking when
    they occur on the receiving side of a remote-content pipeline.
    """
    if "\\" in value or "$" in value:
        return None
    return _shell_tokens(value)


def _env_wrapped_command(tokens: list[str], command: int) -> tuple[str | None, bool]:
    """Return the wrapped command and whether env parsing was unresolved."""
    remaining = tokens[command:]
    cursor = 0
    split_expansions = 0

    def expand_split(value: str, tail: list[str]) -> bool:
        nonlocal remaining, cursor, split_expansions
        if split_expansions >= 8:
            return False
        expanded = _env_split_tokens(value)
        if expanded is None:
            return False
        remaining = expanded + tail
        cursor = 0
        split_expansions += 1
        return True

    while cursor < len(remaining):
        token = remaining[cursor]
        if token == "-":
            cursor += 1
            continue
        if token == "--":
            cursor += 1
            return (remaining[cursor] if cursor < len(remaining) else None), False
        if token in {"-S", "--split-string"}:
            if cursor + 1 >= len(remaining):
                return None, True
            if not expand_split(remaining[cursor + 1], remaining[cursor + 2 :]):
                return None, True
            continue
        if token.startswith("--split-string="):
            if not expand_split(token.split("=", 1)[1], remaining[cursor + 1 :]):
                return None, True
            continue
        if token in {"-C", "-u", "--chdir", "--unset"}:
            if cursor + 1 >= len(remaining):
                return None, True
            cursor += 2
            continue
        if token.startswith(("--chdir=", "--unset=")):
            cursor += 1
            continue
        if token.startswith("--"):
            if token in {
                "--debug",
                "--help",
                "--ignore-environment",
                "--null",
                "--version",
            }:
                cursor += 1
                continue
            return None, True
        if token.startswith("-") and token != "-":
            cluster = token[1:]
            position = 0
            while position < len(cluster):
                option = cluster[position]
                if option in {"0", "i", "v"}:
                    position += 1
                    continue
                if option not in {"C", "S", "u"}:
                    return None, True
                attached = cluster[position + 1 :]
                if attached:
                    value = attached
                    tail = remaining[cursor + 1 :]
                elif cursor + 1 < len(remaining):
                    value = remaining[cursor + 1]
                    tail = remaining[cursor + 2 :]
                else:
                    return None, True
                if option == "S":
                    if not expand_split(value, tail):
                        return None, True
                else:
                    remaining = tail
                    cursor = 0
                break
            else:
                cursor += 1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) is not None:
            cursor += 1
            continue
        return token, False
    return None, False


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
        command_index = index + 1
        if command_index >= len(tokens):
            continue
        initial_command = tokens[command_index]
        command: str | None = initial_command
        unresolved_env = False
        if _shell_basename(initial_command) == "env":
            command, unresolved_env = _env_wrapped_command(tokens, command_index + 1)
        if unresolved_env or (command is not None and _shell_basename(command) in {"sh", "bash"}):
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
