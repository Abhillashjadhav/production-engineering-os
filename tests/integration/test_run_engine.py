"""The engineering run engine: a deterministic admission state machine (PD-11).

Agents propose artifacts; the engine validates them at admission, records
evidence-ledger events matching the trajectory grammar, and owns every stage
transition. The final test walks a full run and proves the ledger it leaves
behind is trajectory-clean — the engine and the trajectory evals agree on the
grammar by construction, not by coincidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.agents.permissions import ReadOnlyViolation
from pmpe.agents.router import ALL_PROFILES
from pmpe.assurance.findings import FindingsStore
from pmpe.assurance.reconcile import OwnerDecision
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.domain.errors import ContractViolation, PmpeError
from pmpe.engineering.candidate import CandidateViolation
from pmpe.engineering.engine import (
    DeploymentBlocked,
    EngineeringRun,
    SubmissionRejected,
)
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.evals.trajectory import evaluate_trajectory
from pmpe.gitops.local import LocalGitAdapter

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "tests" / "fixtures" / "v2" / "contract_approved.json"
AGENTS_DIR = ROOT / ".claude" / "agents"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "deploy").mkdir(parents=True)
    git = LocalGitAdapter(root)
    git.init()
    (root / "api.py").write_text("STATUS = 'ok'\n")
    (root / "deploy" / "run.sh").write_text("#!/bin/sh\necho serving\n")
    (root / "deploy" / "ROLLBACK.md").write_text("# Rollback\n\nRevert and rerun run.sh.\n")
    git.commit_all("chore: base workspace")
    return root


@pytest.fixture()
def run(tmp_path: Path) -> EngineeringRun:
    return EngineeringRun.start(
        CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR, fixture_mode=True
    )


# --- artifact builders (what live agents would return) ---------------------------------


def _arch(digest: str) -> dict[str, Any]:
    return {
        "contract_digest": digest,
        "components": [{"name": "api", "justifying_requirements": ["FR-001"]}],
        "adrs": [
            {
                "id": "ADR-001",
                "title": "Single-process service",
                "context": "one small endpoint",
                "decision": "stdlib http server, one process",
                "consequences": "no HA; acceptable per known_risks",
                "reversibility": "reversible",
            }
        ],
    }


def _plan(digest: str) -> dict[str, Any]:
    task = {
        "requirement_ids": ["FR-001"],
        "component": "api",
        "rollback": "revert the task commit",
    }
    return {
        "contract_digest": digest,
        "tasks": [
            {
                "id": "T-001",
                "behavioural_test": "GET /health returns 200 with status ok",
                "required_capability": "backend",
                **task,
            },
            {
                "id": "T-002",
                "behavioural_test": "acceptance criterion AC-001 has an executed test",
                "required_capability": "test",
                **task,
            },
        ],
    }


def _routing() -> dict[str, Any]:
    selected = [
        {"agent": "v2-backend-engineer", "tasks": ["T-001"], "reason": "owns backend capability"},
        {"agent": "v2-test-engineer", "tasks": ["T-002"], "reason": "owns test capability"},
    ]
    used = {str(entry["agent"]) for entry in selected}
    return {
        "selected": selected,
        "not_selected": [
            {"agent": name, "reason": "no task requires this capability"}
            for name in ALL_PROFILES
            if name not in used
        ],
    }


def _specialist(task_id: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "commits": ["abc1234"],
        "tests_run": [f"tests.test_{task_id.lower().replace('-', '_')}"],
        "results": "passed",
    }


def _integration() -> dict[str, Any]:
    return {
        "integrated_branches": ["specialist/T-001", "specialist/T-002"],
        "checks_run": ["unit", "lint"],
        "candidate_digest": "sha256:integrator-view",
    }


def _review(
    reviewer: str, candidate: str, findings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"reviewer": reviewer, "candidate_digest": candidate, "findings": findings or []}


_CODE_FINDING = {
    "title": "eval() on request input",
    "severity": "high",
    "blocking": True,
    "file": "api.py",
    "line": 1,
    "evidence": "api.py:1 evaluates request-controlled input",
    "failure_mechanism": "arbitrary code execution on a crafted payload",
    "mechanically_fixable": True,
    "requires_product_decision": False,
}

_PRODUCT_FINDING = {
    "title": "rate limiting unspecified for public endpoint",
    "severity": "medium",
    "blocking": False,
    "file": "api.py",
    "line": 1,
    "evidence": "the contract is silent on throttling the public /health endpoint",
    "failure_mechanism": "operators may expose an unthrottled public endpoint",
    "mechanically_fixable": False,
    "requires_product_decision": True,
    "affected_requirement": "FR-001",
}

_REVIEW_FINDINGS: dict[str, list[dict[str, Any]]] = {
    "v2-code-reviewer": [_CODE_FINDING],
    "v2-product-conformance-reviewer": [_PRODUCT_FINDING],
    "v2-architecture-simplicity-reviewer": [],
    "v2-eval-integrity-auditor": [],
}


# --- walk helpers ------------------------------------------------------------------------


def to_review(run: EngineeringRun, repo: Path) -> str:
    """Drive a run from assessment to the frozen candidate; returns its digest."""
    run.record_assessment({"summary": "greenfield workspace, no prior runs"})
    run.submit("v2-system-architect", _arch(run.contract_digest))
    run.submit("v2-implementation-planner", _plan(run.contract_digest))
    run.submit("v2-engineer-router", _routing())
    run.submit("v2-backend-engineer", _specialist("T-001"))
    run.submit("v2-test-engineer", _specialist("T-002"))
    run.submit("v2-integration-engineer", _integration())
    return run.freeze(repo).tree_digest


def run_reviews(run: EngineeringRun, repo: Path, candidate: str, *, findings: bool = True) -> None:
    for reviewer, found in _REVIEW_FINDINGS.items():
        run.begin_review(reviewer, repo)
        run.submit(reviewer, _review(reviewer, candidate, found if findings else []))
        run.end_review(reviewer, repo)


def assure(run: EngineeringRun, repo: Path) -> str:
    """Review -> reconcile -> fix -> retest -> refreeze -> verify; returns cand-002."""
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    run.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    (repo / "api.py").write_text("STATUS = 'ok'  # input is never evaluated\n")
    LocalGitAdapter(repo).commit_all("fix: RF-001 remove eval of request input")
    run.record_gates(repo=repo, passed=True, detail="2/2 executed")
    second = run.freeze(repo).tree_digest
    run.record_fix_verification("RF-001", verifier="v2-code-reviewer")
    return second


def drive_to_deploy(run: EngineeringRun, repo: Path) -> str:
    """Full assurance plus the draft-PR record; leaves the run at the deploy stage."""
    candidate = assure(run, repo)
    run.record_draft_pr("draft PR on claude/production-engineering-os-v2")
    return candidate


# --- start / resume ----------------------------------------------------------------------


def test_start_locks_contract_and_opens_at_assessment(run: EngineeringRun) -> None:
    assert run.stage == "assessment"
    assert run.contract_digest.startswith("sha256:")
    events = run.ledger.read_all()
    assert [e["stage"] for e in events] == ["contract_lock"]
    assert events[0]["action"] == "lock"
    assert events[0]["output_digests"]["contract"] == run.contract_digest


def test_start_twice_fails_closed(run: EngineeringRun) -> None:
    with pytest.raises(PmpeError, match="already"):
        EngineeringRun.start(CONTRACT, run.run_dir, agents_dir=AGENTS_DIR, fixture_mode=True)


def test_start_reserves_the_retention_tombstone_namespace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reserved retention tombstone prefix"):
        EngineeringRun.start(
            CONTRACT,
            tmp_path / ".retention-delete-active-run",
            agents_dir=AGENTS_DIR,
            fixture_mode=True,
        )


def test_start_retry_preserves_an_expired_completed_run(run: EngineeringRun) -> None:
    import os
    from datetime import UTC, datetime

    state = run.run_dir / "run-state.json"
    payload = json.loads(state.read_text())
    payload["stage"] = "complete"
    state.write_text(json.dumps(payload))
    old = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    os.utime(state, (old, old))

    with pytest.raises(PmpeError, match="resume"):
        EngineeringRun.start(
            CONTRACT,
            run.run_dir,
            agents_dir=AGENTS_DIR,
            fixture_mode=True,
            retention_days=30,
            trusted_clock=lambda: datetime(2030, 1, 31, tzinfo=UTC),
        )

    assert state.exists()


def test_resume_preserves_state_and_appends_nothing(run: EngineeringRun) -> None:
    run.record_assessment({"summary": "fresh"})
    run.submit("v2-system-architect", _arch(run.contract_digest))
    before = len(run.ledger.read_all())

    resumed = EngineeringRun.load(run.run_dir)
    assert resumed.stage == "plan"
    assert resumed.contract_digest == run.contract_digest
    assert len(resumed.ledger.read_all()) == before

    # the resumed run continues exactly where the interrupted one stopped
    resumed.submit("v2-implementation-planner", _plan(resumed.contract_digest))
    assert resumed.stage == "route"


def test_resume_rejects_retention_changed_after_admission(run: EngineeringRun) -> None:
    state_path = run.run_dir / "run-state.json"
    state = json.loads(state_path.read_text())
    state["retention_days"] = 365
    state_path.write_text(json.dumps(state))

    with pytest.raises(PmpeError, match="retention policy changed"):
        EngineeringRun.load(run.run_dir)


def test_resume_authenticates_and_binds_pre_retention_run_before_release(
    run: EngineeringRun,
) -> None:
    from pmpe.contracts.digest import canonical_digest

    state_path = run.run_dir / "run-state.json"
    state = json.loads(state_path.read_text())
    state.pop("retention_days")
    state["stage"] = "deploy"
    state_path.write_text(json.dumps(state))
    events = run.ledger.read_all()
    first = events[0]
    first["output_digests"].pop("retention_policy")
    identity = {key: value for key, value in first.items() if key not in {"event_id", "ts"}}
    first["event_id"] = canonical_digest({**identity, "ts": first["ts"]})
    run.ledger.path.write_text("".join(json.dumps(event) + "\n" for event in events))

    resumed = EngineeringRun.load(run.run_dir)

    migrated_state = json.loads(state_path.read_text())
    assert migrated_state["retention_days"] == 30
    migration = next(
        event
        for event in resumed.ledger.read_all()
        if event["action"] == "bind_legacy_retention_policy"
    )
    assert migration["input_digests"]["contract"] == resumed.contract_digest
    resumed.record_release_report(
        "READY_FOR_PRODUCTION_APPROVAL",
        gate_results={"GATE-001": True, "GATE-002": True},
    )
    assert resumed.stage == "complete"
    terminal = resumed.ledger.read_all()[-1]
    assert terminal["output_digests"]["terminal_retention"].startswith("sha256:")


def test_resume_recovers_an_interrupted_legacy_retention_state_write(
    run: EngineeringRun,
) -> None:
    from pmpe.contracts.digest import canonical_digest
    from pmpe.privacy.retention import retention_policy_digest

    state_path = run.run_dir / "run-state.json"
    state = json.loads(state_path.read_text())
    state.pop("retention_days")
    state_path.write_text(json.dumps(state))
    events = run.ledger.read_all()
    first = events[0]
    first["output_digests"].pop("retention_policy")
    identity = {key: value for key, value in first.items() if key not in {"event_id", "ts"}}
    first["event_id"] = canonical_digest({**identity, "ts": first["ts"]})
    run.ledger.path.write_text("".join(json.dumps(event) + "\n" for event in events))
    run.ledger.record(
        stage="contract_lock",
        agent="pmpe-core",
        action="bind_legacy_retention_policy",
        input_digests={"contract": run.contract_digest},
        output_digests={"retention_policy": retention_policy_digest(30)},
        idempotency_key="legacy-retention-policy/v1",
    )
    before = run.ledger.read_all()

    resumed = EngineeringRun.load(run.run_dir)

    assert json.loads(state_path.read_text())["retention_days"] == 30
    assert resumed.ledger.read_all() == before


def test_resume_binds_completed_legacy_retention_and_preserves_completion_time(
    run: EngineeringRun,
    repo: Path,
) -> None:
    from datetime import datetime, timedelta

    from pmpe.contracts.digest import canonical_digest
    from pmpe.privacy.retention import RetentionController

    drive_to_deploy(run, repo)
    run.record_release_report(
        "READY_FOR_PRODUCTION_APPROVAL",
        gate_results={"GATE-001": True, "GATE-002": True},
    )
    state_path = run.run_dir / "run-state.json"
    state = json.loads(state_path.read_text())
    state.pop("retention_days")
    state_path.write_text(json.dumps(state))

    events = run.ledger.read_all()
    first = events[0]
    first["output_digests"].pop("retention_policy")
    report = events[-1]
    report["output_digests"].pop("terminal_retention")
    for event in (first, report):
        identity = {key: value for key, value in event.items() if key not in {"event_id", "ts"}}
        event["event_id"] = canonical_digest({**identity, "ts": event["ts"]})
    run.ledger.path.write_text("".join(json.dumps(event) + "\n" for event in events))

    resumed = EngineeringRun.load(run.run_dir)

    migrated = resumed.ledger.read_all()
    assert [event["action"] for event in migrated[-2:]] == [
        "bind_legacy_retention_policy",
        "bind_legacy_retention_completion",
    ]
    assert migrated[-1]["input_digests"] == {"completion_event": report["event_id"]}
    completed_at = datetime.fromisoformat(str(report["ts"]).replace("Z", "+00:00"))
    result = RetentionController().purge(
        run.run_dir.parent,
        now=completed_at + timedelta(days=31),
    )
    assert run.run_dir.name in result.deleted
    assert not run.run_dir.exists()


def test_resume_fails_closed_on_contract_mutation(run: EngineeringRun) -> None:
    contract_copy = run.run_dir / "contract.json"
    mutated = contract_copy.read_text().replace("Pinger", "Pinger-mutated")
    contract_copy.write_text(mutated)
    with pytest.raises(ContractViolation, match="mutated"):
        EngineeringRun.load(run.run_dir)


# --- admission ---------------------------------------------------------------------------


def test_out_of_stage_submission_is_rejected(run: EngineeringRun) -> None:
    run.record_assessment({"summary": "fresh"})
    with pytest.raises(SubmissionRejected, match="architecture"):
        run.submit("v2-implementation-planner", _plan(run.contract_digest))


def test_invalid_artifact_is_rejected_without_evidence(run: EngineeringRun) -> None:
    run.record_assessment({"summary": "fresh"})
    before = len(run.ledger.read_all())
    with pytest.raises(SubmissionRejected, match="binds contract"):
        run.submit("v2-system-architect", _arch("sha256:wrong"))
    assert len(run.ledger.read_all()) == before
    assert run.stage == "architecture"


def test_completed_stage_rejects_resubmission(run: EngineeringRun) -> None:
    run.record_assessment({"summary": "fresh"})
    run.submit("v2-system-architect", _arch(run.contract_digest))
    with pytest.raises(SubmissionRejected, match="plan"):
        run.submit("v2-system-architect", _arch(run.contract_digest))


# --- build phase -------------------------------------------------------------------------


def test_walk_to_review_emits_the_grammar(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    assert run.stage == "review"
    events = run.ledger.read_all()

    route = next(e for e in events if e["stage"] == "route")
    assert route["detail"] == "selected=v2-backend-engineer,v2-test-engineer"

    implement = [e for e in events if e["stage"] == "implement"]
    assert [(e["action"], e["detail"]) for e in implement] == [
        ("task_tests", "T-001"),
        ("task_implementation", "T-001"),
        ("task_tests", "T-002"),
        ("task_implementation", "T-002"),
    ]

    freeze = next(e for e in events if e["stage"] == "freeze")
    assert freeze["output_digests"]["candidate"] == candidate


# --- review round ------------------------------------------------------------------------


def test_review_round_reaches_reconcile(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    assert run.stage == "reconcile"

    events = run.ledger.read_all()
    submitted = [e for e in events if e["action"] == "submit_review"]
    clean = [e for e in events if e["action"] == "readonly_check" and e["verdict"] == "clean"]
    assert len(submitted) == 4 and len(clean) == 4
    assert all(e["input_digests"]["candidate"] == candidate for e in submitted)

    # findings were taken in under RF ids, originals preserved
    store = FindingsStore(run.run_dir)
    assert {f.finding_id for f in store.all()} == {"RF-001", "RF-002"}


def test_begin_review_fails_closed_on_a_tampered_candidate(run: EngineeringRun, repo: Path) -> None:
    """Reviews must bind to the tree that was frozen, not whatever is there now."""
    to_review(run, repo)
    (repo / "api.py").write_text("TAMPERED = True\n")
    with pytest.raises(CandidateViolation, match="changed after freeze"):
        run.begin_review("v2-code-reviewer", repo)


def test_deploy_with_repo_verifies_the_frozen_tree(run: EngineeringRun, repo: Path) -> None:
    drive_to_deploy(run, repo)
    run.deploy("local", repo=repo)  # matching tree: authorized
    (repo / "late.py").write_text("LATE = True\n")
    with pytest.raises(CandidateViolation, match="changed after freeze"):
        run.deploy("staging", repo=repo)


def test_reviewer_modification_fails_closed(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run.begin_review("v2-code-reviewer", repo)
    run.submit("v2-code-reviewer", _review("v2-code-reviewer", candidate, [_CODE_FINDING]))
    (repo / "api.py").write_text("TAMPERED = True\n")
    with pytest.raises(ReadOnlyViolation):
        run.end_review("v2-code-reviewer", repo)
    dirty = [e for e in run.ledger.read_all() if e["action"] == "readonly_check"]
    assert dirty and dirty[-1]["verdict"] != "clean"
    assert run.stage == "review"


# --- reconciliation ----------------------------------------------------------------------


def test_reconcile_undecided_blocks_without_advancing(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    result = run.reconcile_findings({}, owner="abhillash")
    assert result.undecided == ["RF-001"]
    assert run.stage == "reconcile"
    assert not [e for e in run.ledger.read_all() if e["stage"] == "reconcile"]


def test_reconcile_decides_creates_pcrs_and_enters_fix(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    result = run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    assert result.accepted == ["RF-001"]
    assert result.product_decisions == ["RF-002"]
    assert run.stage == "fix"

    pcrs = ChangeRequestStore(run.run_dir).list()
    assert len(pcrs) == 1 and pcrs[0].status == "OPEN"

    events = run.ledger.read_all()
    reconcile = next(e for e in events if e["action"] == "reconcile")
    assert reconcile["detail"] == "accepted=RF-001;product_decisions=RF-002"
    assert any(e["action"] == "change_request_created" for e in events)


def test_clean_reviews_still_require_the_executed_test_gate(
    run: EngineeringRun, repo: Path
) -> None:
    """A clean review round earns nothing by fiat: the retest gate runs on every path."""
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate, findings=False)
    result = run.reconcile_findings({}, owner="abhillash")
    assert not result.accepted and not result.undecided
    assert run.stage == "retest"
    run.record_gates(repo=repo, passed=True, detail="1/1 executed")
    assert run.stage == "draft_pr"  # nothing was fixed, so no refreeze/verify leg


def test_reviewer_resubmission_is_rejected(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run.begin_review("v2-code-reviewer", repo)
    run.submit("v2-code-reviewer", _review("v2-code-reviewer", candidate, [_CODE_FINDING]))
    with pytest.raises(SubmissionRejected, match="already"):
        run.submit("v2-code-reviewer", _review("v2-code-reviewer", candidate, [_CODE_FINDING]))
    assert len(FindingsStore(run.run_dir).all()) == 1  # no duplicate findings
    submits = [e for e in run.ledger.read_all() if e["action"] == "submit_review"]
    assert len(submits) == 1  # no duplicate evidence


def test_fix_recording_recovers_after_crash_between_store_and_state(
    run: EngineeringRun, repo: Path
) -> None:
    """The findings store landed the transition but run-state was never saved
    (crash window); resubmitting after resume completes the stage instead of
    deadlocking on the non-repeatable store transition."""
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    FindingsStore(run.run_dir).record_fixed(
        "RF-001", fixer="v2-approved-findings-fixer", commits=["fix1234"]
    )
    resumed = EngineeringRun.load(run.run_dir)
    resumed.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    assert resumed.stage == "retest"
    fix_events = [e for e in resumed.ledger.read_all() if e["action"] == "fix"]
    assert len(fix_events) == 0  # recovery adopts the store state, no phantom event


def test_verify_recording_recovers_after_crash_between_store_and_state(
    run: EngineeringRun, repo: Path
) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    run.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    run.record_gates(repo=repo, passed=True, detail="2/2 executed")
    run.freeze(repo)
    FindingsStore(run.run_dir).record_verified("RF-001", verifier="v2-code-reviewer")
    resumed = EngineeringRun.load(run.run_dir)
    resumed.record_fix_verification("RF-001", verifier="v2-code-reviewer")
    assert resumed.stage == "draft_pr"


# --- fix, retest, verify -----------------------------------------------------------------


def test_fixer_is_scoped_to_accepted_findings(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    with pytest.raises(SubmissionRejected, match="RF-002"):
        run.submit(
            "v2-approved-findings-fixer",
            {
                "fixed": [
                    {
                        "finding_id": "RF-002",
                        "commits": ["x"],
                        "checks_rerun": ["unit"],
                        "changed_files": ["api.py"],
                    }
                ]
            },
        )

    # PD-07's other half: the fix may only touch files the accepted findings name
    with pytest.raises(SubmissionRejected, match="outside the accepted-findings scope"):
        run.submit(
            "v2-approved-findings-fixer",
            {
                "fixed": [
                    {
                        "finding_id": "RF-001",
                        "commits": ["x"],
                        "checks_rerun": ["unit"],
                        "changed_files": ["api.py", "unrelated.py"],
                    }
                ]
            },
        )

    run.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    assert FindingsStore(run.run_dir).get("RF-001").status == "FIXED"
    assert run.stage == "retest"


def test_verifier_must_be_a_reviewer_and_not_the_fixer(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    run.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    run.record_gates(repo=repo, passed=True, detail="2/2 executed")
    run.freeze(repo)
    with pytest.raises(PmpeError):
        run.record_fix_verification("RF-001", verifier="v2-approved-findings-fixer")
    run.record_fix_verification("RF-001", verifier="v2-code-reviewer")
    assert FindingsStore(run.run_dir).get("RF-001").status == "VERIFIED"
    assert run.stage == "draft_pr"


# --- deployment ladder -------------------------------------------------------------------


def test_deploy_ladder_blocks_production_until_named_approval(
    run: EngineeringRun,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drive_to_deploy(run, repo)
    assert run.stage == "deploy"
    run.deploy("local", repo=repo)
    run.deploy("staging", repo=repo)

    before = len(run.ledger.read_all())
    with pytest.raises(DeploymentBlocked, match="approval"):
        run.deploy("production", repo=repo, health_verified=True, journey_verified=True)
    assert len(run.ledger.read_all()) == before  # a blocked deploy leaves no deploy event

    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    outcome = run.deploy("production", repo=repo, health_verified=True, journey_verified=True)
    assert "FIXTURE MODE" in outcome.report_line
    assert "no real environment" in outcome.report_line
    import pmpe.engineering.engine as engine_module

    sweeps: list[tuple[Path, Path | None]] = []

    def record_sweep(
        root: Path,
        *,
        trusted_clock: object,
        exclude_run_dir: Path | None = None,
    ) -> None:
        sweeps.append((root, exclude_run_dir))

    monkeypatch.setattr(engine_module, "purge_retained_runs", record_sweep)

    run.record_release_report(
        "READY_FOR_PRODUCTION_APPROVAL",
        gate_results={"GATE-001": True, "GATE-002": True},
    )
    assert run.stage == "complete"
    assert sweeps == [(run.run_dir.parent, run.run_dir)]


def test_every_deployment_path_verifies_candidate_integrity(
    run: EngineeringRun, repo: Path
) -> None:
    """Integrity verification has no opt-out: a drifted tree blocks EVERY
    environment, not only the ones a caller chose to verify."""
    drive_to_deploy(run, repo)
    (repo / "api.py").write_text("DRIFTED = True\n")
    LocalGitAdapter(repo).commit_all("late: unreviewed change")
    for environment in ("local", "staging", "production"):
        with pytest.raises(CandidateViolation, match="changed after freeze"):
            run.deploy(environment, repo=repo, health_verified=True, journey_verified=True)


def test_production_requires_readiness_attestations(run: EngineeringRun, repo: Path) -> None:
    """An approval alone is not enough: unattested health/journey checks block
    production before authorization is even considered."""
    drive_to_deploy(run, repo)
    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    with pytest.raises(DeploymentBlocked, match="readiness not met.*health"):
        run.deploy("production", repo=repo)  # attestations default to unverified
    with pytest.raises(DeploymentBlocked, match="user journey"):
        run.deploy("production", repo=repo, health_verified=True)
    outcome = run.deploy("production", repo=repo, health_verified=True, journey_verified=True)
    assert "FIXTURE MODE" in outcome.report_line


def test_production_requires_rollback_and_runnable_artifact(tmp_path: Path) -> None:
    """A workspace without rollback instructions and a runnable artifact can
    never be production-authorized, approval or not."""
    bare = tmp_path / "bare-workspace"
    bare.mkdir()
    git = LocalGitAdapter(bare)
    git.init()
    (bare / "api.py").write_text("STATUS = 'ok'\n")
    git.commit_all("chore: workspace without deploy collateral")
    run = EngineeringRun.start(
        CONTRACT, tmp_path / "bare-run", agents_dir=AGENTS_DIR, fixture_mode=True
    )
    drive_to_deploy(run, bare)
    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    with pytest.raises(DeploymentBlocked, match="ROLLBACK"):
        run.deploy("production", repo=bare, health_verified=True, journey_verified=True)


# --- release gates -------------------------------------------------------------------------


def test_release_report_refused_without_gate_evaluations(run: EngineeringRun, repo: Path) -> None:
    """The locked contract's binary release gates are product intent (PD-01):
    a release verdict with no gate evaluation is refused."""
    drive_to_deploy(run, repo)
    run.deploy("local", repo=repo)
    with pytest.raises(PmpeError, match="unevaluated: GATE-001, GATE-002"):
        run.record_release_report("READY_FOR_PRODUCTION_APPROVAL")
    assert run.stage == "deploy"  # nothing advanced


def test_release_report_refused_on_a_failed_gate(run: EngineeringRun, repo: Path) -> None:
    drive_to_deploy(run, repo)
    with pytest.raises(PmpeError, match="failed: GATE-002"):
        run.record_release_report(
            "READY_FOR_PRODUCTION_APPROVAL",
            gate_results={"GATE-001": True, "GATE-002": False},
        )
    with pytest.raises(PmpeError, match="unknown gate"):
        run.record_release_report(
            "READY_FOR_PRODUCTION_APPROVAL",
            gate_results={"GATE-001": True, "GATE-002": True, "GATE-999": True},
        )


def test_release_report_persists_the_gate_evaluation(run: EngineeringRun, repo: Path) -> None:
    drive_to_deploy(run, repo)
    run.record_release_report(
        "READY_FOR_PRODUCTION_APPROVAL",
        gate_results={"GATE-001": True, "GATE-002": True},
    )
    artifact = json.loads(
        (run.run_dir / "artifacts" / "release_report--gate-results.json").read_text()
    )
    assert artifact["gates"] == {"GATE-001": True, "GATE-002": True}
    report_event = next(e for e in run.ledger.read_all() if e["stage"] == "release_report")
    assert "GATE-001" in report_event["detail"] and "GATE-002" in report_event["detail"]


# --- executed evidence binds to the candidate ----------------------------------------------


def test_retest_evidence_must_cover_the_frozen_candidate(run: EngineeringRun, repo: Path) -> None:
    """On the no-fix path the tested tree must BE the frozen candidate — evidence
    for some other tree proves nothing about what ships."""
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate, findings=False)
    run.reconcile_findings({}, owner="abhillash")
    assert run.stage == "retest"
    (repo / "api.py").write_text("STATUS = 'ok'  # drifted before retest\n")
    LocalGitAdapter(repo).commit_all("late: unexplained change")
    with pytest.raises(CandidateViolation, match="no accepted fix explains"):
        run.record_gates(repo=repo, passed=True, detail="1/1 executed")


def test_refreeze_binds_to_the_retested_tree(run: EngineeringRun, repo: Path) -> None:
    """The candidate that ships must be exactly the tree the retest executed."""
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate)
    run.reconcile_findings(
        {"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect")},
        owner="abhillash",
    )
    run.submit(
        "v2-approved-findings-fixer",
        {
            "fixed": [
                {
                    "finding_id": "RF-001",
                    "commits": ["fix1234"],
                    "checks_rerun": ["unit"],
                    "changed_files": ["api.py"],
                }
            ]
        },
    )
    (repo / "api.py").write_text("STATUS = 'ok'  # fixed\n")
    LocalGitAdapter(repo).commit_all("fix: RF-001")
    run.record_gates(repo=repo, passed=True, detail="2/2 executed")
    (repo / "api.py").write_text("STATUS = 'ok'  # changed again after retest\n")
    LocalGitAdapter(repo).commit_all("late: post-retest change")
    with pytest.raises(CandidateViolation, match="retested tree"):
        run.freeze(repo)


def test_retest_ledger_event_records_the_tested_tree(run: EngineeringRun, repo: Path) -> None:
    candidate = to_review(run, repo)
    run_reviews(run, repo, candidate, findings=False)
    run.reconcile_findings({}, owner="abhillash")
    run.record_gates(repo=repo, passed=True, detail="1/1 executed")
    gates_event = next(e for e in run.ledger.read_all() if e["action"] == "gates")
    assert gates_event["input_digests"]["candidate"] == candidate
    assert gates_event["input_digests"]["tested_tree"] == candidate  # no-fix path: identical


def test_duplicate_fix_submission_is_rejected(run: EngineeringRun, repo: Path) -> None:
    """A second fixer submission for an already-FIXED finding is rejected loudly,
    not absorbed silently (the fix stage is still open for the other finding)."""
    second_finding = {
        **_CODE_FINDING,
        "title": "unvalidated path join",
        "file": "storage.py",
        "line": 7,
        "evidence": "storage.py:7 joins request input into a filesystem path",
    }
    candidate = to_review(run, repo)
    for reviewer, found in (
        ("v2-code-reviewer", [_CODE_FINDING]),
        ("v2-product-conformance-reviewer", []),
        ("v2-architecture-simplicity-reviewer", [second_finding]),
        ("v2-eval-integrity-auditor", []),
    ):
        run.begin_review(reviewer, repo)
        run.submit(reviewer, _review(reviewer, candidate, found))
        run.end_review(reviewer, repo)
    run.reconcile_findings(
        {
            "RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect"),
            "RF-002": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real defect"),
        },
        owner="abhillash",
    )
    fix_rf_001 = {
        "fixed": [
            {
                "finding_id": "RF-001",
                "commits": ["fix1234"],
                "checks_rerun": ["unit"],
                "changed_files": ["api.py"],
            }
        ]
    }
    run.submit("v2-approved-findings-fixer", fix_rf_001)
    assert run.stage == "fix"  # RF-002 still unfixed — the stage is open
    with pytest.raises(SubmissionRejected, match="already FIXED"):
        run.submit("v2-approved-findings-fixer", fix_rf_001)


# --- the whole trajectory ----------------------------------------------------------------


def test_full_run_ledger_is_trajectory_clean(run: EngineeringRun, repo: Path) -> None:
    drive_to_deploy(run, repo)
    run.deploy("local", repo=repo)
    run.deploy("staging", repo=repo)
    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    run.deploy("production", repo=repo, health_verified=True, journey_verified=True)
    run.record_release_report(
        "READY_FOR_PRODUCTION_APPROVAL",
        gate_results={"GATE-001": True, "GATE-002": True},
    )

    violations = evaluate_trajectory(run.ledger.read_all())
    assert violations == []


def test_ledger_events_carry_detail(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, run_id="r1")
    ledger.record(stage="route", agent="x", action="submit_routing", detail="selected=a,b")
    assert ledger.read_all()[0]["detail"] == "selected=a,b"
