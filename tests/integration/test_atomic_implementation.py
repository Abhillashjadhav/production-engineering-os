from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pmpe.engineering.atomic import (
    AtomicImplementationController,
    AtomicityViolation,
    IssueCandidate,
    MemoryRepositoryAdapter,
    SpecialistTask,
)

from pmpe.gitops.local import LocalGitAdapter

BASE_SHA = "a" * 40
PLAN_DIGEST = "b" * 64
RED_DIGEST = "c" * 64


def _candidate() -> IssueCandidate:
    return IssueCandidate(
        key="contract-17",
        title="Implement contract 17",
        outcome="One atomic implementation slice",
        test_plan_digest=PLAN_DIGEST,
        meaningful_red_digest=RED_DIGEST,
    )


def _controller(tmp_path: Path) -> tuple[AtomicImplementationController, MemoryRepositoryAdapter]:
    adapter = MemoryRepositoryAdapter(repository="owner/repo", protected_base_sha=BASE_SHA)
    controller = AtomicImplementationController(
        run_dir=tmp_path / "run",
        repository=adapter,
        expected_repository="owner/repo",
        expected_base_sha=BASE_SHA,
    )
    return controller, adapter


def test_fresh_slice_is_issue_first_and_opens_one_atomic_draft_pr(tmp_path: Path) -> None:
    controller, adapter = _controller(tmp_path)

    admitted = controller.admit_slice(_candidate())

    assert [effect.action for effect in adapter.effects] == [
        "create_issue",
        "create_branch",
        "create_planning_commit",
        "create_draft_pr",
    ]
    assert admitted.issue.ready is True
    assert admitted.branch.base_sha == BASE_SHA
    assert admitted.planning_commit.test_only is True
    assert admitted.pull_request.draft is True
    assert admitted.pull_request.issue_number == admitted.issue.number
    assert "Outcome" in admitted.pull_request.body
    assert "Tests / evidence" in admitted.pull_request.body
    assert "Risks" in admitted.pull_request.body
    assert "Rollback" in admitted.pull_request.body
    assert not hasattr(adapter, "merge_pull_request")


def test_matching_crash_recovery_reuses_every_repository_effect(tmp_path: Path) -> None:
    controller, adapter = _controller(tmp_path)
    first = controller.admit_slice(_candidate())
    effect_count = len(adapter.effects)

    resumed = AtomicImplementationController.load(tmp_path / "run", repository=adapter).admit_slice(
        _candidate()
    )

    assert resumed == first
    assert len(adapter.effects) == effect_count


@pytest.mark.parametrize("field", ["issue", "branch", "base", "pull_request"])
def test_mismatched_or_duplicate_repository_state_fails_closed(tmp_path: Path, field: str) -> None:
    controller, adapter = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    if field == "issue":
        adapter.issues[admitted.issue.number] = replace(admitted.issue, key="other")
    elif field == "branch":
        adapter.branches[admitted.branch.name] = replace(admitted.branch, issue_number=999)
    elif field == "base":
        adapter.branches[admitted.branch.name] = replace(admitted.branch, base_sha="d" * 40)
    else:
        adapter.add_duplicate_primary_pr(admitted.issue.number)

    with pytest.raises(AtomicityViolation):
        AtomicImplementationController.load(tmp_path / "run", repository=adapter).admit_slice(
            _candidate()
        )


def test_implementation_lease_requires_red_and_scopes_task_and_paths(tmp_path: Path) -> None:
    controller, _ = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    task = SpecialistTask(
        task_id="T-2",
        specialist="frontend-engineer",
        allowed_paths=("src/ui/", "tests/ui/"),
    )

    lease = controller.issue_lease(task, admitted=admitted)

    assert lease.task == task
    assert lease.revoked is False
    assert lease.lease_epoch_digest
    with pytest.raises(AtomicityViolation, match="outside the lease"):
        controller.admit_specialist_result(
            lease,
            commit_sha="e" * 40,
            changed_paths=("src/backend/escape.py",),
            clean=True,
        )


def test_cancellation_freezes_partial_work_and_blocks_candidate_admission(
    tmp_path: Path,
) -> None:
    controller, _ = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/pmpe/",)),
        admitted=admitted,
    )

    stopped = controller.cancel_all(
        reason="product input contradicted",
        partial_paths=("src/pmpe/partial.py",),
        current_tree_sha="f" * 40,
    )

    assert stopped.workers_stopped is True
    assert stopped.active_leases == 0
    assert stopped.partial_output_admissible is False
    assert stopped.baseline_tree_sha == admitted.planning_commit.sha
    with pytest.raises(AtomicityViolation, match="revoked"):
        controller.admit_specialist_result(
            lease,
            commit_sha="1" * 40,
            changed_paths=("src/pmpe/partial.py",),
            clean=True,
        )


def test_integration_is_deterministic_and_rejects_duplicate_task_results(
    tmp_path: Path,
) -> None:
    controller, _ = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    task_b = SpecialistTask("T-2", "frontend-engineer", ("src/ui/",))
    task_a = SpecialistTask("T-1", "v2-backend-engineer", ("src/api/",))
    lease_b = controller.issue_lease(task_b, admitted=admitted)
    lease_a = controller.issue_lease(task_a, admitted=admitted)
    controller.admit_specialist_result(
        lease_b, commit_sha="2" * 40, changed_paths=("src/ui/x.ts",), clean=True
    )
    controller.admit_specialist_result(
        lease_a, commit_sha="3" * 40, changed_paths=("src/api/x.py",), clean=True
    )

    manifest = controller.integration_manifest()

    assert [result.task_id for result in manifest.results] == ["T-1", "T-2"]
    with pytest.raises(AtomicityViolation, match="already has"):
        controller.admit_specialist_result(
            lease_a,
            commit_sha="4" * 40,
            changed_paths=("src/api/y.py",),
            clean=True,
        )


def test_real_worktree_enforces_allowlist_and_preserves_main(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "src").mkdir()
    (root / "src" / "allowed.py").write_text("VALUE = 1\n")
    git.commit_all("base")
    controller, _ = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/",)),
        admitted=admitted,
    )

    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as worktree:
        (worktree.path / "src" / "allowed.py").write_text("VALUE = 2\n")
        commit_sha = worktree.commit("implement T-1")

    assert (root / "src" / "allowed.py").read_text() == "VALUE = 1\n"
    result = controller.admit_specialist_commit(lease, root, commit_sha=commit_sha)
    assert result.changed_paths == ("src/allowed.py",)


def test_ready_and_dequeue_are_exact_head_governed_effects(tmp_path: Path) -> None:
    controller, adapter = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    head = admitted.planning_commit.sha

    ready = controller.mark_ready(
        pr_number=admitted.pull_request.number,
        exact_head_sha=head,
        checks_digest="5" * 64,
        advisory_review_digest="6" * 64,
        blocking_findings=(),
        authorization_digest="7" * 64,
    )
    assert ready.draft is False

    dequeued = controller.invalidate_ready(
        pr_number=ready.number,
        observed_head_sha=head,
        finding_digest="8" * 64,
        authorization_digest="9" * 64,
    )
    assert dequeued.draft is True
    assert adapter.invalidated_approvals == [ready.number]
