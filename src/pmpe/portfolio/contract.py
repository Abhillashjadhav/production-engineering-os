"""The auditor's ProductDecisionContract + policy, bound as one bundle.

The contract is a standard pmpe ProductDecisionContract living at
``products/portfolio-auditor/contract.json`` — locked, digested, and
mutation-checked by the existing ContractStore (PD-03). The auditor adds no
bespoke contract machinery; this module only resolves paths and binds the
(contract digest, policy digest) pair a run pins.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.model import ProductDecisionContract, load_contract
from pmpe.portfolio.policy import AuditorPolicy, load_policy


def product_root() -> Path:
    """The auditor's product config root (contract + policy)."""
    return Path(__file__).resolve().parents[3] / "products" / "portfolio-auditor"


def contract_path() -> Path:
    return product_root() / "contract.json"


@dataclass(frozen=True)
class AuditorBundle:
    """The immutable pair every audit run binds to."""

    contract: ProductDecisionContract
    contract_digest: str
    policy: AuditorPolicy


def load_auditor_bundle(root: Path | None = None) -> AuditorBundle:
    """Load and digest-bind the shipped contract + policy (fail-closed)."""
    base = root or product_root()
    contract_file = base / "contract.json"
    policy_file = base / "policy.json"
    if not contract_file.is_file() or not policy_file.is_file():
        raise FileNotFoundError(
            f"auditor product root {base} must contain contract.json and policy.json"
        )
    contract = load_contract(contract_file)
    return AuditorBundle(
        contract=contract,
        contract_digest=canonical_digest(contract.raw),
        policy=load_policy(policy_file),
    )
