"""Read-only Phase 1 diagnostics, not a model build or an approval operation.

Run from the repository with its installed virtualenv. Existing repository files
are never written: authority checks open with O_WRONLY, without O_TRUNC, then close.
Synthetic candidate files live only in a disposable temporary directory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pmpe.barebones import (
    BubblewrapCandidateSandbox,
    ContractInvalidError,
    Template,
    _criterion_findings,
    compile_barebones_plan,
    default_template,
)
from pmpe.cli.barebones_cmd import CommandModelProvider
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.authoring import verify_contract_approval
from pmpe.contracts.canonical import canonical_digest
from pmpe.domain.errors import ContractViolation

ROOT = Path(__file__).resolve().parents[3]


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def authority_observations() -> dict:
    observations = []
    for relative in (
        "src/pmpe/barebones.py",
        "src/pmpe/contracts/acceptance.py",
        "src/pmpe/contracts/authoring.py",
        "tests/unit/test_acceptance_compiler.py",
    ):
        path = ROOT / relative
        before = digest(path)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        except OSError as error:
            writable, error_text = False, str(error)
        else:
            os.close(fd)
            writable, error_text = True, None
        observations.append({
            "path": relative,
            "opened_for_write": writable,
            "error": error_text,
            "before_digest": before,
            "after_digest": digest(path),
        })
    return {"effective_uid": os.geteuid(), "files": observations, "bytes_written": 0}


def main() -> None:
    if sys.argv[1:] == ["--authority-child"]:
        request = json.load(sys.stdin)["request"]
        print(json.dumps({
            "request_digest": request["request_digest"],
            "diagnostic_only_not_model": True,
            "authority": authority_observations(),
        }))
        return

    started = time.monotonic()
    result = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "python": sys.version,
        "executable": sys.executable,
        "dependencies": {name: version(name) for name in ("pmpe", "jsonschema", "PyYAML", "rfc8785")},
        "diagnostic_only_not_feature_evidence": True,
    }
    contract = json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    new_action = copy.deepcopy(contract)
    new_action["acceptance_criteria"]["AC-001"]["when"]["action"] = "audit.new_action"
    try:
        compile_barebones_plan(contract=new_action, repository_root=ROOT)
    except AcceptanceCompileError as error:
        result["default_new_action"] = [asdict(item) for item in error.diagnostics]
    else:
        result["default_new_action"] = "unexpectedly admitted"
    supplied = Template(
        version="audit-bindings-1",
        files={"product.py": "def observe():\n    return {'sample_size': 1, 'value': 0}\n"},
        actions={"audit.new_action": "product:observe"},
        measures={"audit.missing_records": "product:observe"},
        context={"service": {"running": True}},
    )
    custom_plan = compile_barebones_plan(contract=new_action, repository_root=ROOT, template=supplied)
    result["custom_new_action"] = {
        "compiled": True, "action": custom_plan.criteria[0].when.action,
        "engine_source_changed": False,
    }
    measurement = copy.deepcopy(contract)
    measurement["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"], "measure": "audit.missing_records",
        "operator": "eq", "value": 0, "sample": {"minimum": 1},
    }
    measure_plan = compile_barebones_plan(contract=measurement, repository_root=ROOT, template=supplied)
    result["measure_compilation"] = {
        "compiled": True, "form": measure_plan.criteria[0].form,
        "default_registered_measures": dict(default_template().measures),
    }
    subprocess_commands = []

    def audit_hook(event: str, args: tuple) -> None:
        if event == "subprocess.Popen" and Path(str(args[0])).name in {"prlimit", "bwrap"}:
            subprocess_commands.append(args[1])

    sys.addaudithook(audit_hook)
    with tempfile.TemporaryDirectory(prefix="pmpe-phase1-audit-") as temporary:
        workspace = Path(temporary)
        (workspace / "product.py").write_text(supplied.files["product.py"])
        sandbox = BubblewrapCandidateSandbox()
        try:
            findings = _criterion_findings(
                measure_plan.criteria[0], workspace=workspace, template=supplied, sandbox=sandbox
            )
        except ContractInvalidError as error:
            result["measure_evaluation"] = {"status": "BLOCKED", "error": str(error)}
        else:
            result["measure_evaluation"] = {
                "status": "PASS" if not findings else "FAIL",
                "findings": [asdict(item) for item in findings],
                "fixture_observation": {"sample_size": 1, "value": 0},
                "not_independent_product_measurement": True,
            }
        observation_code = """
import json, os, resource
from pathlib import Path
try:
    fd = os.open('/workspace/product.py', os.O_WRONLY)
except OSError as error:
    write_open = str(error)
else:
    os.close(fd)
    write_open = 'WRITABLE'
print(json.dumps({
    'limits': {name: resource.getrlimit(getattr(resource,name)) for name in
       ('RLIMIT_AS','RLIMIT_CPU','RLIMIT_FSIZE','RLIMIT_NOFILE','RLIMIT_NPROC')},
    'workspace_write_open': write_open,
    'mountinfo': Path('/proc/self/mountinfo').read_text(),
    'environment': dict(os.environ),
}))
"""
        try:
            completed = sandbox.run(
                workspace, [sys.executable, "-I", "-B", "-c", observation_code],
                timeout_seconds=5, environment={"PATH": "/usr/bin:/bin"},
            )
        except ContractInvalidError as error:
            result["sandbox"] = {"status": "BLOCKED", "error": str(error)}
            raw = subprocess.run(
                ["/usr/bin/bwrap", "--unshare-all", "--ro-bind", "/", "/", "--", "/bin/true"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            result["sandbox"]["minimal_diagnostic"] = {
                "argv": raw.args, "exit_code": raw.returncode,
                "stdout": raw.stdout, "stderr": raw.stderr,
            }
        else:
            result["sandbox"] = {
                "status": "PASS" if completed.returncode == 0 else "FAIL",
                "exit_code": completed.returncode, "stderr": completed.stderr,
                "observations": json.loads(completed.stdout) if completed.returncode == 0 else completed.stdout,
            }
    result["sandbox_commands"] = subprocess_commands

    original_receipt = json.loads((ROOT / "examples/barebones/e1-approval-receipt.json").read_text())
    forged_contract = copy.deepcopy(contract)
    forged_contract["acceptance_criteria"]["AC-001"]["then"][0]["value"] = "unreviewed-audit-change"
    try:
        verify_contract_approval(forged_contract, original_receipt, expected_approver="fixture-human")
    except ContractViolation as error:
        unchanged_receipt_rejected = str(error)
    else:
        unchanged_receipt_rejected = None
    reconstructed = copy.deepcopy(forged_contract)
    reconstructed.update(contract_status="DRAFT", approved_by="", approved_at="")
    forged_receipt = dict(original_receipt)
    forged_receipt.pop("receipt_digest")
    forged_receipt["draft_digest"] = canonical_digest(reconstructed)
    forged_receipt["approved_contract_digest"] = canonical_digest(forged_contract)
    forged_receipt["receipt_digest"] = canonical_digest(forged_receipt)
    verified_digest = verify_contract_approval(
        forged_contract, forged_receipt, expected_approver="fixture-human"
    )
    result["approval"] = {
        "synthetic_fixture_only": True, "original_receipt_rejected_change": unchanged_receipt_rejected,
        "forged_receipt_accepted": verified_digest == forged_receipt["receipt_digest"],
        "forged_receipt": forged_receipt, "forged_contract": forged_contract,
        "human_approval_obtained": False, "signing_secret_used": False,
    }
    # This is deliberately last: positive write access triggers the owner's halt.
    request = {"purpose": "read-only privilege diagnostic"}
    request["request_digest"] = canonical_digest(request)
    provider = CommandModelProvider(
        shlex.join([sys.executable, str(Path(__file__).resolve()), "--authority-child"]),
        timeout_seconds=10,
    )
    result["provider_authority"] = dict(provider.invoke(purpose="code", request=request))
    result["in_session_builder_authority"] = authority_observations()
    result["halt"] = {
        "triggered": any(item["opened_for_write"] for item in result["in_session_builder_authority"]["files"]),
        "condition": "acceptance checks reachable by builder",
        "implementation_continued": False,
    }
    result["elapsed_ms"] = (time.monotonic() - started) * 1000
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
