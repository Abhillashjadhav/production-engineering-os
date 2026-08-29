#!/usr/bin/env python3
"""Execute deletion, retention, and telemetry privacy checks for CI evidence."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
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

    def __init__(self, material: bytes | None = None) -> None:
        self._material = material or os.urandom(32)
        if len(self._material) != 32:
            raise ValueError("privacy verifier cipher material must contain 32 bytes")

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


def _event_owner_reference(node: ast.AST, known_owners: set[str] | None = None) -> bool:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) in {2, 3}
        and not node.keywords
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "events"
    ):
        return True
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    if identity is None:
        return False
    if known_owners is not None and identity in known_owners:
        return True
    parts = identity.split(".")
    return (
        len(parts) >= 2
        and parts[-1] == "events"
        and parts[-2]
        in {
            "context",
            "ctx",
            "run_context",
        }
    )


def _event_context_reference(node: ast.AST, known_owners: set[str]) -> bool:
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    return identity is not None and f"{identity}.events" in known_owners


def _object_dictionary_reference(node: ast.AST) -> bool:
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "vars"
        and len(node.args) == 1
        and not node.keywords
        or isinstance(node, ast.Attribute)
        and node.attr == "__dict__"
    )


def _contains_object_dictionary_reference(node: ast.AST) -> bool:
    return any(_object_dictionary_reference(candidate) for candidate in ast.walk(node))


def _dictionary_namespace_reference(node: ast.AST, aliases: set[str]) -> bool:
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    return _contains_object_dictionary_reference(node) or (
        identity is not None and identity in aliases
    )


def _dictionary_getter_reference(
    node: ast.AST,
    dictionary_aliases: set[str],
    getter_aliases: set[str],
) -> bool:
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    if identity is not None and identity in getter_aliases:
        return True
    if isinstance(node, ast.Attribute) and node.attr in {"get", "__getitem__"}:
        return _dictionary_namespace_reference(node.value, dictionary_aliases)
    return bool(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in {"get", "__getitem__"}
        and _dictionary_namespace_reference(node.args[0], dictionary_aliases)
    )


def _literal_string(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    return aliases.get(identity) if identity is not None else None


def _dictionary_value_reference(
    node: ast.AST,
    dictionary_aliases: set[str],
    getter_aliases: set[str],
    value_aliases: set[str],
) -> bool:
    identity = _emitter_identity(node) if isinstance(node, ast.expr) else None
    if identity is not None and identity in value_aliases:
        return True
    if isinstance(node, ast.Call):
        return _dictionary_getter_reference(
            node.func,
            dictionary_aliases,
            getter_aliases,
        )
    return bool(
        isinstance(node, ast.Subscript)
        and _dictionary_namespace_reference(node.value, dictionary_aliases)
    )


def _reflective_emitter_dictionary_access(
    node: ast.AST,
    known_owners: set[str],
    dictionary_aliases: set[str],
    getter_aliases: set[str],
    value_aliases: set[str],
    string_aliases: dict[str, str],
) -> bool:
    """Reject namespace reflection that can recover an emitter outside the alias model."""

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and _literal_string(node.args[1], string_aliases) in {None, "emit"}
        and _dictionary_value_reference(
            node.args[0],
            dictionary_aliases,
            getter_aliases,
            value_aliases,
        )
    ):
        return True
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "emit"
        and _dictionary_value_reference(
            node.value,
            dictionary_aliases,
            getter_aliases,
            value_aliases,
        )
    ):
        return True
    if isinstance(node, ast.Call) and _dictionary_value_reference(
        node.func,
        dictionary_aliases,
        getter_aliases,
        value_aliases,
    ):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "vars"
        and len(node.args) == 1
        and not node.keywords
        and (
            _event_owner_reference(node.args[0], known_owners)
            or _event_context_reference(node.args[0], known_owners)
        )
    ):
        return True
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "__dict__"
        and (
            _event_owner_reference(node.value, known_owners)
            or _event_context_reference(node.value, known_owners)
        )
    ):
        return True
    if (
        isinstance(node, ast.Call)
        and node.args
        and _literal_string(node.args[0], string_aliases) in {"emit", "events"}
        and _dictionary_getter_reference(
            node.func,
            dictionary_aliases,
            getter_aliases,
        )
    ):
        return True
    if not isinstance(node, ast.Subscript):
        return False
    if _literal_string(node.slice, string_aliases) not in {"emit", "events"}:
        return False
    return _dictionary_namespace_reference(node.value, dictionary_aliases)


def _event_owner_escapes(
    node: ast.AST,
    parent: ast.AST | None,
    known_owners: set[str],
) -> bool:
    """Allow an event namespace only as the owner of the governed ``emit`` method."""

    return _event_owner_reference(node, known_owners) and not (
        isinstance(parent, ast.Attribute) and parent.value is node and parent.attr == "emit"
    )


_LEXICAL_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _definition_expressions(scope: ast.AST) -> tuple[ast.AST, ...]:
    if isinstance(scope, ast.Lambda):
        return (
            *scope.args.defaults,
            *(item for item in scope.args.kw_defaults if item is not None),
        )
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        annotations = tuple(
            argument.annotation
            for argument in (
                *scope.args.posonlyargs,
                *scope.args.args,
                *scope.args.kwonlyargs,
            )
            if argument.annotation is not None
        )
        optional_annotations = tuple(
            argument.annotation
            for argument in (scope.args.vararg, scope.args.kwarg)
            if argument is not None and argument.annotation is not None
        )
        returns = (scope.returns,) if scope.returns is not None else ()
        return (
            *scope.decorator_list,
            *scope.args.defaults,
            *(item for item in scope.args.kw_defaults if item is not None),
            *annotations,
            *optional_annotations,
            *returns,
            *tuple(getattr(scope, "type_params", ())),
        )
    if isinstance(scope, ast.ClassDef):
        return (
            *scope.decorator_list,
            *scope.bases,
            *(keyword.value for keyword in scope.keywords),
            *tuple(getattr(scope, "type_params", ())),
        )
    return ()


def _scope_nodes(scope: ast.AST) -> tuple[ast.AST, ...]:
    """Return nodes owned by one lexical scope, excluding nested scope bodies."""

    owned: list[ast.AST] = []
    own_definition_nodes = {
        expression_node
        for expression in _definition_expressions(scope)
        for expression_node in ast.walk(expression)
    }
    pending = list(ast.iter_child_nodes(scope))
    while pending:
        node = pending.pop()
        if node in own_definition_nodes:
            continue
        if isinstance(node, _LEXICAL_SCOPES):
            for expression in _definition_expressions(node):
                owned.extend(ast.walk(expression))
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
            parents = {child: parent for parent in nodes for child in ast.iter_child_nodes(parent)}
            event_owners = {
                identity
                for node in nodes
                if isinstance(node, ast.Attribute) and node.attr == "emit"
                if (identity := _emitter_identity(node.value)) is not None
            }
            string_assignments: dict[str, list[ast.expr]] = {}
            for node in nodes:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                for target in _assignment_targets(node):
                    identity = _emitter_identity(target)
                    if identity is not None:
                        string_assignments.setdefault(identity, []).append(node.value)
            string_aliases: dict[str, str] = {}
            changed = True
            while changed:
                changed = False
                for identity, values in string_assignments.items():
                    resolved = [_literal_string(value, string_aliases) for value in values]
                    if any(value is None for value in resolved) or len(set(resolved)) != 1:
                        continue
                    resolved_value = resolved[0]
                    if (
                        resolved_value is not None
                        and string_aliases.get(identity) != resolved_value
                    ):
                        string_aliases[identity] = resolved_value
                        changed = True
            dictionary_aliases: set[str] = set()
            getter_aliases: set[str] = set()
            value_aliases: set[str] = set()
            changed = True
            while changed:
                changed = False
                for node in nodes:
                    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                        continue
                    value = node.value
                    if value is None:
                        continue
                    is_dictionary = _dictionary_namespace_reference(
                        value,
                        dictionary_aliases,
                    )
                    is_getter = _dictionary_getter_reference(
                        value,
                        dictionary_aliases,
                        getter_aliases,
                    )
                    is_value = _dictionary_value_reference(
                        value,
                        dictionary_aliases,
                        getter_aliases,
                        value_aliases,
                    )
                    if not (is_dictionary or is_getter or is_value):
                        continue
                    destination = (
                        value_aliases
                        if is_value
                        else getter_aliases
                        if is_getter
                        else dictionary_aliases
                    )
                    for target in _assignment_targets(node):
                        identity = _emitter_identity(target)
                        if identity is not None and identity not in destination:
                            destination.add(identity)
                            changed = True
            for node in nodes:
                if _reflective_emitter_dictionary_access(
                    node,
                    event_owners,
                    dictionary_aliases,
                    getter_aliases,
                    value_aliases,
                    string_aliases,
                ) or _event_owner_escapes(
                    node,
                    parents.get(node),
                    event_owners,
                ):
                    raise ValueError(
                        "telemetry emitter uses reflective access: "
                        f"{source_path}:{getattr(node, 'lineno', 0)}"
                    )
            for node in nodes:
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) >= 2
                ):
                    continue
                attribute = node.args[1]
                if _event_owner_reference(node.args[0], event_owners) and (
                    isinstance(attribute, ast.Constant)
                    and attribute.value == "emit"
                    or not (
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
                    if isinstance(scope, ast.ClassDef):
                        raise ValueError(
                            "telemetry emitter escapes into a class namespace: "
                            f"{source_path}:{node.lineno}"
                        )
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


_CHALLENGE_FIELDS = {
    "candidate_sha",
    "challenge_digest",
    "classification",
    "emitted_telemetry",
    "handle",
    "nonce",
    "observed_at",
    "payload_b64",
    "payload_digest",
    "policy_file_digest",
    "residency",
    "retention_days",
    "schema_version",
    "subject_digest",
    "telemetry_allowlist",
    "verifier_file_digest",
}
_RECEIPT_FIELDS = {
    "candidate_sha",
    "challenge_digest",
    "quarantine_delete_returned",
    "quarantine_existed_before_delete",
    "quarantine_exists_after_delete",
    "quarantine_read_digest",
    "receipt_digest",
    "schema_version",
}


def _exact_digest(value: dict[str, Any], digest_field: str) -> bool:
    claimed = value.get(digest_field)
    shell = dict(value)
    shell.pop(digest_field, None)
    return isinstance(claimed, str) and claimed == canonical_digest(shell)


def _read_exact_json(path: Path, *, fields: set[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} is malformed")
    return value


def _decode_exact_json(payload: str, *, fields: set[str], label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is unavailable") from exc
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label} is malformed")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if payload != canonical:
        raise ValueError(f"{label} is not canonical")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if path == Path("-"):
        sys.stdout.write(payload)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)


def _seed_expired_run(probe_root: Path, *, retention_days: int, now: datetime) -> None:
    expired_run = probe_root / "runs" / "expired-run"
    expired_run.mkdir(parents=True)
    (expired_run / "run-state.json").write_text(
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
    events = expired_ledger.read_all()
    terminal = events[-1]
    terminal["ts"] = (now - timedelta(days=retention_days + 1)).isoformat()
    identity = {key: value for key, value in terminal.items() if key not in {"event_id", "ts"}}
    terminal["event_id"] = canonical_digest(
        identity if terminal["idempotency_key"] else {**identity, "ts": terminal["ts"]}
    )
    expired_ledger.path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    )


def _prepare_probe(
    candidate_sha: str,
    policy_path: Path,
    repository_root: Path,
    probe_root: Path,
) -> dict[str, Any]:
    if not _SHA.fullmatch(candidate_sha):
        raise ValueError("privacy verifier candidate SHA is malformed")
    if probe_root.is_symlink() or probe_root.exists():
        raise ValueError("privacy probe root must be a new directory")
    privacy = _load_policy(policy_path)
    emitted_telemetry = _inventory_telemetry_fields(repository_root.resolve())
    telemetry_allowlist = tuple(str(item) for item in privacy["telemetry_allowlist"])
    if not set(emitted_telemetry) <= set(telemetry_allowlist):
        raise ValueError("candidate telemetry exceeds the reviewed allowlist")
    probe_root.mkdir(parents=True, mode=0o700)
    now = datetime.now(UTC)
    retention_days = int(privacy["retention_days"])
    _seed_expired_run(probe_root, retention_days=retention_days, now=now)
    nonce = secrets.token_hex(32)
    payload = hashlib.sha256(f"{candidate_sha}:{nonce}".encode()).digest()
    shell: dict[str, Any] = {
        "candidate_sha": candidate_sha,
        "classification": str(privacy["classification"]),
        "emitted_telemetry": list(emitted_telemetry),
        "handle": f"PRIVACY-{nonce[:16].upper()}",
        "nonce": nonce,
        "observed_at": now.isoformat(),
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "payload_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "policy_file_digest": _file_digest(policy_path),
        "residency": privacy.get("residency"),
        "retention_days": retention_days,
        "schema_version": "candidate-privacy-challenge/v1",
        "subject_digest": canonical_digest({"candidate_sha": candidate_sha}),
        "telemetry_allowlist": list(telemetry_allowlist),
        "verifier_file_digest": _file_digest(Path(__file__)),
    }
    return {**shell, "challenge_digest": canonical_digest(shell)}


def _load_challenge(path: Path) -> dict[str, Any]:
    value = _read_exact_json(path, fields=_CHALLENGE_FIELDS, label="privacy challenge")
    if value.get("schema_version") != "candidate-privacy-challenge/v1" or not _exact_digest(
        value, "challenge_digest"
    ):
        raise ValueError("privacy challenge authentication failed")
    return value


def _probe_candidate_runtime(
    candidate_sha: str,
    challenge_path: Path,
    probe_root: Path,
) -> dict[str, Any]:
    challenge = _load_challenge(challenge_path)
    if challenge.get("candidate_sha") != candidate_sha:
        raise ValueError("privacy challenge candidate does not match")
    payload = base64.b64decode(str(challenge["payload_b64"]), validate=True)
    material = bytes.fromhex(str(challenge["nonce"]))
    quarantine = FileQuarantineStore(
        probe_root / "quarantine",
        cipher=_EphemeralCipher(material),
        max_bytes=1024,
    )
    handle = str(challenge["handle"])
    quarantine.put(handle, payload, {"content_type": "application/octet-stream"})
    existed_before_delete = quarantine.exists(handle)
    read_payload = quarantine.read(handle)
    delete_returned = quarantine.delete(handle)

    now = datetime.fromisoformat(str(challenge["observed_at"]))
    retention_days = int(challenge["retention_days"])
    current_run = probe_root / "runs" / "current-run"
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
    LifecycleControlPlane.create(
        current_run,
        run_id="privacy-verification-run",
        subject_digest=str(challenge["subject_digest"]),
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=budget,
        retention_days=retention_days,
        trusted_clock=lambda: now,
    )
    event_log = EventLog(current_run)
    event_log.emit(
        "privacy_verification",
        **dict.fromkeys((str(item) for item in challenge["emitted_telemetry"]), "synthetic"),
    )
    shell: dict[str, Any] = {
        "candidate_sha": candidate_sha,
        "challenge_digest": challenge["challenge_digest"],
        "quarantine_delete_returned": delete_returned,
        "quarantine_existed_before_delete": existed_before_delete,
        "quarantine_exists_after_delete": quarantine.exists(handle),
        "quarantine_read_digest": "sha256:" + hashlib.sha256(read_payload).hexdigest(),
        "schema_version": "candidate-privacy-receipt/v1",
    }
    return {**shell, "receipt_digest": canonical_digest(shell)}


def _finalize_probe(
    candidate_sha: str,
    policy_path: Path,
    repository_root: Path,
    challenge_path: Path,
    probe_root: Path,
    receipt_source: Path | dict[str, Any],
) -> dict[str, Any]:
    challenge = _load_challenge(challenge_path)
    receipt = (
        _read_exact_json(
            receipt_source,
            fields=_RECEIPT_FIELDS,
            label="candidate privacy receipt",
        )
        if isinstance(receipt_source, Path)
        else receipt_source
    )
    if set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("candidate privacy receipt is malformed")
    privacy = _load_policy(policy_path)
    emitted_telemetry = _inventory_telemetry_fields(repository_root.resolve())
    expected_challenge = bool(
        challenge.get("candidate_sha") == candidate_sha
        and challenge.get("policy_file_digest") == _file_digest(policy_path)
        and challenge.get("verifier_file_digest") == _file_digest(Path(__file__))
        and challenge.get("classification") == privacy["classification"]
        and challenge.get("residency") == privacy.get("residency")
        and challenge.get("retention_days") == privacy["retention_days"]
        and challenge.get("emitted_telemetry") == list(emitted_telemetry)
        and challenge.get("telemetry_allowlist") == privacy["telemetry_allowlist"]
    )
    receipt_valid = bool(
        receipt.get("schema_version") == "candidate-privacy-receipt/v1"
        and _exact_digest(receipt, "receipt_digest")
        and receipt.get("candidate_sha") == candidate_sha
        and receipt.get("challenge_digest") == challenge.get("challenge_digest")
        and receipt.get("quarantine_existed_before_delete") is True
        and receipt.get("quarantine_delete_returned") is True
        and receipt.get("quarantine_exists_after_delete") is False
        and receipt.get("quarantine_read_digest") == challenge.get("payload_digest")
    )
    quarantine_root = probe_root / "quarantine"
    deletion_test_passed = bool(
        receipt_valid
        and quarantine_root.is_dir()
        and not quarantine_root.is_symlink()
        and not any(quarantine_root.iterdir())
    )
    current_run = probe_root / "runs" / "current-run"
    try:
        lifecycle = LifecycleControlPlane.load(current_run)
        events = EventLog(current_run).read_all()
    except (OSError, TypeError, ValueError):
        lifecycle = None
        events = []
    expected_event = {
        "type": "privacy_verification",
        **dict.fromkeys(emitted_telemetry, "synthetic"),
    }
    event_body = {key: value for key, value in events[0].items() if key != "ts"} if events else {}
    retention_test_passed = bool(
        expected_challenge
        and lifecycle is not None
        and lifecycle.run_id == "privacy-verification-run"
        and lifecycle.subject_digest == challenge.get("subject_digest")
        and lifecycle.state is LifecycleState.CONTRACT_RECEIVED
        and not (probe_root / "runs" / "expired-run").exists()
        and len(events) == 1
        and event_body == expected_event
    )
    telemetry_test_passed = bool(
        expected_challenge
        and set(emitted_telemetry) <= {str(item) for item in privacy["telemetry_allowlist"]}
    )
    shell = {
        "candidate_sha": candidate_sha,
        "classification": str(privacy["classification"]),
        "deletion_test_passed": deletion_test_passed,
        "emitted_telemetry": list(emitted_telemetry),
        "policy_file_digest": _file_digest(policy_path),
        "residency": privacy.get("residency"),
        "retention_days": int(privacy["retention_days"]),
        "retention_test_passed": retention_test_passed,
        "telemetry_test_passed": telemetry_test_passed,
        "verifier_file_digest": _file_digest(Path(__file__)),
    }
    if not deletion_test_passed or not retention_test_passed or not telemetry_test_passed:
        raise ValueError("candidate privacy control verification failed")
    return {**shell, "evidence_digest": canonical_digest(shell)}


def _probe_state_digest(probe_root: Path) -> str:
    records: list[dict[str, Any]] = []
    for path in sorted(probe_root.rglob("*")):
        relative = path.relative_to(probe_root).as_posix()
        if path.is_symlink():
            raise ValueError("candidate privacy probe contains a symlink")
        if path.is_dir():
            records.append({"path": relative, "type": "directory"})
        elif path.is_file():
            records.append(
                {
                    "digest": _file_digest(path),
                    "path": relative,
                    "size": path.stat().st_size,
                    "type": "file",
                }
            )
        else:
            raise ValueError("candidate privacy probe contains a special file")
    return canonical_digest(records)


def _supervise_candidate_runtime(
    candidate_sha: str,
    policy_path: Path,
    repository_root: Path,
    probe_root: Path,
) -> dict[str, Any]:
    """Keep candidate imports below a trusted parent that alone emits evidence."""

    challenge = _prepare_probe(candidate_sha, policy_path, repository_root, probe_root)
    challenge_path = probe_root.parent / "privacy-challenge.json"
    _write_json(challenge_path, challenge)
    verifier_path = Path(__file__).resolve()
    candidate_source = repository_root.resolve() / "src"
    site_packages = [
        path for path in sys.path if path.endswith("site-packages") and Path(path).is_dir()
    ]
    if not candidate_source.is_dir() or not site_packages:
        raise ValueError("candidate privacy runtime paths are unavailable")
    child_paths = [str(candidate_source), *site_packages]
    launcher = (
        "import json,os,pathlib,runpy,sys;"
        "_dumps=json.dumps;_exit=os._exit;_write=os.write;_Path=pathlib.Path;"
        f"sys.path[:0]={child_paths!r};"
        f"_scope=runpy.run_path({str(verifier_path)!r},run_name='_candidate_privacy_probe');"
        "_probe=_scope['_probe_candidate_runtime'];"
        f"_receipt=_probe({candidate_sha!r},_Path({str(challenge_path)!r}),"
        f"_Path({str(probe_root)!r}));"
        "_payload=(_dumps(_receipt,sort_keys=True,separators=(',',':'))+'\\n').encode();"
        "_write(1,_payload);_exit(0)"
    )
    command = [
        sys.executable,
        "-I",
        "-S",
        "-c",
        launcher,
    ]
    try:
        completed = subprocess.run(  # nosec B603 - protected exact interpreter and script
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            cwd=probe_root.parent,
            env={
                "HOME": "/tmp/candidate-home",
                "LANG": "C.UTF-8",
                "PATH": "/runtime/venv/bin:/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONSAFEPATH": "1",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("candidate privacy subprocess failed") from exc
    if completed.returncode != 0 or not completed.stdout or completed.stderr:
        raise ValueError("candidate privacy subprocess did not complete exactly")
    receipt = _decode_exact_json(
        completed.stdout,
        fields=_RECEIPT_FIELDS,
        label="candidate privacy receipt",
    )
    finalized = _finalize_probe(
        candidate_sha,
        policy_path,
        repository_root,
        challenge_path,
        probe_root,
        receipt,
    )
    finalized_digest = finalized.pop("evidence_digest", None)
    if finalized_digest != canonical_digest(finalized):
        raise ValueError("candidate privacy finalization digest is invalid")
    nonce = secrets.token_bytes(32)
    shell: dict[str, Any] = {
        **finalized,
        "candidate_process_returncode": completed.returncode,
        "candidate_receipt_digest": receipt["receipt_digest"],
        "probe_state_digest": _probe_state_digest(probe_root),
        "schema_version": "candidate-privacy-supervisor-evidence/v1",
        "supervisor_nonce_digest": "sha256:" + hashlib.sha256(nonce).hexdigest(),
    }
    return {**shell, "evidence_digest": canonical_digest(shell)}


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
        expired_events = expired_ledger.read_all()
        expired_terminal = expired_events[-1]
        expired_terminal["ts"] = (now - timedelta(days=retention_days + 1)).isoformat()
        expired_identity = {
            key: value for key, value in expired_terminal.items() if key not in {"event_id", "ts"}
        }
        expired_terminal["event_id"] = canonical_digest(
            expired_identity
            if expired_terminal["idempotency_key"]
            else {**expired_identity, "ts": expired_terminal["ts"]}
        )
        expired_ledger.path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in expired_events)
        )
        current_run = runs_root / "current-run"
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
    parser.add_argument(
        "--mode",
        choices=("direct", "prepare", "probe", "finalize", "supervise"),
        default="direct",
    )
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--challenge", type=Path)
    parser.add_argument("--probe-root", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "direct":
        evidence = _verify(args.candidate_sha, args.policy, args.root)
    elif args.mode == "prepare":
        if args.probe_root is None:
            parser.error("prepare mode requires --probe-root")
        evidence = _prepare_probe(
            args.candidate_sha,
            args.policy,
            args.root,
            args.probe_root,
        )
    elif args.mode == "probe":
        if args.challenge is None or args.probe_root is None:
            parser.error("probe mode requires --challenge and --probe-root")
        evidence = _probe_candidate_runtime(
            args.candidate_sha,
            args.challenge,
            args.probe_root,
        )
    elif args.mode == "finalize":
        if args.challenge is None or args.probe_root is None or args.receipt is None:
            parser.error("finalize mode requires --challenge, --probe-root, and --receipt")
        evidence = _finalize_probe(
            args.candidate_sha,
            args.policy,
            args.root,
            args.challenge,
            args.probe_root,
            args.receipt,
        )
    else:
        if args.probe_root is None:
            parser.error("supervise mode requires --probe-root")
        evidence = _supervise_candidate_runtime(
            args.candidate_sha,
            args.policy,
            args.root,
            args.probe_root,
        )
    _write_json(args.output, evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
