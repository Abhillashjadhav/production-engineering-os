"""The fixer allowlist gate (PD-07).

The Approved Findings Fixer's authority is exactly the ACCEPTED finding IDs and
the files those findings name. Everything else — undecided findings, rejected
findings, product decisions, unrelated files — is out of scope and fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from pmpe.assurance.findings import FindingsStore
from pmpe.domain.errors import PmpeError


class FixScopeViolation(PmpeError):  # noqa: N818 — deliberate: it is a violation
    """The fixer attempted to act outside its accepted-findings allowlist."""


@dataclass(frozen=True)
class FixScope:
    finding_ids: list[str]
    allowed_files: set[str]


class FixerGate:
    def __init__(self, store: FindingsStore, extra_allowed_files: set[str] | None = None) -> None:
        self.store = store
        self.extra_allowed_files = extra_allowed_files or set()

    def scope(self) -> FixScope:
        """Authority is granted at reconciliation and does not shrink as fixes land:
        the allowed-file set covers every accepted finding, including those already
        FIXED/VERIFIED, so multi-finding fix rounds are order-insensitive."""
        granted = [f for f in self.store.all() if f.status in ("ACCEPTED", "FIXED", "VERIFIED")]
        return FixScope(
            finding_ids=[f.finding_id for f in granted if f.status == "ACCEPTED"],
            allowed_files={f.file for f in granted if f.file} | self.extra_allowed_files,
        )

    def record_fix(
        self, finding_id: str, *, fixer: str, commits: list[str], changed_files: list[str]
    ) -> None:
        scope = self.scope()
        if finding_id not in scope.finding_ids:
            status = self.store.get(finding_id).status
            raise FixScopeViolation(
                f"{finding_id} is {status}, not ACCEPTED — the fixer may only act on "
                "accepted finding IDs (PD-07)"
            )
        out_of_scope = sorted(set(changed_files) - scope.allowed_files)
        if out_of_scope:
            raise FixScopeViolation(
                f"fix for {finding_id} touched file(s) outside the accepted scope: "
                + ", ".join(out_of_scope)
            )
        self.store.record_fixed(finding_id, fixer=fixer, commits=commits)
