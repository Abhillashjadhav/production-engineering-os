#!/usr/bin/env python3
"""Run and package the real ChatGPT-authenticated #146 evidence matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
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
CONTROL_COMPARISONS = frozenset(
    f"{baseline}--{current}"
    for baseline, current, expected_exit_code in COMPARISONS
    if expected_exit_code == 0 and f"{baseline}--{current}" != PLANTED_COMPARISON
)


def _command(argv: list[str], *, environment: dict[str, str], timeout: int) -> tuple[int, str]:
    process = subprocess.Popen(
        argv,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
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


def _pmpe_command() -> list[str]:
    source_root = str(ROOT / "src")
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


def _gate_passes(
    run_results: list[dict[str, Any]], comparison_results: list[dict[str, Any]]
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
    source = {
        **source_identity,
        "auth_mode": "chatgpt",
        "created_at": datetime.now(UTC).isoformat(),
        "paid_api_environment_removed": list(PAID_API_ENVIRONMENT),
    }
    _json_file(output / "source.json", source)

    provider_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(PROVIDER))}"
    pmpe_command = _pmpe_command()
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
            str(ROOT / spec.contract),
            "--workspace",
            str(candidates / spec.run_id),
            "--run-id",
            spec.run_id,
            "--repository-root",
            str(evidence_root),
            "--approval-receipt",
            str(ROOT / spec.receipt),
            "--expected-approver",
            spec.approver,
            "--provider-command",
            provider_command,
            "--provider-timeout",
            str(args.provider_timeout),
        ]
        exit_code, command_output = _command(
            argv,
            environment=run_environment,
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
            str(ROOT),
        ]
        exit_code, command_output = _command(argv, environment=environment, timeout=60)
        (comparisons / f"{name}.json").write_text(command_output)
        comparison_results.append(
            {
                "name": name,
                "exit_code": exit_code,
                "expected_exit_code": expected_exit_code,
                "result": _parse_json(command_output),
            }
        )

    source_reverification = _reverify_source_identity(source_identity, commands, environment)
    passed = source_reverification.get("status") == "PASS" and _gate_passes(
        run_results, comparison_results
    )
    summary = {
        "gate": "PASS" if passed else "FAIL",
        "runs": run_results,
        "comparisons": comparison_results,
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
