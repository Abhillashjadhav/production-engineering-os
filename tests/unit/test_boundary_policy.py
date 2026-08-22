from __future__ import annotations

import pytest

from pmpe.policies.boundary import BoundaryDenied, BoundaryPolicy, BoundaryPolicyError


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

    with pytest.raises(BoundaryDenied):
        policy.authorize_outbound(
            destination="huggingface.co",
            capability="read",
            bound_policy_digest=policy.digest,
        )

    with pytest.raises(BoundaryDenied):
        policy.authorize_outbound(
            destination="api.openai.com",
            capability="write",
            bound_policy_digest=policy.digest,
        )

    with pytest.raises(BoundaryDenied):
        policy.authorize_outbound(
            destination="api.openai.com",
            capability="read",
            bound_policy_digest="sha256:stale-policy",
        )


def test_external_input_cannot_grant_capability_even_when_capability_is_listed() -> None:
    policy = _policy()

    with pytest.raises(BoundaryDenied, match="source of authority"):
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

    with pytest.raises(BoundaryDenied):
        policy.authorize_capability_grant(
            capability="deploy_production",
            authority_origin="boundary_policy",
            bound_policy_digest=policy.digest,
        )


def test_boundary_policy_cannot_be_directly_constructed_with_forged_authority() -> None:
    with pytest.raises(TypeError, match="from_payload"):
        BoundaryPolicy()


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
