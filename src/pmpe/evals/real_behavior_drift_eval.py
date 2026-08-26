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

ROOT = Path(__file__).resolve().parents[3]
PROVIDER = ROOT / "examples/barebones/codex-cli-provider.py"
PROMPT_PROFILE_ENV = "PMPE_CODEX_PROMPT_PROFILE"
PAID_API_ENVIRONMENT = ("CODEX_API_KEY", "OPENAI_API_KEY")


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
        "fixture-human",
    ),
    RunSpec(
        "e1-v1-02",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        "fixture-human",
    ),
    RunSpec(
        "e1-v1-03",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        "fixture-human",
    ),
    RunSpec(
        "e1-v2-01",
        "examples/barebones/e1-contract.json",
        "examples/barebones/e1-approval-receipt.json",
        "fixture-human",
        "drift-eval-v2",
    ),
    RunSpec(
        "readiness-v1-01",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        "fixture-human",
    ),
    RunSpec(
        "readiness-v1-02",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        "fixture-human",
    ),
    RunSpec(
        "readiness-v1-03",
        "examples/barebones/readiness-contract.json",
        "examples/barebones/readiness-approval-receipt.json",
        "fixture-human",
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


def _checked_output(argv: list[str], *, timeout: int = 30) -> str:
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"preflight failed: {argv[0]} {argv[1:]!r}: {output}")
    return output


def _preflight() -> dict[str, str]:
    if sys.platform != "linux" or not Path("/proc/self/exe").is_file():
        raise RuntimeError("real drift evaluation requires Linux with mounted /proc")
    resolved: dict[str, str] = {}
    for command in ("bwrap", "codex", "git", "pmpe", "prlimit"):
        executable = shutil.which(command)
        if executable is None:
            raise RuntimeError(f"required command is missing: {command}")
        resolved[command] = executable
    auth = _checked_output([resolved["codex"], "login", "status"])
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
        ]
    )
    _checked_output([resolved["git"], "diff", "--quiet"])
    _checked_output([resolved["git"], "diff", "--cached", "--quiet"])
    return resolved


def _json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    version_change = by_name.get("e1-v1-01--e1-v2-01", {}).get("result")
    if not isinstance(version_change, dict):
        return False
    drift = version_change.get("behavior_drift")
    return bool(
        isinstance(drift, dict)
        and drift.get("detected") is True
        and "prompt_version" in drift.get("attribution", [])
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
    commands = _preflight()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else Path.home() / f"pmpe-real-drift-{timestamp}"
    )
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

    environment = dict(os.environ)
    for name in PAID_API_ENVIRONMENT:
        environment.pop(name, None)
    environment.pop(PROMPT_PROFILE_ENV, None)
    source = {
        "auth_mode": "chatgpt",
        "codex_version": _checked_output([commands["codex"], "--version"]),
        "created_at": datetime.now(UTC).isoformat(),
        "git_head": _checked_output([commands["git"], "rev-parse", "HEAD"]),
        "paid_api_environment_removed": list(PAID_API_ENVIRONMENT),
        "provider_digest": "sha256:" + _sha256(PROVIDER),
        "python": sys.version.split()[0],
    }
    _json_file(output / "source.json", source)

    provider_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(PROVIDER))}"
    run_results: list[dict[str, Any]] = []
    for spec in RUNS:
        print(f"running {spec.run_id} ({spec.prompt_profile})", flush=True)
        run_environment = dict(environment)
        if spec.prompt_profile != "default":
            run_environment[PROMPT_PROFILE_ENV] = spec.prompt_profile
        argv = [
            commands["pmpe"],
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
            timeout=args.provider_timeout + 60,
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
            commands["pmpe"],
            "barebones",
            "compare",
            baseline,
            current,
            "--baseline-root",
            str(evidence_root),
            "--current-root",
            str(evidence_root),
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

    passed = _gate_passes(run_results, comparison_results)
    summary = {
        "gate": "PASS" if passed else "FAIL",
        "runs": run_results,
        "comparisons": comparison_results,
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
