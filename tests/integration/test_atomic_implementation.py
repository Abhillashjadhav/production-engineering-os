from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.engineering.atomic import (
    AdmittedSlice,
    AtomicImplementationController,
    AtomicityViolation,
    IntegrationManifest,
    IssueCandidate,
    IssueRecord,
    MemoryRepositoryAdapter,
    PullRequestRecord,
    ReadyInvalidationSignal,
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


def _controller(
    tmp_path: Path, *, planning_commit_sha: str | None = None
) -> tuple[AtomicImplementationController, MemoryRepositoryAdapter]:
    adapter = MemoryRepositoryAdapter(
        repository="owner/repo",
        protected_base_sha=BASE_SHA,
        planning_commit_sha=planning_commit_sha,
    )
    controller = AtomicImplementationController(
        run_dir=tmp_path / "run",
        repository=adapter,
        expected_repository="owner/repo",
        expected_base_sha=BASE_SHA,
    )
    return controller, adapter


def _integrated_candidate(
    tmp_path: Path,
) -> tuple[
    AtomicImplementationController,
    MemoryRepositoryAdapter,
    Path,
    AdmittedSlice,
    IntegrationManifest,
    str,
]:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "src").mkdir()
    (root / "src" / "base.py").write_text("BASE = True\n")
    planning_sha = git.commit_all("base")
    controller, adapter = _controller(tmp_path, planning_commit_sha=planning_sha)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/",)), admitted=admitted
    )
    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as worktree:
        (worktree.path / "src" / "candidate.py").write_text("VALUE = 1\n")
        candidate_head = worktree.commit("implement candidate")
    controller.admit_specialist_commit(lease, root, commit_sha=candidate_head)
    return (
        controller,
        adapter,
        root,
        admitted,
        controller.integration_manifest(),
        candidate_head,
    )


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


def test_repository_effect_is_prejournaled_and_recovers_after_side_effect_crash(
    tmp_path: Path,
) -> None:
    class CrashOnceAdapter(MemoryRepositoryAdapter):
        fail_once = True

        def ensure_issue(self, candidate: IssueCandidate, *, idempotency_key: str) -> IssueRecord:
            issue = super().ensure_issue(candidate, idempotency_key=idempotency_key)
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("crash after remote issue creation")
            return issue

    adapter = CrashOnceAdapter(repository="owner/repo", protected_base_sha=BASE_SHA)
    controller = AtomicImplementationController(
        run_dir=tmp_path / "run",
        repository=adapter,
        expected_repository="owner/repo",
        expected_base_sha=BASE_SHA,
    )

    with pytest.raises(RuntimeError, match="crash after"):
        controller.admit_slice(_candidate())

    ledger = tmp_path / "run" / "repository-effects.jsonl"
    first = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [(event["action"], event["status"]) for event in first] == [("create_issue", "PLANNED")]

    admitted = AtomicImplementationController.load(
        tmp_path / "run", repository=adapter
    ).admit_slice(_candidate())
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert admitted.issue.number == 1
    assert len(adapter.issues) == 1
    assert events[1]["action"] == "create_issue"
    assert events[1]["status"] == "OBSERVED"


def test_repository_effect_ledger_tampering_fails_closed(tmp_path: Path) -> None:
    controller, adapter = _controller(tmp_path)
    controller.admit_slice(_candidate())
    ledger = tmp_path / "run" / "repository-effects.jsonl"
    lines = ledger.read_text().splitlines()
    event = json.loads(lines[0])
    event["subject_digest"] = "0" * 64
    lines[0] = json.dumps(event)
    ledger.write_text("\n".join(lines) + "\n")

    with pytest.raises(AtomicityViolation, match="ledger integrity"):
        AtomicImplementationController.load(tmp_path / "run", repository=adapter)


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
        controller._admit_specialist_result(
            lease,
            commit_sha="e" * 40,
            changed_paths=("src/backend/escape.py",),
            clean=True,
        )

    with pytest.raises(ValueError, match="belongs to"):
        SpecialistTask(
            task_id="T-bad",
            specialist="frontend-engineer",
            allowed_paths=("src/",),
            required_capability="backend",
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
    blocked_issue = controller.repository.issue(admitted.issue.number)
    blocked_pr = controller.repository.pull_request(admitted.pull_request.number)
    assert blocked_issue is not None and blocked_issue.blocked is True
    assert blocked_pr is not None and blocked_pr.blocked is True
    assert (
        AtomicImplementationController.load(
            tmp_path / "run", repository=controller.repository
        ).stop_evidence
        == stopped
    )
    with pytest.raises(AtomicityViolation, match="revoked"):
        controller._admit_specialist_result(
            lease,
            commit_sha="1" * 40,
            changed_paths=("src/pmpe/partial.py",),
            clean=True,
        )


def test_same_scope_reset_requires_exact_restore_and_fresh_plan_and_red(
    tmp_path: Path,
) -> None:
    controller, adapter = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    controller.cancel_all(
        reason="missing product truth",
        partial_paths=("src/partial.py",),
        current_tree_sha="f" * 40,
    )
    replacement = replace(_candidate(), test_plan_digest="d" * 64, meaningful_red_digest="e" * 64)

    with pytest.raises(AtomicityViolation, match="exact pre-code"):
        controller.readmit_after_product_input(replacement, restored_tree_sha="0" * 40)

    resumed = controller.readmit_after_product_input(
        replacement, restored_tree_sha=admitted.planning_commit.sha
    )

    assert resumed.issue.number == admitted.issue.number
    assert resumed.pull_request.number == admitted.pull_request.number
    assert resumed.planning_commit.sha != admitted.planning_commit.sha
    assert resumed.planning_commit.meaningful_red_digest == "e" * 64
    assert resumed.issue.blocked is False
    assert resumed.pull_request.blocked is False
    assert len(adapter.primary_pull_requests(admitted.issue.number)) == 1
    assert controller.integration_manifest().results == ()


def test_changed_outcome_or_closed_pr_cannot_reuse_same_primary_pr(tmp_path: Path) -> None:
    controller, adapter = _controller(tmp_path)
    admitted = controller.admit_slice(_candidate())
    controller.cancel_all(
        reason="product changed",
        partial_paths=(),
        current_tree_sha="f" * 40,
    )

    with pytest.raises(AtomicityViolation, match="new issue"):
        controller.readmit_after_product_input(
            replace(_candidate(), outcome="Different outcome"),
            restored_tree_sha=admitted.planning_commit.sha,
        )

    adapter.pull_requests[admitted.pull_request.number] = replace(
        admitted.pull_request, open=False, draft=False
    )
    with pytest.raises(AtomicityViolation, match="cannot be reused"):
        controller.readmit_after_product_input(
            replace(
                _candidate(),
                test_plan_digest="d" * 64,
                meaningful_red_digest="e" * 64,
            ),
            restored_tree_sha=admitted.planning_commit.sha,
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
    controller._admit_specialist_result(
        lease_b, commit_sha="2" * 40, changed_paths=("src/ui/x.ts",), clean=True
    )
    controller._admit_specialist_result(
        lease_a, commit_sha="3" * 40, changed_paths=("src/api/x.py",), clean=True
    )

    manifest = controller.integration_manifest()

    assert [result.task_id for result in manifest.results] == ["T-1", "T-2"]
    with pytest.raises(AtomicityViolation, match="already has"):
        controller._admit_specialist_result(
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
    planning_sha = git.commit_all("base")
    controller, _ = _controller(tmp_path, planning_commit_sha=planning_sha)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/",)),
        admitted=admitted,
    )

    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as worktree:
        first_branch = worktree.branch
        (worktree.path / "src" / "allowed.py").write_text("VALUE = 2\n")
        commit_sha = worktree.commit("implement T-1")

    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as retry:
        assert retry.branch != first_branch

    assert (root / "src" / "allowed.py").read_text() == "VALUE = 1\n"
    result = controller.admit_specialist_commit(lease, root, commit_sha=commit_sha)
    assert result.changed_paths == ("src/allowed.py",)


def test_specialist_commit_must_descend_from_exact_lease_baseline(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "src").mkdir()
    (root / "src" / "allowed.py").write_text("VALUE = 1\n")
    planning_sha = git.commit_all("base")
    unrelated = git._run("commit-tree", git._run("write-tree"), "-m", "unrelated")
    controller, _ = _controller(tmp_path, planning_commit_sha=planning_sha)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/",)), admitted=admitted
    )

    assert not hasattr(controller, "admit_specialist_result")
    with pytest.raises(AtomicityViolation, match="does not descend"):
        controller.admit_specialist_commit(lease, root, commit_sha=unrelated)


def test_specialist_admission_diffs_full_range_from_lease_baseline(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "src").mkdir()
    (root / "src" / "allowed.py").write_text("VALUE = 1\n")
    planning_sha = git.commit_all("base")
    controller, _ = _controller(tmp_path, planning_commit_sha=planning_sha)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-1", "v2-backend-engineer", ("src/",)), admitted=admitted
    )
    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as worktree:
        (worktree.path / "docs").mkdir()
        (worktree.path / "docs" / "escape.md").write_text("outside\n")
        worktree.commit("out of scope first commit")
        (worktree.path / "src" / "allowed.py").write_text("VALUE = 2\n")
        tip = worktree.commit("allowed tip")

    with pytest.raises(AtomicityViolation, match="outside the lease"):
        controller.admit_specialist_commit(lease, root, commit_sha=tip)


def test_cancellation_removes_active_worktree_after_preserving_dirty_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "src").mkdir()
    (root / "src" / "partial.py").write_text("VALUE = 1\n")
    planning_sha = git.commit_all("base")
    controller, _ = _controller(tmp_path, planning_commit_sha=planning_sha)
    admitted = controller.admit_slice(_candidate())
    lease = controller.issue_lease(
        SpecialistTask("T-stop", "v2-backend-engineer", ("src/",)),
        admitted=admitted,
    )

    with controller.specialist_worktree(
        root, lease=lease, worktrees_root=tmp_path / "worktrees"
    ) as worktree:
        path = worktree.path
        (path / "src" / "partial.py").write_text("VALUE = 2\n")
        stopped = controller.cancel_all(
            reason="contradictory product truth",
            partial_paths=(),
            current_tree_sha=planning_sha,
        )
        assert not path.exists()

    assert stopped.partial_paths == ("src/partial.py",)
    assert stopped.workers_stopped is True
    assert stopped.active_leases == 0


def test_ready_and_dequeue_are_exact_head_governed_effects(tmp_path: Path) -> None:
    controller, adapter, repo, admitted, manifest, head = _integrated_candidate(tmp_path)
    published = controller.publish_candidate(
        repo=repo,
        manifest=manifest,
        candidate_head_sha=head,
        verification_digest="d" * 64,
    )
    assert published.draft is True
    assert published.head_sha == head
    assert manifest.digest in published.body

    with pytest.raises(AtomicityViolation, match="published integrated"):
        controller.mark_ready(
            pr_number=published.number,
            exact_head_sha=admitted.planning_commit.sha,
            base_sha=BASE_SHA,
            policy_digest="1" * 64,
            toolchain_digest="2" * 64,
            prospective_tree_digest="3" * 64,
            checks_digest="5" * 64,
            advisory_review_digest="6" * 64,
            blocking_findings=(),
            authorization_digest="7" * 64,
        )

    ready = controller.mark_ready(
        pr_number=admitted.pull_request.number,
        exact_head_sha=head,
        base_sha=BASE_SHA,
        policy_digest="1" * 64,
        toolchain_digest="2" * 64,
        prospective_tree_digest="3" * 64,
        checks_digest="5" * 64,
        advisory_review_digest="6" * 64,
        blocking_findings=(),
        authorization_digest="7" * 64,
    )
    assert ready.draft is False

    bot_finding = ReadyInvalidationSignal(
        kind="blocking_finding",
        source="security-bot",
        exact_head_sha=head,
        evidence_digest="8" * 64,
        trace_digest="0" * 64,
        credible=True,
        authenticated=True,
        blocking=True,
        reviewer_eligible=False,
    )
    dequeued = controller.invalidate_ready(
        pr_number=ready.number,
        signal=bot_finding,
        authorization_digest="9" * 64,
    )
    assert dequeued.draft is True
    assert adapter.invalidated_approvals == [ready.number]
    with pytest.raises(AtomicityViolation, match="repair cycle"):
        controller.issue_lease(
            SpecialistTask("T-fix", "v2-backend-engineer", ("src/",)),
            admitted=controller.admitted_slice,
        )
    controller.begin_repair_cycle(
        exact_head_sha=head,
        finding_inventory_digest="a" * 64,
        repair_test_plan_digest="b" * 64,
        meaningful_red_digest="c" * 64,
    )
    repair_lease = controller.issue_lease(
        SpecialistTask("T-fix", "v2-backend-engineer", ("src/",)),
        admitted=controller.admitted_slice,
    )
    assert repair_lease.baseline_sha == head


def test_candidate_publication_requires_exact_manifest_history_and_content(
    tmp_path: Path,
) -> None:
    controller, _, repo, _, manifest, head = _integrated_candidate(tmp_path)
    git = LocalGitAdapter(repo)
    baseline_tree = git._run("rev-parse", f"{manifest.baseline_sha}^{{tree}}")
    reverted = git._run("commit-tree", baseline_tree, "-p", head, "-m", "revert result")

    with pytest.raises(AtomicityViolation, match="differs from the integration manifest"):
        controller.publish_candidate(
            repo=repo,
            manifest=manifest,
            candidate_head_sha=reverted,
            verification_digest="d" * 64,
        )

    unrelated = git._run("commit-tree", baseline_tree, "-m", "unrelated")
    with pytest.raises(AtomicityViolation, match="not bound"):
        controller.publish_candidate(
            repo=repo,
            manifest=manifest,
            candidate_head_sha=unrelated,
            verification_digest="d" * 64,
        )


def test_ready_invalidation_rejects_untraceable_or_nonblocking_signal(tmp_path: Path) -> None:
    with pytest.raises(AtomicityViolation, match="credible authenticated blocking"):
        controller, _, repo, _, manifest, head = _integrated_candidate(tmp_path)
        published = controller.publish_candidate(
            repo=repo,
            manifest=manifest,
            candidate_head_sha=head,
            verification_digest="f" * 64,
        )
        ready = controller.mark_ready(
            pr_number=published.number,
            exact_head_sha=published.head_sha,
            base_sha=BASE_SHA,
            policy_digest="1" * 64,
            toolchain_digest="2" * 64,
            prospective_tree_digest="3" * 64,
            checks_digest="4" * 64,
            advisory_review_digest="5" * 64,
            blocking_findings=(),
            authorization_digest="6" * 64,
        )
        controller.invalidate_ready(
            pr_number=ready.number,
            signal=ReadyInvalidationSignal(
                kind="required_check_drift",
                source="ci",
                exact_head_sha=ready.head_sha,
                evidence_digest="7" * 64,
                trace_digest="8" * 64,
                credible=True,
                authenticated=False,
                blocking=True,
                check_state="pending",
            ),
            authorization_digest="9" * 64,
        )


def test_candidate_ready_and_dequeue_adopt_observed_effect_after_state_save_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, adapter, repo, admitted, manifest, head = _integrated_candidate(tmp_path)

    def crash_state_save() -> None:
        raise RuntimeError("state save crash")

    monkeypatch.setattr(controller, "_save", crash_state_save)
    with pytest.raises(RuntimeError, match="state save crash"):
        controller.publish_candidate(
            repo=repo,
            manifest=manifest,
            candidate_head_sha=head,
            verification_digest="f" * 64,
        )

    resumed = AtomicImplementationController.load(tmp_path / "run", repository=adapter)
    published = resumed.publish_candidate(
        repo=repo,
        manifest=manifest,
        candidate_head_sha=head,
        verification_digest="f" * 64,
    )

    def mark_ready(target: AtomicImplementationController) -> PullRequestRecord:
        return target.mark_ready(
            pr_number=published.number,
            exact_head_sha=head,
            base_sha=BASE_SHA,
            policy_digest="1" * 64,
            toolchain_digest="2" * 64,
            prospective_tree_digest="3" * 64,
            checks_digest="4" * 64,
            advisory_review_digest="5" * 64,
            blocking_findings=(),
            authorization_digest="6" * 64,
        )

    def crash_ready_save() -> None:
        raise RuntimeError("ready save crash")

    monkeypatch.setattr(resumed, "_save", crash_ready_save)
    with pytest.raises(RuntimeError, match="ready save crash"):
        mark_ready(resumed)

    resumed = AtomicImplementationController.load(tmp_path / "run", repository=adapter)
    with pytest.raises(AtomicityViolation):
        resumed.mark_ready(
            pr_number=published.number,
            exact_head_sha=head,
            base_sha=BASE_SHA,
            policy_digest="1" * 64,
            toolchain_digest="2" * 64,
            prospective_tree_digest="3" * 64,
            checks_digest="4" * 64,
            advisory_review_digest="5" * 64,
            blocking_findings=(),
            authorization_digest="0" * 64,
        )
    ready = mark_ready(resumed)
    signal = ReadyInvalidationSignal(
        kind="required_check_drift",
        source="ci",
        exact_head_sha=head,
        evidence_digest="7" * 64,
        trace_digest="8" * 64,
        credible=True,
        authenticated=True,
        blocking=True,
        check_state="failed",
    )

    def crash_draft_save() -> None:
        raise RuntimeError("draft save crash")

    monkeypatch.setattr(resumed, "_save", crash_draft_save)
    with pytest.raises(RuntimeError, match="draft save crash"):
        resumed.invalidate_ready(
            pr_number=ready.number, signal=signal, authorization_digest="9" * 64
        )

    resumed = AtomicImplementationController.load(tmp_path / "run", repository=adapter)
    with pytest.raises(AtomicityViolation):
        resumed.invalidate_ready(
            pr_number=ready.number,
            signal=replace(signal, source="different-source"),
            authorization_digest="9" * 64,
        )
    draft = resumed.invalidate_ready(
        pr_number=ready.number, signal=signal, authorization_digest="9" * 64
    )
    assert draft.draft is True
    assert len(adapter.primary_pull_requests(admitted.issue.number)) == 1
