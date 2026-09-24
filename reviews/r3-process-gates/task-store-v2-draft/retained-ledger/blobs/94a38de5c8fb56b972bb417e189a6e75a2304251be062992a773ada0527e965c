"""Deterministic replay for immutable admitted model proposals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pmpe.contracts.digest import canonical_digest


@dataclass(frozen=True)
class ProposalAdmission:
    proposal_digest: str
    input_digest: str
    policy_digest: str
    decision: str
    reason_digests: tuple[str, ...]

    @property
    def admission_digest(self) -> str:
        return canonical_digest(
            {
                "proposal_digest": self.proposal_digest,
                "input_digest": self.input_digest,
                "policy_digest": self.policy_digest,
                "decision": self.decision,
                "reason_digests": list(self.reason_digests),
            }
        )


def proposal_subject(proposal: object) -> str:
    return canonical_digest(proposal)


def replay_admission(
    admission: ProposalAdmission,
    *,
    proposal: object,
    inputs: object,
    policy: object,
    evaluator: Callable[[object, object, object], tuple[str, tuple[str, ...]]],
) -> bool:
    """Replay one exact proposal; regeneration necessarily creates another subject."""

    if (
        proposal_subject(proposal) != admission.proposal_digest
        or canonical_digest(inputs) != admission.input_digest
        or canonical_digest(policy) != admission.policy_digest
    ):
        return False
    decision, reasons = evaluator(proposal, inputs, policy)
    return decision == admission.decision and reasons == admission.reason_digests
