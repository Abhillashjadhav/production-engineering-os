"""Compile the frozen PMOS-TASK-TRACKER-001 contract with whichever pmpe the running venv has.

Usage: python compile_frozen.py <contract-file.py> <packet-dir> <repository-root-dir> <label>

The Template is built by the load_template() function of the given PEOS
examples/barebones/contract-file.py (imported unchanged, main() not executed), exactly as
its compatibility() step does: read_json() -> load_template(bindings.json) ->
_require_approved_contract(contract, receipt, contract["approved_by"]) ->
compile_barebones_plan(contract=..., repository_root=..., template=...), then
canonical_digest(plan.as_dict()) is compared with canonical_digest(compiled-plan.json).
Nothing in the packet is written. Prints one JSON report.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import traceback
from importlib import metadata
from pathlib import Path

EXPECTED_PLAN_DIGEST = "sha256:1dad520ebc6ac6973aeb23d80fe5c98d67e3d8a5fa20d902f56d45a180777b28"


def raw(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    entry, packet, repo_root, label = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    dist = metadata.distribution("pmpe")
    report: dict[str, object] = {
        "label": label,
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "pmpe_direct_url": json.loads(dist.read_text("direct_url.json") or "null"),
        "entry_script": str(entry),
        "entry_script_sha256": raw(entry),
        "repository_root": str(repo_root),
        "inputs": {
            name: raw(packet / name)
            for name in ("bindings.json", "contract.approved.json", "approval-receipt.json", "compiled-plan.json")
        },
    }
    spec = importlib.util.spec_from_file_location("contract_file_entry", entry)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)  # defines functions only; main() is guarded

    from pmpe.barebones import compile_barebones_plan
    from pmpe.cli.barebones_cmd import _require_approved_contract
    from pmpe.contracts.acceptance import AcceptanceCompileError
    from pmpe.contracts.canonical import canonical_digest

    template = module.load_template(packet / "bindings.json")
    report["template_version"] = template.version
    contract = module.read_json(packet / "contract.approved.json")
    receipt = module.read_json(packet / "approval-receipt.json")
    report["contract_canonical_digest"] = canonical_digest(contract)
    try:
        report["receipt_check"] = repr(_require_approved_contract(contract, receipt, contract["approved_by"]))
    except Exception as exc:  # report, do not hide
        report["receipt_check"] = f"RAISED {type(exc).__name__}: {exc}"
    frozen_plan = module.read_json(packet / "compiled-plan.json")
    report["frozen_plan_canonical_digest"] = canonical_digest(frozen_plan)
    report["frozen_plan_recorded_plan_digest"] = frozen_plan.get("plan_digest")
    try:
        plan = compile_barebones_plan(contract=contract, repository_root=repo_root, template=template)
    except AcceptanceCompileError as error:
        report["status"] = "COMPILE_REJECTED"
        report["error_type"] = type(error).__name__
        report["error_str"] = str(error)
        report["diagnostics"] = [
            {k: getattr(d, k) for k in ("code", "subject_id", "message", "path") if hasattr(d, k)}
            if not isinstance(d, dict) else d
            for d in error.diagnostics
        ]
        report["diagnostics_repr"] = [repr(d) for d in error.diagnostics]
    except Exception as error:
        report["status"] = "COMPILE_ERROR_OTHER"
        report["error_type"] = type(error).__name__
        report["error_str"] = str(error)
        report["traceback"] = traceback.format_exc()
    else:
        computed = canonical_digest(plan.as_dict())
        report["status"] = "COMPILES"
        report["criteria_count"] = len(plan.criteria)
        report["criteria_forms"] = sorted({c.form for c in plan.criteria})
        report["computed_plan_canonical_digest"] = computed
        report["canonical_digest_equal_to_frozen_plan"] = computed == report["frozen_plan_canonical_digest"]
        report["computed_plan_digest"] = plan.plan_digest
        report["plan_digest_equal_expected"] = plan.plan_digest == EXPECTED_PLAN_DIGEST
        report["expected_plan_digest"] = EXPECTED_PLAN_DIGEST
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("status") == "COMPILES" else 1


if __name__ == "__main__":
    raise SystemExit(main())
