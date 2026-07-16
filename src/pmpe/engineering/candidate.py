"""Candidate freeze: the immutable review target.

candidate-manifest.json binds the candidate commit, the content tree digest, and
the contract digest at freeze time. Reviews, approvals, and deployments bind to
this digest; any change to the tree invalidates them all (fail closed).
"""

from __future__ import annotations

import json
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


def _combined_digest(files: dict[str, str]) -> str:
    # one digest home for the whole system (see pmpe.contracts.digest)
    return canonical_digest(files)


def freeze_candidate(repo: Path, run_dir: Path, *, contract_digest: str) -> Candidate:
    repo = Path(repo)
    run_dir = Path(run_dir)
    git = LocalGitAdapter(repo)
    commit = git._run("rev-parse", "HEAD")  # noqa: SLF001
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
