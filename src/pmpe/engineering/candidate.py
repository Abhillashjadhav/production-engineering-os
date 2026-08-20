"""Candidate freeze: the immutable review target.

candidate-manifest.json binds the candidate commit, the content tree digest, and
the contract digest at freeze time. Reviews, approvals, and deployments bind to
this digest; any change to the tree invalidates them all (fail closed).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pmpe.assurance.readonly_guard import tree_digest as file_map
from pmpe.contracts.digest import canonical_digest
from pmpe.domain.errors import PmpeError
from pmpe.domain.serialize import atomic_write_json, jsonable
from pmpe.gitops.local import LocalGitAdapter
from pmpe.telemetry.events import utc_now


class CandidateViolation(PmpeError):  # noqa: N818 — deliberate: it is a violation
    """The candidate tree no longer matches its frozen manifest."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    commit: str
    tree_digest: str
    contract_digest: str
    frozen_at: str


_GIT_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_CONTENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReviewSubject:
    """Exact Git and policy inputs that advisory/readiness evidence reviews."""

    protected_base_sha: str
    pr_head_sha: str
    prospective_merge_tree_digest: str
    repository_rules_digest: str
    architecture_policy_digest: str
    toolchain_policy_digest: str
    environment_profile_digest: str
    security_policy_digest: str
    verification_policy_digest: str
    evidence_policy_digest: str
    frozen_at: str

    @property
    def digest(self) -> str:
        return canonical_digest(self)


def _combined_digest(files: dict[str, str]) -> str:
    # one digest home for the whole system (see pmpe.contracts.digest)
    return canonical_digest(files)


def tree_content_digest(repo: Path) -> str:
    """The content digest of a workspace tree — the same digest a freeze records."""
    return _combined_digest(file_map(Path(repo)))


def freeze_candidate(repo: Path, run_dir: Path, *, contract_digest: str) -> Candidate:
    repo = Path(repo)
    run_dir = Path(run_dir)
    git = LocalGitAdapter(repo)
    commit = git._run("rev-parse", "HEAD")  # noqa: SLF001
    dirty = git._run("status", "--porcelain")  # noqa: SLF001
    if dirty.strip():
        raise CandidateViolation(
            f"cannot freeze a dirty worktree: the manifest would record commit "
            f"{commit[:12]} while the digest certifies uncommitted content — "
            "commit or discard first: " + "; ".join(dirty.strip().splitlines()[:5])
        )
    digest = _combined_digest(file_map(repo))

    history_dir = run_dir / "candidates"
    history_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = f"CAND-{len(list(history_dir.glob('CAND-*.json'))) + 1:03d}"
    candidate = Candidate(
        candidate_id=candidate_id,
        commit=commit,
        tree_digest=digest,
        contract_digest=contract_digest,
        frozen_at=utc_now(),
    )
    payload = jsonable(candidate)
    atomic_write_json(history_dir / f"{candidate_id}.json", payload)
    atomic_write_json(run_dir / "candidate-manifest.json", payload)
    return candidate


def load_candidate(run_dir: Path) -> Candidate:
    path = Path(run_dir) / "candidate-manifest.json"
    if not path.exists():
        raise CandidateViolation(f"no frozen candidate at {path}")
    raw = json.loads(path.read_text())
    return Candidate(
        candidate_id=raw["candidate_id"],
        commit=raw["commit"],
        tree_digest=raw["tree_digest"],
        contract_digest=raw["contract_digest"],
        frozen_at=raw["frozen_at"],
    )


def verify_frozen(repo: Path, run_dir: Path) -> Candidate:
    candidate = load_candidate(run_dir)
    current = _combined_digest(file_map(Path(repo)))
    if current != candidate.tree_digest:
        raise CandidateViolation(
            f"candidate {candidate.candidate_id} tree changed after freeze "
            f"(frozen {candidate.tree_digest}, found {current}) — reviews and approvals "
            "bound to this candidate are invalid"
        )
    return candidate


def freeze_review_subject(run_dir: Path, subject: ReviewSubject) -> str:
    """Persist one immutable readiness subject; retries are exact or rejected."""

    if not _GIT_SHA.fullmatch(subject.protected_base_sha) or not _GIT_SHA.fullmatch(
        subject.pr_head_sha
    ):
        raise CandidateViolation("review subject requires exact base and head SHAs")
    digest_fields = (
        subject.prospective_merge_tree_digest,
        subject.repository_rules_digest,
        subject.architecture_policy_digest,
        subject.toolchain_policy_digest,
        subject.environment_profile_digest,
        subject.security_policy_digest,
        subject.verification_policy_digest,
        subject.evidence_policy_digest,
    )
    if any(not _CONTENT_DIGEST.fullmatch(value) for value in digest_fields):
        raise CandidateViolation("review subject policy/tree digests are malformed")
    path = Path(run_dir) / "review-subject.json"
    payload = jsonable(subject)
    if path.exists():
        if json.loads(path.read_text()) != payload:
            raise CandidateViolation("review subject changed after freeze")
        return subject.digest
    atomic_write_json(path, payload)
    return subject.digest


def verify_review_subject(run_dir: Path, observed: ReviewSubject) -> str:
    path = Path(run_dir) / "review-subject.json"
    if not path.exists() or json.loads(path.read_text()) != jsonable(observed):
        raise CandidateViolation("protected base, PR head, merge tree, or policy changed")
    return observed.digest
