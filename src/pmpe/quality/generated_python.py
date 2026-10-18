"""Trusted, static checks for the stdlib-only Python generation profile.

Candidate code is data: neither imports nor candidate tool configuration execute.
This profile supplements acceptance/security checks; it does not certify behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PurePosixPath
from typing import Any

from pmpe.contracts.canonical import canonical_digest

PROFILE = "python-stdlib-quality/v1"
_CHECKS = ("syntax", "dependencies", "verification_integrity", "format", "lint", "types")
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
    try:
        distribution(name)
    except PackageNotFoundError:
        return False
    return True


def missing_quality_tools() -> tuple[str, ...]:
    return tuple(name for name in ("ruff", "mypy") if not _tool_available(name))


_OUTPUT_LIMIT = 65536
_TOTAL_SECONDS = 60.0
_LIMITS = (
    "import resource\n"
    "def lower(kind, cap):\n"
    " soft, hard = resource.getrlimit(kind)\n"
    " hard = cap if hard == resource.RLIM_INFINITY else min(hard, cap)\n"
    " soft = hard if soft == resource.RLIM_INFINITY else min(soft, hard)\n"
    " resource.setrlimit(kind, (soft, hard))\n"
    "lower(resource.RLIMIT_AS, 1073741824)\n"
    "lower(resource.RLIMIT_CPU, 20)\n"
    "lower(resource.RLIMIT_STACK, 8388608)\n"
    "lower(resource.RLIMIT_FSIZE, 65536)\n"
)
_STATIC_SCRIPT = r"""
import ast, io, json, re, sys, tokenize

sources = json.loads(sys.stdin.buffer.read(12000001))
problems = {name: [] for name in ("syntax", "dependencies", "verification_integrity")}
local_roots = {path.split("/")[0].removesuffix(".py") for path in sources}
suppressors = {"no_type_check", "no_type_check_decorator"}
for relative, encoded in sources.items():
    try:
        source = bytes.fromhex(encoded).decode("utf-8")
        tree = ast.parse(source, filename=relative)
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and re.search(
                r"noqa|type:\s*ignore|mypy:|ruff:", token.string, re.I
            ):
                problems["verification_integrity"].append(
                    f"{relative}:{token.start[0]}: checker suppression"
                )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module in {"typing", "typing_extensions"}
                and any(a.name in suppressors for a in node.names)
            ) or (isinstance(node, ast.Attribute) and node.attr in suppressors):
                problems["verification_integrity"].append(
                    f"{relative}: type-check suppression decorator"
                )
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                modules = [node.module]
            for module in modules:
                name = module.split(".")[0]
                if name not in sys.stdlib_module_names and name not in local_roots:
                    problems["dependencies"].append(
                        f"{relative}:{getattr(node, 'lineno', 0)}: unsupported import {name}"
                    )
    except (
        SyntaxError,
        UnicodeError,
        tokenize.TokenError,
        RecursionError,
        MemoryError,
        ValueError,
    ) as exc:
        problems["syntax"].append(f"{relative}: {type(exc).__name__}")
print(json.dumps(problems))
"""
_TOOL_SCRIPT = (
    "import sys,runpy,json\n"
    "sys.path[:0]=json.loads(sys.argv.pop(1))\n"
    "name=sys.argv.pop(1)\n"
    "assert name in {'ruff','mypy'}\n"
    "sys.argv[0]=name\n"
    "runpy.run_module(name,run_name='__main__')\n"
)


def _run_bounded(
    script: str, arguments: tuple[str, ...], payload: bytes, root: Path, deadline: float
) -> tuple[int, bytes, bytes]:
    """Run only fixed verifier code, with bounded resources/output and group cleanup."""
    if not all(hasattr(os, name) for name in ("waitid", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT")):
        return -1, b"", b""
    try:
        library = Path(sys.executable).resolve(strict=True).parent.parent / "lib"
        if ":" in str(library):
            return -1, b"", b""
        with (
            tempfile.TemporaryFile() as incoming,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            incoming.write(payload)
            incoming.seek(0)
            if time.monotonic() >= deadline:
                return -1, b"", b""
            process = subprocess.Popen(
                [sys.executable, "-I", "-S", "-B", "-c", _LIMITS + script, *arguments],
                stdin=incoming,
                stdout=stdout,
                stderr=stderr,
                cwd=root,
                env={"PATH": os.defpath, "LC_ALL": "C", "LD_LIBRARY_PATH": str(library)},
                start_new_session=True,
            )
            timed_out = False
            lost_child = False
            try:
                while (
                    os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
                ):
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    time.sleep(0.01)
            except ChildProcessError:
                # An external reaper released this PID. It no longer identifies
                # an owned child/group and must never be signalled.
                lost_child = True
            finally:
                # Fence descendants before reaping, so the PID cannot have been reused.
                if not lost_child and process.returncode is None:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                elif lost_child:
                    with suppress(ChildProcessError):
                        process.wait()
            stdout.seek(0)
            stderr.seek(0)
            out, err = stdout.read(_OUTPUT_LIMIT + 1), stderr.read(_OUTPUT_LIMIT + 1)
            if lost_child or timed_out or len(out) + len(err) > _OUTPUT_LIMIT:
                return -1, b"", b""
            return process.returncode if process.returncode is not None else -1, out, err
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return -1, b"", b""


def _run_tool(name: str, arguments: list[str], root: Path, deadline: float) -> tuple[str, str]:
    if not _tool_available(name):
        return "UNAVAILABLE", f"required checker missing: {name}; install PEOS dev dependencies"
    tool_roots = sorted(
        {
            str(Path(str(distribution(name).locate_file(""))).resolve()),
            *(str(Path(sysconfig.get_path(key)).resolve()) for key in ("purelib", "platlib")),
            *(
                str(
                    Path(
                        sysconfig.get_path(
                            key,
                            vars={
                                "base": sys.base_prefix,
                                "platbase": sys.base_exec_prefix,
                            },
                        )
                    ).resolve()
                )
                for key in ("purelib", "platlib")
            ),
        }
    )
    if any(
        Path(path).is_relative_to(root) or root.is_relative_to(Path(path)) for path in tool_roots
    ):
        return "UNAVAILABLE", "checker installation overlaps candidate source"
    code, stdout, stderr = _run_bounded(
        _TOOL_SCRIPT,
        (json.dumps(tool_roots), name, *arguments),
        b"",
        root,
        min(deadline, time.monotonic() + 30),
    )
    if code < 0:
        return "UNAVAILABLE", f"required checker could not complete: {name}"
    details = (stdout + stderr).decode("utf-8", errors="replace").strip()[:20000]
    return ("PASS" if code == 0 else "FAIL"), details


def check_python_candidate(
    snapshot: Mapping[str, bytes],
    *,
    trusted_paths: frozenset[str] = frozenset(),
) -> PythonQualityReport:
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
    sources = {
        path: data
        for path, data in snapshot.items()
        if path.endswith(".py") and path not in trusted_paths
    }
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
    deadline = time.monotonic() + _TOTAL_SECONDS
    with tempfile.TemporaryDirectory(prefix="pmpe-python-quality-") as temporary:
        root = Path(temporary)
        code, raw, _ = _run_bounded(
            _STATIC_SCRIPT,
            (),
            json.dumps({name: value.hex() for name, value in sources.items()}).encode(),
            root,
            min(deadline, time.monotonic() + 5),
        )
        try:
            problems = json.loads(raw) if code == 0 else None
        except (ValueError, UnicodeError):
            problems = None
        if (
            not isinstance(problems, dict)
            or set(problems) != {"syntax", "dependencies", "verification_integrity"}
            or any(
                not isinstance(items, list) or not all(isinstance(item, str) for item in items)
                for items in problems.values()
            )
        ):
            return PythonQualityReport(
                PROFILE,
                digest,
                (PythonCheck("syntax", "FAIL", "static analyzer exceeded execution bounds"),),
            )
        checks = [
            PythonCheck(name, "FAIL" if problems[name] else "PASS", "; ".join(problems[name]))
            for name in ("syntax", "dependencies", "verification_integrity")
        ]
        if problems["syntax"]:
            checks.extend(
                PythonCheck(name, "NOT_RUN", "source syntax or complexity check failed")
                for name in ("format", "lint", "types")
            )
            return PythonQualityReport(PROFILE, digest, tuple(checks))
        for relative, payload in sources.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        paths = ["./" + path for path in sorted(sources)]
        commands = {
            "format": ("ruff", ["format", "--isolated", "--check", "--", *paths]),
            "lint": ("ruff", ["check", "--isolated", "--select", "E9,F", "--", *paths]),
            "types": (
                "mypy",
                [
                    "--config-file=/dev/null",
                    "--no-incremental",
                    "--cache-dir=/dev/null",
                    "--no-site-packages",
                    "--strict",
                    "--",
                    *paths,
                ],
            ),
        }
        for name, (tool, arguments) in commands.items():
            status, details = _run_tool(tool, arguments, root, deadline)
            checks.append(PythonCheck(name, status, details))
    return PythonQualityReport(PROFILE, digest, tuple(checks))
