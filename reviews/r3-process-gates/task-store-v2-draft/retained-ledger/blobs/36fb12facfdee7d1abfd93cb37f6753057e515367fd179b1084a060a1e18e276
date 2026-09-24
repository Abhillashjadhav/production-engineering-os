"""TRAJ-FS: full-stack trajectory rules over the evidence ledger.

Event-grammar extensions the V3 engine emits (on top of the V2 grammar in
``pmpe.evals.trajectory``):

- ``journey_validation``/validate — input ``contract`` digest, output
  ``journey_record`` digest (PD-V3-16: before any frontend implementation).
- ``implement`` events carry ``detail`` markers ``surface=frontend`` or
  ``surface=backend`` alongside the task id.
- ``browser_verification``/verify — ``detail`` lists the executed suites and
  the mock posture, e.g. ``suites=a11y,keyboard,responsive,journeys;
  mocked=false`` (PD-V3-16: no mocked backend in the delivered path).
- ``preview``/record — ``detail`` carries ``kind=local_preview|
  containerized_preview``; ``input_digests.candidate`` must equal the freeze's
  output candidate digest (PD-V3-10/14; cloud claims are never verifiable).
- ``review`` events from the six PD-V3-15 lenses (``v3-*`` agents), each with
  a matching ``readonly_check`` verdict ``clean`` (intact) or
  ``infrastructure_invalid`` (an honestly-recorded degraded proof — acceptable
  for a HOLD, never for a PROCEED).
- ``api_contract``/verify — verdict ``current`` when the committed OpenAPI
  document matches the live app (PD-V3-13); anything else is drift.

A ledger with none of these stages, no frontend surface, and no v3 agents is
a V2 run — out of TRAJ-FS scope, owned by the V2 rules. Any violation is a
hard HOLD.
"""

from __future__ import annotations

from typing import Any

from pmpe.agents.permissions import FULLSTACK_REVIEW_LENSES
from pmpe.evals.trajectory import TrajectoryViolation

FULLSTACK_STAGES = ("journey_validation", "browser_verification", "preview", "api_contract")
ALLOWED_PREVIEW_KINDS = ("local_preview", "containerized_preview")
REQUIRED_LENS_AGENTS = frozenset(FULLSTACK_REVIEW_LENSES.values())


def _detail(event: dict[str, Any]) -> str:
    return str(event.get("detail", ""))


def _detail_field(event: dict[str, Any], key: str) -> str | None:
    for part in _detail(event).split(";"):
        name, _, value = part.partition("=")
        if name.strip() == key:
            return value.strip()
    return None


def _first_index(events: list[dict[str, Any]], stage: str) -> int | None:
    for i, event in enumerate(events):
        if event.get("stage") == stage:
            return i
    return None


def _is_fullstack_run(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("stage") in FULLSTACK_STAGES:
            return True
        if "surface=frontend" in _detail(event):
            return True
        if str(event.get("agent", "")).startswith("v3-"):
            return True
    return False


def evaluate_fullstack_trajectory(events: list[dict[str, Any]]) -> list[TrajectoryViolation]:
    """Named TRAJ-FS violations ([] = the full-stack trajectory holds)."""
    if not _is_fullstack_run(events):
        return []

    violations: list[TrajectoryViolation] = []

    def violate(check_id: str, description: str, evidence: str) -> None:
        violations.append(TrajectoryViolation(check_id, description, evidence))

    journey_i = _first_index(events, "journey_validation")
    freeze_i = _first_index(events, "freeze")
    report_i = _first_index(events, "release_report")

    # TRAJ-FS-01: no frontend implementation before a validated journey
    frontend_impl = [
        (i, e)
        for i, e in enumerate(events)
        if e.get("stage") == "implement" and _detail_field(e, "surface") == "frontend"
    ]
    if frontend_impl:
        first_frontend = frontend_impl[0][0]
        if journey_i is None:
            violate(
                "TRAJ-FS-01",
                "frontend implementation with no validated journey in the run",
                _detail(frontend_impl[0][1]),
            )
        elif first_frontend < journey_i:
            violate(
                "TRAJ-FS-01",
                "frontend implementation before the journey was validated",
                _detail(frontend_impl[0][1]),
            )

    # TRAJ-FS-02: the journey record is bound to the locked contract digest
    lock_i = _first_index(events, "contract_lock")
    if journey_i is not None and lock_i is not None:
        locked = (events[lock_i].get("output_digests") or {}).get("contract")
        journey_input = (events[journey_i].get("input_digests") or {}).get("contract")
        if locked is None:
            # a digest-less lock would silently disable this binding check,
            # and no V2 rule owns that case — fail closed here
            violate(
                "TRAJ-FS-02",
                "the contract lock emitted no digest — the journey binding cannot be verified",
                str(events[lock_i].get("output_digests")),
            )
        elif journey_input != locked:
            violate(
                "TRAJ-FS-02",
                "journey validated against a different contract digest than the lock",
                f"locked={locked}, journey={journey_input}",
            )

    # TRAJ-FS-03: browser verification exists, before the release report, unmocked
    browser_events = [e for e in events if e.get("stage") == "browser_verification"]
    if not browser_events:
        violate(
            "TRAJ-FS-03",
            "no browser verification in a full-stack run",
            "stages present: " + ",".join(sorted({str(e.get("stage")) for e in events})),
        )
    for event in browser_events:
        if _detail_field(event, "mocked") != "false":
            violate(
                "TRAJ-FS-03",
                "browser verification did not declare an unmocked backend",
                _detail(event),
            )

    # TRAJ-FS-04: preview evidence bound to the frozen candidate, allowed kind only
    candidate_digest = None
    if freeze_i is not None:
        candidate_digest = (events[freeze_i].get("output_digests") or {}).get("candidate")
    for event in events:
        if event.get("stage") != "preview":
            continue
        kind = _detail_field(event, "kind")
        if kind not in ALLOWED_PREVIEW_KINDS:
            violate(
                "TRAJ-FS-04",
                f"preview kind '{kind}' is not a verifiable preview",
                _detail(event),
            )
        preview_candidate = (event.get("input_digests") or {}).get("candidate")
        if candidate_digest is not None and preview_candidate != candidate_digest:
            violate(
                "TRAJ-FS-04",
                "preview evidence bound to a different candidate than the freeze",
                f"frozen={candidate_digest}, preview={preview_candidate}",
            )

    # TRAJ-FS-05: all six lenses reviewed, and only roster agents claim lenses
    v3_reviews = [
        e
        for e in events
        if e.get("stage") == "review"
        and e.get("action") == "submit_review"  # readonly_check shares the stage
        and str(e.get("agent", "")).startswith("v3-")
    ]
    if v3_reviews or freeze_i is not None:
        reviewed_by = {str(e.get("agent")) for e in v3_reviews}
        missing = REQUIRED_LENS_AGENTS - reviewed_by
        # a frozen full-stack candidate with zero lens reviews is the worst
        # case of "missing", not an exemption
        if freeze_i is not None and missing:
            violate(
                "TRAJ-FS-05",
                "full-stack lens(es) missing from the review set",
                ", ".join(sorted(missing)),
            )
        strangers = reviewed_by - REQUIRED_LENS_AGENTS
        if strangers:
            violate(
                "TRAJ-FS-05",
                "review submitted by an agent outside the six-lens roster",
                ", ".join(sorted(strangers)),
            )

    # TRAJ-FS-06: every v3 reviewer proves read-only per run. "clean" is an
    # intact proof; "infrastructure_invalid" is an honestly-recorded degraded
    # proof (harness interference, not a reviewer write) — acceptable for a
    # HOLD/INSUFFICIENT_EVIDENCE but never for a PROCEED. Any other verdict
    # ("modified", or none) is a compromise. This mirrors release_report, so the
    # trajectory auditor and the orchestrator agree about the same run.
    readonly_verdicts = {
        str(e.get("agent")): str(e.get("verdict"))
        for e in events
        if e.get("action") == "readonly_check" and str(e.get("agent", "")).startswith("v3-")
    }
    acceptable = {"clean", "infrastructure_invalid"}
    for event in v3_reviews:
        agent = str(event.get("agent"))
        if readonly_verdicts.get(agent) not in acceptable:
            violate(
                "TRAJ-FS-06",
                "a full-stack reviewer has no acceptable read-only proof for this run",
                f"{agent}={readonly_verdicts.get(agent)}",
            )
    if report_i is not None and str(events[report_i].get("verdict")) == "PROCEED":
        degraded = sorted(a for a, v in readonly_verdicts.items() if v == "infrastructure_invalid")
        if degraded:
            violate(
                "TRAJ-FS-06",
                "a PROCEED release rests on an infrastructure-invalid read-only proof",
                ", ".join(degraded),
            )

    # TRAJ-FS-07: the a11y suite executed before the release report
    if report_i is not None:
        a11y_before_report = any(
            "a11y" in (_detail_field(e, "suites") or "").split(",")
            for i, e in enumerate(events)
            if e.get("stage") == "browser_verification" and i < report_i
        )
        if browser_events and not a11y_before_report:
            violate(
                "TRAJ-FS-07",
                "release report issued without an executed accessibility suite",
                "suites seen: "
                + "; ".join(_detail_field(e, "suites") or "" for e in browser_events),
            )

    # TRAJ-FS-08: the committed API contract is current before the freeze
    api_events = [(i, e) for i, e in enumerate(events) if e.get("stage") == "api_contract"]
    if freeze_i is not None:
        current_before_freeze = any(
            str(e.get("verdict")) == "current" for i, e in api_events if i < freeze_i
        )
        drifted = [e for _, e in api_events if str(e.get("verdict")) not in ("current", "")]
        if drifted:
            violate(
                "TRAJ-FS-08",
                "the committed API contract drifted from the live application",
                "; ".join(str(e.get("verdict")) for e in drifted),
            )
        elif not current_before_freeze:
            violate(
                "TRAJ-FS-08",
                "no current api-contract verification before the freeze",
                f"api_contract events: {len(api_events)}",
            )

    return violations
