#!/usr/bin/env python3
"""Run and package the real ChatGPT-authenticated #146 evidence matrix."""

from __future__ import annotations

import argparse
import ast
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmpe.barebones import BudgetCaps

ROOT = Path(__file__).resolve().parents[3]
PROVIDER = ROOT / "examples/barebones/codex-cli-provider.py"
PROMPT_PROFILE_ENV = "PMPE_CODEX_PROMPT_PROFILE"
PAID_API_ENVIRONMENT = ("CODEX_API_KEY", "OPENAI_API_KEY")
_RUN_WRAPPER_OVERHEAD_SECONDS = 300
MATRIX_APPROVER = "fixture-human"
_PROVIDER_CONFIGURATION_FIELDS = ("provider", "model", "prompt_version", "cli_version")
_F_ADD_SEALS = getattr(fcntl, "F_ADD_SEALS", 1033)
_F_SEAL_SEAL = getattr(fcntl, "F_SEAL_SEAL", 0x0001)
_F_SEAL_SHRINK = getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
_F_SEAL_GROW = getattr(fcntl, "F_SEAL_GROW", 0x0004)
_F_SEAL_WRITE = getattr(fcntl, "F_SEAL_WRITE", 0x0008)


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    contract: str
    receipt: str
    approver: str
    prompt_profile: str = "default"


RUNS = (
    RunSpec(
        "e1-v1-01",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        MATRIX_APPROVER,
    ),
    RunSpec(
        "e1-v1-02",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        MATRIX_APPROVER,
    ),
    RunSpec(
        "e1-v1-03",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        MATRIX_APPROVER,
    ),
    RunSpec(
        "e1-v2-01",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        MATRIX_APPROVER,
        "drift-eval-v2",
    ),
    RunSpec(
        "readiness-v1-01",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        MATRIX_APPROVER,
    ),
    RunSpec(
        "readiness-v1-02",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        MATRIX_APPROVER,
    ),
    RunSpec(
        "readiness-v1-03",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        MATRIX_APPROVER,
    ),
)

COMPARISONS = (
    ("e1-v1-01", "e1-v1-02", 0),
    ("e1-v1-01", "e1-v1-03", 0),
    ("e1-v1-01", "e1-v2-01", 0),
    ("readiness-v1-01", "readiness-v1-02", 0),
    ("readiness-v1-01", "readiness-v1-03", 0),
    ("e1-v1-01", "readiness-v1-01", 3),
)
PLANTED_COMPARISON = "e1-v1-01--e1-v2-01"
PLANTED_BASELINE_RUN_ID = "e1-v1-01"
PLANTED_RUN_ID = "e1-v2-01"
PLANTED_FILE = "product.py"
PLANTED_CONSTANT = "PMPE_PROMPT_PROFILE"
PLANTED_VALUE = "drift-eval-v2"
CONTROL_COMPARISONS = frozenset(
    f"{baseline}--{current}"
    for baseline, current, expected_exit_code in COMPARISONS
    if expected_exit_code == 0 and f"{baseline}--{current}" != PLANTED_COMPARISON
)


def _command(
    argv: list[str],
    *,
    environment: dict[str, str],
    pass_fds: tuple[int, ...] = (),
    timeout: int,
    cwd: Path = ROOT,
) -> tuple[int, str]:
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        pass_fds=pass_fds,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        return 124, output + "\nEVAL_WRAPPER_TIMEOUT\n"


def _sanitized_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in PAID_API_ENVIRONMENT:
        environment.pop(name, None)
    environment.pop(PROMPT_PROFILE_ENV, None)
    return environment


def _checked_output(argv: list[str], *, environment: dict[str, str], timeout: int = 30) -> str:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"preflight failed: {argv[0]} {argv[1:]!r}: {output}")
    return output


def _preflight(environment: dict[str, str]) -> dict[str, str]:
    if sys.platform != "linux" or not Path("/proc/self/exe").is_file():
        raise RuntimeError("real drift evaluation requires Linux with mounted /proc")
    resolved: dict[str, str] = {}
    for command in ("bwrap", "codex", "git", "prlimit"):
        executable = shutil.which(command, path=environment.get("PATH"))
        if executable is None:
            raise RuntimeError(f"required command is missing: {command}")
        resolved[command] = executable
    auth = _checked_output([resolved["codex"], "login", "status"], environment=environment)
    normalized_auth = auth.lower()
    if (
        re.search(r"\blogged in (?:using|with) chatgpt\b", normalized_auth) is None
        or "api key" in normalized_auth
        or "api-key" in normalized_auth
    ):
        raise RuntimeError("Codex CLI must be authenticated using ChatGPT, not an API key")
    _checked_output(
        [
            resolved["bwrap"],
            "--unshare-all",
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "/bin/true",
        ],
        environment=environment,
    )
    _checked_output([resolved["git"], "diff", "--quiet"], environment=environment)
    _checked_output([resolved["git"], "diff", "--cached", "--quiet"], environment=environment)
    status = _checked_output(
        [resolved["git"], "status", "--porcelain=v1", "--untracked-files=all"],
        environment=environment,
    )
    if status:
        raise RuntimeError("source checkout must be clean before real drift evaluation")
    return resolved


def _pmpe_command(source_checkout: Path = ROOT) -> list[str]:
    source_root = str(source_checkout / "src")
    launcher = (
        f"import sys;sys.path.insert(0,{source_root!r});"
        "from pmpe.cli import main;raise SystemExit(main())"
    )
    return [sys.executable, "-I", "-c", launcher]


def _run_wrapper_timeout(provider_timeout: int) -> int:
    """Outlive every bounded provider call so inner process-group fencing runs first."""

    return provider_timeout * BudgetCaps().max_model_calls + _RUN_WRAPPER_OVERHEAD_SECONDS


def _validate_output_path(output: Path) -> None:
    if output == ROOT or output.is_relative_to(ROOT):
        raise ValueError("--output-dir must be outside the source checkout")


def _json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_image(
    source_checkout: Path,
) -> tuple[list[dict[str, str | int]], list[tuple[str, bytes, int]]]:
    entries: list[dict[str, str | int]] = [
        {
            "mode": stat.S_IMODE(source_checkout.stat().st_mode),
            "path": ".",
            "type": "directory",
        }
    ]
    files: list[tuple[str, bytes, int]] = []
    for path in sorted(source_checkout.rglob("*")):
        relative = path.relative_to(source_checkout).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("source snapshot contains a symbolic link")
        if stat.S_ISDIR(metadata.st_mode):
            entries.append(
                {
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "path": relative,
                    "type": "directory",
                }
            )
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError("source snapshot contains an unsupported file type")
        content = path.read_bytes()
        entries.append(
            {
                "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "mode": stat.S_IMODE(metadata.st_mode),
                "path": relative,
                "type": "file",
            }
        )
        files.append((relative, content, stat.S_IMODE(metadata.st_mode)))
    return entries, files


def _snapshot_entries_digest(entries: list[dict[str, str | int]]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _snapshot_mode(entry: dict[str, str | int]) -> str:
    mode = entry.get("mode")
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
        raise RuntimeError("source snapshot contains an invalid mode")
    return f"{mode:04o}"


def _snapshot_tree_digest(source_checkout: Path) -> str:
    """Hash every source entry, including its path, type, mode, and content."""

    entries, _ = _snapshot_image(source_checkout)
    return _snapshot_entries_digest(entries)


def _assert_snapshot_identity(source_checkout: Path, expected_tree_digest: str) -> None:
    try:
        observed = _snapshot_tree_digest(source_checkout)
    except OSError as exc:
        raise RuntimeError("source snapshot could not be reverified") from exc
    if observed != expected_tree_digest:
        raise RuntimeError("source snapshot changed during the matrix")


def _sealed_memfd(content: bytes) -> int:
    try:
        descriptor = os.memfd_create(
            "pmpe-source",
            flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
        )
        remaining = memoryview(content)
        while remaining:
            written = os.write(descriptor, remaining)
            remaining = remaining[written:]
        os.lseek(descriptor, 0, os.SEEK_SET)
        fcntl.fcntl(
            descriptor,
            _F_ADD_SEALS,
            _F_SEAL_SEAL | _F_SEAL_SHRINK | _F_SEAL_GROW | _F_SEAL_WRITE,
        )
    except (AttributeError, OSError) as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise RuntimeError("could not seal the private source image") from exc
    return descriptor


def _snapshot_command(
    argv: list[str],
    *,
    bwrap_executable: str,
    environment: dict[str, str],
    expected_tree_digest: str,
    source_checkout: Path,
    timeout: int,
) -> tuple[int, str]:
    """Execute with the source mounted read-only and verify it at both boundaries."""

    _assert_snapshot_identity(source_checkout, expected_tree_digest)
    entries, files = _snapshot_image(source_checkout)
    if _snapshot_entries_digest(entries) != expected_tree_digest:
        raise RuntimeError("private source image does not match the captured snapshot")
    descriptors: list[int] = []
    root_entry = entries[0]
    if root_entry.get("path") != "." or root_entry.get("type") != "directory":
        raise RuntimeError("source snapshot root entry is invalid")
    command = [
        bwrap_executable,
        "--die-with-parent",
        "--bind",
        "/",
        "/",
        "--perms",
        _snapshot_mode(root_entry),
        "--tmpfs",
        str(source_checkout),
    ]
    for entry in entries:
        if entry["type"] == "directory" and entry["path"] != ".":
            command.extend(
                (
                    "--perms",
                    _snapshot_mode(entry),
                    "--dir",
                    str(source_checkout / str(entry["path"])),
                )
            )
    try:
        for relative, content, mode in files:
            descriptor = _sealed_memfd(content)
            descriptors.append(descriptor)
            command.extend(
                (
                    "--perms",
                    f"{mode:04o}",
                    "--file",
                    str(descriptor),
                    str(source_checkout / relative),
                )
            )
        command.extend(
            (
                "--remount-ro",
                str(source_checkout),
                "--chdir",
                str(source_checkout),
                "--",
                *argv,
            )
        )
        return _command(
            command,
            environment=environment,
            pass_fds=tuple(descriptors),
            timeout=timeout,
            cwd=source_checkout,
        )
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        _assert_snapshot_identity(source_checkout, expected_tree_digest)


def _materialize_source_snapshot(
    destination: Path,
    *,
    git_executable: str,
    git_head: str,
    environment: dict[str, str],
) -> dict[str, str]:
    """Extract one content-addressed Git tree and make it read-only for all children."""

    if destination.exists():
        raise RuntimeError("source snapshot destination already exists")
    destination.mkdir(parents=True)
    try:
        with tempfile.TemporaryFile() as archive_file:
            completed = subprocess.run(
                [git_executable, "archive", "--format=tar", git_head],
                cwd=ROOT,
                env=environment,
                stdout=archive_file,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("could not archive the captured source commit")
            archive_file.seek(0)
            archive_hasher = hashlib.sha256()
            while chunk := archive_file.read(1024 * 1024):
                archive_hasher.update(chunk)
            archive_file.seek(0)
            with tarfile.open(fileobj=archive_file, mode="r:") as bundle:
                bundle.extractall(destination, filter="data")
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        raise RuntimeError("could not materialize the captured source commit") from exc

    snapshot_provider = destination / "examples/barebones/codex-cli-provider.py"
    if not snapshot_provider.is_file():
        raise RuntimeError("source snapshot does not contain the reviewed provider")
    for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise RuntimeError("source snapshot contains a symbolic link")
        path.chmod(0o555 if path.is_dir() else 0o444)
    destination.chmod(0o555)
    return {
        "archive_digest": "sha256:" + archive_hasher.hexdigest(),
        "git_head": git_head,
        "provider_digest": "sha256:" + _sha256(snapshot_provider),
        "tree_digest": _snapshot_tree_digest(destination),
    }


def _source_identity(commands: dict[str, str], environment: dict[str, str]) -> dict[str, str]:
    """Capture the mutable source/provider identity used by matrix children."""

    return {
        "codex_version": _checked_output([commands["codex"], "--version"], environment=environment),
        "git_head": _checked_output(
            [commands["git"], "rev-parse", "HEAD"], environment=environment
        ),
        "git_status": _checked_output(
            [commands["git"], "status", "--porcelain=v1", "--untracked-files=all"],
            environment=environment,
        ),
        "provider_digest": "sha256:" + _sha256(PROVIDER),
        "python": sys.version.split()[0],
    }


def _reverify_source_identity(
    expected: dict[str, str],
    commands: dict[str, str],
    environment: dict[str, str],
) -> dict[str, Any]:
    """Fail closed when source or provider identity changes during the matrix."""

    try:
        observed = _source_identity(commands, environment)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"status": "FAIL", "error": str(exc)}
    changed_fields = sorted(
        field for field, value in expected.items() if observed.get(field) != value
    )
    return {
        "status": "PASS" if not changed_fields else "FAIL",
        "changed_fields": changed_fields,
        "observed": observed,
    }


def _write_manifest(output: Path) -> None:
    entries = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        entries.append(f"{_sha256(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS").write_text("\n".join(entries) + "\n")


def _parse_json(output: str) -> dict[str, Any] | None:
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _provider_configuration_changes(comparison: dict[str, Any]) -> list[str] | None:
    baseline = comparison.get("baseline")
    current = comparison.get("current")
    baseline_behavior = baseline.get("provider_behavior") if isinstance(baseline, dict) else None
    current_behavior = current.get("provider_behavior") if isinstance(current, dict) else None
    if not isinstance(baseline_behavior, dict) or not isinstance(current_behavior, dict):
        return None
    if any(
        not isinstance(baseline_behavior.get(field), str)
        or not isinstance(current_behavior.get(field), str)
        for field in _PROVIDER_CONFIGURATION_FIELDS
    ):
        return None
    return [
        field
        for field in _PROVIDER_CONFIGURATION_FIELDS
        if baseline_behavior[field] != current_behavior[field]
    ]


def _has_exact_planted_constant(content: str) -> bool:
    """Require one exact top-level assignment in the sealed planted candidate."""

    try:
        module = ast.parse(content)
    except SyntaxError:
        return False
    assignments: list[ast.expr | None] = []
    for statement in module.body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == PLANTED_CONSTANT for target in targets
        ):
            assignments.append(statement.value)
    return (
        len(assignments) == 1
        and isinstance(assignments[0], ast.Constant)
        and (assignments[0].value == PLANTED_VALUE)
    )


def _inspect_planted_behavior(
    pmpe_command: list[str],
    evidence_root: Path,
    environment: dict[str, str],
    *,
    bwrap_executable: str,
    expected_tree_digest: str,
    source_checkout: Path = ROOT,
) -> dict[str, Any]:
    """Verify the requested plant in the immutable candidate ledger, not the workspace."""

    def inspect(run_id: str) -> tuple[int, str | None, bool]:
        exit_code, command_output = _snapshot_command(
            [
                *pmpe_command,
                "barebones",
                "inspect",
                run_id,
                "--repository-root",
                str(evidence_root),
                "--file",
                PLANTED_FILE,
            ],
            bwrap_executable=bwrap_executable,
            environment=environment,
            expected_tree_digest=expected_tree_digest,
            source_checkout=source_checkout,
            timeout=60,
        )
        result = _parse_json(command_output)
        selected_file = result.get("selected_file") if isinstance(result, dict) else None
        content = selected_file.get("content") if isinstance(selected_file, dict) else None
        digest = selected_file.get("digest") if isinstance(selected_file, dict) else None
        observed = isinstance(content, str) and _has_exact_planted_constant(content)
        return exit_code, digest if isinstance(digest, str) else None, observed

    baseline_exit_code, baseline_digest, baseline_observed = inspect(PLANTED_BASELINE_RUN_ID)
    exit_code, digest, observed = inspect(PLANTED_RUN_ID)
    return {
        "baseline_exit_code": baseline_exit_code,
        "baseline_run_id": PLANTED_BASELINE_RUN_ID,
        "baseline_selected_file_digest": baseline_digest,
        "baseline_observed": baseline_observed,
        "exit_code": exit_code,
        "run_id": PLANTED_RUN_ID,
        "file": PLANTED_FILE,
        "selected_file_digest": digest if isinstance(digest, str) else None,
        "constant": PLANTED_CONSTANT,
        "expected_value": PLANTED_VALUE,
        "observed": observed,
    }


def _gate_passes(
    run_results: list[dict[str, Any]],
    comparison_results: list[dict[str, Any]],
    planted_behavior: dict[str, Any],
) -> bool:
    if len(run_results) != len(RUNS) or len(comparison_results) != len(COMPARISONS):
        return False
    if any(
        item.get("exit_code") != 0
        or not isinstance(item.get("result"), dict)
        or item["result"].get("state") != "RELEASE_READY"
        or item["result"].get("cause") != "PASS"
        for item in run_results
    ):
        return False
    if (
        planted_behavior.get("baseline_exit_code") != 0
        or planted_behavior.get("baseline_run_id") != PLANTED_BASELINE_RUN_ID
        or not isinstance(planted_behavior.get("baseline_selected_file_digest"), str)
        or planted_behavior.get("baseline_observed") is not False
        or planted_behavior.get("exit_code") != 0
        or planted_behavior.get("run_id") != PLANTED_RUN_ID
        or planted_behavior.get("file") != PLANTED_FILE
        or planted_behavior.get("constant") != PLANTED_CONSTANT
        or planted_behavior.get("expected_value") != PLANTED_VALUE
        or planted_behavior.get("observed") is not True
        or not isinstance(planted_behavior.get("selected_file_digest"), str)
    ):
        return False
    for item in comparison_results:
        result = item.get("result")
        if item.get("exit_code") != item.get("expected_exit_code") or not isinstance(result, dict):
            return False
        if item["expected_exit_code"] == 0:
            if result.get("status") != "COMPARABLE" or result.get("plan_repeatable") is not True:
                return False
        elif result.get("status") != "NOT_COMPARABLE" or result.get("cause") != "CONTRACT_CHANGED":
            return False
    by_name = {item["name"]: item for item in comparison_results}
    for name in CONTROL_COMPARISONS:
        control = by_name.get(name, {}).get("result")
        if not isinstance(control, dict):
            return False
        control_drift = control.get("behavior_drift")
        if (
            not isinstance(control_drift, dict)
            or control_drift.get("attribution") != []
            or _provider_configuration_changes(control) != []
        ):
            return False
    version_change = by_name.get(PLANTED_COMPARISON, {}).get("result")
    if not isinstance(version_change, dict):
        return False
    drift = version_change.get("behavior_drift")
    return bool(
        isinstance(drift, dict)
        and drift.get("detected") is True
        and drift.get("attribution") == ["prompt_version"]
        and _provider_configuration_changes(version_change) == ["prompt_version"]
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--provider-timeout", type=int, default=960)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.provider_timeout < 60 or args.provider_timeout > 3600:
        raise SystemExit("--provider-timeout must be between 60 and 3600 seconds")
    environment = _sanitized_environment()
    commands = _preflight(environment)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else Path.home() / f"pmpe-real-drift-{timestamp}"
    )
    try:
        _validate_output_path(output)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    archive = output.parent / f"{output.name}.tgz"
    if output.exists():
        raise SystemExit(f"output directory already exists: {output}")
    if archive.exists():
        raise SystemExit(f"archive already exists: {archive}")
    evidence_root = output / "evidence"
    candidates = output / "candidates"
    logs = output / "logs"
    comparisons = output / "comparisons"
    for directory in (evidence_root, candidates, logs, comparisons):
        directory.mkdir(parents=True)

    source_identity = _source_identity(commands, environment)
    source_checkout = output / "source-snapshot"
    snapshot_identity = _materialize_source_snapshot(
        source_checkout,
        git_executable=commands["git"],
        git_head=source_identity["git_head"],
        environment=environment,
    )
    if snapshot_identity["provider_digest"] != source_identity["provider_digest"]:
        raise RuntimeError("captured source snapshot does not match the reviewed provider")
    source = {
        **source_identity,
        "auth_mode": "chatgpt",
        "created_at": datetime.now(UTC).isoformat(),
        "execution_source": "read_only_git_snapshot",
        "paid_api_environment_removed": list(PAID_API_ENVIRONMENT),
        "snapshot": snapshot_identity,
    }
    _json_file(output / "source.json", source)

    snapshot_provider = source_checkout / "examples/barebones/codex-cli-provider.py"
    provider_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(snapshot_provider))}"
    pmpe_command = _pmpe_command(source_checkout)
    run_results: list[dict[str, Any]] = []
    for spec in RUNS:
        print(f"running {spec.run_id} ({spec.prompt_profile})", flush=True)
        run_environment = dict(environment)
        if spec.prompt_profile != "default":
            run_environment[PROMPT_PROFILE_ENV] = spec.prompt_profile
        argv = [
            *pmpe_command,
            "barebones",
            "run",
            str(source_checkout / spec.contract),
            "--workspace",
            str(candidates / spec.run_id),
            "--run-id",
            spec.run_id,
            "--repository-root",
            str(evidence_root),
            "--approval-receipt",
            str(source_checkout / spec.receipt),
            "--expected-approver",
            spec.approver,
            "--provider-command",
            provider_command,
            "--provider-timeout",
            str(args.provider_timeout),
        ]
        exit_code, command_output = _snapshot_command(
            argv,
            bwrap_executable=commands["bwrap"],
            environment=run_environment,
            expected_tree_digest=snapshot_identity["tree_digest"],
            source_checkout=source_checkout,
            timeout=_run_wrapper_timeout(args.provider_timeout),
        )
        (logs / f"{spec.run_id}.log").write_text(command_output)
        run_results.append(
            {
                **asdict(spec),
                "exit_code": exit_code,
                "result": _parse_json(command_output),
            }
        )

    comparison_results: list[dict[str, Any]] = []
    for baseline, current, expected_exit_code in COMPARISONS:
        name = f"{baseline}--{current}"
        argv = [
            *pmpe_command,
            "barebones",
            "compare",
            baseline,
            current,
            "--baseline-root",
            str(evidence_root),
            "--current-root",
            str(evidence_root),
            "--expected-approver",
            MATRIX_APPROVER,
            "--compiler-root",
            str(source_checkout),
        ]
        exit_code, command_output = _snapshot_command(
            argv,
            bwrap_executable=commands["bwrap"],
            environment=environment,
            expected_tree_digest=snapshot_identity["tree_digest"],
            source_checkout=source_checkout,
            timeout=60,
        )
        (comparisons / f"{name}.json").write_text(command_output)
        comparison_results.append(
            {
                "name": name,
                "exit_code": exit_code,
                "expected_exit_code": expected_exit_code,
                "result": _parse_json(command_output),
            }
        )

    planted_behavior = _inspect_planted_behavior(
        pmpe_command,
        evidence_root,
        environment,
        bwrap_executable=commands["bwrap"],
        expected_tree_digest=snapshot_identity["tree_digest"],
        source_checkout=source_checkout,
    )
    _assert_snapshot_identity(source_checkout, snapshot_identity["tree_digest"])
    source_reverification = _reverify_source_identity(source_identity, commands, environment)
    passed = source_reverification.get("status") == "PASS" and _gate_passes(
        run_results, comparison_results, planted_behavior
    )
    summary = {
        "gate": "PASS" if passed else "FAIL",
        "runs": run_results,
        "comparisons": comparison_results,
        "planted_behavior": planted_behavior,
        "source_reverification": source_reverification,
    }
    _json_file(output / "summary.json", summary)
    _write_manifest(output)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(output, arcname=output.name)
    print(
        json.dumps(
            {
                "archive": str(archive),
                "gate": summary["gate"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
