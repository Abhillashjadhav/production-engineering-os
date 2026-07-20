"""Sandbox remediation PRs and the gated merge decision (M7).

Auto-merge authority applies only to sandbox remediation PRs — never to
any real repository and never to the auditor's own branch (PD-PA-05,
PD-08). Remediation PRs are generated ONLY for findings with an honest
mechanical fix: today that is secret removal, where the fix is provably
correct from the finding itself. Findings that need human judgment (claim
rewrites, lockfile generation) get NO generated fix — fabricating one
would itself be the forbidden action ``insufficient_evidence``.

``decide_merge`` is a fail-closed pure function: every policy gate must be
explicitly true (a missing key fails), any forbidden action refuses, the
PR must bind the sandbox's exact snapshot digest, and a non-sandbox target
refuses unconditionally. ``apply_merge`` refuses to apply anything but a
MERGE decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pmpe.domain.errors import PmpeError
from pmpe.portfolio.inspection import DeepInspection
from pmpe.portfolio.policy import AuditorPolicy, load_policy
from pmpe.portfolio.scanner import RepoScan

GENERATOR_VERSION = "pa-remediation-1"


@dataclass(frozen=True)
class SandboxRepo:
    """A sandbox working copy: files plus the snapshot digest they represent."""

    repository: str
    files: dict[str, str]
    snapshot_digest: str


@dataclass
class RemediationPR:
    """One generated, sandbox-only remediation proposal.

    ``patch`` maps each affected path to the replacement text for its
    flagged lines; ``line_edits`` names the exact 1-indexed lines replaced.
    The patch never contains a removed value — only the replacement marker.
    """

    pr_id: str
    repository: str
    finding_ids: tuple[str, ...]
    base_snapshot_digest: str
    patch: dict[str, str]
    line_edits: dict[str, tuple[int, ...]]
    description: str
    sandbox_only: bool = True
    flags: tuple[str, ...] = field(default_factory=tuple)
    generator_version: str = GENERATOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_id": self.pr_id,
            "repository": self.repository,
            "finding_ids": list(self.finding_ids),
            "base_snapshot_digest": self.base_snapshot_digest,
            "patch": dict(sorted(self.patch.items())),
            "line_edits": {k: list(v) for k, v in sorted(self.line_edits.items())},
            "description": self.description,
            "sandbox_only": self.sandbox_only,
            "flags": list(self.flags),
            "generator_version": self.generator_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RemediationPR:
        return cls(
            pr_id=str(d["pr_id"]),
            repository=str(d["repository"]),
            finding_ids=tuple(str(f) for f in d.get("finding_ids", [])),
            base_snapshot_digest=str(d["base_snapshot_digest"]),
            patch={str(k): str(v) for k, v in d.get("patch", {}).items()},
            line_edits={
                str(k): tuple(int(x) for x in v) for k, v in d.get("line_edits", {}).items()
            },
            description=str(d.get("description", "")),
            sandbox_only=bool(d.get("sandbox_only", True)),
            flags=tuple(str(f) for f in d.get("flags", [])),
            generator_version=str(d.get("generator_version", GENERATOR_VERSION)),
        )


def generate_remediation_prs(scan: RepoScan, inspection: DeepInspection) -> list[RemediationPR]:
    """Generate sandbox remediation PRs for honestly-fixable findings only.

    Secret findings are mechanically fixable: the flagged lines are replaced
    with a removal marker naming the finding — correct by construction and
    carrying no secret value. Everything else stays on the human backlog.
    """
    # Anchored match: finding ids embed the repo NAME, so a repository
    # legally named with "-SEC-" in it must not turn its claim-gap or
    # dependency findings into "secret" findings (M7 review blocker —
    # repo-name injection). A PR is also never emitted without actual
    # secret hits to point its line edits at.
    sec_id = re.compile(rf"PA-{re.escape(scan.name)}-SEC-\d{{3}}\Z")
    secret_findings = [f for f in inspection.findings if sec_id.fullmatch(f.finding_id)]
    if not secret_findings or not scan.security.secret_hits:
        return []
    by_path: dict[str, list[int]] = {}
    for hit in scan.security.secret_hits:
        by_path.setdefault(hit.path, []).append(hit.line)
    finding_ids = tuple(sorted(f.finding_id for f in secret_findings))
    patch: dict[str, str] = {}
    line_edits: dict[str, tuple[int, ...]] = {}
    for path, lines in sorted(by_path.items()):
        uniq = tuple(sorted(set(lines)))
        line_edits[path] = uniq
        patch[path] = (
            "# credential removed — rotate the secret and load it from the "
            f"environment (findings: {', '.join(finding_ids)})"
        )
    return [
        RemediationPR(
            pr_id=f"RPR-{scan.name}-001",
            repository=f"{scan.owner}/{scan.name}",
            finding_ids=finding_ids,
            base_snapshot_digest=inspection.snapshot_digest,
            patch=patch,
            line_edits=line_edits,
            description=(
                f"Remove {sum(len(v) for v in line_edits.values())} committed "
                f"secret-shaped line(s) across {len(patch)} file(s); resolves "
                f"{', '.join(finding_ids)}. Values are not reproduced anywhere "
                "in this proposal; rotate the credentials before merging."
            ),
        )
    ]


@dataclass(frozen=True)
class MergeDecision:
    """The gated auto-merge decision — REFUSE names every failed condition."""

    decision: str  # "MERGE" | "REFUSE"
    failing_gates: tuple[str, ...]
    forbidden_hits: tuple[str, ...]
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "failing_gates": list(self.failing_gates),
            "forbidden_hits": list(self.forbidden_hits),
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MergeDecision:
        return cls(
            decision=str(d["decision"]),
            failing_gates=tuple(str(g) for g in d.get("failing_gates", [])),
            forbidden_hits=tuple(str(f) for f in d.get("forbidden_hits", [])),
            reasoning=str(d.get("reasoning", "")),
        )


def decide_merge(
    pr: RemediationPR,
    *,
    gates: dict[str, bool],
    sandbox: SandboxRepo,
    policy: AuditorPolicy | None = None,
) -> MergeDecision:
    """Fail-closed gated merge decision for one sandbox remediation PR."""
    pol = policy or load_policy()
    reasons: list[str] = []

    if not pr.sandbox_only:
        return MergeDecision(
            decision="REFUSE",
            failing_gates=(),
            forbidden_hits=(),
            reasoning=(
                f"{pr.pr_id} targets a non-sandbox repository — auto-merge "
                "authority applies to sandbox remediation PRs only, never to a "
                "real repository or the auditor's own branch (PD-PA-05, PD-08)"
            ),
        )
    if pr.repository != sandbox.repository:
        return MergeDecision(
            decision="REFUSE",
            failing_gates=(),
            forbidden_hits=(),
            reasoning=(
                f"{pr.pr_id} targets {pr.repository} but the sandbox holds "
                f"{sandbox.repository} — refusing a cross-repository merge"
            ),
        )

    failing = [
        gate for gate in pol.remediation.auto_merge_required_gates if gates.get(gate) is not True
    ]
    if pr.base_snapshot_digest != sandbox.snapshot_digest:
        if "bound_to_inspected_commit" not in failing:
            failing.append("bound_to_inspected_commit")
        reasons.append(
            "the sandbox snapshot drifted from the inspected state the PR was "
            f"generated against ({pr.base_snapshot_digest} != {sandbox.snapshot_digest})"
        )
    forbidden = tuple(f for f in pr.flags if f in pol.remediation.forbidden_auto_merge_actions)

    if failing or forbidden:
        if failing:
            reasons.insert(0, f"gates not affirmatively passed: {', '.join(failing)}")
        if forbidden:
            reasons.append(f"forbidden auto-merge action(s) flagged: {', '.join(forbidden)}")
        return MergeDecision(
            decision="REFUSE",
            failing_gates=tuple(failing),
            forbidden_hits=forbidden,
            reasoning="; ".join(reasons),
        )
    return MergeDecision(
        decision="MERGE",
        failing_gates=(),
        forbidden_hits=(),
        reasoning=(
            f"all {len(pol.remediation.auto_merge_required_gates)} gates "
            f"affirmatively passed for {pr.pr_id} in sandbox {sandbox.repository}, "
            "snapshot digest bound, no forbidden actions"
        ),
    )


def apply_merge(sandbox: SandboxRepo, pr: RemediationPR, decision: MergeDecision) -> dict[str, str]:
    """Apply a MERGE decision to the sandbox files (pure; returns new files)."""
    if decision.decision != "MERGE":
        raise PmpeError(
            f"refusing to apply {pr.pr_id}: the merge decision is REFUSE ({decision.reasoning})"
        )
    # Defense in depth (M7 review notes 3-4): a decision object is
    # in-process state and could be forged — re-assert the two invariants
    # that make application safe, and treat an out-of-range line edit as a
    # tamper tripwire rather than skipping it silently.
    if not pr.sandbox_only:
        raise PmpeError(f"refusing to apply {pr.pr_id}: not a sandbox-only PR (PD-PA-05, PD-08)")
    if pr.base_snapshot_digest != sandbox.snapshot_digest:
        raise PmpeError(
            f"refusing to apply {pr.pr_id}: snapshot digest mismatch "
            f"({pr.base_snapshot_digest} != {sandbox.snapshot_digest})"
        )
    patched = dict(sandbox.files)
    for path, lines in pr.line_edits.items():
        original = patched.get(path, "")
        rows = original.split("\n")
        for lineno in lines:
            if not 1 <= lineno <= len(rows):
                raise PmpeError(
                    f"refusing to apply {pr.pr_id}: line edit {path}:{lineno} lies "
                    f"outside the snapshot ({len(rows)} lines) — possible tampering"
                )
            rows[lineno - 1] = pr.patch[path]
        patched[path] = "\n".join(rows)
    return patched
