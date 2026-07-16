"""The engineering run engine: a deterministic admission state machine (PD-11).

Agents propose artifacts; the engine validates them at admission, records
evidence-ledger events matching the trajectory grammar, and owns every stage
transition. The final test walks a full run and proves the ledger it leaves
behind is trajectory-clean — the engine and the trajectory evals agree on the
grammar by construction, not by coincidence.
"""

from __future__ import annotations

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
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "api.py").write_text("STATUS = 'ok'\n")
    git.commit_all("chore: base workspace")
    return root


@pytest.fixture()
def run(tmp_path: Path) -> EngineeringRun:
    return EngineeringRun.start(CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR)


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
    run.record_gates(passed=True, detail="2/2 executed")
    (repo / "api.py").write_text("STATUS = 'ok'  # input is never evaluated\n")
    LocalGitAdapter(repo).commit_all("fix: RF-001 remove eval of request input")
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
        EngineeringRun.start(CONTRACT, run.run_dir, agents_dir=AGENTS_DIR)


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
    run.record_gates(passed=True, detail="1/1 executed")
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
    run.record_gates(passed=True, detail="2/2 executed")
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
    run.record_gates(passed=True, detail="2/2 executed")
    run.freeze(repo)
    with pytest.raises(PmpeError):
        run.record_fix_verification("RF-001", verifier="v2-approved-findings-fixer")
    run.record_fix_verification("RF-001", verifier="v2-code-reviewer")
    assert FindingsStore(run.run_dir).get("RF-001").status == "VERIFIED"
    assert run.stage == "draft_pr"


# --- deployment ladder -------------------------------------------------------------------


def test_deploy_ladder_blocks_production_until_named_approval(
    run: EngineeringRun, repo: Path
) -> None:
    drive_to_deploy(run, repo)
    assert run.stage == "deploy"
    run.deploy("local")
    run.deploy("staging")

    before = len(run.ledger.read_all())
    with pytest.raises(DeploymentBlocked, match="approval"):
        run.deploy("production")
    assert len(run.ledger.read_all()) == before  # a blocked deploy leaves no deploy event

    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    outcome = run.deploy("production")
    assert "FIXTURE MODE" in outcome.report_line
    assert "no real environment" in outcome.report_line

    run.record_release_report("READY_FOR_PRODUCTION_APPROVAL")
    assert run.stage == "complete"


# --- the whole trajectory ----------------------------------------------------------------


def test_full_run_ledger_is_trajectory_clean(run: EngineeringRun, repo: Path) -> None:
    drive_to_deploy(run, repo)
    run.deploy("local")
    run.deploy("staging")
    run.approve_production(owner="abhillash", reason="pilot cohort launch")
    run.deploy("production")
    run.record_release_report("READY_FOR_PRODUCTION_APPROVAL")

    violations = evaluate_trajectory(run.ledger.read_all())
    assert violations == []


def test_ledger_events_carry_detail(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path, run_id="r1")
    ledger.record(stage="route", agent="x", action="submit_routing", detail="selected=a,b")
    assert ledger.read_all()[0]["detail"] == "selected=a,b"
