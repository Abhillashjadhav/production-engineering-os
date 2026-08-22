"""Deterministic two-sided authority checks for governed agent boundaries.

This module is deliberately small. Runtime adapters can call it *before* an
external action or capability grant; trajectory evaluation independently checks
that the same authority was respected in the evidence ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.contracts.canonical import canonical_digest


class BoundaryPolicyError(ValueError):
    """The frozen boundary policy is malformed or ambiguous."""


class BoundaryDenied(PermissionError):
    """The requested boundary crossing is outside frozen authority."""


@dataclass(frozen=True, order=True)
class OutboundGrant:
    destination: str
    capability: str


@dataclass(frozen=True)
class BoundaryPolicy:
    allowed_outbound: frozenset[OutboundGrant]
    allowed_capabilities: frozenset[str]
    digest: str

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

        return cls(
            allowed_outbound=frozenset(parsed_outbound),
            allowed_capabilities=frozenset(parsed_capabilities),
            digest=canonical_digest(payload),
        )

    def _require_binding(self, bound_policy_digest: str | None) -> None:
        if bound_policy_digest != self.digest:
            raise BoundaryDenied("boundary event is not bound to the frozen policy")

    def authorize_outbound(
        self,
        *,
        destination: str,
        capability: str,
        bound_policy_digest: str | None,
    ) -> None:
        self._require_binding(bound_policy_digest)
        if OutboundGrant(destination, capability) not in self.allowed_outbound:
            raise BoundaryDenied("outbound destination/capability is not authorized")

    def authorize_capability_grant(
        self,
        *,
        capability: str,
        authority_origin: str,
        bound_policy_digest: str | None,
    ) -> None:
        self._require_binding(bound_policy_digest)
        if authority_origin != "boundary_policy":
            raise BoundaryDenied("external input cannot become the source of authority")
        if capability not in self.allowed_capabilities:
            raise BoundaryDenied("capability is not authorized by the frozen policy")
