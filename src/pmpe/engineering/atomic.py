"""Issue-first, atomic repository orchestration for implementation work.

The controller is deliberately narrower than a GitHub SDK.  It owns ordering,
identity, idempotency, specialist leases, and evidence.  A repository adapter
owns external effects, but its interface intentionally has no approval or merge
operation.  Production adapters can therefore be released only by the lifecycle
mutation authority while tests use the deterministic in-memory adapter below.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from threading import RLock, local
from types import TracebackType
from typing import Protocol, TypeVar

from pmpe.agents.router import ALL_PROFILES, SPECIALIST_PROFILES
from pmpe.domain.errors import GitError
from pmpe.domain.serialize import atomic_write_json
from pmpe.engineering.worktree import SpecialistWorktree, specialist_worktree
from pmpe.gitops.local import LocalGitAdapter
from pmpe.workflows.locking import exclusive_file_lock

_SHA40 = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATE_FILE = "atomic-implementation.json"
_EFFECT_LEDGER = "repository-effects.jsonl"
_ACTIVE_WORKTREES_FILE = "active-worktrees.json"
_RUN_LOCK_FILE = "atomic-implementation.lock"
_T = TypeVar("_T")
_RUN_LOCKS_GUARD = RLock()


class _ReentrantRunLock:
    """Serialize one run across threads and OS processes, including nested calls."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._thread_lock = RLock()
        self._thread_state = local()

    def __enter__(self) -> _ReentrantRunLock:
        self._thread_lock.acquire()
        depth = int(getattr(self._thread_state, "depth", 0))
        if depth == 0:
            file_lock = exclusive_file_lock(self._path)
            try:
                file_lock.__enter__()
            except BaseException:
                self._thread_lock.release()
                raise
            self._thread_state.file_lock = file_lock
        self._thread_state.depth = depth + 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        depth = int(self._thread_state.depth)
        try:
            if depth == 1:
                file_lock: AbstractContextManager[None] = self._thread_state.file_lock
                try:
                    file_lock.__exit__(exc_type, exc, traceback)
                finally:
                    del self._thread_state.file_lock
                    del self._thread_state.depth
            else:
                self._thread_state.depth = depth - 1
        finally:
            self._thread_lock.release()


_RUN_LOCKS: dict[Path, _ReentrantRunLock] = {}


class AtomicityViolation(RuntimeError):  # noqa: N818 - policy outcome vocabulary
    """Repository state or specialist output violates the admitted atomic slice."""


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_sha(value: str, *, field: str) -> None:
    if not _SHA40.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase 40-character commit SHA")


def _require_digest(value: str, *, field: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("issue key must contain a branch-safe character")
    return slug[:48]


def _paths_touched_between(git: LocalGitAdapter, baseline_sha: str, tip_sha: str) -> set[str]:
    return {
        line
        for revision in _commits_between(git, baseline_sha, tip_sha)
        for line in git._run(  # noqa: SLF001 - inspect each commit, including merge parents
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-m",
            revision,
            "--",
        ).splitlines()
        if line
    }


def _commits_between(git: LocalGitAdapter, baseline_sha: str, tip_sha: str) -> tuple[str, ...]:
    return tuple(
        line
        for line in git._run(  # noqa: SLF001 - exact reachable history is admission evidence
            "rev-list", "--reverse", f"{baseline_sha}..{tip_sha}"
        ).splitlines()
        if line
    )


def _active_worktree_lock(run_dir: Path) -> _ReentrantRunLock:
    key = run_dir.resolve()
    with _RUN_LOCKS_GUARD:
        return _RUN_LOCKS.setdefault(key, _ReentrantRunLock(key / _RUN_LOCK_FILE))


@dataclass(frozen=True)
class IssueCandidate:
    key: str
    title: str
    outcome: str
    test_plan_digest: str
    meaningful_red_digest: str

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.title.strip() or not self.outcome.strip():
            raise ValueError("issue candidate identity, title, and outcome are required")
        _require_digest(self.test_plan_digest, field="test_plan_digest")
        _require_digest(self.meaningful_red_digest, field="meaningful_red_digest")

    @property
    def digest(self) -> str:
        return _canonical_digest(asdict(self))


@dataclass(frozen=True)
class IssueRecord:
    number: int
    key: str
    title: str
    outcome: str
    ready: bool
    open: bool = True
    blocked: bool = False


@dataclass(frozen=True)
class BranchRecord:
    name: str
    base_sha: str
    issue_number: int


@dataclass(frozen=True)
class PlanningCommitRecord:
    sha: str
    branch: str
    issue_number: int
    test_plan_digest: str
    meaningful_red_digest: str
    test_only: bool


@dataclass(frozen=True)
class PullRequestRecord:
    number: int
    issue_number: int
    branch: str
    base_sha: str
    head_sha: str
    title: str
    body: str
    draft: bool
    open: bool = True
    blocked: bool = False


@dataclass(frozen=True)
class RepositoryEffect:
    sequence: int
    action: str
    idempotency_key: str
    subject_digest: str
    result_digest: str


@dataclass(frozen=True)
class AdmittedSlice:
    candidate_digest: str
    issue: IssueRecord
    branch: BranchRecord
    planning_commit: PlanningCommitRecord
    pull_request: PullRequestRecord


@dataclass(frozen=True)
class SpecialistTask:
    task_id: str
    specialist: str
    allowed_paths: tuple[str, ...]
    required_capability: str = ""

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.specialist.strip():
            raise ValueError("specialist task identity is incomplete")
        if not self.allowed_paths:
            raise ValueError("specialist task must allow at least one path")
        if self.specialist not in ALL_PROFILES:
            raise ValueError(f"unknown specialist profile: {self.specialist}")
        if self.required_capability:
            expected = SPECIALIST_PROFILES.get(self.required_capability)
            if expected is None:
                raise ValueError(f"unknown required capability: {self.required_capability}")
            if expected != self.specialist:
                raise ValueError(
                    f"capability {self.required_capability} belongs to {expected}, "
                    f"not {self.specialist}"
                )
        for raw in self.allowed_paths:
            _normalize_allowed_path(raw)


@dataclass(frozen=True)
class SpecialistLease:
    task: SpecialistTask
    admitted_candidate_digest: str
    baseline_sha: str
    lease_epoch_digest: str
    repair_admission_digest: str = ""
    revoked: bool = False


@dataclass(frozen=True)
class SpecialistResult:
    task_id: str
    specialist: str
    commit_sha: str
    changed_paths: tuple[str, ...]
    lease_epoch_digest: str
    admission_digest: str = ""


def _specialist_result_admission_digest(
    lease: SpecialistLease,
    *,
    commit_sha: str,
    changed_paths: Sequence[str],
) -> str:
    return _canonical_digest(
        {
            "task": lease.task.task_id,
            "specialist": lease.task.specialist,
            "lease_epoch": lease.lease_epoch_digest,
            "commit": commit_sha,
            "changed_paths": list(changed_paths),
        }
    )


def _specialist_result_admission_key(lease: SpecialistLease) -> str:
    return f"specialist:{lease.task.task_id}:{lease.lease_epoch_digest}:admit-result"


def _specialist_lease_admission_digest(lease: SpecialistLease) -> str:
    return _canonical_digest(
        {
            "task": asdict(lease.task),
            "candidate": lease.admitted_candidate_digest,
            "baseline": lease.baseline_sha,
            "lease_epoch": lease.lease_epoch_digest,
            "repair_admission": lease.repair_admission_digest,
        }
    )


def _specialist_lease_admission_key(lease: SpecialistLease) -> str:
    return f"specialist:{lease.task.task_id}:{lease.lease_epoch_digest}:issue-lease"


@dataclass(frozen=True)
class IntegrationManifest:
    baseline_sha: str
    results: tuple[SpecialistResult, ...]
    digest: str


@dataclass(frozen=True)
class WorkStopEvidence:
    reason: str
    workers_stopped: bool
    active_leases: int
    partial_output_admissible: bool
    baseline_tree_sha: str
    current_tree_sha: str
    partial_paths: tuple[str, ...]
    lease_epoch_digest: str
    revocation_digest: str


@dataclass(frozen=True)
class RepositoryBlockRecord:
    issue: IssueRecord
    pull_request: PullRequestRecord
    evidence_digest: str


@dataclass(frozen=True)
class ReadyInvalidationSignal:
    kind: str
    source: str
    exact_head_sha: str
    evidence_digest: str
    trace_digest: str
    credible: bool
    authenticated: bool
    blocking: bool
    reviewer_eligible: bool = False
    check_state: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {
            "blocking_finding",
            "required_check_drift",
            "head_drift",
            "base_or_policy_drift",
        }:
            raise ValueError("unsupported ready invalidation kind")
        if not self.source.strip():
            raise ValueError("ready invalidation source is required")
        _require_sha(self.exact_head_sha, field="exact_head_sha")
        _require_digest(self.evidence_digest, field="evidence_digest")
        _require_digest(self.trace_digest, field="trace_digest")
        if self.kind == "required_check_drift" and self.check_state not in {
            "stale",
            "revoked",
            "pending",
            "failed",
        }:
            raise ValueError("required-check drift needs a non-passing check state")


class AtomicRepositoryAdapter(Protocol):
    """External repository seam.  Approval and merge are intentionally absent."""

    @property
    def repository_name(self) -> str: ...

    @property
    def protected_base_sha(self) -> str: ...

    def ensure_issue(self, candidate: IssueCandidate, *, idempotency_key: str) -> IssueRecord: ...

    def issue(self, number: int) -> IssueRecord | None: ...

    def ensure_branch(
        self,
        *,
        name: str,
        base_sha: str,
        issue_number: int,
        idempotency_key: str,
    ) -> BranchRecord: ...

    def branch(self, name: str) -> BranchRecord | None: ...

    def ensure_planning_commit(
        self,
        *,
        branch: BranchRecord,
        candidate: IssueCandidate,
        idempotency_key: str,
    ) -> PlanningCommitRecord: ...

    def planning_commit(self, sha: str) -> PlanningCommitRecord | None: ...

    def ensure_draft_pr(
        self,
        *,
        issue: IssueRecord,
        branch: BranchRecord,
        planning_commit: PlanningCommitRecord,
        body: str,
        idempotency_key: str,
    ) -> PullRequestRecord: ...

    def primary_pull_requests(self, issue_number: int) -> tuple[PullRequestRecord, ...]: ...

    def pull_request(self, number: int) -> PullRequestRecord | None: ...

    def block_slice(
        self,
        *,
        issue_number: int,
        pr_number: int,
        exact_head_sha: str,
        reason: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> RepositoryBlockRecord: ...

    def unblock_slice(
        self,
        *,
        issue_number: int,
        pr_number: int,
        exact_head_sha: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> RepositoryBlockRecord: ...

    def update_draft_pr(
        self,
        *,
        number: int,
        expected_head_sha: str,
        candidate_head_sha: str,
        body: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord: ...

    def mark_ready(
        self,
        *,
        number: int,
        exact_head_sha: str,
        evidence_digest: str,
        authorization_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord: ...

    def convert_to_draft(
        self,
        *,
        number: int,
        exact_head_sha: str,
        evidence_digest: str,
        authorization_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord: ...


class MemoryRepositoryAdapter:
    """Deterministic repository used for executable policy and crash tests."""

    def __init__(
        self,
        *,
        repository: str,
        protected_base_sha: str,
        planning_commit_sha: str | None = None,
    ) -> None:
        if not repository.strip():
            raise ValueError("repository identity is required")
        _require_sha(protected_base_sha, field="protected_base_sha")
        if planning_commit_sha is not None:
            _require_sha(planning_commit_sha, field="planning_commit_sha")
        self._repository = repository
        self._protected_base_sha = protected_base_sha
        self._planning_commit_sha = planning_commit_sha
        self._planning_commit_override_consumed = False
        self.issues: dict[int, IssueRecord] = {}
        self.branches: dict[str, BranchRecord] = {}
        self.planning_commits: dict[str, PlanningCommitRecord] = {}
        self.pull_requests: dict[int, PullRequestRecord] = {}
        self.effects: list[RepositoryEffect] = []
        self.invalidated_approvals: list[int] = []
        self._effect_keys: dict[str, str] = {}

    @property
    def repository_name(self) -> str:
        return self._repository

    @property
    def protected_base_sha(self) -> str:
        return self._protected_base_sha

    def _record(self, action: str, key: str, subject: object, result: object) -> None:
        subject_digest = _canonical_digest(subject)
        previous = self._effect_keys.get(key)
        if previous is not None:
            if previous != subject_digest:
                raise AtomicityViolation("idempotency key is bound to another repository effect")
            return
        self._effect_keys[key] = subject_digest
        self.effects.append(
            RepositoryEffect(
                sequence=len(self.effects) + 1,
                action=action,
                idempotency_key=key,
                subject_digest=subject_digest,
                result_digest=_canonical_digest(result),
            )
        )

    def ensure_issue(self, candidate: IssueCandidate, *, idempotency_key: str) -> IssueRecord:
        matching = [issue for issue in self.issues.values() if issue.key == candidate.key]
        if len(matching) > 1:
            raise AtomicityViolation("candidate maps to multiple issues")
        if matching:
            issue = matching[0]
            if (
                not issue.open
                or not issue.ready
                or issue.title != candidate.title
                or issue.outcome != candidate.outcome
            ):
                raise AtomicityViolation("existing issue metadata does not match admission")
            return issue
        issue = IssueRecord(
            number=max(self.issues, default=0) + 1,
            key=candidate.key,
            title=candidate.title,
            outcome=candidate.outcome,
            ready=True,
        )
        self.issues[issue.number] = issue
        self._record("create_issue", idempotency_key, asdict(candidate), asdict(issue))
        return issue

    def issue(self, number: int) -> IssueRecord | None:
        return self.issues.get(number)

    def ensure_branch(
        self,
        *,
        name: str,
        base_sha: str,
        issue_number: int,
        idempotency_key: str,
    ) -> BranchRecord:
        existing = self.branches.get(name)
        expected = BranchRecord(name=name, base_sha=base_sha, issue_number=issue_number)
        if existing is not None:
            if existing != expected:
                raise AtomicityViolation("existing branch does not match admitted issue/base")
            return existing
        if base_sha != self.protected_base_sha:
            raise AtomicityViolation("branch is not rooted at the exact protected base")
        self.branches[name] = expected
        self._record("create_branch", idempotency_key, asdict(expected), asdict(expected))
        return expected

    def branch(self, name: str) -> BranchRecord | None:
        return self.branches.get(name)

    def ensure_planning_commit(
        self,
        *,
        branch: BranchRecord,
        candidate: IssueCandidate,
        idempotency_key: str,
    ) -> PlanningCommitRecord:
        subject = {
            "branch": asdict(branch),
            "test_plan_digest": candidate.test_plan_digest,
            "meaningful_red_digest": candidate.meaningful_red_digest,
            "test_only": True,
        }
        sha = (
            self._planning_commit_sha
            if self._planning_commit_sha is not None and not self._planning_commit_override_consumed
            else _canonical_digest(subject)[:40]
        )
        existing = self.planning_commits.get(sha)
        expected = PlanningCommitRecord(
            sha=sha,
            branch=branch.name,
            issue_number=branch.issue_number,
            test_plan_digest=candidate.test_plan_digest,
            meaningful_red_digest=candidate.meaningful_red_digest,
            test_only=True,
        )
        if existing is not None:
            if existing != expected:
                raise AtomicityViolation("planning commit metadata does not match admission")
            return existing
        self.planning_commits[sha] = expected
        self._planning_commit_override_consumed = True
        self._record("create_planning_commit", idempotency_key, subject, asdict(expected))
        return expected

    def planning_commit(self, sha: str) -> PlanningCommitRecord | None:
        return self.planning_commits.get(sha)

    def ensure_draft_pr(
        self,
        *,
        issue: IssueRecord,
        branch: BranchRecord,
        planning_commit: PlanningCommitRecord,
        body: str,
        idempotency_key: str,
    ) -> PullRequestRecord:
        primary = self.primary_pull_requests(issue.number)
        if len(primary) > 1:
            raise AtomicityViolation("issue has multiple primary pull requests")
        if primary:
            existing = primary[0]
            if (
                not existing.open
                or existing.branch != branch.name
                or existing.base_sha != branch.base_sha
                or existing.head_sha != planning_commit.sha
                or not existing.draft
                or existing.body != body
            ):
                raise AtomicityViolation("existing primary pull request does not match admission")
            return existing
        record = PullRequestRecord(
            number=max(self.pull_requests, default=0) + 1,
            issue_number=issue.number,
            branch=branch.name,
            base_sha=branch.base_sha,
            head_sha=planning_commit.sha,
            title=issue.title,
            body=body,
            draft=True,
        )
        self.pull_requests[record.number] = record
        self._record("create_draft_pr", idempotency_key, asdict(record), asdict(record))
        return record

    def primary_pull_requests(self, issue_number: int) -> tuple[PullRequestRecord, ...]:
        return tuple(
            sorted(
                (pr for pr in self.pull_requests.values() if pr.issue_number == issue_number),
                key=lambda pr: pr.number,
            )
        )

    def pull_request(self, number: int) -> PullRequestRecord | None:
        return self.pull_requests.get(number)

    def block_slice(
        self,
        *,
        issue_number: int,
        pr_number: int,
        exact_head_sha: str,
        reason: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> RepositoryBlockRecord:
        issue = self.issue(issue_number)
        pull_request = self.pull_request(pr_number)
        if (
            issue is not None
            and pull_request is not None
            and issue.blocked
            and pull_request.blocked
            and pull_request.head_sha == exact_head_sha
            and idempotency_key in self._effect_keys
        ):
            return RepositoryBlockRecord(issue, pull_request, evidence_digest)
        if (
            issue is None
            or pull_request is None
            or not issue.open
            or not pull_request.open
            or not pull_request.draft
            or pull_request.head_sha != exact_head_sha
            or pull_request.issue_number != issue_number
        ):
            raise AtomicityViolation("cannot block a stale or non-draft repository slice")
        blocked_issue = replace(issue, blocked=True)
        blocked_pr = replace(
            pull_request,
            blocked=True,
            body=pull_request.body + f"\n## Blocked\n\n{reason}. Evidence `{evidence_digest}`.\n",
        )
        self.issues[issue_number] = blocked_issue
        self.pull_requests[pr_number] = blocked_pr
        record = RepositoryBlockRecord(blocked_issue, blocked_pr, evidence_digest)
        self._record(
            "block_slice",
            idempotency_key,
            {
                "issue": issue_number,
                "pr": pr_number,
                "head": exact_head_sha,
                "reason": reason,
                "evidence": evidence_digest,
            },
            asdict(record),
        )
        return record

    def unblock_slice(
        self,
        *,
        issue_number: int,
        pr_number: int,
        exact_head_sha: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> RepositoryBlockRecord:
        issue = self.issue(issue_number)
        pull_request = self.pull_request(pr_number)
        if (
            issue is not None
            and pull_request is not None
            and not issue.blocked
            and not pull_request.blocked
            and pull_request.head_sha == exact_head_sha
            and idempotency_key in self._effect_keys
        ):
            return RepositoryBlockRecord(issue, pull_request, evidence_digest)
        if (
            issue is None
            or pull_request is None
            or not issue.open
            or not pull_request.open
            or not issue.blocked
            or not pull_request.blocked
            or pull_request.head_sha != exact_head_sha
        ):
            raise AtomicityViolation("cannot re-admit an unblocked or stale repository slice")
        unblocked_issue = replace(issue, blocked=False)
        unblocked_pr = replace(pull_request, blocked=False)
        self.issues[issue_number] = unblocked_issue
        self.pull_requests[pr_number] = unblocked_pr
        record = RepositoryBlockRecord(unblocked_issue, unblocked_pr, evidence_digest)
        self._record(
            "unblock_slice",
            idempotency_key,
            {
                "issue": issue_number,
                "pr": pr_number,
                "head": exact_head_sha,
                "evidence": evidence_digest,
            },
            asdict(record),
        )
        return record

    def add_duplicate_primary_pr(self, issue_number: int) -> PullRequestRecord:
        source = self.primary_pull_requests(issue_number)[0]
        duplicate = replace(source, number=max(self.pull_requests) + 1)
        self.pull_requests[duplicate.number] = duplicate
        return duplicate

    def update_draft_pr(
        self,
        *,
        number: int,
        expected_head_sha: str,
        candidate_head_sha: str,
        body: str,
        evidence_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord:
        current = self.pull_request(number)
        if (
            current is not None
            and current.open
            and current.draft
            and current.head_sha == candidate_head_sha
            and current.body == body
            and idempotency_key in self._effect_keys
        ):
            return current
        if (
            current is None
            or not current.open
            or not current.draft
            or current.head_sha != expected_head_sha
        ):
            raise AtomicityViolation("draft PR changed before candidate publication")
        updated = replace(current, head_sha=candidate_head_sha, body=body)
        self.pull_requests[number] = updated
        subject = {
            "pr": number,
            "expected_head": expected_head_sha,
            "candidate_head": candidate_head_sha,
            "body_digest": _canonical_digest(body),
            "evidence": evidence_digest,
        }
        self._record("update_draft_pr", idempotency_key, subject, asdict(updated))
        return updated

    def mark_ready(
        self,
        *,
        number: int,
        exact_head_sha: str,
        evidence_digest: str,
        authorization_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord:
        current = self.pull_request(number)
        if current is None or not current.open or current.head_sha != exact_head_sha:
            raise AtomicityViolation("ready action does not match the open exact-head PR")
        ready = replace(current, draft=False)
        self.pull_requests[number] = ready
        subject = {
            "pr": number,
            "head": exact_head_sha,
            "evidence": evidence_digest,
            "authorization": authorization_digest,
        }
        self._record("mark_pr_ready", idempotency_key, subject, asdict(ready))
        return ready

    def convert_to_draft(
        self,
        *,
        number: int,
        exact_head_sha: str,
        evidence_digest: str,
        authorization_digest: str,
        idempotency_key: str,
    ) -> PullRequestRecord:
        current = self.pull_request(number)
        if current is None or not current.open or current.head_sha != exact_head_sha:
            raise AtomicityViolation("dequeue action does not match the open exact-head PR")
        draft = replace(current, draft=True)
        self.pull_requests[number] = draft
        if number not in self.invalidated_approvals:
            self.invalidated_approvals.append(number)
        subject = {
            "pr": number,
            "head": exact_head_sha,
            "evidence": evidence_digest,
            "authorization": authorization_digest,
        }
        self._record("convert_pr_to_draft", idempotency_key, subject, asdict(draft))
        return draft


class AtomicImplementationController:
    """Fail-closed authority for one issue/branch/primary-PR implementation slice."""

    def __init__(
        self,
        *,
        run_dir: Path,
        repository: AtomicRepositoryAdapter,
        expected_repository: str,
        expected_base_sha: str,
    ) -> None:
        _require_sha(expected_base_sha, field="expected_base_sha")
        self.run_dir = Path(run_dir)
        self.repository = repository
        self.expected_repository = expected_repository
        self.expected_base_sha = expected_base_sha
        self._admitted: AdmittedSlice | None = None
        self._candidate_digest = ""
        self._work_baseline_sha = ""
        self._leases: dict[str, SpecialistLease] = {}
        self._results: dict[str, SpecialistResult] = {}
        self._pending_lease_admission_keys: set[str] = set()
        self._pending_result_admission_keys: set[str] = set()
        self._published_candidate_head = ""
        self._repair_admission_digest = ""
        self._cancelled = False
        self._revocation_digest = ""
        self._stop_evidence: WorkStopEvidence | None = None
        self._effect_events: list[dict[str, object]] = []
        self._active_worktrees: dict[str, tuple[Path, Path]] = {}
        self._worktree_attempts: dict[str, int] = {}
        self._active_worktrees_lock = _active_worktree_lock(self.run_dir)

    @classmethod
    def load(
        cls, run_dir: Path, *, repository: AtomicRepositoryAdapter
    ) -> AtomicImplementationController:
        path = Path(run_dir) / _STATE_FILE
        if not path.is_file():
            raise AtomicityViolation(f"missing atomic implementation state at {path}")
        raw = json.loads(path.read_text())
        controller = cls(
            run_dir=run_dir,
            repository=repository,
            expected_repository=str(raw["expected_repository"]),
            expected_base_sha=str(raw["expected_base_sha"]),
        )
        controller._candidate_digest = str(raw.get("candidate_digest", ""))
        controller._work_baseline_sha = str(raw.get("work_baseline_sha", ""))
        controller._load_effect_events()
        admitted = raw.get("admitted")
        if admitted:
            controller._admitted = _decode_admitted(admitted)
        for task_id, lease in raw.get("leases", {}).items():
            controller._leases[task_id] = _decode_lease(lease)
        for task_id, result in raw.get("results", {}).items():
            controller._results[task_id] = SpecialistResult(
                task_id=str(result["task_id"]),
                specialist=str(result["specialist"]),
                commit_sha=str(result["commit_sha"]),
                changed_paths=tuple(result["changed_paths"]),
                lease_epoch_digest=str(result["lease_epoch_digest"]),
                admission_digest=str(result.get("admission_digest", "")),
            )
        controller._published_candidate_head = str(raw.get("published_candidate_head", ""))
        controller._repair_admission_digest = str(raw.get("repair_admission_digest", ""))
        if controller._repair_admission_digest:
            _require_digest(
                controller._repair_admission_digest,
                field="repair_admission_digest",
            )
        controller._worktree_attempts = {
            str(task_id): int(attempt)
            for task_id, attempt in raw.get("worktree_attempts", {}).items()
        }
        controller._load_active_worktrees()
        controller._cancelled = bool(raw.get("cancelled", False))
        controller._revocation_digest = str(raw.get("revocation_digest", ""))
        stop = raw.get("stop_evidence")
        if isinstance(stop, Mapping):
            controller._stop_evidence = WorkStopEvidence(
                reason=str(stop["reason"]),
                workers_stopped=bool(stop["workers_stopped"]),
                active_leases=int(stop["active_leases"]),
                partial_output_admissible=bool(stop["partial_output_admissible"]),
                baseline_tree_sha=str(stop["baseline_tree_sha"]),
                current_tree_sha=str(stop["current_tree_sha"]),
                partial_paths=tuple(stop["partial_paths"]),
                lease_epoch_digest=str(stop["lease_epoch_digest"]),
                revocation_digest=str(stop["revocation_digest"]),
            )
        controller._verify_persisted_lease_authority()
        controller._verify_repository_identity()
        if controller._admitted is not None:
            controller._verify_persisted_repository_authority(controller._admitted)
        controller._verify_persisted_publication_authority()
        return controller

    @property
    def stop_evidence(self) -> WorkStopEvidence | None:
        return self._stop_evidence

    @property
    def admitted_slice(self) -> AdmittedSlice:
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        return self._admitted

    def _verify_repository_identity(self) -> None:
        if self.repository.repository_name != self.expected_repository:
            raise AtomicityViolation("repository identity differs from the admitted repository")
        if self.repository.protected_base_sha != self.expected_base_sha:
            raise AtomicityViolation("protected base moved or differs from the admitted base")

    def _verify_persisted_lease_authority(self) -> None:
        if self._admitted is None:
            if self._leases or self._results or self._repair_admission_digest:
                raise AtomicityViolation("persisted lease authority has no admitted slice")
            return
        repair_required = self._work_baseline_sha != self._admitted.planning_commit.sha
        if repair_required and not self._repair_admission_digest:
            raise AtomicityViolation("persisted repair admission evidence is missing")
        if not repair_required and self._repair_admission_digest:
            raise AtomicityViolation("persisted repair admission evidence is stale")
        self._pending_lease_admission_keys.clear()
        self._pending_result_admission_keys.clear()
        issued_lease_keys: set[str] = set()
        for task_id, persisted_lease in self._leases.items():
            expected_epoch = _canonical_digest(
                {
                    "candidate": self._admitted.candidate_digest,
                    "baseline": self._work_baseline_sha,
                    "repair_admission": self._repair_admission_digest,
                    "task": asdict(persisted_lease.task),
                }
            )
            if (
                task_id != persisted_lease.task.task_id
                or persisted_lease.admitted_candidate_digest != self._admitted.candidate_digest
                or persisted_lease.baseline_sha != self._work_baseline_sha
                or persisted_lease.repair_admission_digest != self._repair_admission_digest
                or persisted_lease.lease_epoch_digest != expected_epoch
            ):
                raise AtomicityViolation("persisted specialist lease authority is malformed")
            lease_key = _specialist_lease_admission_key(persisted_lease)
            issued_lease_keys.add(lease_key)
            lease_digest = _specialist_lease_admission_digest(persisted_lease)
            related = [
                event for event in self._effect_events if event["idempotency_key"] == lease_key
            ]
            if (
                len(related) not in {1, 2}
                or [event["status"] for event in related]
                not in (["PLANNED"], ["PLANNED", "OBSERVED"])
                or any(
                    event["action"] != "issue_specialist_lease"
                    or event["subject_digest"] != lease_digest
                    or event["result_digest"] != lease_digest
                    for event in related
                )
            ):
                raise AtomicityViolation(
                    "persisted specialist lease lacks independent admission evidence"
                )
            if len(related) == 1:
                self._pending_lease_admission_keys.add(lease_key)
        admitted_result_keys: set[str] = set()
        for task_id, result in self._results.items():
            result_lease = self._leases.get(task_id)
            try:
                normalized_paths = tuple(
                    sorted({_normalize_changed_path(path) for path in result.changed_paths})
                )
            except AtomicityViolation as exc:
                raise AtomicityViolation(
                    "persisted specialist result authority is malformed"
                ) from exc
            outside = [
                path
                for path in normalized_paths
                if result_lease is not None
                and not any(
                    _path_allowed(path, allowed) for allowed in result_lease.task.allowed_paths
                )
            ]
            if (
                result_lease is None
                or result.task_id != task_id
                or result.specialist != result_lease.task.specialist
                or result.lease_epoch_digest != result_lease.lease_epoch_digest
                or not _SHA40.fullmatch(result.commit_sha)
                or not normalized_paths
                or normalized_paths != result.changed_paths
                or outside
                or result.admission_digest
                != _specialist_result_admission_digest(
                    result_lease,
                    commit_sha=result.commit_sha,
                    changed_paths=result.changed_paths,
                )
            ):
                raise AtomicityViolation("persisted specialist result authority is malformed")
            related = [
                event
                for event in self._effect_events
                if event["idempotency_key"] == _specialist_result_admission_key(result_lease)
            ]
            admission_key = _specialist_result_admission_key(result_lease)
            admitted_result_keys.add(admission_key)
            expected_result_digest = _canonical_digest(asdict(result))
            if (
                len(related) not in {1, 2}
                or [event["status"] for event in related]
                not in (["PLANNED"], ["PLANNED", "OBSERVED"])
                or any(
                    event["action"] != "admit_specialist_result"
                    or event["subject_digest"] != result.admission_digest
                    or event["result_digest"] != expected_result_digest
                    for event in related
                )
            ):
                raise AtomicityViolation(
                    "persisted specialist result lacks independent admission evidence"
                )
            if len(related) == 1:
                self._pending_result_admission_keys.add(admission_key)
        retired_lease_keys: set[str] = set()
        retired_admission_keys: set[str] = set()
        for event in self._effect_events:
            key = str(event["idempotency_key"])
            if (
                event["action"]
                not in {
                    "retire_specialist_lease",
                    "retire_specialist_result",
                }
                and ":retire:" not in key
            ):
                continue
            admission_key, separator, authority_digest = key.rpartition(":retire:")
            expected_action = (
                "retire_specialist_lease"
                if admission_key.endswith(":issue-lease")
                else "retire_specialist_result"
                if admission_key.endswith(":admit-result")
                else ""
            )
            if (
                event["action"] != expected_action
                or event["status"] != "OBSERVED"
                or not separator
                or not _DIGEST.fullmatch(authority_digest)
                or not _DIGEST.fullmatch(str(event["result_digest"]))
                or event["subject_digest"]
                != _canonical_digest(
                    {
                        "admission_key": admission_key,
                        "authority": authority_digest,
                    }
                )
            ):
                raise AtomicityViolation("specialist authority retirement evidence is malformed")
            if expected_action == "retire_specialist_lease":
                retired_lease_keys.add(admission_key)
            else:
                retired_admission_keys.add(admission_key)
        if issued_lease_keys & retired_lease_keys or admitted_result_keys & retired_admission_keys:
            raise AtomicityViolation("persisted specialist authority was already retired")
        lease_events: dict[str, list[dict[str, object]]] = {}
        for event in self._effect_events:
            key = str(event["idempotency_key"])
            if event["action"] == "issue_specialist_lease" or (
                key.startswith("specialist:") and key.endswith(":issue-lease")
            ):
                lease_events.setdefault(key, []).append(event)
        for key, related in lease_events.items():
            if key in issued_lease_keys or key in retired_lease_keys:
                continue
            if (
                len(related) == 1
                and related[0]["action"] == "issue_specialist_lease"
                and related[0]["status"] == "PLANNED"
            ):
                self._pending_lease_admission_keys.add(key)
                continue
            raise AtomicityViolation(
                "specialist lease admission ledger is missing persisted authority"
            )
        admission_events: dict[str, list[dict[str, object]]] = {}
        for event in self._effect_events:
            key = str(event["idempotency_key"])
            if event["action"] == "admit_specialist_result" or (
                key.startswith("specialist:") and key.endswith(":admit-result")
            ):
                admission_events.setdefault(key, []).append(event)
        for key, related in admission_events.items():
            if key in admitted_result_keys or key in retired_admission_keys:
                continue
            if (
                len(related) == 1
                and related[0]["action"] == "admit_specialist_result"
                and related[0]["status"] == "PLANNED"
            ):
                self._pending_result_admission_keys.add(key)
                continue
            raise AtomicityViolation(
                "specialist result admission ledger is missing persisted authority"
            )

    def admit_slice(self, candidate: IssueCandidate) -> AdmittedSlice:
        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._admit_slice_locked(candidate)

    def _admit_slice_locked(self, candidate: IssueCandidate) -> AdmittedSlice:
        self._verify_repository_identity()
        if self._candidate_digest and self._candidate_digest != candidate.digest:
            raise AtomicityViolation("run is already bound to a different issue candidate")
        if self._admitted is not None:
            if self._admitted.candidate_digest != candidate.digest:
                raise AtomicityViolation("run is already bound to a different issue candidate")
            self._verify_admitted(self._admitted)
            return self._admitted

        self._candidate_digest = candidate.digest
        self._save()
        prefix = candidate.digest[:20]
        issue_key = f"{prefix}:issue"
        issue = self._execute_repository_effect(
            action="create_issue",
            idempotency_key=issue_key,
            subject=asdict(candidate),
            invoke=lambda: self.repository.ensure_issue(candidate, idempotency_key=issue_key),
        )
        if not issue.open or not issue.ready:
            raise AtomicityViolation("implementation issue is not open and ready")
        branch_name = f"agent/{issue.number}-{_slug(candidate.key)}"
        branch_key = f"{prefix}:branch"
        branch_subject = {
            "name": branch_name,
            "base_sha": self.expected_base_sha,
            "issue_number": issue.number,
        }
        branch = self._execute_repository_effect(
            action="create_branch",
            idempotency_key=branch_key,
            subject=branch_subject,
            invoke=lambda: self.repository.ensure_branch(
                name=branch_name,
                base_sha=self.expected_base_sha,
                issue_number=issue.number,
                idempotency_key=branch_key,
            ),
        )
        planning_key = f"{prefix}:planning"
        planning_subject = {
            "branch": asdict(branch),
            "test_plan_digest": candidate.test_plan_digest,
            "meaningful_red_digest": candidate.meaningful_red_digest,
            "test_only": True,
        }
        planning = self._execute_repository_effect(
            action="create_planning_commit",
            idempotency_key=planning_key,
            subject=planning_subject,
            invoke=lambda: self.repository.ensure_planning_commit(
                branch=branch,
                candidate=candidate,
                idempotency_key=planning_key,
            ),
        )
        if not planning.test_only:
            raise AtomicityViolation("initial planning commit contains implementation output")
        body = _primary_pr_body(issue, candidate)
        pr_key = f"{prefix}:draft-pr"
        pr_subject = {
            "issue": asdict(issue),
            "branch": asdict(branch),
            "planning_commit": asdict(planning),
            "body": body,
        }
        pull_request = self._execute_repository_effect(
            action="create_draft_pr",
            idempotency_key=pr_key,
            subject=pr_subject,
            invoke=lambda: self.repository.ensure_draft_pr(
                issue=issue,
                branch=branch,
                planning_commit=planning,
                body=body,
                idempotency_key=pr_key,
            ),
        )
        self._admitted = AdmittedSlice(
            candidate_digest=candidate.digest,
            issue=issue,
            branch=branch,
            planning_commit=planning,
            pull_request=pull_request,
        )
        self._work_baseline_sha = planning.sha
        self._verify_admitted(self._admitted)
        self._save()
        return self._admitted

    def _verify_admitted(self, admitted: AdmittedSlice) -> None:
        issue = self.repository.issue(admitted.issue.number)
        branch = self.repository.branch(admitted.branch.name)
        planning = self.repository.planning_commit(admitted.planning_commit.sha)
        primary = self.repository.primary_pull_requests(admitted.issue.number)
        if issue != admitted.issue:
            raise AtomicityViolation("admitted issue changed")
        if branch != admitted.branch:
            raise AtomicityViolation("admitted branch/base changed")
        if planning != admitted.planning_commit:
            raise AtomicityViolation("admitted planning commit changed")
        if len(primary) != 1 or primary[0] != admitted.pull_request:
            raise AtomicityViolation("one-issue/one-primary-PR mapping changed")
        if (
            admitted.branch.issue_number != admitted.issue.number
            or admitted.planning_commit.branch != admitted.branch.name
            or admitted.pull_request.branch != admitted.branch.name
            or admitted.pull_request.issue_number != admitted.issue.number
        ):
            raise AtomicityViolation("admitted repository records are not atomically linked")

    def _verify_persisted_repository_authority(self, admitted: AdmittedSlice) -> None:
        issue = self.repository.issue(admitted.issue.number)
        branch = self.repository.branch(admitted.branch.name)
        planning = self.repository.planning_commit(admitted.planning_commit.sha)
        primary = self.repository.primary_pull_requests(admitted.issue.number)
        if branch != admitted.branch:
            raise AtomicityViolation("admitted branch/base changed")
        if planning != admitted.planning_commit:
            raise AtomicityViolation("admitted planning commit changed")
        if (
            admitted.branch.issue_number != admitted.issue.number
            or admitted.planning_commit.branch != admitted.branch.name
            or admitted.pull_request.branch != admitted.branch.name
            or admitted.pull_request.issue_number != admitted.issue.number
        ):
            raise AtomicityViolation("admitted repository records are not atomically linked")
        if issue is None or len(primary) != 1:
            raise AtomicityViolation("one-issue/one-primary-PR mapping changed")
        current = primary[0]
        if replace(issue, blocked=admitted.issue.blocked) != admitted.issue or (
            current.number,
            current.issue_number,
            current.branch,
            current.base_sha,
            current.title,
            current.open,
        ) != (
            admitted.pull_request.number,
            admitted.pull_request.issue_number,
            admitted.pull_request.branch,
            admitted.pull_request.base_sha,
            admitted.pull_request.title,
            admitted.pull_request.open,
        ):
            raise AtomicityViolation("one-issue/one-primary-PR mapping changed")
        if issue == admitted.issue and current == admitted.pull_request:
            return

        grouped: dict[str, list[dict[str, object]]] = {}
        for event in self._effect_events:
            grouped.setdefault(str(event["idempotency_key"]), []).append(event)
        mutable_actions = {
            "block_slice",
            "convert_pr_to_draft",
            "create_draft_pr",
            "mark_pr_ready",
            "unblock_slice",
            "update_draft_pr",
        }
        mutable_events = [
            event for event in self._effect_events if event["action"] in mutable_actions
        ]
        latest_key = str(mutable_events[-1]["idempotency_key"]) if mutable_events else ""

        def transition_matches(
            *,
            action: str,
            key: str,
            subject_digest: str | None = None,
            result_digest: str | None = None,
        ) -> bool:
            related = grouped.get(key, [])
            statuses = [event["status"] for event in related]
            if (
                key != latest_key
                or statuses not in (["PLANNED"], ["PLANNED", "OBSERVED"])
                or any(event["action"] != action for event in related)
                or (
                    subject_digest is not None
                    and any(event["subject_digest"] != subject_digest for event in related)
                )
            ):
                return False
            return statuses == ["PLANNED"] or (
                result_digest is not None and related[-1]["result_digest"] == result_digest
            )

        current_digest = _canonical_digest(asdict(current))
        ready_key = f"pr:{current.number}:{current.head_sha}:ready"
        if (
            issue == admitted.issue
            and current == replace(admitted.pull_request, draft=False)
            and transition_matches(
                action="mark_pr_ready",
                key=ready_key,
                result_digest=current_digest,
            )
        ):
            return
        draft_prefix = f"pr:{current.number}:{current.head_sha}:draft:"
        if (
            issue == admitted.issue
            and current == replace(admitted.pull_request, draft=True)
            and latest_key.startswith(draft_prefix)
            and _DIGEST.fullmatch(latest_key.removeprefix(draft_prefix))
            and transition_matches(
                action="convert_pr_to_draft",
                key=latest_key,
                result_digest=current_digest,
            )
        ):
            return
        block_key = f"pr:{current.number}:{current.head_sha}:block:{self._revocation_digest}"
        block_subject = {
            "issue": issue.number,
            "pr": current.number,
            "head": current.head_sha,
            "reason": self._stop_evidence.reason if self._stop_evidence else "",
            "revocation_digest": self._revocation_digest,
        }
        if (
            self._stop_evidence is not None
            and issue == replace(admitted.issue, blocked=True)
            and current
            == replace(
                admitted.pull_request,
                blocked=True,
                body=admitted.pull_request.body
                + f"\n## Blocked\n\n{self._stop_evidence.reason}. Evidence "
                + f"`{self._revocation_digest}`.\n",
            )
            and transition_matches(
                action="block_slice",
                key=block_key,
                subject_digest=_canonical_digest(block_subject),
                result_digest=_canonical_digest(
                    asdict(RepositoryBlockRecord(issue, current, self._revocation_digest))
                ),
            )
        ):
            return
        body_prefix = (
            admitted.pull_request.body.split("\n## Integrated candidate\n", 1)[0]
            + "\n## Integrated candidate\n\n"
        )
        if current.body.startswith(body_prefix):
            publication = re.fullmatch(
                r"Head `([0-9a-f]{40})`; integration `([0-9a-f]{64})`; "
                r"verification `([0-9a-f]{64})`\.\n",
                current.body[len(body_prefix) :],
            )
            if publication is not None:
                head, integration_digest, verification_digest = publication.groups()
                manifest = self.integration_manifest()
                key = f"pr:{current.number}:{head}:publish"
                subject = {
                    "pr": current.number,
                    "expected_head": manifest.baseline_sha,
                    "candidate_head": head,
                    "body_digest": _canonical_digest(current.body),
                    "integration_manifest_digest": manifest.digest,
                    "verification_digest": verification_digest,
                }
                if (
                    integration_digest == manifest.digest
                    and current == replace(admitted.pull_request, head_sha=head, body=current.body)
                    and transition_matches(
                        action="update_draft_pr",
                        key=key,
                        subject_digest=_canonical_digest(subject),
                        result_digest=current_digest,
                    )
                ):
                    return
        readmission = re.fullmatch(
            re.escape(
                f"Relates to #{admitted.issue.number}.\n\n"
                "## Outcome\n\n"
                f"{admitted.issue.outcome}\n\n"
                "## Decisions\n\n"
                "One issue, one exact-base branch, one primary draft PR.\n\n"
                "## Tests / evidence\n\n"
                "Test plan `"
            )
            + r"([0-9a-f]{64})"
            + re.escape("`; meaningful red `")
            + r"([0-9a-f]{64})"
            + re.escape(
                "`.\n\n"
                "## Risks\n\nRepository identity, scope escape, and stale evidence.\n\n"
                "## Rollback\n\nClose only this draft PR and dedicated branch; "
                "never rewrite shared history.\n"
            ),
            current.body,
        )
        if readmission is not None:
            test_plan_digest, meaningful_red_digest = readmission.groups()
            candidate = IssueCandidate(
                key=admitted.issue.key,
                title=admitted.issue.title,
                outcome=admitted.issue.outcome,
                test_plan_digest=test_plan_digest,
                meaningful_red_digest=meaningful_red_digest,
            )
            new_planning = self.repository.planning_commit(current.head_sha)
            expected_planning = PlanningCommitRecord(
                sha=current.head_sha,
                branch=admitted.branch.name,
                issue_number=admitted.issue.number,
                test_plan_digest=test_plan_digest,
                meaningful_red_digest=meaningful_red_digest,
                test_only=True,
            )
            update_key = f"{candidate.digest[:20]}:readmit-draft-pr"
            update_subject = {
                "pr": current.number,
                "old_head": admitted.pull_request.head_sha,
                "planning_head": current.head_sha,
                "body_digest": _canonical_digest(current.body),
                "restored_tree_sha": self._work_baseline_sha,
            }
            intermediate = replace(
                admitted.pull_request,
                head_sha=current.head_sha,
                body=current.body,
            )
            if (
                new_planning == expected_planning
                and current == intermediate
                and transition_matches(
                    action="update_draft_pr",
                    key=update_key,
                    subject_digest=_canonical_digest(update_subject),
                    result_digest=current_digest,
                )
            ):
                return
            update_events = grouped.get(update_key, [])
            planning_subject = {
                "branch": asdict(admitted.branch),
                "restored_tree_sha": self._work_baseline_sha,
                "test_plan_digest": test_plan_digest,
                "meaningful_red_digest": meaningful_red_digest,
                "test_only": True,
            }
            planning_digest = _canonical_digest(planning_subject)
            unblock_key = f"{candidate.digest[:20]}:readmit-unblock"
            unblock_subject = {
                "issue": admitted.issue.number,
                "pr": current.number,
                "head": current.head_sha,
                "planning_digest": planning_digest,
            }
            blocked_current = replace(current, blocked=True)
            if (
                new_planning == expected_planning
                and issue == replace(admitted.issue, blocked=False)
                and blocked_current == intermediate
                and [event["status"] for event in update_events] == ["PLANNED", "OBSERVED"]
                and all(
                    event["action"] == "update_draft_pr"
                    and event["subject_digest"] == _canonical_digest(update_subject)
                    for event in update_events
                )
                and update_events[-1]["result_digest"] == _canonical_digest(asdict(blocked_current))
                and transition_matches(
                    action="unblock_slice",
                    key=unblock_key,
                    subject_digest=_canonical_digest(unblock_subject),
                    result_digest=_canonical_digest(
                        asdict(RepositoryBlockRecord(issue, current, planning_digest))
                    ),
                )
            ):
                return
        raise AtomicityViolation("persisted admitted repository authority changed")

    def _verify_persisted_publication_authority(self) -> None:
        if not self._published_candidate_head:
            return
        _require_sha(self._published_candidate_head, field="published_candidate_head")
        if self._admitted is None:
            raise AtomicityViolation("published candidate has no admitted repository slice")
        current = self.repository.pull_request(self._admitted.pull_request.number)
        if current is None or current.head_sha != self._published_candidate_head:
            raise AtomicityViolation("published candidate head differs from the admitted PR")
        try:
            manifest = self._integration_manifest_from_results()
        except AtomicityViolation as exc:
            raise AtomicityViolation(
                "published candidate lacks a complete integration manifest"
            ) from exc
        publication_body = current.body.split("\n## Blocked\n", 1)[0]
        base_body, separator, integrated = publication_body.partition(
            "\n## Integrated candidate\n\n"
        )
        match = re.fullmatch(
            r"Head `([0-9a-f]{40})`; integration `([0-9a-f]{64})`; "
            r"verification `([0-9a-f]{64})`\.\n",
            integrated,
        )
        if not separator or match is None:
            raise AtomicityViolation("published candidate PR evidence is malformed")
        head, integration_digest, verification_digest = match.groups()
        if head != self._published_candidate_head or integration_digest != manifest.digest:
            raise AtomicityViolation("published candidate evidence does not match persisted state")
        body = base_body + separator + integrated
        key = f"pr:{current.number}:{head}:publish"
        subject = {
            "pr": current.number,
            "expected_head": manifest.baseline_sha,
            "candidate_head": head,
            "body_digest": _canonical_digest(body),
            "integration_manifest_digest": manifest.digest,
            "verification_digest": verification_digest,
        }
        related = [event for event in self._effect_events if event["idempotency_key"] == key]
        published_pr = replace(current, body=body, draft=True, blocked=False)
        if (
            [event["status"] for event in related] != ["PLANNED", "OBSERVED"]
            or any(
                event["action"] != "update_draft_pr"
                or event["subject_digest"] != _canonical_digest(subject)
                for event in related
            )
            or related[-1]["result_digest"] != _canonical_digest(asdict(published_pr))
        ):
            raise AtomicityViolation("published candidate lacks exact publication evidence")

    def issue_lease(self, task: SpecialistTask, *, admitted: AdmittedSlice) -> SpecialistLease:
        with self._active_worktrees_lock:
            self._refresh_worktree_authority()
            return self._issue_lease_locked(task, admitted=admitted)

    def _issue_lease_locked(
        self, task: SpecialistTask, *, admitted: AdmittedSlice
    ) -> SpecialistLease:
        if self._cancelled:
            raise AtomicityViolation("work authority was revoked")
        if self._admitted is None or admitted != self._admitted:
            raise AtomicityViolation("specialist lease requires the exact admitted slice")
        self._verify_admitted(admitted)
        if not admitted.pull_request.draft or admitted.pull_request.blocked:
            raise AtomicityViolation("specialist work requires an unblocked draft PR")
        if self._published_candidate_head:
            raise AtomicityViolation(
                "published candidate must be invalidated and enter a repair cycle first"
            )
        repair_required = self._work_baseline_sha != admitted.planning_commit.sha
        if repair_required and not self._repair_admission_digest:
            raise AtomicityViolation("repair lease requires persisted repair admission evidence")
        current = self._leases.get(task.task_id)
        subject = {
            "candidate": admitted.candidate_digest,
            "baseline": self._work_baseline_sha,
            "repair_admission": self._repair_admission_digest,
            "task": asdict(task),
        }
        epoch = _canonical_digest(subject)
        expected = SpecialistLease(
            task=task,
            admitted_candidate_digest=admitted.candidate_digest,
            baseline_sha=self._work_baseline_sha,
            lease_epoch_digest=epoch,
            repair_admission_digest=self._repair_admission_digest,
        )
        if current is not None and current != expected:
            raise AtomicityViolation("task already has a different specialist lease")
        self._load_effect_events()
        key = _specialist_lease_admission_key(expected)
        lease_digest = _specialist_lease_admission_digest(expected)
        related = [event for event in self._effect_events if event["idempotency_key"] == key]
        if any(
            event["action"] != "issue_specialist_lease"
            or event["subject_digest"] != lease_digest
            or event["result_digest"] != lease_digest
            for event in related
        ) or [event["status"] for event in related] not in (
            [],
            ["PLANNED"],
            ["PLANNED", "OBSERVED"],
        ):
            raise AtomicityViolation("specialist lease admission evidence changed during replay")
        if not related:
            self._append_effect_event(
                action="issue_specialist_lease",
                idempotency_key=key,
                subject_digest=lease_digest,
                status="PLANNED",
                result_digest=lease_digest,
            )
        self._leases[task.task_id] = expected
        self._save()
        if not any(event["status"] == "OBSERVED" for event in related):
            self._append_effect_event(
                action="issue_specialist_lease",
                idempotency_key=key,
                subject_digest=lease_digest,
                status="OBSERVED",
                result_digest=lease_digest,
            )
        self._pending_lease_admission_keys.discard(key)
        return expected

    @contextmanager
    def specialist_worktree(
        self, repo: Path, *, lease: SpecialistLease, worktrees_root: Path
    ) -> Iterator[SpecialistWorktree]:
        self._require_live_lease(lease)
        repo_path = Path(repo).resolve()
        repo_git = LocalGitAdapter(repo_path)
        if repo_git._run("rev-parse", "HEAD") != lease.baseline_sha:  # noqa: SLF001
            raise AtomicityViolation("specialist worktree must start at the admitted work baseline")
        root_path = Path(worktrees_root).resolve()
        with self._active_worktrees_lock:
            self._refresh_worktree_authority()
            self._require_live_lease(lease)
            self._load_active_worktrees()
            if lease.task.task_id in self._active_worktrees:
                raise AtomicityViolation("task already has an active specialist worktree")
            attempt = self._worktree_attempts.get(lease.task.task_id, 0) + 1
            self._worktree_attempts[lease.task.task_id] = attempt
            self._save()
            suffix = f"{lease.lease_epoch_digest[:12]}-{attempt}"
            worktree_path = root_path / f"{lease.task.task_id}-{suffix}"
            active_record = (repo_path, worktree_path)
            self._active_worktrees[lease.task.task_id] = active_record
            self._save_active_worktrees()
            manager = specialist_worktree(
                repo_path,
                task_id=lease.task.task_id,
                worktrees_root=root_path,
                branch_name=f"specialist/{lease.task.task_id}-{suffix}",
                worktree_name=f"{lease.task.task_id}-{suffix}",
            )
            try:
                worktree = manager.__enter__()
            except BaseException:
                self._active_worktrees.pop(lease.task.task_id, None)
                self._save_active_worktrees()
                raise
        try:
            try:
                yield worktree
            except BaseException as exc:
                if not manager.__exit__(type(exc), exc, exc.__traceback__):
                    raise
            else:
                manager.__exit__(None, None, None)
        finally:
            with self._active_worktrees_lock:
                self._load_active_worktrees()
                if self._active_worktrees.get(lease.task.task_id) == active_record:
                    self._active_worktrees.pop(lease.task.task_id, None)
                    self._save_active_worktrees()

    def admit_specialist_commit(
        self, lease: SpecialistLease, repo: Path, *, commit_sha: str
    ) -> SpecialistResult:
        with self._active_worktrees_lock:
            self._refresh_worktree_authority()
            self._require_live_lease(lease)
            return self._admit_specialist_commit_locked(lease, Path(repo), commit_sha=commit_sha)

    def _admit_specialist_commit_locked(
        self, lease: SpecialistLease, repo: Path, *, commit_sha: str
    ) -> SpecialistResult:
        _require_sha(commit_sha, field="commit_sha")
        git = LocalGitAdapter(repo)
        try:
            git._run(  # noqa: SLF001 - exact ancestry is part of commit admission
                "merge-base", "--is-ancestor", lease.baseline_sha, commit_sha
            )
        except GitError as exc:
            raise AtomicityViolation(
                "specialist commit does not descend from the exact leased baseline"
            ) from exc
        try:
            touched = _paths_touched_between(git, lease.baseline_sha, commit_sha)
            changed = tuple(
                sorted(
                    line
                    for line in git._run(  # noqa: SLF001 - adapter is the local git seam
                        "diff", "--name-only", lease.baseline_sha, commit_sha, "--"
                    ).splitlines()
                    if line
                )
            )
        except GitError as exc:
            raise AtomicityViolation(
                "specialist commit is not present in the admitted repo"
            ) from exc
        historical_outside = sorted(
            path
            for path in touched
            if not any(_path_allowed(path, allowed) for allowed in lease.task.allowed_paths)
        )
        if historical_outside:
            raise AtomicityViolation(
                "commit history touched a path outside the lease: " + ", ".join(historical_outside)
            )
        return self._admit_specialist_result_locked(
            lease, commit_sha=commit_sha, changed_paths=changed, clean=True
        )

    def _admit_specialist_result(
        self,
        lease: SpecialistLease,
        *,
        commit_sha: str,
        changed_paths: Sequence[str],
        clean: bool,
    ) -> SpecialistResult:
        with self._active_worktrees_lock:
            self._refresh_worktree_authority()
            self._require_live_lease(lease)
            return self._admit_specialist_result_locked(
                lease,
                commit_sha=commit_sha,
                changed_paths=changed_paths,
                clean=clean,
            )

    def _admit_specialist_result_locked(
        self,
        lease: SpecialistLease,
        *,
        commit_sha: str,
        changed_paths: Sequence[str],
        clean: bool,
    ) -> SpecialistResult:
        self._require_live_lease(lease)
        _require_sha(commit_sha, field="commit_sha")
        if not clean:
            raise AtomicityViolation("specialist result has a dirty worktree")
        normalized = tuple(sorted({_normalize_changed_path(path) for path in changed_paths}))
        if not normalized:
            raise AtomicityViolation("specialist result has no changed paths")
        outside = [
            path
            for path in normalized
            if not any(_path_allowed(path, allowed) for allowed in lease.task.allowed_paths)
        ]
        if outside:
            raise AtomicityViolation("changed path is outside the lease: " + ", ".join(outside))
        result = SpecialistResult(
            task_id=lease.task.task_id,
            specialist=lease.task.specialist,
            commit_sha=commit_sha,
            changed_paths=normalized,
            lease_epoch_digest=lease.lease_epoch_digest,
            admission_digest=_specialist_result_admission_digest(
                lease,
                commit_sha=commit_sha,
                changed_paths=normalized,
            ),
        )
        current = self._results.get(result.task_id)
        if current is not None and current != result:
            raise AtomicityViolation(f"task {lease.task.task_id} already has an admitted result")
        self._load_effect_events()
        key = _specialist_result_admission_key(lease)
        related = [event for event in self._effect_events if event["idempotency_key"] == key]
        result_digest = _canonical_digest(asdict(result))
        if any(
            event["action"] != "admit_specialist_result"
            or event["subject_digest"] != result.admission_digest
            or event["result_digest"] != result_digest
            for event in related
        ) or [event["status"] for event in related] not in (
            [],
            ["PLANNED"],
            ["PLANNED", "OBSERVED"],
        ):
            raise AtomicityViolation("specialist result admission evidence changed during replay")
        if not related:
            self._append_effect_event(
                action="admit_specialist_result",
                idempotency_key=key,
                subject_digest=result.admission_digest,
                status="PLANNED",
                result_digest=result_digest,
            )
        self._results[result.task_id] = result
        self._save()
        if not any(event["status"] == "OBSERVED" for event in related):
            self._append_effect_event(
                action="admit_specialist_result",
                idempotency_key=key,
                subject_digest=result.admission_digest,
                status="OBSERVED",
                result_digest=result_digest,
            )
        self._pending_result_admission_keys.discard(key)
        return result

    def _retire_specialist_result_admissions(self, *, authority_digest: str) -> None:
        _require_digest(authority_digest, field="authority_digest")
        self._load_effect_events()
        retirements: dict[str, str] = {}
        for task_id, result in self._results.items():
            lease = self._leases.get(task_id)
            if lease is None:
                raise AtomicityViolation("specialist result has no lease to retire")
            admission_key = _specialist_result_admission_key(lease)
            retirements[admission_key] = result.admission_digest
        for admission_key in self._pending_result_admission_keys:
            planned = [
                event
                for event in self._effect_events
                if event["idempotency_key"] == admission_key
                and event["action"] == "admit_specialist_result"
                and event["status"] == "PLANNED"
            ]
            if len(planned) != 1:
                raise AtomicityViolation("pending specialist admission evidence is malformed")
            retirements[admission_key] = str(planned[0]["result_digest"])
        for admission_key, admission_digest in retirements.items():
            key = f"{admission_key}:retire:{authority_digest}"
            subject_digest = _canonical_digest(
                {
                    "admission_key": admission_key,
                    "authority": authority_digest,
                }
            )
            related = [event for event in self._effect_events if event["idempotency_key"] == key]
            if any(
                event["action"] != "retire_specialist_result"
                or event["status"] != "OBSERVED"
                or event["subject_digest"] != subject_digest
                or event["result_digest"] != admission_digest
                for event in related
            ):
                raise AtomicityViolation("specialist result retirement evidence changed")
            if not related:
                self._append_effect_event(
                    action="retire_specialist_result",
                    idempotency_key=key,
                    subject_digest=subject_digest,
                    status="OBSERVED",
                    result_digest=admission_digest,
                )
            self._pending_result_admission_keys.discard(admission_key)

    def _retire_specialist_lease_admissions(self, *, authority_digest: str) -> None:
        _require_digest(authority_digest, field="authority_digest")
        self._load_effect_events()
        retirements = {
            _specialist_lease_admission_key(lease): _specialist_lease_admission_digest(lease)
            for lease in self._leases.values()
        }
        for admission_key in self._pending_lease_admission_keys:
            planned = [
                event
                for event in self._effect_events
                if event["idempotency_key"] == admission_key
                and event["action"] == "issue_specialist_lease"
                and event["status"] == "PLANNED"
            ]
            if len(planned) != 1:
                raise AtomicityViolation("pending specialist lease evidence is malformed")
            retirements[admission_key] = str(planned[0]["result_digest"])
        for admission_key, admission_digest in retirements.items():
            key = f"{admission_key}:retire:{authority_digest}"
            subject_digest = _canonical_digest(
                {
                    "admission_key": admission_key,
                    "authority": authority_digest,
                }
            )
            related = [event for event in self._effect_events if event["idempotency_key"] == key]
            if any(
                event["action"] != "retire_specialist_lease"
                or event["status"] != "OBSERVED"
                or event["subject_digest"] != subject_digest
                or event["result_digest"] != admission_digest
                for event in related
            ):
                raise AtomicityViolation("specialist lease retirement evidence changed")
            if not related:
                self._append_effect_event(
                    action="retire_specialist_lease",
                    idempotency_key=key,
                    subject_digest=subject_digest,
                    status="OBSERVED",
                    result_digest=admission_digest,
                )
            self._pending_lease_admission_keys.discard(admission_key)

    def _retire_specialist_authority(self, *, authority_digest: str) -> None:
        self._retire_specialist_result_admissions(authority_digest=authority_digest)
        self._retire_specialist_lease_admissions(authority_digest=authority_digest)

    def integration_manifest(self) -> IntegrationManifest:
        if self._cancelled:
            raise AtomicityViolation("partial output is non-admissible after cancellation")
        if self._pending_lease_admission_keys or self._pending_result_admission_keys:
            raise AtomicityViolation("specialist authority admission recovery is pending")
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        return self._integration_manifest_from_results()

    def _integration_manifest_from_results(self) -> IntegrationManifest:
        if not self._results:
            raise AtomicityViolation("integration requires at least one specialist result")
        missing = sorted(set(self._leases) - set(self._results))
        if missing:
            raise AtomicityViolation("specialist result missing for task(s): " + ", ".join(missing))
        results = tuple(self._results[key] for key in sorted(self._results))
        path_owners: dict[str, str] = {}
        for result in results:
            for path in result.changed_paths:
                prior = path_owners.get(path)
                if prior is not None:
                    raise AtomicityViolation(
                        f"specialist results overlap on {path}: {prior}, {result.task_id}"
                    )
                path_owners[path] = result.task_id
        payload = {
            "baseline_sha": self._work_baseline_sha,
            "results": [asdict(result) for result in results],
        }
        return IntegrationManifest(
            baseline_sha=self._work_baseline_sha,
            results=results,
            digest=_canonical_digest(payload),
        )

    def cancel_all(
        self,
        *,
        reason: str,
        partial_paths: Sequence[str],
        current_tree_sha: str,
    ) -> WorkStopEvidence:
        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._cancel_all_locked(
                reason=reason,
                partial_paths=partial_paths,
                current_tree_sha=current_tree_sha,
            )

    def _cancel_all_locked(
        self,
        *,
        reason: str,
        partial_paths: Sequence[str],
        current_tree_sha: str,
    ) -> WorkStopEvidence:
        if self._admitted is None:
            raise AtomicityViolation("cannot stop work before repository admission")
        if not reason.strip():
            raise ValueError("cancellation reason is required")
        _require_sha(current_tree_sha, field="current_tree_sha")
        observed_partial = {_normalize_changed_path(path) for path in partial_paths}
        with self._active_worktrees_lock:
            self._refresh_worktree_authority()
            self._load_active_worktrees()
            for repo, worktree_path in tuple(self._active_worktrees.values()):
                if not worktree_path.exists():
                    continue
                repo_git = LocalGitAdapter(repo)
                registered_worktrees = {
                    Path(line.removeprefix("worktree ")).resolve()
                    for line in repo_git._run(  # noqa: SLF001 - destructive target verification
                        "worktree", "list", "--porcelain"
                    ).splitlines()
                    if line.startswith("worktree ")
                }
                if worktree_path.resolve() not in registered_worktrees:
                    raise AtomicityViolation(
                        "persisted active worktree is not registered with the admitted repository"
                    )
                worktree_git = LocalGitAdapter(worktree_path)
                for line in worktree_git._run(  # noqa: SLF001
                    "status", "--porcelain", "--untracked-files=all"
                ).splitlines():
                    parts = line.split(maxsplit=1)
                    raw_path = parts[1].split(" -> ")[-1] if len(parts) == 2 else ""
                    if raw_path:
                        observed_partial.add(_normalize_changed_path(raw_path))
                repo_git._run(  # noqa: SLF001
                    "worktree", "remove", "--force", str(worktree_path)
                )
                if worktree_path.exists():
                    raise AtomicityViolation(
                        "specialist worktree remained active after cancellation"
                    )
            self._active_worktrees.clear()
            self._save_active_worktrees()
            normalized = tuple(sorted(observed_partial))
            epochs = sorted(lease.lease_epoch_digest for lease in self._leases.values())
            lease_epoch_digest = _canonical_digest(epochs)
            revocation = _canonical_digest(
                {
                    "candidate": self._admitted.candidate_digest,
                    "baseline": self._work_baseline_sha,
                    "current": current_tree_sha,
                    "partial_paths": normalized,
                    "lease_epoch_digest": lease_epoch_digest,
                    "reason": reason,
                    "status": "REVOKED",
                }
            )
            self._cancelled = True
            self._revocation_digest = revocation
            self._leases = {
                task_id: replace(lease, revoked=True) for task_id, lease in self._leases.items()
            }
            stopped = WorkStopEvidence(
                reason=reason,
                workers_stopped=True,
                active_leases=0,
                partial_output_admissible=False,
                baseline_tree_sha=self._work_baseline_sha,
                current_tree_sha=current_tree_sha,
                partial_paths=normalized,
                lease_epoch_digest=lease_epoch_digest,
                revocation_digest=revocation,
            )
            self._stop_evidence = stopped
            self._save()
        current_pr = self.repository.pull_request(self._admitted.pull_request.number)
        if current_pr is None:
            raise AtomicityViolation("admitted primary PR disappeared during cancellation")
        issue_number = self._admitted.issue.number
        block_key = f"pr:{current_pr.number}:{current_pr.head_sha}:block:{revocation}"
        block_subject = {
            "issue": issue_number,
            "pr": current_pr.number,
            "head": current_pr.head_sha,
            "reason": reason,
            "revocation_digest": revocation,
        }
        blocked = self._execute_repository_effect(
            action="block_slice",
            idempotency_key=block_key,
            subject=block_subject,
            invoke=lambda: self.repository.block_slice(
                issue_number=issue_number,
                pr_number=current_pr.number,
                exact_head_sha=current_pr.head_sha,
                reason=reason,
                evidence_digest=revocation,
                idempotency_key=block_key,
            ),
        )
        self._admitted = replace(
            self._admitted,
            issue=blocked.issue,
            pull_request=blocked.pull_request,
        )
        self._save()
        return stopped

    def readmit_after_product_input(
        self, candidate: IssueCandidate, *, restored_tree_sha: str
    ) -> AdmittedSlice:
        """Re-admit the same atomic outcome only after exact pre-code restoration.

        The old leases and results remain non-admissible.  A new test plan and a
        new meaningful-red digest produce a new planning commit before the same
        issue/branch/draft PR can receive implementation again.
        """

        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._readmit_after_product_input_locked(
                candidate,
                restored_tree_sha=restored_tree_sha,
            )

    def _readmit_after_product_input_locked(
        self, candidate: IssueCandidate, *, restored_tree_sha: str
    ) -> AdmittedSlice:

        if self._admitted is None or not self._cancelled:
            raise AtomicityViolation("product-input re-admission requires a stopped slice")
        _require_sha(restored_tree_sha, field="restored_tree_sha")
        previous = self._admitted
        if restored_tree_sha != self._work_baseline_sha:
            raise AtomicityViolation("same-PR recovery did not restore the exact pre-code tree")
        if (
            candidate.key != previous.issue.key
            or candidate.title != previous.issue.title
            or candidate.outcome != previous.issue.outcome
        ):
            raise AtomicityViolation("changed atomic outcome requires a new issue and primary PR")
        if (
            candidate.test_plan_digest == previous.planning_commit.test_plan_digest
            or candidate.meaningful_red_digest == previous.planning_commit.meaningful_red_digest
        ):
            raise AtomicityViolation(
                "product-input re-admission requires a fresh test plan and meaningful red"
            )
        current = self.repository.pull_request(previous.pull_request.number)
        if current is None or not current.open or not current.draft:
            raise AtomicityViolation("merged, closed, or ready PR cannot be reused for recovery")
        prefix = candidate.digest[:20]
        planning_key = f"{prefix}:readmit-planning"
        planning_subject = {
            "branch": asdict(previous.branch),
            "restored_tree_sha": restored_tree_sha,
            "test_plan_digest": candidate.test_plan_digest,
            "meaningful_red_digest": candidate.meaningful_red_digest,
            "test_only": True,
        }
        planning = self._execute_repository_effect(
            action="create_planning_commit",
            idempotency_key=planning_key,
            subject=planning_subject,
            invoke=lambda: self.repository.ensure_planning_commit(
                branch=previous.branch,
                candidate=candidate,
                idempotency_key=planning_key,
            ),
        )
        body = _primary_pr_body(previous.issue, candidate)
        pr_key = f"{prefix}:readmit-draft-pr"
        expected_pr_head = previous.pull_request.head_sha
        pr_subject = {
            "pr": current.number,
            "old_head": expected_pr_head,
            "planning_head": planning.sha,
            "body_digest": _canonical_digest(body),
            "restored_tree_sha": restored_tree_sha,
        }
        pull_request = self._execute_repository_effect(
            action="update_draft_pr",
            idempotency_key=pr_key,
            subject=pr_subject,
            invoke=lambda: self.repository.update_draft_pr(
                number=current.number,
                expected_head_sha=expected_pr_head,
                candidate_head_sha=planning.sha,
                body=body,
                evidence_digest=_canonical_digest(planning_subject),
                idempotency_key=pr_key,
            ),
        )
        unblock_key = f"{prefix}:readmit-unblock"
        unblock_subject = {
            "issue": previous.issue.number,
            "pr": pull_request.number,
            "head": pull_request.head_sha,
            "planning_digest": _canonical_digest(planning_subject),
        }
        unblocked = self._execute_repository_effect(
            action="unblock_slice",
            idempotency_key=unblock_key,
            subject=unblock_subject,
            invoke=lambda: self.repository.unblock_slice(
                issue_number=previous.issue.number,
                pr_number=pull_request.number,
                exact_head_sha=pull_request.head_sha,
                evidence_digest=_canonical_digest(planning_subject),
                idempotency_key=unblock_key,
            ),
        )
        self._candidate_digest = candidate.digest
        self._work_baseline_sha = planning.sha
        self._admitted = AdmittedSlice(
            candidate_digest=candidate.digest,
            issue=unblocked.issue,
            branch=previous.branch,
            planning_commit=planning,
            pull_request=unblocked.pull_request,
        )
        self._retire_specialist_authority(authority_digest=candidate.digest)
        self._leases.clear()
        self._results.clear()
        self._published_candidate_head = ""
        self._repair_admission_digest = ""
        self._cancelled = False
        self._revocation_digest = ""
        self._stop_evidence = None
        self._verify_admitted(self._admitted)
        self._save()
        return self._admitted

    def publish_candidate(
        self,
        *,
        repo: Path,
        manifest: IntegrationManifest,
        candidate_head_sha: str,
        verification_digest: str,
    ) -> PullRequestRecord:
        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._publish_candidate_locked(
                repo=Path(repo),
                manifest=manifest,
                candidate_head_sha=candidate_head_sha,
                verification_digest=verification_digest,
            )

    def _publish_candidate_locked(
        self,
        *,
        repo: Path,
        manifest: IntegrationManifest,
        candidate_head_sha: str,
        verification_digest: str,
    ) -> PullRequestRecord:
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        if manifest != self.integration_manifest():
            raise AtomicityViolation("integration manifest is stale or not authoritative")
        _require_sha(candidate_head_sha, field="candidate_head_sha")
        _require_digest(verification_digest, field="verification_digest")
        self._verify_integrated_candidate(repo, manifest, candidate_head_sha)
        current = self.repository.pull_request(self._admitted.pull_request.number)
        if current is None or not current.open or not current.draft:
            raise AtomicityViolation("candidate publication requires the admitted draft PR")
        base_body = self._admitted.pull_request.body.split("\n## Integrated candidate\n", 1)[0]
        body = (
            base_body
            + "\n## Integrated candidate\n\n"
            + f"Head `{candidate_head_sha}`; integration `{manifest.digest}`; "
            + f"verification `{verification_digest}`.\n"
        )
        key = f"pr:{current.number}:{candidate_head_sha}:publish"
        expected_head_sha = manifest.baseline_sha
        subject = {
            "pr": current.number,
            "expected_head": expected_head_sha,
            "candidate_head": candidate_head_sha,
            "body_digest": _canonical_digest(body),
            "integration_manifest_digest": manifest.digest,
            "verification_digest": verification_digest,
        }
        if (
            current.head_sha == candidate_head_sha
            and current.body == body
            and self._effect_observed_matches(
                action="update_draft_pr",
                idempotency_key=key,
                subject=subject,
                result=current,
            )
        ):
            updated = current
        else:
            updated = self._execute_repository_effect(
                action="update_draft_pr",
                idempotency_key=key,
                subject=subject,
                invoke=lambda: self.repository.update_draft_pr(
                    number=current.number,
                    expected_head_sha=expected_head_sha,
                    candidate_head_sha=candidate_head_sha,
                    body=body,
                    evidence_digest=_canonical_digest(
                        {
                            "integration": manifest.digest,
                            "verification": verification_digest,
                        }
                    ),
                    idempotency_key=key,
                ),
            )
        self._admitted = replace(self._admitted, pull_request=updated)
        self._published_candidate_head = candidate_head_sha
        self._save()
        return updated

    @staticmethod
    def _verify_integrated_candidate(
        repo: Path, manifest: IntegrationManifest, candidate_head_sha: str
    ) -> None:
        git = LocalGitAdapter(repo)
        try:
            git._run(  # noqa: SLF001 - candidate ancestry is release evidence
                "merge-base", "--is-ancestor", manifest.baseline_sha, candidate_head_sha
            )
            actual_paths = {
                line
                for line in git._run(  # noqa: SLF001 - exact range is release evidence
                    "diff", "--name-only", manifest.baseline_sha, candidate_head_sha, "--"
                ).splitlines()
                if line
            }
            expected_paths = {path for result in manifest.results for path in result.changed_paths}
            history_paths = _paths_touched_between(git, manifest.baseline_sha, candidate_head_sha)
            unexpected_history = sorted(history_paths - expected_paths)
            if unexpected_history:
                raise AtomicityViolation(
                    "candidate history touched a path outside the integration manifest: "
                    + ", ".join(unexpected_history)
                )
            if actual_paths != expected_paths:
                missing = sorted(expected_paths - actual_paths)
                extra = sorted(actual_paths - expected_paths)
                raise AtomicityViolation(
                    "candidate tree differs from the integration manifest: "
                    f"missing={missing}; extra={extra}"
                )
            admitted_history: set[str] = set()
            for result in manifest.results:
                git._run(  # noqa: SLF001 - every result must be in candidate history
                    "merge-base", "--is-ancestor", result.commit_sha, candidate_head_sha
                )
                admitted_history.update(
                    _commits_between(git, manifest.baseline_sha, result.commit_sha)
                )
                for path in result.changed_paths:
                    if _git_tree_entry(git, result.commit_sha, path) != _git_tree_entry(
                        git, candidate_head_sha, path
                    ):
                        raise AtomicityViolation(
                            f"candidate tree entry for {path} differs from task {result.task_id}"
                        )
            candidate_history = _commits_between(git, manifest.baseline_sha, candidate_head_sha)
            integration_commits = [
                revision for revision in candidate_history if revision not in admitted_history
            ]
            allowed_entries = {
                path: {
                    _git_tree_entry(git, manifest.baseline_sha, path),
                    _git_tree_entry(git, result.commit_sha, path),
                }
                for result in manifest.results
                for path in result.changed_paths
            }
            for revision in integration_commits:
                parents = git._run(  # noqa: SLF001 - topology binds integration authority
                    "rev-list", "--parents", "-n", "1", revision
                ).split()[1:]
                if len(parents) < 2:
                    raise AtomicityViolation(
                        "candidate history contains an unadmitted non-integration commit"
                    )
                if any(
                    _git_tree_entry(git, revision, path) not in entries
                    for path, entries in allowed_entries.items()
                ):
                    raise AtomicityViolation(
                        "integration commit contains content not admitted by a specialist result"
                    )
        except GitError as exc:
            raise AtomicityViolation(
                "candidate head is not bound to the integration baseline and results"
            ) from exc

    def mark_ready(
        self,
        *,
        pr_number: int,
        exact_head_sha: str,
        base_sha: str,
        policy_digest: str,
        toolchain_digest: str,
        prospective_tree_digest: str,
        checks_digest: str,
        advisory_review_digest: str,
        blocking_findings: Sequence[str],
        authorization_digest: str,
    ) -> PullRequestRecord:
        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._mark_ready_locked(
                pr_number=pr_number,
                exact_head_sha=exact_head_sha,
                base_sha=base_sha,
                policy_digest=policy_digest,
                toolchain_digest=toolchain_digest,
                prospective_tree_digest=prospective_tree_digest,
                checks_digest=checks_digest,
                advisory_review_digest=advisory_review_digest,
                blocking_findings=blocking_findings,
                authorization_digest=authorization_digest,
            )

    def _mark_ready_locked(
        self,
        *,
        pr_number: int,
        exact_head_sha: str,
        base_sha: str,
        policy_digest: str,
        toolchain_digest: str,
        prospective_tree_digest: str,
        checks_digest: str,
        advisory_review_digest: str,
        blocking_findings: Sequence[str],
        authorization_digest: str,
    ) -> PullRequestRecord:
        if self._cancelled:
            raise AtomicityViolation("cancelled run cannot enter readiness")
        current = self.repository.pull_request(pr_number)
        if exact_head_sha != self._published_candidate_head:
            raise AtomicityViolation("ready action requires the published integrated candidate")
        if base_sha != self.expected_base_sha:
            raise AtomicityViolation("ready action base differs from the admitted protected base")
        for field, value in (
            ("policy_digest", policy_digest),
            ("toolchain_digest", toolchain_digest),
            ("prospective_tree_digest", prospective_tree_digest),
            ("checks_digest", checks_digest),
            ("advisory_review_digest", advisory_review_digest),
            ("authorization_digest", authorization_digest),
        ):
            _require_digest(value, field=field)
        if blocking_findings:
            raise AtomicityViolation("ready action is blocked by unresolved findings")
        evidence = _canonical_digest(
            {
                "head": exact_head_sha,
                "base": base_sha,
                "policy": policy_digest,
                "toolchain": toolchain_digest,
                "prospective_tree": prospective_tree_digest,
                "checks": checks_digest,
                "advisory_review": advisory_review_digest,
                "blocking_findings": [],
            }
        )
        key = f"pr:{pr_number}:{exact_head_sha}:ready"
        subject = {
            "pr": pr_number,
            "head": exact_head_sha,
            "evidence": evidence,
            "authorization": authorization_digest,
        }
        if (
            current is not None
            and current.open
            and not current.draft
            and current.head_sha == exact_head_sha
            and self._effect_observed_matches(
                action="mark_pr_ready",
                idempotency_key=key,
                subject=subject,
                result=current,
            )
        ):
            ready = current
        elif (
            current is not None
            and current.open
            and not current.draft
            and current.head_sha == exact_head_sha
            and self._effect_planned_matches(
                action="mark_pr_ready",
                idempotency_key=key,
                subject=subject,
            )
        ):
            ready = self._execute_repository_effect(
                action="mark_pr_ready",
                idempotency_key=key,
                subject=subject,
                invoke=lambda: self.repository.mark_ready(
                    number=pr_number,
                    exact_head_sha=exact_head_sha,
                    evidence_digest=evidence,
                    authorization_digest=authorization_digest,
                    idempotency_key=key,
                ),
            )
        else:
            self._require_admitted_pr(pr_number, exact_head_sha)
            ready = self._execute_repository_effect(
                action="mark_pr_ready",
                idempotency_key=key,
                subject=subject,
                invoke=lambda: self.repository.mark_ready(
                    number=pr_number,
                    exact_head_sha=exact_head_sha,
                    evidence_digest=evidence,
                    authorization_digest=authorization_digest,
                    idempotency_key=key,
                ),
            )
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        self._admitted = replace(self._admitted, pull_request=ready)
        self._save()
        return ready

    def invalidate_ready(
        self,
        *,
        pr_number: int,
        signal: ReadyInvalidationSignal,
        authorization_digest: str,
    ) -> PullRequestRecord:
        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._invalidate_ready_locked(
                pr_number=pr_number,
                signal=signal,
                authorization_digest=authorization_digest,
            )

    def _invalidate_ready_locked(
        self,
        *,
        pr_number: int,
        signal: ReadyInvalidationSignal,
        authorization_digest: str,
    ) -> PullRequestRecord:
        _require_digest(authorization_digest, field="authorization_digest")
        if not signal.credible or not signal.authenticated or not signal.blocking:
            raise AtomicityViolation(
                "ready invalidation requires credible authenticated blocking evidence"
            )
        evidence = _canonical_digest(
            {
                "kind": signal.kind,
                "source": signal.source,
                "head": signal.exact_head_sha,
                "evidence": signal.evidence_digest,
                "trace": signal.trace_digest,
                "reviewer_eligible": signal.reviewer_eligible,
                "check_state": signal.check_state,
                "approvals": "INVALIDATED",
            }
        )
        key = f"pr:{pr_number}:{signal.exact_head_sha}:draft:{signal.evidence_digest}"
        subject = {
            "pr": pr_number,
            "head": signal.exact_head_sha,
            "evidence": evidence,
            "authorization": authorization_digest,
        }
        current = self.repository.pull_request(pr_number)
        if (
            current is not None
            and current.open
            and current.draft
            and current.head_sha == signal.exact_head_sha
            and self._effect_observed_matches(
                action="convert_pr_to_draft",
                idempotency_key=key,
                subject=subject,
                result=current,
            )
        ):
            draft = current
        elif (
            current is not None
            and current.open
            and current.draft
            and current.head_sha == signal.exact_head_sha
            and self._effect_planned_matches(
                action="convert_pr_to_draft",
                idempotency_key=key,
                subject=subject,
            )
        ):
            draft = self._execute_repository_effect(
                action="convert_pr_to_draft",
                idempotency_key=key,
                subject=subject,
                invoke=lambda: self.repository.convert_to_draft(
                    number=pr_number,
                    exact_head_sha=signal.exact_head_sha,
                    evidence_digest=evidence,
                    authorization_digest=authorization_digest,
                    idempotency_key=key,
                ),
            )
        else:
            self._require_admitted_pr(pr_number, signal.exact_head_sha, allow_ready=True)
            draft = self._execute_repository_effect(
                action="convert_pr_to_draft",
                idempotency_key=key,
                subject=subject,
                invoke=lambda: self.repository.convert_to_draft(
                    number=pr_number,
                    exact_head_sha=signal.exact_head_sha,
                    evidence_digest=evidence,
                    authorization_digest=authorization_digest,
                    idempotency_key=key,
                ),
            )
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        self._admitted = replace(self._admitted, pull_request=draft)
        self._save()
        return draft

    def begin_repair_cycle(
        self,
        *,
        exact_head_sha: str,
        finding_inventory_digest: str,
        repair_test_plan_digest: str,
        meaningful_red_digest: str,
    ) -> str:
        """Admit scoped repair work only after the ready PR was governed to draft."""

        with self._active_worktrees_lock:
            self._refresh_persisted_state()
            return self._begin_repair_cycle_locked(
                exact_head_sha=exact_head_sha,
                finding_inventory_digest=finding_inventory_digest,
                repair_test_plan_digest=repair_test_plan_digest,
                meaningful_red_digest=meaningful_red_digest,
            )

    def _begin_repair_cycle_locked(
        self,
        *,
        exact_head_sha: str,
        finding_inventory_digest: str,
        repair_test_plan_digest: str,
        meaningful_red_digest: str,
    ) -> str:
        if self._admitted is None:
            raise AtomicityViolation("repository slice has not been admitted")
        current = self.repository.pull_request(self._admitted.pull_request.number)
        if (
            current is None
            or not current.open
            or not current.draft
            or current.blocked
            or current.head_sha != exact_head_sha
            or exact_head_sha != self._published_candidate_head
        ):
            raise AtomicityViolation(
                "repair requires the governed draft form of the published exact head"
            )
        for field, value in (
            ("finding_inventory_digest", finding_inventory_digest),
            ("repair_test_plan_digest", repair_test_plan_digest),
            ("meaningful_red_digest", meaningful_red_digest),
        ):
            _require_digest(value, field=field)
        repair_admission_digest = _canonical_digest(
            {
                "head": exact_head_sha,
                "finding_inventory": finding_inventory_digest,
                "repair_test_plan": repair_test_plan_digest,
                "meaningful_red": meaningful_red_digest,
            }
        )
        self._retire_specialist_authority(authority_digest=repair_admission_digest)
        self._leases.clear()
        self._results.clear()
        self._published_candidate_head = ""
        self._work_baseline_sha = exact_head_sha
        self._repair_admission_digest = repair_admission_digest
        self._save()
        return self._repair_admission_digest

    def _require_admitted_pr(
        self, number: int, exact_head_sha: str, *, allow_ready: bool = False
    ) -> PullRequestRecord:
        self._verify_repository_identity()
        if self._admitted is None or self._admitted.pull_request.number != number:
            raise AtomicityViolation("PR is not the admitted primary pull request")
        current = self.repository.pull_request(number)
        if current is None or not current.open or current.head_sha != exact_head_sha:
            raise AtomicityViolation("PR/head observation is stale")
        if current.blocked:
            raise AtomicityViolation("blocked PR cannot enter review or readiness")
        if not allow_ready and not current.draft:
            raise AtomicityViolation("PR is already ready")
        if allow_ready and current.draft:
            raise AtomicityViolation("only a ready PR can be dequeued")
        return current

    def _require_live_lease(self, lease: SpecialistLease) -> None:
        current = self._leases.get(lease.task.task_id)
        if (
            self._cancelled
            or lease.revoked
            or current is None
            or current != lease
            or current.lease_epoch_digest != lease.lease_epoch_digest
        ):
            raise AtomicityViolation("specialist lease is stale or revoked")

    def _execute_repository_effect(
        self,
        *,
        action: str,
        idempotency_key: str,
        subject: object,
        invoke: Callable[[], _T],
    ) -> _T:
        with self._active_worktrees_lock:
            self._load_effect_events()
            return self._execute_repository_effect_locked(
                action=action,
                idempotency_key=idempotency_key,
                subject=subject,
                invoke=invoke,
            )

    def _execute_repository_effect_locked(
        self,
        *,
        action: str,
        idempotency_key: str,
        subject: object,
        invoke: Callable[[], _T],
    ) -> _T:
        subject_digest = _canonical_digest(subject)
        matching = [
            event for event in self._effect_events if event["idempotency_key"] == idempotency_key
        ]
        if any(event["subject_digest"] != subject_digest for event in matching):
            raise AtomicityViolation("repository effect key is bound to another subject")
        if any(event["action"] != action for event in matching):
            raise AtomicityViolation("repository effect key is bound to another action")
        if not matching:
            self._append_effect_event(
                action=action,
                idempotency_key=idempotency_key,
                subject_digest=subject_digest,
                status="PLANNED",
                result_digest="",
            )
        result = invoke()
        try:
            result_digest = _canonical_digest(asdict(result))  # type: ignore[call-overload]
        except TypeError as exc:
            raise AtomicityViolation("repository adapter returned unrecordable evidence") from exc
        observed = [event for event in matching if event["status"] == "OBSERVED"]
        if observed:
            if any(event["result_digest"] != result_digest for event in observed):
                raise AtomicityViolation("repository effect result changed during replay")
        else:
            self._append_effect_event(
                action=action,
                idempotency_key=idempotency_key,
                subject_digest=subject_digest,
                status="OBSERVED",
                result_digest=result_digest,
            )
        return result

    def _effect_observed_matches(
        self,
        *,
        action: str,
        idempotency_key: str,
        subject: object,
        result: object,
    ) -> bool:
        with self._active_worktrees_lock:
            self._load_effect_events()
            return self._effect_observed_matches_locked(
                action=action,
                idempotency_key=idempotency_key,
                subject=subject,
                result=result,
            )

    def _effect_observed_matches_locked(
        self,
        *,
        action: str,
        idempotency_key: str,
        subject: object,
        result: object,
    ) -> bool:
        subject_digest = _canonical_digest(subject)
        try:
            result_digest = _canonical_digest(asdict(result))  # type: ignore[call-overload]
        except TypeError as exc:
            raise AtomicityViolation("repository adapter returned unrecordable evidence") from exc
        related = [
            event for event in self._effect_events if event["idempotency_key"] == idempotency_key
        ]
        if any(
            event["action"] != action or event["subject_digest"] != subject_digest
            for event in related
        ):
            raise AtomicityViolation("crash adoption does not match the journaled effect")
        observed = [event for event in related if event["status"] == "OBSERVED"]
        if any(event["result_digest"] != result_digest for event in observed):
            raise AtomicityViolation("crash adoption result differs from journaled evidence")
        return bool(observed)

    def _effect_planned_matches(
        self, *, action: str, idempotency_key: str, subject: object
    ) -> bool:
        with self._active_worktrees_lock:
            self._load_effect_events()
            return self._effect_planned_matches_locked(
                action=action,
                idempotency_key=idempotency_key,
                subject=subject,
            )

    def _effect_planned_matches_locked(
        self, *, action: str, idempotency_key: str, subject: object
    ) -> bool:
        subject_digest = _canonical_digest(subject)
        related = [
            event for event in self._effect_events if event["idempotency_key"] == idempotency_key
        ]
        if any(
            event["action"] != action or event["subject_digest"] != subject_digest
            for event in related
        ):
            raise AtomicityViolation("effect replay does not match the journaled plan")
        return any(event["status"] == "PLANNED" for event in related) and not any(
            event["status"] == "OBSERVED" for event in related
        )

    def _append_effect_event(
        self,
        *,
        action: str,
        idempotency_key: str,
        subject_digest: str,
        status: str,
        result_digest: str,
    ) -> None:
        previous = str(self._effect_events[-1]["event_digest"]) if self._effect_events else ""
        body: dict[str, object] = {
            "sequence": len(self._effect_events) + 1,
            "action": action,
            "idempotency_key": idempotency_key,
            "subject_digest": subject_digest,
            "status": status,
            "result_digest": result_digest,
            "previous_digest": previous,
        }
        body["event_digest"] = _canonical_digest(body)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / _EFFECT_LEDGER).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._effect_events.append(body)

    def _load_effect_events(self) -> None:
        self._effect_events.clear()
        path = self.run_dir / _EFFECT_LEDGER
        if not path.exists():
            return
        previous = ""
        for sequence, line in enumerate(path.read_text().splitlines(), start=1):
            try:
                event: dict[str, object] = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AtomicityViolation("repository effect ledger is malformed") from exc
            claimed = str(event.pop("event_digest", ""))
            if (
                event.get("sequence") != sequence
                or event.get("previous_digest") != previous
                or claimed != _canonical_digest(event)
            ):
                raise AtomicityViolation("repository effect ledger integrity failed")
            event["event_digest"] = claimed
            self._effect_events.append(event)
            previous = claimed

    def _save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.run_dir / _STATE_FILE,
            {
                "schema_version": "1.0.0",
                "expected_repository": self.expected_repository,
                "expected_base_sha": self.expected_base_sha,
                "candidate_digest": self._candidate_digest,
                "work_baseline_sha": self._work_baseline_sha,
                "admitted": asdict(self._admitted) if self._admitted else None,
                "leases": {key: asdict(value) for key, value in sorted(self._leases.items())},
                "results": {key: asdict(value) for key, value in sorted(self._results.items())},
                "published_candidate_head": self._published_candidate_head,
                "repair_admission_digest": self._repair_admission_digest,
                "worktree_attempts": dict(sorted(self._worktree_attempts.items())),
                "cancelled": self._cancelled,
                "revocation_digest": self._revocation_digest,
                "stop_evidence": asdict(self._stop_evidence) if self._stop_evidence else None,
            },
        )

    def _refresh_persisted_state(self) -> None:
        if not (self.run_dir / _STATE_FILE).is_file():
            return
        persisted = type(self).load(self.run_dir, repository=self.repository)
        self._candidate_digest = persisted._candidate_digest
        self._work_baseline_sha = persisted._work_baseline_sha
        self._admitted = persisted._admitted
        self._leases = dict(persisted._leases)
        self._results = dict(persisted._results)
        self._pending_lease_admission_keys = set(persisted._pending_lease_admission_keys)
        self._pending_result_admission_keys = set(persisted._pending_result_admission_keys)
        self._published_candidate_head = persisted._published_candidate_head
        self._repair_admission_digest = persisted._repair_admission_digest
        self._cancelled = persisted._cancelled
        self._revocation_digest = persisted._revocation_digest
        self._stop_evidence = persisted._stop_evidence
        self._effect_events = list(persisted._effect_events)
        self._active_worktrees = dict(persisted._active_worktrees)
        self._worktree_attempts = dict(persisted._worktree_attempts)

    def _load_active_worktrees(self) -> None:
        self._active_worktrees.clear()
        path = self.run_dir / _ACTIVE_WORKTREES_FILE
        if not path.is_file():
            return
        raw = json.loads(path.read_text())
        if not isinstance(raw, Mapping):
            raise AtomicityViolation("active worktree registry is malformed")
        for task_id, record in raw.items():
            if (
                not isinstance(record, Mapping)
                or "repo" not in record
                or "worktree" not in record
                or str(task_id) not in self._leases
            ):
                raise AtomicityViolation("active worktree registry is malformed")
            repo = Path(str(record["repo"]))
            worktree = Path(str(record["worktree"]))
            if not repo.is_absolute() or not worktree.is_absolute():
                raise AtomicityViolation("active worktree registry is malformed")
            self._active_worktrees[str(task_id)] = (repo, worktree)

    def _refresh_worktree_authority(self) -> None:
        path = self.run_dir / _STATE_FILE
        if not path.is_file():
            raise AtomicityViolation("missing persisted worktree authority")
        self._refresh_persisted_state()

    def _save_active_worktrees(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.run_dir / _ACTIVE_WORKTREES_FILE,
            {
                task_id: {"repo": str(repo), "worktree": str(worktree)}
                for task_id, (repo, worktree) in sorted(self._active_worktrees.items())
            },
        )


def _primary_pr_body(issue: IssueRecord, candidate: IssueCandidate) -> str:
    return (
        f"Relates to #{issue.number}.\n\n"
        "## Outcome\n\n"
        f"{candidate.outcome}\n\n"
        "## Decisions\n\n"
        "One issue, one exact-base branch, one primary draft PR.\n\n"
        "## Tests / evidence\n\n"
        f"Test plan `{candidate.test_plan_digest}`; meaningful red "
        f"`{candidate.meaningful_red_digest}`.\n\n"
        "## Risks\n\nRepository identity, scope escape, and stale evidence.\n\n"
        "## Rollback\n\nClose only this draft PR and dedicated branch; "
        "never rewrite shared history.\n"
    )


def _normalize_allowed_path(value: str) -> str:
    raw = value.replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw.startswith("/") or ".." in path.parts:
        raise ValueError(f"unsafe allowed path: {value!r}")
    normalized = path.as_posix()
    return normalized.rstrip("/") + ("/" if raw.endswith("/") else "")


def _normalize_changed_path(value: str) -> str:
    raw = value.replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw.startswith("/") or ".." in path.parts or raw.endswith("/"):
        raise AtomicityViolation(f"unsafe changed path: {value!r}")
    return path.as_posix()


def _path_allowed(path: str, allowed: str) -> bool:
    normalized = _normalize_allowed_path(allowed)
    return path.startswith(normalized) if normalized.endswith("/") else path == normalized


def _git_tree_entry(git: LocalGitAdapter, commit_sha: str, path: str) -> str:
    try:
        entry = git._run("ls-tree", commit_sha, "--", path)  # noqa: SLF001
        return entry.split("\t", maxsplit=1)[0] if entry else "<missing>"
    except GitError:
        return "<missing>"


def _decode_admitted(raw: Mapping[str, object]) -> AdmittedSlice:
    return AdmittedSlice(
        candidate_digest=str(raw["candidate_digest"]),
        issue=IssueRecord(**raw["issue"]),  # type: ignore[arg-type]
        branch=BranchRecord(**raw["branch"]),  # type: ignore[arg-type]
        planning_commit=PlanningCommitRecord(**raw["planning_commit"]),  # type: ignore[arg-type]
        pull_request=PullRequestRecord(**raw["pull_request"]),  # type: ignore[arg-type]
    )


def _decode_lease(raw: Mapping[str, object]) -> SpecialistLease:
    task_raw = raw["task"]
    if not isinstance(task_raw, Mapping):
        raise AtomicityViolation("persisted specialist task is malformed")
    task = SpecialistTask(
        task_id=str(task_raw["task_id"]),
        specialist=str(task_raw["specialist"]),
        allowed_paths=tuple(task_raw["allowed_paths"]),
        required_capability=str(task_raw.get("required_capability", "")),
    )
    return SpecialistLease(
        task=task,
        admitted_candidate_digest=str(raw["admitted_candidate_digest"]),
        baseline_sha=str(raw["baseline_sha"]),
        lease_epoch_digest=str(raw["lease_epoch_digest"]),
        repair_admission_digest=str(raw.get("repair_admission_digest", "")),
        revoked=bool(raw.get("revoked", False)),
    )
