"""Deterministic two-sided authority checks for governed agent boundaries.

Runtime adapters call this authorizer before an external action or capability
grant. Trajectory evaluation independently checks that the same authority was
respected in the evidence ledger.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

import rfc8785

from pmpe.contracts.canonical import canonical_digest


class BoundaryPolicyError(ValueError):
    """The frozen boundary policy is malformed or ambiguous."""


class BoundaryDeniedError(PermissionError):
    """The requested boundary crossing is outside frozen authority."""


@dataclass(frozen=True, order=True)
class OutboundGrant:
    destination: str
    capability: str


class BoundaryPolicy(tuple[object, ...]):
    """Validated immutable authority derived only from its canonical payload.

    Direct construction is deliberately blocked so grants can never be paired
    with an unrelated trusted digest. Use ``from_payload``.
    """

    __slots__ = ()

    def __new__(cls, _iterable: Iterable[object] = (), /) -> BoundaryPolicy:
        raise TypeError("BoundaryPolicy must be created with from_payload()")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("BoundaryPolicy is immutable")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BoundaryPolicy:
        if set(payload) != {"allowed_outbound", "allowed_capabilities"}:
            raise BoundaryPolicyError("boundary policy has unknown or missing fields")

        outbound = payload["allowed_outbound"]
        capabilities = payload["allowed_capabilities"]
        if not isinstance(outbound, list) or not isinstance(capabilities, list):
            raise BoundaryPolicyError("boundary policy grants must be lists")

        parsed_outbound: list[OutboundGrant] = []
        for item in outbound:
            if not isinstance(item, dict) or set(item) != {"destination", "capability"}:
                raise BoundaryPolicyError("outbound grant must name destination and capability")
            destination = item["destination"]
            capability = item["capability"]
            if not isinstance(destination, str) or not destination.strip():
                raise BoundaryPolicyError("outbound destination must be a non-empty string")
            if not isinstance(capability, str) or not capability.strip():
                raise BoundaryPolicyError("outbound capability must be a non-empty string")
            parsed_outbound.append(OutboundGrant(destination, capability))

        parsed_capabilities: list[str] = []
        for capability in capabilities:
            if not isinstance(capability, str) or not capability.strip():
                raise BoundaryPolicyError("allowed capability must be a non-empty string")
            parsed_capabilities.append(capability)

        if len(set(parsed_outbound)) != len(parsed_outbound):
            raise BoundaryPolicyError("boundary policy contains duplicate outbound grants")
        if len(set(parsed_capabilities)) != len(parsed_capabilities):
            raise BoundaryPolicyError("boundary policy contains duplicate capabilities")

        try:
            digest = canonical_digest(payload)
        except (rfc8785.CanonicalizationError, OverflowError, ValueError) as exc:
            raise BoundaryPolicyError(
                "boundary policy is outside the canonical JSON domain"
            ) from exc

        return cast(
            BoundaryPolicy,
            tuple.__new__(
                cls,
                (frozenset(parsed_outbound), frozenset(parsed_capabilities), digest),
            ),
        )

    @property
    def allowed_outbound(self) -> frozenset[OutboundGrant]:
        return cast(frozenset[OutboundGrant], self[0])

    @property
    def allowed_capabilities(self) -> frozenset[str]:
        return cast(frozenset[str], self[1])

    @property
    def digest(self) -> str:
        return cast(str, self[2])

    def _require_binding(self, bound_policy_digest: str | None) -> None:
        if bound_policy_digest != self.digest:
            raise BoundaryDeniedError("boundary event is not bound to the frozen policy")

    def authorize_outbound(
        self,
        *,
        destination: str,
        capability: str,
        bound_policy_digest: str | None,
    ) -> None:
        self._require_binding(bound_policy_digest)
        if OutboundGrant(destination, capability) not in self.allowed_outbound:
            raise BoundaryDeniedError("outbound destination/capability is not authorized")

    def authorize_capability_grant(
        self,
        *,
        capability: str,
        authority_origin: str,
        bound_policy_digest: str | None,
    ) -> None:
        self._require_binding(bound_policy_digest)
        if authority_origin != "boundary_policy":
            raise BoundaryDeniedError("external input cannot become the source of authority")
        if capability not in self.allowed_capabilities:
            raise BoundaryDeniedError("capability is not authorized by the frozen policy")
