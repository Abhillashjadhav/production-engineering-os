"""Recheck compiled acceptance predicates against sealed observer responses."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from pmpe.barebones import Template, _assertion_passes
from pmpe.contracts.acceptance import AcceptanceBuildPlan, PropertyAssertion
from pmpe.evidence.ledger import EvidenceIntegrityError
from pmpe.task_tracker_harness import REGISTRY_NAME

_READBACK_PREDICATE_SECONDS = 120.0


def verify_observation_predicates(
    plan: AcceptanceBuildPlan,
    template: Template,
    observations: Mapping[str, Mapping[str, Any]],
) -> None:
    """REV_OBSERVER_SEMANTICS: rederive assertion truth, action and adapter identity.

    The recorded response is a supervisor observation. This does not execute the
    candidate again, authenticate the provider, or grant customer delivery proof.
    """

    deadline = time.monotonic() + _READBACK_PREDICATE_SECONDS
    if set(observations) != {item.criterion_id for item in plan.criteria}:
        raise EvidenceIntegrityError("product acceptance readback has incomplete observations")
    try:
        for criterion in plan.criteria:
            observed = observations[criterion.criterion_id]
            response = observed.get("response")
            if not isinstance(response, Mapping):
                raise EvidenceIntegrityError("product acceptance response is malformed")
            if template.version == REGISTRY_NAME and "trace" not in observed:
                raise EvidenceIntegrityError("fixed task-tracker observer trace is missing")
            if criterion.form == "measure":
                if (
                    criterion.operator is None
                    or criterion.minimum_sample is None
                    or observed.get("action") != criterion.measure
                    or observed.get("target") != template.measures.get(criterion.measure)
                    or template.version != REGISTRY_NAME
                ):
                    raise EvidenceIntegrityError("measure observer binding changed")
                sample = response.get("sample_size")
                passed = (
                    type(sample) is int
                    and sample >= criterion.minimum_sample
                    and "value" in response
                    and _assertion_passes(
                        PropertyAssertion("value", criterion.operator, criterion.value),
                        response,
                        deadline=deadline,
                    )
                )
            elif criterion.form == "given_when_then" and criterion.when is not None:
                if (
                    observed.get("action") != criterion.when.action
                    or observed.get("target") != template.actions.get(criterion.when.action)
                    or not all(
                        _assertion_passes(item, template.context, deadline=deadline)
                        for item in criterion.given
                    )
                ):
                    raise EvidenceIntegrityError("action observer binding changed")
                passed = all(
                    _assertion_passes(item, {"result": response}, deadline=deadline)
                    for item in criterion.then
                )
            else:
                raise EvidenceIntegrityError("criterion has no protected observation adapter")
            if observed.get("assertions_passed") is not passed:
                raise EvidenceIntegrityError("recorded acceptance assertion differs from response")
    except EvidenceIntegrityError:
        raise
    except (RuntimeError, ValueError, RecursionError, TypeError) as exc:
        raise EvidenceIntegrityError("product acceptance predicate readback failed") from exc
