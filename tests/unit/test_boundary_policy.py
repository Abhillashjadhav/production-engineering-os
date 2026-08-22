from __future__ import annotations

import pytest

import pmpe.policies.boundary as boundary_module
from pmpe.policies.boundary import (
    BoundaryDeniedError,
    BoundaryPolicy,
    BoundaryPolicyError,
    OutboundGrant,
)


def _policy() -> BoundaryPolicy:
    return BoundaryPolicy.from_payload(
        {
            "allowed_outbound": [
                {"destination": "api.openai.com", "capability": "read"},
            ],
            "allowed_capabilities": ["read_support_case", "write_support_draft"],
        }
    )


def test_outbound_authorization_requires_exact_destination_capability_and_digest() -> None:
    policy = _policy()
    policy.authorize_outbound(
        destination="api.openai.com",
        capability="read",
        bound_policy_digest=policy.digest,
    )

    with pytest.raises(BoundaryDeniedError):
        policy.authorize_outbound(
            destination="huggingface.co",
            capability="read",
            bound_policy_digest=policy.digest,
        )

    with pytest.raises(BoundaryDeniedError):
        policy.authorize_outbound(
            destination="api.openai.com",
            capability="write",
            bound_policy_digest=policy.digest,
        )

    with pytest.raises(BoundaryDeniedError):
        policy.authorize_outbound(
            destination="api.openai.com",
            capability="read",
            bound_policy_digest="sha256:stale-policy",
        )


def test_external_input_cannot_grant_capability_even_when_capability_is_listed() -> None:
    policy = _policy()

    with pytest.raises(BoundaryDeniedError, match="source of authority"):
        policy.authorize_capability_grant(
            capability="write_support_draft",
            authority_origin="external_input",
            bound_policy_digest=policy.digest,
        )


def test_policy_can_grant_only_a_capability_it_already_contains() -> None:
    policy = _policy()
    policy.authorize_capability_grant(
        capability="write_support_draft",
        authority_origin="boundary_policy",
        bound_policy_digest=policy.digest,
    )

    with pytest.raises(BoundaryDeniedError):
        policy.authorize_capability_grant(
            capability="deploy_production",
            authority_origin="boundary_policy",
            bound_policy_digest=policy.digest,
        )


def test_boundary_policy_cannot_be_directly_constructed_with_forged_authority() -> None:
    with pytest.raises(TypeError, match="from_payload"):
        BoundaryPolicy()


def test_boundary_policy_cannot_be_mutated_after_construction() -> None:
    policy = _policy()

    with pytest.raises(AttributeError, match="immutable"):
        policy._allowed_outbound = frozenset({OutboundGrant("huggingface.co", "read")})
    with pytest.raises(AttributeError, match="immutable"):
        policy._digest = "sha256:forged"

    with pytest.raises(BoundaryDeniedError):
        policy.authorize_outbound(
            destination="huggingface.co",
            capability="read",
            bound_policy_digest=policy.digest,
        )


def test_boundary_policy_authority_cannot_be_replaced_via_object_primitives() -> None:
    policy = _policy()
    trusted_digest = policy.digest

    try:
        object.__setattr__(
            policy,
            "_allowed_outbound",
            frozenset({OutboundGrant("huggingface.co", "read")}),
        )
    except (AttributeError, TypeError):
        pass
    else:
        with pytest.raises(BoundaryDeniedError):
            policy.authorize_outbound(
                destination="huggingface.co",
                capability="read",
                bound_policy_digest=trusted_digest,
            )
    try:
        empty_shell = object.__new__(BoundaryPolicy)
    except TypeError:
        pass
    else:
        with pytest.raises(BoundaryDeniedError):
            empty_shell.authorize_outbound(
                destination="api.openai.com",
                capability="read",
                bound_policy_digest=policy.digest,
            )


def test_tuple_primitive_cannot_forge_usable_boundary_authority() -> None:
    with pytest.raises((BoundaryDeniedError, TypeError)):
        forged = tuple.__new__(
            BoundaryPolicy,
            (
                frozenset({OutboundGrant("huggingface.co", "read")}),
                frozenset(),
                "sha256:caller-chosen",
            ),
        )
        forged.authorize_outbound(
            destination="huggingface.co",
            capability="read",
            bound_policy_digest="sha256:caller-chosen",
        )


def test_boundary_integrity_oracle_is_not_exposed_to_adapters() -> None:
    assert not callable(getattr(boundary_module, "_state_tag", None))


def test_malformed_or_ambiguous_policy_is_rejected() -> None:
    with pytest.raises(BoundaryPolicyError):
        BoundaryPolicy.from_payload(
            {
                "allowed_outbound": [
                    {"destination": "api.openai.com", "capability": "read"},
                    {"destination": "api.openai.com", "capability": "read"},
                ],
                "allowed_capabilities": [],
            }
        )

    with pytest.raises(BoundaryPolicyError):
        BoundaryPolicy.from_payload(
            {
                "allowed_outbound": [],
                "allowed_capabilities": [],
                "caller_says_approved": True,
            }
        )

    with pytest.raises(BoundaryPolicyError):
        BoundaryPolicy.from_payload(
            {
                "allowed_outbound": [
                    {
                        "destination": "api.openai.com",
                        "capability": "read",
                        "caller_says_approved": True,
                    }
                ],
                "allowed_capabilities": [],
            }
        )


def test_noncanonical_policy_value_is_rejected() -> None:
    with pytest.raises(BoundaryPolicyError):
        BoundaryPolicy.from_payload(
            {
                "allowed_outbound": [],
                "allowed_capabilities": [float("nan")],
            }
        )
