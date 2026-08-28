#!/usr/bin/env python3
"""Execute deletion, retention, and telemetry privacy checks for CI evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.intake import FileQuarantineStore
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.orchestration.lifecycle import BudgetPolicy, LifecycleControlPlane, LifecycleState
from pmpe.privacy.retention import retention_policy_digest, terminal_retention_digest
from pmpe.telemetry.events import EventLog

_SHA = re.compile(r"^[0-9a-f]{40}$")


class _EphemeralCipher:
    key_version = "privacy-verifier-ephemeral/v1"

    def __init__(self) -> None:
        self._material = os.urandom(32)

    def _transform(self, payload: bytes) -> bytes:
        return bytes(
            value ^ self._material[index % len(self._material)]
            for index, value in enumerate(payload)
        )

    def encrypt(self, payload: bytes) -> bytes:
        return self._transform(payload)

    def decrypt(self, payload: bytes) -> bytes:
        return self._transform(payload)


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_policy(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("version") != "repository-security-profile/v2"
        or not isinstance(value.get("privacy"), dict)
    ):
        raise ValueError("privacy policy is malformed")
    privacy = dict(value["privacy"])
    expected = {
        "approved_by",
        "classification",
        "deletion_required",
        "expires_at",
        "justification",
        "residency",
        "retention_days",
        "telemetry_allowlist",
    }
    if set(privacy) != expected:
        raise ValueError("privacy policy is malformed")
    for field in ("approved_by", "justification"):
        if not isinstance(privacy[field], str) or not privacy[field].strip():
            raise ValueError("privacy policy lacks reviewed lifecycle metadata")
    expires_at = privacy["expires_at"]
    if not isinstance(expires_at, str):
        raise ValueError("privacy policy expiration is malformed")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("privacy policy expiration is malformed") from exc
    if expiry.tzinfo is None or expiry <= datetime.now(UTC):
        raise ValueError("privacy policy review has expired")
    records = privacy["telemetry_allowlist"]
    if not isinstance(records, list) or not records:
        raise ValueError("privacy telemetry allowlist is malformed")
    telemetry: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "approved_by",
            "expires_at",
            "field",
            "justification",
        }:
            raise ValueError("privacy telemetry grant is malformed")
        if any(
            not isinstance(record[field], str) or not record[field].strip()
            for field in ("approved_by", "field", "justification")
        ):
            raise ValueError("privacy telemetry grant lacks reviewed metadata")
        try:
            record_expiry = datetime.fromisoformat(str(record["expires_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("privacy telemetry grant expiration is malformed") from exc
        if record_expiry.tzinfo is None or record_expiry <= datetime.now(UTC):
            raise ValueError("privacy telemetry grant has expired")
        telemetry.append(str(record["field"]))
    if len(telemetry) != len(set(telemetry)):
        raise ValueError("privacy telemetry allowlist contains duplicate grants")
    return {
        "classification": privacy["classification"],
        "deletion_required": privacy["deletion_required"],
        "residency": privacy["residency"],
        "retention_days": privacy["retention_days"],
        "telemetry_allowlist": telemetry,
    }


def _emitter_identity(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _emitter_identity(node.value)
        if parent is not None:
            return f"{parent}.{node.attr}"
    return None


def _assignment_targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return list(node.targets) if isinstance(node, ast.Assign) else [node.target]


def _is_supported_alias_assignment(parent: ast.AST | None, node: ast.expr) -> bool:
    return bool(
        isinstance(parent, (ast.Assign, ast.AnnAssign))
        and parent.value is node
        and all(_emitter_identity(target) is not None for target in _assignment_targets(parent))
    )


_LEXICAL_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _scope_nodes(scope: ast.AST) -> tuple[ast.AST, ...]:
    """Return nodes owned by one lexical scope, excluding nested scope bodies."""

    owned: list[ast.AST] = []
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, _LEXICAL_SCOPES):
            continue
        owned.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return tuple(owned)


def _nested_scopes(scope: ast.AST) -> tuple[ast.AST, ...]:
    nested: list[ast.AST] = []
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if isinstance(node, _LEXICAL_SCOPES):
            nested.append(node)
            continue
        pending.extend(ast.iter_child_nodes(node))
    return tuple(nested)


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts), set())
    return set()


def _local_names(scope: ast.AST, nodes: tuple[ast.AST, ...]) -> set[str]:
    names: set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = scope.args
        names.update(
            argument.arg
            for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        )
        if arguments.vararg is not None:
            names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            names.add(arguments.kwarg.arg)
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in _assignment_targets(node):
                names.update(_target_names(target))
        elif isinstance(node, (ast.NamedExpr, ast.For, ast.AsyncFor)):
            names.update(_target_names(node.target))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names.update(_target_names(item.optional_vars))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
    names.update(
        nested.name
        for nested in _nested_scopes(scope)
        if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )
    global_names = {
        name
        for node in nodes
        if isinstance(node, (ast.Global, ast.Nonlocal))
        for name in node.names
    }
    return names - global_names


def _inventory_telemetry_fields(root: Path) -> tuple[str, ...]:
    fields: set[str] = set()
    source_roots = (
        root / "src" / "pmpe",
        root / "products" / "pm-evals-web" / "backend" / "src",
    )
    source_paths = sorted(
        path
        for source_root in source_roots
        if source_root.is_dir()
        for path in source_root.rglob("*.py")
    )
    for path in source_paths:
        tree = ast.parse(path.read_text(), filename=str(path))

        def analyze_scope(
            scope: ast.AST,
            inherited_aliases: set[str],
            source_path: Path = path,
        ) -> None:
            nodes = _scope_nodes(scope)
            locals_ = _local_names(scope, nodes)
            aliases = {
                alias for alias in inherited_aliases if alias.split(".", 1)[0] not in locals_
            }
            for node in nodes:
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                ):
                    continue
                attribute = node.args[1]
                owner = _emitter_identity(node.args[0])
                if (
                    isinstance(attribute, ast.Constant)
                    and attribute.value == "emit"
                    or owner is not None
                    and owner.endswith(".events")
                    and not (
                        isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)
                    )
                ):
                    raise ValueError(
                        f"telemetry emitter uses reflective access: {source_path}:{node.lineno}"
                    )
            changed = True
            while changed:
                changed = False
                for node in nodes:
                    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                        continue
                    value = node.value
                    if value is None:
                        continue
                    is_emitter = bool(
                        isinstance(value, ast.Attribute)
                        and value.attr == "emit"
                        or _emitter_identity(value) in aliases
                    )
                    if not is_emitter:
                        continue
                    for target in _assignment_targets(node):
                        identity = _emitter_identity(target)
                        if identity is None:
                            raise ValueError(
                                "telemetry emitter escapes supported name/attribute alias: "
                                f"{source_path}:{node.lineno}"
                            )
                        if identity not in aliases:
                            aliases.add(identity)
                            changed = True
            parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
            for node in nodes:
                if not isinstance(node, (ast.Name, ast.Attribute)) or not isinstance(
                    node.ctx, ast.Load
                ):
                    continue
                identity = _emitter_identity(node)
                is_emitter_reference = bool(
                    isinstance(node, ast.Attribute) and node.attr == "emit" or identity in aliases
                )
                if not is_emitter_reference:
                    continue
                parent = parents.get(node)
                called_directly = isinstance(parent, ast.Call) and parent.func is node
                if called_directly:
                    continue
                if _is_supported_alias_assignment(parent, node):
                    continue
                raise ValueError(
                    "telemetry emitter escapes supported alias binding: "
                    f"{source_path}:{node.lineno}"
                )
            for node in nodes:
                if not (
                    isinstance(node, ast.Call)
                    and (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "emit"
                        or _emitter_identity(node.func) in aliases
                    )
                ):
                    continue
                for keyword in node.keywords:
                    if keyword.arg is None:
                        raise ValueError(
                            "telemetry emission uses unresolved field expansion: "
                            f"{source_path}:{node.lineno}"
                        )
                    fields.add(keyword.arg)
            for nested in _nested_scopes(scope):
                analyze_scope(nested, aliases)

        analyze_scope(tree, set())
    if not fields:
        raise ValueError("no product telemetry emissions were observed")
    return tuple(sorted(fields))


def _verify(
    candidate_sha: str,
    policy_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("privacy verifier candidate SHA is malformed")
    privacy = _load_policy(policy_path)
    retention_days = int(privacy["retention_days"])
    telemetry_allowlist = tuple(str(item) for item in privacy["telemetry_allowlist"])
    emitted_telemetry = _inventory_telemetry_fields(repository_root.resolve())
    now = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="pmpe-privacy-verifier-") as temporary:
        root = Path(temporary)
        quarantine = FileQuarantineStore(
            root / "quarantine",
            cipher=_EphemeralCipher(),
            max_bytes=1024,
        )
        handle = "PRIVACY-VERIFICATION-OBJECT"
        payload = b"synthetic-non-production-data"
        quarantine.put(handle, payload, {"content_type": "application/octet-stream"})
        deletion_test_passed = (
            quarantine.exists(handle)
            and quarantine.read(handle) == payload
            and quarantine.delete(handle)
            and not quarantine.exists(handle)
        )

        runs_root = root / "runs"
        expired_run = runs_root / "expired-run"
        expired_run.mkdir(parents=True)
        expired = expired_run / "run-state.json"
        expired.write_text(
            json.dumps(
                {
                    "retention_days": retention_days,
                    "run_id": "privacy-expired-run",
                    "stage": "complete",
                }
            )
        )
        expired_ledger = EvidenceLedger(expired_run, run_id="privacy-expired-run")
        expired_ledger.record(
            stage="contract_lock",
            agent="privacy-verifier",
            action="lock",
            output_digests={"retention_policy": retention_policy_digest(retention_days)},
        )
        expired_ledger.record(
            stage="release_report",
            agent="privacy-verifier",
            action="report",
            output_digests={
                "terminal_retention": terminal_retention_digest(
                    retention_days,
                    stage="complete",
                )
            },
        )
        current_run = runs_root / "current-run"
        old_time = (now - timedelta(days=retention_days + 1)).timestamp()
        os.utime(expired, (old_time, old_time))
        budget = BudgetPolicy(
            version="privacy-verifier/v1",
            limits={
                "tokens": 1,
                "credits": 1,
                "elapsed_seconds": 1,
                "external_compute_seconds": 1,
                "spend_microunits": 1,
            },
            repair_attempts_per_finding=1,
            repair_attempts_per_stage=1,
            reserved_safety_units=1,
            approved_by="repository-security-owner",
        )
        lifecycle = LifecycleControlPlane.create(
            current_run,
            run_id="privacy-verification-run",
            subject_digest=canonical_digest({"candidate_sha": candidate_sha}),
            initial_state=LifecycleState.CONTRACT_RECEIVED,
            budget_policy=budget,
            retention_days=retention_days,
            trusted_clock=lambda: now,
        )
        event_log = EventLog(current_run)
        event_log.emit("privacy_verification", **dict.fromkeys(emitted_telemetry, "synthetic"))
        retention_test_passed = (
            not expired.exists()
            and lifecycle.ledger_path.exists()
            and event_log.path.exists()
            and len(event_log.read_all()) == 1
        )
        telemetry_test_passed = set(emitted_telemetry) <= set(telemetry_allowlist)

    shell = {
        "candidate_sha": candidate_sha,
        "classification": str(privacy["classification"]),
        "deletion_test_passed": deletion_test_passed,
        "emitted_telemetry": list(emitted_telemetry),
        "policy_file_digest": _file_digest(policy_path),
        "residency": privacy.get("residency"),
        "retention_days": retention_days,
        "retention_test_passed": retention_test_passed,
        "telemetry_test_passed": telemetry_test_passed,
        "verifier_file_digest": _file_digest(Path(__file__)),
    }
    if not deletion_test_passed or not retention_test_passed or not telemetry_test_passed:
        raise ValueError("privacy control verification failed")
    return {**shell, "evidence_digest": canonical_digest(shell)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = _verify(args.candidate_sha, args.policy, args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
