#!/usr/bin/env python3
"""Load frozen contract bindings into the existing engine; no isolation is added.

The explicit host fallback uses the existing container with resource limits.
It is not a sandbox. Root can still tamper with this process or its evidence.
"""

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
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from pmpe.barebones import (
    BudgetCaps,
    ContractInvalidError,
    Template,
    _safe_path,
    _verify_snapshot,
    _workspace_snapshot,
    compile_barebones_plan,
    run_to_release_ready,
)
from pmpe.cli.barebones_cmd import CommandModelProvider, _require_approved_contract
from pmpe.contracts.canonical import canonical_digest, strict_loads
from pmpe.contracts.model import load_contract

LIMIT = 1_000_000


def read_json(path):
    return strict_loads(Path(path).read_bytes(), "application/json")


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, default=str) + "\n")


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append(path, value):
    with Path(path).open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, default=str) + "\n")


def load_template(path):
    """Admit only explicit files and protected action/measure targets; never import them here."""
    data = read_json(path)
    if set(data) - {"version", "files", "actions", "measures", "context"}:
        raise ValueError("BINDINGS_UNSUPPORTED: use explicit action/measure bindings; no proofs")
    template = Template(**data)
    if not isinstance(template.version, str) or not template.version:
        raise ValueError("BINDINGS_INVALID: version is required")
    for relative, content in template.files.items():
        _safe_path(Path("/unused-validation-root"), relative)
        if not isinstance(content, str):
            raise ValueError("BINDINGS_INVALID: file contents must be UTF-8 text")
    for target in (*template.actions.values(), *template.measures.values()):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)", target)
        if match is None:
            raise ValueError("BINDINGS_INVALID: target must be module:function")
        relative = match[1].replace(".", "/") + ".py"
        if not relative.startswith("tests/") or relative not in template.files:
            raise ValueError("BINDING_PERMISSION_DENIED: evaluator must be a frozen tests/ file")
        for parent in Path(relative).parents:
            if str(parent) != "." and str(parent / "__init__.py") not in template.files:
                raise ValueError("BINDINGS_INVALID: explicit package initializer required")
    return template


class TamperDetectedError(RuntimeError):
    """Fatal to the run, including when the behavioral check would pass."""


class DigestGuard:
    def __init__(self, manifest, roots, expected, log):
        self.manifest = Path(manifest)
        self.expected = expected
        data = read_json(self.manifest)
        if canonical_digest(data) != expected:
            raise TamperDetectedError("FREEZE_DIGEST_MISMATCH")
        self.entries = []
        for item in data["artifacts"]:
            root = Path(roots[item["repository"]]).resolve()
            path = _safe_path(root, item["path"])
            self.entries.append((path, item["sha256"]))
        self.entries += [(self.manifest.resolve(), digest(self.manifest))]
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.inventory = canonical_digest([(str(path), sha) for path, sha in self.entries])

    def check(self, stage, subject="bundle", extra=None):
        mismatches = []
        entries = self.entries + list((extra or {}).items())
        observed = []
        for path, expected in entries:
            path = Path(path)
            try:
                # A replacement symlink is also an artifact change even if its target matches.
                actual = "SYMLINK" if path.is_symlink() else digest(path)
            except OSError:
                actual = "MISSING_OR_UNREADABLE"
            observed.append((str(path), actual))
            if actual != expected:
                mismatches.append({"path": str(path), "expected": expected, "actual": actual})
        append(
            self.log,
            {
                "stage": stage,
                "subject": subject,
                "checked": len(entries),
                "expected_inventory_digest": canonical_digest([(str(p), s) for p, s in entries]),
                "observed_inventory_digest": canonical_digest(observed),
                "mismatches": mismatches,
            },
        )
        if mismatches:
            raise TamperDetectedError("APPROVAL_BOUND_ARTIFACT_CHANGED: " + str(mismatches))

    @contextmanager
    def boundary(self, subject, extra=None):
        self.check("before", subject, extra)
        try:
            yield
        finally:
            self.check("after", subject, extra)


class HostExecution:
    """Explicitly authorized container-process fallback, not an isolation boundary."""

    def __init__(self, guard, template, caps, criteria, log):
        self.guard, self.template, self.caps = guard, template, caps
        self.criteria, self.log, self.count = criteria, Path(log), 0
        self.entry_digest = digest(__file__)

    def run(self, workspace, argv, *, timeout_seconds, environment):
        protected = {
            _safe_path(workspace, path): "sha256:" + hashlib.sha256(source.encode()).hexdigest()
            for path, source in self.template.files.items()
            if path.startswith("tests/")
        }
        protected[Path(__file__).resolve()] = self.entry_digest
        criterion = self.criteria[self.count % len(self.criteria)] if self.criteria else None
        subject = criterion.criterion_id if criterion else "fixture"
        record = {
            "check_index": self.count,
            "criterion_id": subject,
            "mode": "AUTHORIZED_HOST_FALLBACK_NO_ADDITIONAL_ISOLATION",
        }
        self.count += 1
        started = time.monotonic()
        with self.guard.boundary(subject, protected):
            try:
                command = list(argv)
                if command[:4] != [sys.executable, "-I", "-B", "-c"]:
                    raise ValueError(
                        "RUNNER_UNSUPPORTED: only the existing action runner is admitted"
                    )
                # The existing engine addresses its mounted workspace as /workspace.
                # Host fallback translates that constant to the disposable candidate directory.
                command[4] = command[4].replace("'/workspace'", repr(str(workspace)))
                caps = self.caps
                command = [
                    "prlimit",
                    f"--as={caps['address_space_bytes']}",
                    f"--cpu={caps['action_cpu_seconds']}",
                    f"--fsize={caps['file_size_bytes']}",
                    f"--nofile={caps['open_files']}",
                    f"--nproc={caps['processes']}",
                    "--",
                    *command,
                ]
                record.update(
                    {
                        "argv": command,
                        "timeout_seconds": timeout_seconds,
                        "environment": dict(environment),
                    }
                )
                with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
                    process = subprocess.Popen(
                        command,
                        cwd=workspace,
                        env=dict(environment),
                        stdout=out,
                        stderr=err,
                        start_new_session=True,
                    )
                    try:
                        process.wait(timeout=timeout_seconds)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                        raise ContractInvalidError("candidate execution timed out") from None
                    out.seek(0)
                    err.seek(0)
                    stdout, stderr = out.read(LIMIT + 1), err.read(LIMIT + 1)
                if len(stdout) > LIMIT or len(stderr) > LIMIT:
                    raise ContractInvalidError("candidate output exceeded limit")
                completed = subprocess.CompletedProcess(
                    command,
                    process.returncode,
                    stdout.decode("utf-8", errors="replace"),
                    stderr.decode("utf-8", errors="replace"),
                )
                record.update(
                    {
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    }
                )
                return completed
            except BaseException as exc:
                record["error"] = type(exc).__name__ + ": " + str(exc)
                raise
            finally:
                record["elapsed_ms"] = (time.monotonic() - started) * 1000
                append(self.log, record)


def compatibility(packet, template, profile, repository_root, fallback):
    reasons = []
    if not fallback:
        reasons.append(
            "HOST_FALLBACK_NOT_AUTHORIZED: supply --authorized-host-fallback for this run"
        )
    if sys.version_info[:2] != (3, 12):
        reasons.append("RUNTIME_UNSUPPORTED: approved profile requires CPython 3.12")
    if not shutil.which("prlimit"):
        reasons.append("RESOURCE_LIMITER_MISSING: install prlimit before execution")
    if profile["candidate_dependencies"]:
        reasons.append(
            "DEPENDENCIES_UNSUPPORTED: this entry admits the approved standard-library profile"
        )
    model = load_contract(packet / "contract.approved.json")
    if not model.runnable:
        reasons.append("CONTRACT_NOT_APPROVED: use the PMOS approval publisher")
    contract = read_json(packet / "contract.approved.json")
    receipt = read_json(packet / "approval-receipt.json")
    _require_approved_contract(contract, receipt, contract["approved_by"])
    plan = compile_barebones_plan(
        contract=contract, repository_root=repository_root, template=template
    )
    if any(c.form not in {"given_when_then", "measure"} for c in plan.criteria):
        reasons.append("EVALUATOR_UNSUPPORTED: this entry admits only action and measure criteria")
    if canonical_digest(plan.as_dict()) != canonical_digest(
        read_json(packet / "compiled-plan.json")
    ):
        reasons.append("PLAN_CHANGED: compiled plan differs from frozen plan")
    return (
        {
            "compatible": not reasons,
            "reasons": reasons,
            "plan_digest": plan.plan_digest,
            "runtime": sys.version,
            "dependencies": profile["candidate_dependencies"],
            "profile_digest": digest(packet / "execution-profile.json"),
            "missing_isolations": profile["authorized_fallback"][
                "unavailable_additional_protections"
            ],
            "scope": "can attempt and evaluate; not a delivery guarantee",
        },
        contract,
        receipt,
        plan,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "build", "verify"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument(
        "--root", action="append", required=True, help="manifest repository=directory"
    )
    parser.add_argument("--freeze-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--authorized-host-fallback", action="store_true")
    args = parser.parse_args()
    roots = dict(item.split("=", 1) for item in args.root)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    packet = args.packet.resolve()
    guard = DigestGuard(
        packet / "freeze-manifest.json",
        roots,
        args.freeze_digest,
        args.output / "digest-checks.jsonl",
    )
    entry = {Path(__file__).resolve(): digest(__file__)}
    write_json(
        args.output / "execution-source.json",
        {
            "entry_digest": digest(__file__),
            "freeze_digest": args.freeze_digest,
            "argv": sys.argv,
            "kind": "new engineering adapter; frozen source/evaluator not modified",
        },
    )
    try:
        with guard.boundary("command", entry):
            template = load_template(packet / "bindings.json")
            profile = read_json(packet / "execution-profile.json")
            report, contract, receipt, plan = compatibility(
                packet, template, profile, args.output, args.authorized_host_fallback
            )
            write_json(args.output / "compatibility.json", report)
            if not report["compatible"]:
                raise ValueError("INCOMPATIBLE: " + "; ".join(report["reasons"]))
            if args.mode == "check":
                print(json.dumps(report))
                return 0
            execution = HostExecution(
                guard,
                template,
                profile["resource_caps"],
                plan.criteria,
                args.output / "processes.jsonl",
            )
            if args.mode == "build":
                shim = Path(__file__).with_name("session-file-provider.py")
                provider = CommandModelProvider(
                    shlex.join(
                        [
                            sys.executable,
                            str(shim),
                            "--handoff-dir",
                            str(args.output.resolve() / "handoff"),
                        ]
                    ),
                    600,
                )
                result = run_to_release_ready(
                    contract=contract,
                    repository_root=args.output,
                    workspace=args.output / "candidate",
                    run_id="task-tracker-live",
                    provider=provider,
                    template=template,
                    budget=BudgetCaps(**profile["build_budget"]),
                    candidate_sandbox=execution,
                    approval_receipt=receipt,
                    approval_authority=contract["approved_by"],
                    approval_receipt_bytes=(packet / "approval-receipt.json").read_bytes(),
                )
                write_json(args.output / "result.json", asdict(result))
                print(json.dumps(asdict(result), default=str))
                return 0 if result.cause == "PASS" else 1
            if args.candidate is None:
                raise ValueError("--candidate is required for verify")
            snapshot = _workspace_snapshot(args.candidate)
            findings = _verify_snapshot(plan, snapshot, template, execution)
            failed = {finding.subject_id for finding in findings}
            result = {
                "criteria": {
                    c.criterion_id: "FAIL" if c.criterion_id in failed else "PASS"
                    for c in plan.criteria
                },
                "findings": [asdict(f) for f in findings],
            }
            write_json(args.output / "result.json", result)
            print(json.dumps(result))
            return 1 if findings else 0
    except Exception as exc:
        write_json(args.output / "failure.json", {"error": type(exc).__name__, "detail": str(exc)})
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
