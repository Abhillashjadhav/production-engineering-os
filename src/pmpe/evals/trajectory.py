"""Trajectory evals over the evidence ledger (the system of record).

Event grammar the engine emits and these checks consume:

- contract_lock/lock (output contract digest) -> assessment -> architecture/
  submit_architecture -> plan/submit_plan -> route/submit_routing
  (detail: "selected=a,b") -> implement (agent=specialist, action=task_tests |
  task_implementation, detail=task id) -> integrate -> freeze/freeze (output
  candidate digest) -> review/submit_review (input candidate digest) + review/
  readonly_check (verdict "clean") -> reconcile/reconcile (detail
  "accepted=RF-...;product_decisions=RF-...") [-> change_request_created]
  -> fix/fix (detail finding id) -> retest/gates -> draft_pr/record ->
  deploy/deploy (detail environment; production requires input approval digest)
  -> release_report/report

Every check is a named TRAJ-xx rule; any violation is a hard HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmpe.agents.permissions import REVIEWER_NAMES

# one home for the reviewer roster: the permission model (PD-06)
REVIEWER_AGENTS = set(REVIEWER_NAMES)


@dataclass(frozen=True)
class TrajectoryViolation:
    check_id: str
    description: str
    evidence: str


def _first_index(events: list[dict[str, Any]], stage: str) -> int | None:
    for i, event in enumerate(events):
        if event.get("stage") == stage:
            return i
    return None


def _digest(event: dict[str, Any], side: str, key: str) -> str | None:
    digests = event.get(side) or {}
    value = digests.get(key)
    return str(value) if value is not None else None


def evaluate_trajectory(events: list[dict[str, Any]]) -> list[TrajectoryViolation]:
    violations: list[TrajectoryViolation] = []

    def violate(check_id: str, description: str, evidence: str) -> None:
        violations.append(TrajectoryViolation(check_id, description, evidence))

    lock_i = _first_index(events, "contract_lock")
    arch_i = _first_index(events, "architecture")
    impl_i = _first_index(events, "implement")
    freeze_i = _first_index(events, "freeze")
    review_i = _first_index(events, "review")

    # TRAJ-01: contract validated/locked before architecture
    if arch_i is not None and (lock_i is None or lock_i > arch_i):
        violate(
            "TRAJ-01",
            "architecture ran before the contract was locked",
            f"architecture at event {arch_i}, lock at {lock_i}",
        )

    # TRAJ-02: contract digest never changes
    contract_digests = {
        digest
        for event in events
        for digest in (
            _digest(event, "input_digests", "contract"),
            _digest(event, "output_digests", "contract"),
        )
        if digest
    }
    if len(contract_digests) > 1:
        violate(
            "TRAJ-02", "contract digest changed during the run", ", ".join(sorted(contract_digests))
        )

    # TRAJ-03: architecture precedes implementation
    if impl_i is not None and (arch_i is None or arch_i > impl_i):
        violate(
            "TRAJ-03",
            "implementation ran before architecture",
            f"implement at event {impl_i}, architecture at {arch_i}",
        )

    # TRAJ-04: implementing specialists were selected by the router
    selected: set[str] = set()
    for event in events:
        if event.get("stage") == "route":
            detail = str(event.get("detail", ""))
            if detail.startswith("selected="):
                selected = {a for a in detail.removeprefix("selected=").split(",") if a}
    implementers = {str(e.get("agent")) for e in events if e.get("stage") == "implement"}
    unrouted = sorted(implementers - selected) if selected or implementers else []
    if unrouted:
        violate(
            "TRAJ-04",
            "specialist(s) implemented without being selected by the router",
            ", ".join(unrouted),
        )

    # TRAJ-05: tests precede implementation per task (where both exist)
    tests_seen: set[str] = set()
    for event in events:
        if event.get("stage") != "implement":
            continue
        task = str(event.get("detail", ""))
        if event.get("action") == "task_tests":
            tests_seen.add(task)
        elif event.get("action") == "task_implementation" and task not in tests_seen:
            violate("TRAJ-05", "task implemented before its tests were written", task)

    # TRAJ-06: implementers do not approve/review their own work
    builders = implementers | {str(e.get("agent")) for e in events if e.get("stage") == "integrate"}
    for event in events:
        if event.get("stage") == "review" and event.get("action") == "submit_review":
            agent = str(event.get("agent"))
            if agent in builders:
                violate("TRAJ-06", "an implementer reviewed its own work", agent)
            if agent not in REVIEWER_AGENTS:
                violate("TRAJ-06", "review submitted by a non-reviewer agent", agent)

    # TRAJ-07: candidate frozen before reviews
    if review_i is not None and (freeze_i is None or freeze_i > review_i):
        violate(
            "TRAJ-07",
            "review ran before any candidate was frozen",
            f"review at event {review_i}, freeze at {freeze_i}",
        )

    # TRAJ-08: every review inspected the most recently frozen candidate
    current_candidate: str | None = None
    for event in events:
        if event.get("stage") == "freeze":
            current_candidate = _digest(event, "output_digests", "candidate")
        if event.get("stage") == "review" and event.get("action") == "submit_review":
            seen = _digest(event, "input_digests", "candidate")
            if current_candidate is None or seen != current_candidate:
                violate(
                    "TRAJ-08",
                    "reviewer inspected a different candidate than the frozen one",
                    f"{event.get('agent')}: saw {seen}, frozen {current_candidate}",
                )

    # TRAJ-09: reviewers wrote nothing (readonly_check clean per submitting reviewer)
    submitted = {
        str(e.get("agent"))
        for e in events
        if e.get("stage") == "review" and e.get("action") == "submit_review"
    }
    clean = {
        str(e.get("agent"))
        for e in events
        if e.get("action") == "readonly_check" and e.get("verdict") == "clean"
    }
    dirty = {
        str(e.get("agent"))
        for e in events
        if e.get("action") == "readonly_check" and e.get("verdict") != "clean"
    }
    for reviewer in sorted(submitted & dirty):
        violate("TRAJ-09", "reviewer modified files during review", reviewer)
    for reviewer in sorted(submitted - clean - dirty):
        violate("TRAJ-09", "reviewer has no read-only verification recorded", reviewer)

    # TRAJ-10: fixer acted only on accepted findings
    accepted: set[str] = set()
    for event in events:
        if event.get("stage") == "reconcile":
            detail = str(event.get("detail", ""))
            for part in detail.split(";"):
                if part.startswith("accepted="):
                    accepted = {f for f in part.removeprefix("accepted=").split(",") if f}
        if event.get("stage") == "fix" and event.get("action") == "fix":
            finding = str(event.get("detail", ""))
            if finding not in accepted:
                violate("TRAJ-10", "fix applied to a non-accepted finding", finding)

    # TRAJ-11: every product-decision finding creates a change request — bound by
    # finding id, so one unrelated PCR event cannot excuse the rest
    product_findings: set[str] = set()
    change_requests_for: set[str] = {
        str(e.get("detail", "")) for e in events if e.get("action") == "change_request_created"
    }
    for event in events:
        if event.get("stage") == "reconcile":
            for part in str(event.get("detail", "")).split(";"):
                if part.startswith("product_decisions="):
                    product_findings = {
                        f for f in part.removeprefix("product_decisions=").split(",") if f
                    }
    missing_pcrs = sorted(product_findings - change_requests_for)
    if missing_pcrs:
        violate(
            "TRAJ-11",
            "product-decision finding(s) produced no ProductChangeRequest",
            ", ".join(missing_pcrs),
        )

    # TRAJ-12: required checks rerun after fixes
    fix_indices = [
        i for i, e in enumerate(events) if e.get("stage") == "fix" and e.get("action") == "fix"
    ]
    if fix_indices:
        last_fix = max(fix_indices)
        retest_after = any(e.get("stage") == "retest" for e in events[last_fix + 1 :])
        if not retest_after:
            violate("TRAJ-12", "no retest after the last fix", f"last fix at {last_fix}")

    # TRAJ-13: draft PR follows assurance
    pr_i = _first_index(events, "draft_pr")
    reconcile_i = _first_index(events, "reconcile")
    if pr_i is not None and (review_i is None or reconcile_i is None or pr_i < reconcile_i):
        violate(
            "TRAJ-13",
            "draft PR created before assurance completed",
            f"draft_pr at {pr_i}, reconcile at {reconcile_i}",
        )

    # TRAJ-14: production deployment requires a bound approval
    for event in events:
        is_production_deploy = (
            event.get("stage") == "deploy"
            and event.get("action") == "deploy"
            and str(event.get("detail", "")) == "production"
        )
        if is_production_deploy and not _digest(event, "input_digests", "approval"):
            violate("TRAJ-14", "production deployment without a recorded approval", str(event))

    return violations
