"""Versioned contract registry + run-scoped immutability lock.

PD-03 rules enforced here:
- rule 2/3: canonical digest computed and persisted; runs bind to (id, version, digest)
- rule 4: any post-lock mutation fails closed (``verify_unchanged``)
- rule 5: a changed contract is a new version, never an overwrite
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest, canonical_json
from pmpe.contracts.model import load_contract
from pmpe.domain.errors import ContractViolation
from pmpe.domain.serialize import atomic_write_json
from pmpe.telemetry.events import utc_now

__all__ = [
    "ContractDiff",
    "ContractRecord",
    "ContractStore",
    "ContractViolation",
    "diff_contracts",
]

_SAFE_CONTRACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


@dataclass(frozen=True)
class ContractRecord:
    contract_id: str
    version: int
    digest: str


class ContractStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "registry.json"

    def _index(self) -> dict[str, dict[str, str]]:
        if not self._index_path.exists():
            return {}
        loaded: dict[str, dict[str, str]] = json.loads(self._index_path.read_text())
        return loaded

    def register(self, path: Path) -> ContractRecord:
        contract = load_contract(path)  # structural validation
        data = contract.raw
        digest = canonical_digest(data)
        if not _SAFE_CONTRACT_ID.fullmatch(contract.contract_id):
            raise ContractViolation("contract_id is not safe for registry storage")
        index = self._index()
        versions = index.setdefault(contract.contract_id, {})
        existing = versions.get(str(contract.contract_version))
        if existing is not None and existing != digest:
            raise ContractViolation(
                f"{contract.contract_id} v{contract.contract_version} is already registered "
                f"with a different digest — a changed contract must be a new version, "
                "never an overwrite (PD-03)"
            )
        if existing is None:
            versions[str(contract.contract_version)] = digest
            stored = self.root / contract.contract_id / f"v{contract.contract_version}.json"
            root = self.root.resolve()
            if not stored.resolve().is_relative_to(root):
                raise ContractViolation("contract registry path escapes its configured root")
            stored.parent.mkdir(parents=True, exist_ok=True)
            stored.write_text(canonical_json(data) + "\n")
            atomic_write_json(self._index_path, index)
        return ContractRecord(contract.contract_id, contract.contract_version, digest)

    def versions(self, contract_id: str) -> list[int]:
        return sorted(int(v) for v in self._index().get(contract_id, {}))

    # --- run lock ---------------------------------------------------------------

    def lock_for_run(self, source: Path, run_dir: Path) -> ContractRecord:
        contract = load_contract(source)
        if not contract.runnable:
            raise ContractViolation(
                "only an APPROVED, unblocked contract can enter an engineering run: "
                + "; ".join(contract.blockers)
            )
        record = self.register(source)
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "contract.json").write_text(canonical_json(contract.raw) + "\n")
        atomic_write_json(
            run_dir / "contract.lock.json",
            {
                "contract_id": record.contract_id,
                "contract_version": record.version,
                "digest": record.digest,
                "locked_at": utc_now(),
            },
        )
        return record

    def verify_unchanged(self, run_dir: Path) -> ContractRecord:
        """Fail closed on any mutation of the run's locked contract (PD-03 rule 4)."""
        run_dir = Path(run_dir)
        lock = json.loads((run_dir / "contract.lock.json").read_text())
        data = json.loads((run_dir / "contract.json").read_text())
        digest = canonical_digest(data)
        if digest != lock["digest"]:
            raise ContractViolation(
                f"contract for run at {run_dir} was mutated after lock "
                f"(locked {lock['digest']}, found {digest}) — failing closed"
            )
        return ContractRecord(lock["contract_id"], int(lock["contract_version"]), digest)


# --- diff -----------------------------------------------------------------------------


@dataclass
class ContractDiff:
    old_digest: str
    new_digest: str
    added: list[str]
    removed: list[str]
    changed: list[str]


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in items if isinstance(item, dict)}


def diff_contracts(old_path: Path, new_path: Path) -> ContractDiff:
    old: dict[str, Any] = json.loads(Path(old_path).read_text())
    new: dict[str, Any] = json.loads(Path(new_path).read_text())
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    id_keyed = (
        "functional_requirements",
        "acceptance_criteria",
        "binary_release_gates",
        "scored_eval_rubric",
        "non_functional_requirements",
        "approved_product_decisions",
        "unresolved_questions",
    )
    for key in sorted(set(old) | set(new)):
        old_value, new_value = old.get(key), new.get(key)
        if old_value == new_value:
            continue
        if key in id_keyed and isinstance(old_value, list) and isinstance(new_value, list):
            old_ids, new_ids = _by_id(old_value), _by_id(new_value)
            for item_id in sorted(set(new_ids) - set(old_ids)):
                added.append(f"{key}[{item_id}]")
            for item_id in sorted(set(old_ids) - set(new_ids)):
                removed.append(f"{key}[{item_id}]")
            for item_id in sorted(set(old_ids) & set(new_ids)):
                if old_ids[item_id] != new_ids[item_id]:
                    changed.append(f"{key}[{item_id}]")
        elif isinstance(old_value, list) and isinstance(new_value, list):
            for i, (a, b) in enumerate(zip(old_value, new_value, strict=False)):
                if a != b:
                    changed.append(f"{key}[{i}]: {a!r} -> {b!r}")
            for i in range(len(old_value), len(new_value)):
                added.append(f"{key}[{i}]: {new_value[i]!r}")
            for i in range(len(new_value), len(old_value)):
                removed.append(f"{key}[{i}]: {old_value[i]!r}")
        else:
            changed.append(f"{key}: {old_value!r} -> {new_value!r}")

    return ContractDiff(
        old_digest=canonical_digest(old),
        new_digest=canonical_digest(new),
        added=added,
        removed=removed,
        changed=changed,
    )
