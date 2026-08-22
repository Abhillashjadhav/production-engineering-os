"""Deterministic two-sided authority checks for governed agent boundaries.

Runtime adapters call this authorizer before an external action or capability
grant. Trajectory evaluation independently checks that the same authority was
respected in the evidence ledger.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias, cast

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


PolicyState: TypeAlias = tuple[frozenset[OutboundGrant], frozenset[str], str]


def _build_state_registry() -> tuple[
    Callable[[object, PolicyState], None], Callable[[object], PolicyState | None]
]:
    states: weakref.WeakKeyDictionary[object, PolicyState] = weakref.WeakKeyDictionary()

    def register(subject: object, state: PolicyState) -> None:
        states[subject] = state

    def read(subject: object) -> PolicyState | None:
        return states.get(subject)

    return register, read


_register_policy_state, _read_policy_state = _build_state_registry()


class BoundaryPolicy:
    """Validated immutable authority derived only from its canonical payload.

    Direct construction is deliberately blocked so grants can never be paired
    with an unrelated trusted digest. Use ``from_payload``.
    """

    __slots__ = ("__weakref__",)

    def __new__(cls) -> BoundaryPolicy:
        raise TypeError("BoundaryPolicy must be created with from_payload()")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("BoundaryPolicy is immutable")

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        _register_state: Callable[[object, PolicyState], None] | None = _register_policy_state,
    ) -> BoundaryPolicy:
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
            if type(destination) is not str:  # noqa: E721
                raise BoundaryPolicyError("outbound destination must be a non-empty string")
            if not destination.strip():
                raise BoundaryPolicyError("outbound destination must be a non-empty string")
            if type(capability) is not str:  # noqa: E721
                raise BoundaryPolicyError("outbound capability must be a non-empty string")
            if not capability.strip():
                raise BoundaryPolicyError("outbound capability must be a non-empty string")
            parsed_outbound.append(OutboundGrant(destination, capability))

        parsed_capabilities: list[str] = []
        for capability in capabilities:
            if type(capability) is not str:  # noqa: E721
                raise BoundaryPolicyError("allowed capability must be a non-empty string")
            if not capability.strip():
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

        frozen_outbound = frozenset(parsed_outbound)
        frozen_capabilities = frozenset(parsed_capabilities)
        instance = object.__new__(cls)
        if _register_state is None:
            raise BoundaryPolicyError("boundary policy authority is unavailable")
        _register_state(instance, (frozen_outbound, frozen_capabilities, digest))
        return instance

    def _validated_state(
        self,
        _read_state: Callable[[object], PolicyState | None] = _read_policy_state,
    ) -> PolicyState:
        state = _read_state(self)
        if state is None:
            raise BoundaryDeniedError("boundary policy authority is invalid")
        return state

    @property
    def allowed_outbound(self) -> frozenset[OutboundGrant]:
        outbound, _, _ = self._validated_state()
        return outbound

    @property
    def allowed_capabilities(self) -> frozenset[str]:
        _, capabilities, _ = self._validated_state()
        return capabilities

    @property
    def digest(self) -> str:
        _, _, digest = self._validated_state()
        return digest

    def authorize_outbound(
        self,
        *,
        destination: str,
        capability: str,
        bound_policy_digest: str | None,
    ) -> None:
        outbound, _, digest = self._validated_state()
        if bound_policy_digest != digest:
            raise BoundaryDeniedError("boundary event is not bound to the frozen policy")
        if OutboundGrant(destination, capability) not in outbound:
            raise BoundaryDeniedError("outbound destination/capability is not authorized")

    def authorize_capability_grant(
        self,
        *,
        capability: str,
        authority_origin: str,
        bound_policy_digest: str | None,
    ) -> None:
        _, capabilities, digest = self._validated_state()
        if bound_policy_digest != digest:
            raise BoundaryDeniedError("boundary event is not bound to the frozen policy")
        if authority_origin != "boundary_policy":
            raise BoundaryDeniedError("external input cannot become the source of authority")
        if capability not in capabilities:
            raise BoundaryDeniedError("capability is not authorized by the frozen policy")


def _bind_policy_constructor(
    method: Any,
    register: Callable[[object, PolicyState], None],
) -> Any:
    method.__kwdefaults__ = {"_register_state": None}

    def bound(cls: type[BoundaryPolicy], payload: dict[str, Any]) -> BoundaryPolicy:
        return cast(BoundaryPolicy, method(cls, payload, _register_state=register))

    return classmethod(bound)


type.__setattr__(
    BoundaryPolicy,
    "from_payload",
    _bind_policy_constructor(
        cast(Any, BoundaryPolicy.from_payload).__func__,
        _register_policy_state,
    ),
)

del _bind_policy_constructor, _build_state_registry, _read_policy_state, _register_policy_state
