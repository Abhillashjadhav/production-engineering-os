"""Trusted, static checks for the stdlib-only Python generation profile.

Candidate code is data: neither imports nor candidate tool configuration execute.
This profile supplements acceptance/security checks; it does not certify behavior.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.contracts.canonical import canonical_digest

PROFILE = "python-stdlib-quality/v1"
_CHECKS = ("syntax", "dependencies", "verification_integrity", "format", "lint", "types")
_SUPPRESSION = re.compile(r"noqa|type:\s*ignore|mypy:|ruff:", re.IGNORECASE)
_OTHER_CODE = {".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".sh"}


@dataclass(frozen=True)
class PythonCheck:
    name: str
    status: str
    details: str


@dataclass(frozen=True)
class PythonQualityReport:
    profile: str
    candidate_digest: str
    checks: tuple[PythonCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.status == "PASS" for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def generation_policy() -> dict[str, Any]:
    """The builder receives the same requirements the trusted verifier enforces."""
    return {
        "profile": PROFILE,
        "required_checks": list(_CHECKS),
        "dependencies": "Python standard library and candidate-local modules only",
        "instructions": [
            "Implement the approved contract; do not change acceptance expectations.",
            "Keep module responsibilities explicit; reuse existing local components.",
            "Use typed public interfaces and explicit error handling.",
            "Use ruff formatting and fix undefined names and type mismatches.",
            "Do not add checker suppressions, external dependencies or unrelated code.",
            "Make the smallest coherent repair for the supplied findings.",
        ],
    }


def _tool_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def missing_quality_tools() -> tuple[str, ...]:
    return tuple(name for name in ("ruff", "mypy") if not _tool_available(name))


def _run_tool(name: str, arguments: list[str], root: Path) -> tuple[str, str]:
    if not _tool_available(name):
        return "UNAVAILABLE", f"required checker missing: {name}; install PEOS dev dependencies"
    try:
        result = subprocess.run(
            [sys.executable, "-P", "-m", name, *arguments],
            cwd=root,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "UNAVAILABLE", f"required checker could not complete: {name}"
    details = (result.stdout + result.stderr).strip()[:20000]
    return ("PASS" if result.returncode == 0 else "FAIL"), details


def check_python_candidate(snapshot: Mapping[str, bytes]) -> PythonQualityReport:
    """Check an immutable snapshot in a disposable directory, ignoring its config."""
    for relative in snapshot:
        path = PurePosixPath(relative)
        if (
            not relative
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in relative
            or str(path) != relative
        ):
            raise ValueError("candidate contains an unsafe path")
    digest = canonical_digest(
        {
            path: "sha256:" + hashlib.sha256(payload).hexdigest()
            for path, payload in sorted(snapshot.items())
        }
    )
    sources = {path: data for path, data in snapshot.items() if path.endswith(".py")}
    if not sources or any(PurePosixPath(p).suffix in _OTHER_CODE for p in snapshot):
        return PythonQualityReport(
            PROFILE,
            digest,
            (
                PythonCheck(
                    "syntax", "FAIL", "profile requires Python source; other stacks unsupported"
                ),
            ),
        )
    if len(snapshot) > 1000 or sum(map(len, snapshot.values())) > 2_000_000:
        return PythonQualityReport(
            PROFILE,
            digest,
            (PythonCheck("syntax", "FAIL", "candidate exceeds static verification budget"),),
        )
    syntax: list[str] = []
    dependencies: list[str] = []
    integrity: list[str] = []
    local_roots = {PurePosixPath(path).parts[0].removesuffix(".py") for path in sources}
    with tempfile.TemporaryDirectory(prefix="pmpe-python-quality-") as temporary:
        root = Path(temporary)
        for relative, payload in sources.items():
            try:
                source = payload.decode("utf-8")
                tree = ast.parse(source, filename=relative)
                for token in tokenize.generate_tokens(io.StringIO(source).readline):
                    if token.type == tokenize.COMMENT and _SUPPRESSION.search(token.string):
                        integrity.append(f"{relative}:{token.start[0]}: checker suppression")
                for node in ast.walk(tree):
                    modules: list[str] = []
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                        modules = [node.module]
                    for module in modules:
                        name = module.split(".")[0]
                        if name not in sys.stdlib_module_names and name not in local_roots:
                            dependencies.append(
                                f"{relative}:{getattr(node, 'lineno', 0)}: "
                                f"unsupported import {name}"
                            )
            except (SyntaxError, UnicodeError, tokenize.TokenError) as exc:
                syntax.append(f"{relative}: {type(exc).__name__}")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        checks = [
            PythonCheck(name, "FAIL" if problems else "PASS", "; ".join(problems))
            for name, problems in (
                ("syntax", syntax),
                ("dependencies", dependencies),
                ("verification_integrity", integrity),
            )
        ]
        paths = sorted(sources)
        commands = {
            "format": ("ruff", ["format", "--isolated", "--check", *paths]),
            "lint": ("ruff", ["check", "--isolated", "--select", "E9,F", *paths]),
            "types": (
                "mypy",
                [
                    "--config-file=/dev/null",
                    "--no-incremental",
                    "--cache-dir=/dev/null",
                    "--no-site-packages",
                    "--strict",
                    *paths,
                ],
            ),
        }
        for name, (tool, arguments) in commands.items():
            status, details = _run_tool(tool, arguments, root)
            checks.append(PythonCheck(name, status, details))
    return PythonQualityReport(PROFILE, digest, tuple(checks))
