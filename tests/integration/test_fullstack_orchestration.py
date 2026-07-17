"""Integrated V3 orchestration: the FullStackRun emits the extended ledger
grammar and enforces every full-stack gate fail-closed — journey before
frontend implementation, api-contract currency before freeze, unmocked
browser verification, verified digest-bound previews, the six-lens roster,
and per-run read-only proofs. The final pin: a complete happy-path ledger is
clean under BOTH the V2 and TRAJ-FS rule sets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.evals.trajectory import evaluate_trajectory
from pmpe.evals.trajectory_fullstack import evaluate_fullstack_trajectory
from pmpe.fullstack.journey import JourneyNotValidated
from pmpe.fullstack.orchestration import FullStackRun, OrchestrationViolation
from pmpe.fullstack.preview import record_preview
from pmpe.gitops.local import LocalGitAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
LENSES = (
    "v3-ux-journey-reviewer",
    "v3-frontend-accessibility-reviewer",
    "v3-backend-api-security-reviewer",
    "v3-architecture-simplicity-reviewer",
    "v3-product-conformance-reviewer",
    "v3-evidence-integrity-reviewer",
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "app.py").write_text("VALUE = 1\n")
    git.commit_all("feat: base")
    return root


def _start(tmp_path: Path) -> FullStackRun:
    return FullStackRun.start(CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR)


def _preview_evidence(path: Path, source_digest: str) -> Path:
    record_preview(
        path,
        source_digest=source_digest,
        deployment_kind="local_preview",
        artifacts={"frontend-next-build-id": "buildid"},
        journeys={"a11y": "passed", "keyboard": "passed", "journeys": "passed"},
        recorded_at="2026-07-17T00:00:00Z",
    )
    return path


def _drive_to_freeze(run: FullStackRun, repo: Path) -> None:
    run.validate_journey()
    run.record_architecture(agent="v2-system-architect", digest="sha256:archpack")
    run.record_plan(agent="v2-implementation-planner", digest="sha256:plan")
    run.record_routing(
        agent="v2-engineer-router", selected=("v2-backend-engineer", "v2-test-engineer")
    )
    run.record_implementation(
        agent="v2-test-engineer", action="task_tests", task="T-1", surface="backend"
    )
    run.record_implementation(
        agent="v2-backend-engineer", action="task_implementation", task="T-1", surface="backend"
    )
    run.record_implementation(
        agent="v2-test-engineer", action="task_tests", task="T-2", surface="frontend"
    )
    run.record_implementation(
        agent="v2-backend-engineer",
        action="task_implementation",
        task="T-2",
        surface="frontend",
    )
    run.record_api_contract(current=True)
    run.freeze(repo)


def test_start_refuses_a_non_runnable_contract(tmp_path: Path) -> None:
    draft = tmp_path / "draft.json"
    data = json.loads(CONTRACT.read_text())
    data["contract_status"] = "DRAFT"
    draft.write_text(json.dumps(data))
    with pytest.raises(OrchestrationViolation, match="runnable"):
        FullStackRun.start(draft, tmp_path / "run", agents_dir=AGENTS_DIR)


def test_start_locks_the_fullstack_contract_digest(tmp_path: Path) -> None:
    run = _start(tmp_path)
    events = run.events()
    assert events[0]["stage"] == "contract_lock"
    assert events[0]["output_digests"]["contract"] == run.contract_digest


def test_frontend_implementation_before_journey_is_refused(tmp_path: Path) -> None:
    run = _start(tmp_path)
    with pytest.raises(JourneyNotValidated):
        run.record_implementation(
            agent="v2-backend-engineer",
            action="task_implementation",
            task="T-FE",
            surface="frontend",
        )


def test_backend_implementation_is_allowed_before_journey(tmp_path: Path) -> None:
    run = _start(tmp_path)
    run.record_implementation(
        agent="v2-backend-engineer", action="task_implementation", task="T-BE", surface="backend"
    )
    assert any(e["stage"] == "implement" for e in run.events())


def test_freeze_requires_a_current_api_contract_verdict(tmp_path: Path, repo: Path) -> None:
    run = _start(tmp_path)
    run.validate_journey()
    with pytest.raises(OrchestrationViolation, match="api"):
        run.freeze(repo)


def test_api_drift_is_recorded_and_refused(tmp_path: Path) -> None:
    run = _start(tmp_path)
    with pytest.raises(OrchestrationViolation, match="drift"):
        run.record_api_contract(current=False)
    drift_events = [e for e in run.events() if e["stage"] == "api_contract"]
    assert drift_events and drift_events[0]["verdict"] == "drift"


def test_mocked_browser_verification_is_refused(tmp_path: Path, repo: Path) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    with pytest.raises(OrchestrationViolation, match="mock"):
        run.record_browser_verification(
            suites=("a11y", "keyboard", "responsive", "journeys"), mocked=True, passed=True
        )


def test_preview_evidence_is_verified_and_bound_to_the_candidate(
    tmp_path: Path, repo: Path
) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    evidence = _preview_evidence(tmp_path / "preview-evidence.json", "sha256:" + "s" * 64)
    run.record_preview(evidence, expected_source_digest="sha256:" + "s" * 64)
    event = next(e for e in run.events() if e["stage"] == "preview")
    assert event["input_digests"]["candidate"] == run.candidate_digest
    assert event["detail"] == "kind=local_preview"


def test_a_doctored_preview_is_refused(tmp_path: Path, repo: Path) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    evidence = _preview_evidence(tmp_path / "preview-evidence.json", "sha256:" + "s" * 64)
    with pytest.raises(OrchestrationViolation, match="preview"):
        run.record_preview(evidence, expected_source_digest="sha256:" + "x" * 64)


def test_release_requires_all_six_lenses(tmp_path: Path, repo: Path) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    run.record_browser_verification(
        suites=("a11y", "keyboard", "responsive", "journeys"), mocked=False, passed=True
    )
    evidence = _preview_evidence(tmp_path / "preview-evidence.json", "sha256:" + "s" * 64)
    run.record_preview(evidence, expected_source_digest="sha256:" + "s" * 64)
    for lens in LENSES[:5]:
        run.begin_review(lens, repo)
        run.end_review(lens, repo)
    with pytest.raises(OrchestrationViolation, match="lens"):
        run.release_report(verdict="PROCEED")


def test_a_reviewer_write_is_refused_and_recorded(tmp_path: Path, repo: Path) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    run.begin_review(LENSES[0], repo)
    (repo / "app.py").write_text("VALUE = 2\n")
    with pytest.raises(OrchestrationViolation, match="read-only"):
        run.end_review(LENSES[0], repo)
    verdicts = [
        e["verdict"] for e in run.events() if e["action"] == "readonly_check"
    ]
    assert "modified" in verdicts


def test_the_happy_path_ledger_is_clean_under_both_rule_sets(
    tmp_path: Path, repo: Path
) -> None:
    run = _start(tmp_path)
    _drive_to_freeze(run, repo)
    run.record_browser_verification(
        suites=("a11y", "keyboard", "responsive", "journeys"), mocked=False, passed=True
    )
    evidence = _preview_evidence(tmp_path / "preview-evidence.json", "sha256:" + "s" * 64)
    run.record_preview(evidence, expected_source_digest="sha256:" + "s" * 64)
    for lens in LENSES:
        run.begin_review(lens, repo)
        run.end_review(lens, repo)
    run.release_report(verdict="PROCEED")
    events = run.events()
    assert evaluate_fullstack_trajectory(events) == []
    assert evaluate_trajectory(events) == []  # the TRAJ-06 roster collision is resolved


def test_v2_ledgers_still_judge_identically(tmp_path: Path) -> None:
    """Extending the reviewer roster must not change any V2 verdict — v3
    agents never appear in V2 ledgers."""
    fixture = REPO_ROOT / "evals" / "fixtures" / "trajectory" / "good_run.jsonl"
    events = [json.loads(line) for line in fixture.read_text().splitlines() if line.strip()]
    assert evaluate_trajectory(events) == []
