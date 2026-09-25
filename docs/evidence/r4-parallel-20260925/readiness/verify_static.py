"""Verify readiness claims using committed text only; never import product code."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def committed(repo: Path, revision: str, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", revision + ":" + path])


def function(source: bytes, name: str) -> ast.FunctionDef:
    found = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(found) == 1, "function missing or ambiguous: " + name)
    return found[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process", type=Path, required=True)
    parser.add_argument("--pmos", type=Path, required=True)
    parser.add_argument("--historical", type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    report_path = here / "assessment.json"
    if not report_path.is_file():
        print(json.dumps({"status": "FAIL", "reason": "assessment.json is missing"}))
        return 1
    try:
        report = json.loads(report_path.read_text())
        require(report["status"] == "BLOCKED", "readiness must stay BLOCKED")
        peos = report["sources"]["peos"]
        pmos = report["sources"]["pmos"]
        historical = report["sources"]["historical"]
        require(args.historical is not None, "historical source path is required for this assessment")
        require(peos["commit"] == "c67716638731ba3be4ceeab20be6e6fdee631fd3", "wrong PEOS revision")
        require(pmos["commit"] == "639875203503ae5c9f15e2ff0f7f8317c788e5a1", "wrong PMOS revision")
        text_sources: dict[str, bytes] = {}
        for label, repo, identity in (("peos", args.process, peos), ("pmos", args.pmos, pmos), ("historical", args.historical, historical)):
            tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", identity["commit"] + "^{tree}"], text=True).strip()
            require(tree == identity["tree"], "wrong tree identity: " + label)
            for path, expected in identity["files"].items():
                payload = committed(repo, identity["commit"], path)
                require(hashlib.sha256(payload).hexdigest() == expected, "source digest mismatch: " + path)
                text_sources[label + ":" + path] = payload

        evaluator = function(text_sources["peos:src/pmpe/process_evaluators.py"], "generation_provenance_result")
        statuses = [node for node in ast.walk(evaluator) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "status" for target in node.targets)]
        require(len(statuses) == 1 and isinstance(statuses[0].value, ast.IfExp), "generation status assignment changed")
        value = statuses[0].value
        require(isinstance(value.test, ast.Name) and value.test.id == "reasons", "unexpected generation status condition")
        require(isinstance(value.body, ast.Constant) and value.body.value == "FAIL", "unexpected failure status")
        require(isinstance(value.orelse, ast.Constant) and value.orelse.value == "NOT_EVALUATED", "fresh PASS path requires reassessment")
        returns = [node for node in ast.walk(evaluator) if isinstance(node, ast.Return)]
        require(len(returns) == 1 and isinstance(returns[0].value, ast.Tuple), "generation return changed")
        result = returns[0].value.elts
        require(len(result) == 2 and isinstance(result[0], ast.Name) and result[0].id == "status", "generation returns unexpected status")
        require(isinstance(result[1], ast.Dict), "generation evidence changed")
        freshness = [v for k, v in zip(result[1].keys, result[1].values) if isinstance(k, ast.Constant) and k.value == "freshness_verified"]
        require(len(freshness) == 1 and isinstance(freshness[0], ast.Constant) and freshness[0].value is False, "freshness verification changed")
        require(report["gate004"]["reachable_statuses"] == ["FAIL", "NOT_EVALUATED"], "incorrect runtime status claim")
        require(report["gate004"]["freshness_verified"] is False and report["gate004"]["pass_reachable"] is False, "incorrect freshness claim")

        reader = function(text_sources["peos:src/pmpe/evidence/process_gate_validation.py"], "validate_process_gate_evidence")
        branches = [node for node in ast.walk(reader) if isinstance(node, ast.If) and ast.dump(node.test) == ast.dump(ast.parse('kind == "generation_provenance"', mode="eval").body)]
        require(len(branches) == 1 and len(branches[0].body) == 1 and isinstance(branches[0].body[0], ast.Raise), "retained freshness validation changed")
        require("FRESH_GENERATION_NOT_MECHANICALLY_VERIFIED" in ast.unparse(branches[0].body[0]), "retained rejection reason changed")
        require(report["gate004"]["retained_pass_accepted"] is False, "incorrect retained PASS claim")

        cli = function(text_sources["peos:src/pmpe/cli/barebones_cmd.py"], "_run")
        calls = [node for node in ast.walk(cli) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "run_to_release_ready"]
        require(len(calls) == 1 and all(item.arg != "process_gate_inputs" for item in calls[0].keywords), "CLI process input support changed")
        require(report["entrypoints"]["default_cli_supplies_process_inputs"] is False, "incorrect CLI claim")

        old = here.parents[1] / "r4-repair-20260924"
        replay = json.loads((old / "resume-replay-summary.json").read_text())
        migration = json.loads((old / "resume-migration.json").read_text())
        draft = json.loads((old / "resume-contract.draft.json").read_text())
        require(report["observed_replay"]["state"] == replay["state"] == "HALTED", "replay state mismatch")
        require(report["observed_replay"]["gates"] == replay["gates"], "replay gate mismatch")
        require(report["observed_replay"]["fresh_model_calls"] == replay["fresh_model_calls"] == 0, "replay freshness mismatch")
        require(report["observed_replay"]["approval"] == replay["approval"], "replay approval mismatch")
        require(report["observed_replay"]["process_records"] == replay["process_records"] == 56, "record count mismatch")
        require(report["observed_replay"]["digest_boundaries"] == replay["digest_boundaries"] == 117, "boundary count mismatch")
        require(draft["contract_status"] == "DRAFT" and migration["approval_receipt_created"] is False, "approval status changed")
        require(report["owner_decision"]["status"] == "UNAPPROVED", "decision must remain unapproved")
        require(report["screening_stopped_checks"] == {"active_external_cache": "UNVERIFIED", "retained_context_binding": "UNVERIFIED"}, "blocked checks misrepresented")
        require((here / "READINESS.md").is_file(), "human-readable readiness report is missing")
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}))
        return 1
    print(json.dumps({"status": "PASS", "scope": "static source and saved-report consistency only", "product_code_imported": False, "fresh_model_calls": 0, "adversarial_execution": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
