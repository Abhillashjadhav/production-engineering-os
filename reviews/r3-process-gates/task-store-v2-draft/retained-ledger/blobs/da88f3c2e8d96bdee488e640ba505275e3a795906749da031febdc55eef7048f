"""Integrated V3 orchestration: the FullStackRun (PD-V3-15/16/17).

A thin, fail-closed state machine over the V2 primitives (evidence ledger,
candidate freeze, read-only guard) that emits the extended event grammar the
TRAJ-FS rules judge. It does not replace the V2 EngineeringRun — it is the
full-stack path, enforcing V2's core disciplines through the same primitives:

- the fullstack contract must be runnable and stack-assessable at start, and
  the six-lens roster read-only proven (PD-V3-15);
- no frontend implementation before a validated journey (PD-V3-16), enforced
  through ``require_validated_journey``'s digest-bound record;
- the committed API contract must be verified current before freeze
  (PD-V3-13); drift is recorded as evidence and refused;
- browser verification against a mocked backend is refused outright;
- preview evidence is verified through ``verify_preview`` (fail closed) and
  bound to the frozen candidate digest in the ledger (PD-V3-10/14);
- reviews run under snapshot/verify read-only proofs; a write is recorded as
  ``modified`` and refused;
- the release report requires the full six-lens roster, an executed
  accessibility suite, and verified preview evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmpe.agents.permissions import (
    FULLSTACK_REVIEW_LENSES,
    assert_fullstack_reviewers_read_only,
)
from pmpe.agents.registry import AgentRegistry
from pmpe.assurance.readonly_guard import readonly_snapshot, verify_unmodified
from pmpe.domain.errors import PmpeError
from pmpe.engineering.candidate import Candidate, freeze_candidate
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.fullstack.contract import FullStackProductContract, load_fullstack_contract
from pmpe.fullstack.journey import (
    record_validated_journey,
    require_validated_journey,
    validate_ux_architecture,
)
from pmpe.fullstack.preview import verify_preview
from pmpe.fullstack.stack import REFERENCE_STACK

_CORE = "pmpe-core"
_STATE_FILE = "fullstack-run-state.json"
REQUIRED_LENSES = tuple(FULLSTACK_REVIEW_LENSES.values())
_RELEASE_VERDICTS = ("PROCEED", "HOLD", "INSUFFICIENT_EVIDENCE")

# Per-lens reviewer-integrity states for the read-only proof:
#   valid                  — snapshot/verify clean; the reviewer touched nothing
#   infrastructure_invalid — the proof could not be validly established because
#                            of infrastructure interference (e.g. harness
#                            runtime-file churn), NOT a reviewer write; the
#                            findings still stand, only the mechanical proof is
#                            unavailable
#   compromised            — a real tracked-file modification (never recorded as
#                            a review — ``end_review`` raises)
INTEGRITY_VALID = "valid"
INTEGRITY_INFRASTRUCTURE_INVALID = "infrastructure_invalid"


class OrchestrationViolation(PmpeError):  # noqa: N818 — deliberate: it is a violation
    """A full-stack gate refused the requested step."""


@dataclass(frozen=True)
class ReleaseReport:
    """The release verdict as three separated dimensions.

    ``product_verdict`` answers "ship it?"; ``verification_integrity`` answers
    "can we trust the reviewer proofs?"; the reviewer *findings* live in the
    per-lens review artifacts (this object records that all six lenses reviewed
    and each lens's integrity state). A PROCEED requires intact integrity; an
    honest HOLD or INSUFFICIENT_EVIDENCE may be issued even when a proof is
    infrastructure-invalid.
    """

    product_verdict: str
    verification_integrity: str  # "valid" | "degraded"
    integrity_by_lens: dict[str, str] = field(default_factory=dict)
    lenses_reviewed: tuple[str, ...] = ()


class FullStackRun:
    def __init__(
        self, run_dir: Path, contract: FullStackProductContract, state: dict[str, Any]
    ) -> None:
        self.run_dir = Path(run_dir)
        self.contract = contract
        self._state = state
        # reviews: lens -> {"integrity": <state>, "reason"?: str}. Default here so
        # a run persisted before the integrity model loads without a crash.
        self._state.setdefault("reviews", {})
        self._state.setdefault("release_integrity", "")
        self.ledger = EvidenceLedger(self.run_dir, run_id=str(state["run_id"]))
        self._snapshots: dict[str, dict[str, str]] = {}

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def start(cls, contract_path: Path, run_dir: Path, *, agents_dir: Path) -> FullStackRun:
        run_dir = Path(run_dir)
        if (run_dir / _STATE_FILE).exists():
            raise OrchestrationViolation(
                f"a full-stack run already exists at {run_dir} — resume it instead"
            )
        contract = load_fullstack_contract(Path(contract_path))
        if not contract.runnable:
            raise OrchestrationViolation(
                "the contract is not runnable: " + "; ".join(contract.blockers)
            )
        problems = REFERENCE_STACK.assess_contract(contract)
        if problems:
            raise OrchestrationViolation("the stack refuses this contract: " + "; ".join(problems))
        assert_fullstack_reviewers_read_only(AgentRegistry(Path(agents_dir)))
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "fullstack-contract.json").write_text(Path(contract_path).read_text())
        state: dict[str, Any] = {
            "run_id": f"fs-{contract.contract_id.lower()}",
            "contract_digest": contract.digest,
            "journey_validated": False,
            "api_contract_current": False,
            "candidate_digest": "",
            "browser_suites": [],
            "preview_recorded": False,
            "reviews": {},
            "release_verdict": "",
            "release_integrity": "",
        }
        run = cls(run_dir, contract, state)
        run.ledger.record(
            stage="contract_lock",
            agent=_CORE,
            action="lock",
            output_digests={"contract": contract.digest},
        )
        run._save()
        return run

    @classmethod
    def load(cls, run_dir: Path) -> FullStackRun:
        run_dir = Path(run_dir)
        path = run_dir / _STATE_FILE
        if not path.exists():
            raise OrchestrationViolation(f"no full-stack run at {run_dir}")
        state: dict[str, Any] = json.loads(path.read_text())
        contract = load_fullstack_contract(run_dir / "fullstack-contract.json")
        if contract.digest != state["contract_digest"]:
            raise OrchestrationViolation(
                "the run's contract file no longer matches the locked digest"
            )
        return cls(run_dir, contract, state)

    @property
    def contract_digest(self) -> str:
        return str(self._state["contract_digest"])

    @property
    def candidate_digest(self) -> str:
        return str(self._state["candidate_digest"])

    def events(self) -> list[dict[str, Any]]:
        ledger_path = self.run_dir / "ledger.jsonl"
        if not ledger_path.exists():
            return []
        return [json.loads(line) for line in ledger_path.read_text().splitlines() if line.strip()]

    # -- journey (PD-V3-16) --------------------------------------------------

    def validate_journey(self) -> None:
        problems = validate_ux_architecture(self.contract)
        if problems:
            raise OrchestrationViolation(
                "the UX architecture is incoherent: " + "; ".join(problems)
            )
        record_validated_journey(self.run_dir, self.contract)
        self._state["journey_validated"] = True
        self.ledger.record(
            stage="journey_validation",
            agent=_CORE,
            action="validate",
            input_digests={"contract": self.contract_digest},
            output_digests={"journey_record": self.contract_digest},
        )
        self._save()

    # -- V2-arc pass-through emitters ---------------------------------------

    def record_architecture(self, *, agent: str, digest: str) -> None:
        self.ledger.record(
            stage="architecture",
            agent=agent,
            action="submit_architecture",
            input_digests={"contract": self.contract_digest},
            output_digests={"architecture_pack": digest},
        )

    def record_plan(self, *, agent: str, digest: str) -> None:
        self.ledger.record(
            stage="plan",
            agent=agent,
            action="submit_plan",
            input_digests={"contract": self.contract_digest},
            output_digests={"plan": digest},
        )

    def record_routing(self, *, agent: str, selected: tuple[str, ...]) -> None:
        self.ledger.record(
            stage="route",
            agent=agent,
            action="submit_routing",
            detail="selected=" + ",".join(selected),
        )

    def record_implementation(self, *, agent: str, action: str, task: str, surface: str) -> None:
        if surface not in ("frontend", "backend"):
            raise OrchestrationViolation(f"unknown surface '{surface}'")
        if surface == "frontend":
            # fail closed through the digest-bound journey record, not a flag
            require_validated_journey(self.run_dir, self.contract_digest)
        self.ledger.record(
            stage="implement",
            agent=agent,
            action=action,
            detail=f"task={task};surface={surface}",
        )

    # -- API contract (PD-V3-13) --------------------------------------------

    def record_api_contract(self, *, current: bool) -> None:
        verdict = "current" if current else "drift"
        self.ledger.record(stage="api_contract", agent=_CORE, action="verify", verdict=verdict)
        if not current:
            raise OrchestrationViolation(
                "the committed API contract drifted from the live application — "
                "regenerate and re-review before proceeding"
            )
        self._state["api_contract_current"] = True
        self._save()

    # -- freeze --------------------------------------------------------------

    def freeze(self, repo: Path) -> Candidate:
        if not self._state["journey_validated"]:
            raise OrchestrationViolation("cannot freeze before the journey is validated")
        # the flag alone is tamperable state — the digest-bound record is the
        # evidence (same asymmetry fix as record_implementation)
        require_validated_journey(self.run_dir, self.contract_digest)
        if not self._state["api_contract_current"]:
            raise OrchestrationViolation(
                "cannot freeze without a current api-contract verification"
            )
        candidate = freeze_candidate(Path(repo), self.run_dir, contract_digest=self.contract_digest)
        self._state["candidate_digest"] = candidate.tree_digest
        self.ledger.record(
            stage="freeze",
            agent=_CORE,
            action="freeze",
            output_digests={"candidate": candidate.tree_digest},
        )
        self._save()
        return candidate

    # -- browser verification (PD-V3-16) ------------------------------------

    def record_browser_verification(
        self, *, suites: tuple[str, ...], mocked: bool, passed: bool
    ) -> None:
        if mocked:
            raise OrchestrationViolation(
                "browser verification against a mocked backend is not evidence (PD-V3-16)"
            )
        if not passed:
            raise OrchestrationViolation("a failed browser verification cannot be recorded as done")
        self._require_candidate()
        self.ledger.record(
            stage="browser_verification",
            agent=_CORE,
            action="verify",
            detail="suites=" + ",".join(suites) + ";mocked=false",
            input_digests={"candidate": self.candidate_digest},
            verdict="passed",
        )
        self._state["browser_suites"] = sorted(set(self._state["browser_suites"]) | set(suites))
        self._save()

    # -- preview (PD-V3-10/14) ----------------------------------------------

    def record_preview(self, evidence_path: Path, *, expected_source_digest: str) -> None:
        self._require_candidate()
        problems = verify_preview(
            Path(evidence_path), expected_source_digest=expected_source_digest
        )
        if problems:
            raise OrchestrationViolation("preview evidence refused: " + "; ".join(problems))
        kind = json.loads(Path(evidence_path).read_text())["deployment_kind"]
        self.ledger.record(
            stage="preview",
            agent=_CORE,
            action="record",
            detail=f"kind={kind}",
            input_digests={"candidate": self.candidate_digest},
            output_digests={"preview_evidence": expected_source_digest},
        )
        self._state["preview_recorded"] = True
        self._save()

    # -- six-lens reviews (PD-V3-15) -----------------------------------------

    def begin_review(self, lens_agent: str, repo: Path) -> None:
        if lens_agent not in REQUIRED_LENSES:
            raise OrchestrationViolation(f"'{lens_agent}' is not on the six-lens roster")
        self._require_candidate()
        self._snapshots[lens_agent] = readonly_snapshot(Path(repo))

    def end_review(self, lens_agent: str, repo: Path) -> None:
        before = self._snapshots.pop(lens_agent, None)
        if before is None:
            raise OrchestrationViolation(f"no open review for '{lens_agent}'")
        self.ledger.record(
            stage="review",
            agent=lens_agent,
            action="submit_review",
            input_digests={"candidate": self.candidate_digest},
        )
        changed = verify_unmodified(Path(repo), before)
        verdict = "clean" if not changed else "modified"
        self.ledger.record(
            stage="review", agent=lens_agent, action="readonly_check", verdict=verdict
        )
        if changed:
            # a real tracked-file change is a genuine compromise, never recorded
            # as a completed review — the run cannot reach release with it
            raise OrchestrationViolation(
                f"reviewer '{lens_agent}' violated read-only: " + "; ".join(changed[:5])
            )
        self._state["reviews"][lens_agent] = {"integrity": INTEGRITY_VALID}
        self._save()

    def record_infrastructure_invalid_review(self, lens_agent: str, *, reason: str) -> None:
        """Record a review whose read-only proof could not be validly established
        because of infrastructure interference (e.g. a harness runtime file the
        harness itself churned), NOT a reviewer write.

        The reviewer's findings still stand; only the mechanical integrity proof
        is unavailable, and that is recorded honestly as audit evidence. A run
        carrying such a review may still issue HOLD/INSUFFICIENT_EVIDENCE but is
        refused PROCEED (integrity is degraded, not intact).
        """
        if lens_agent not in REQUIRED_LENSES:
            raise OrchestrationViolation(f"'{lens_agent}' is not on the six-lens roster")
        self._require_candidate()
        self._snapshots.pop(lens_agent, None)
        self.ledger.record(
            stage="review",
            agent=lens_agent,
            action="submit_review",
            input_digests={"candidate": self.candidate_digest},
        )
        self.ledger.record(
            stage="review",
            agent=lens_agent,
            action="readonly_check",
            verdict=INTEGRITY_INFRASTRUCTURE_INVALID,
            detail=reason,
        )
        self._state["reviews"][lens_agent] = {
            "integrity": INTEGRITY_INFRASTRUCTURE_INVALID,
            "reason": reason,
        }
        self._save()

    # -- release -------------------------------------------------------------

    def release_report(self, *, verdict: str) -> ReleaseReport:
        """Emit the release verdict across three separated dimensions.

        - product verdict (the argument, vocabulary-bound);
        - reviewer findings — represented here by all six lenses having a review;
        - verification integrity — ``valid`` if every read-only proof is intact,
          ``degraded`` if one or more are infrastructure-invalid.

        PROCEED requires ``valid`` integrity; HOLD and INSUFFICIENT_EVIDENCE are
        honest even when integrity is ``degraded``.
        """
        if verdict not in _RELEASE_VERDICTS:
            raise OrchestrationViolation(
                f"'{verdict}' is not a release verdict (PROCEED/HOLD/INSUFFICIENT_EVIDENCE)"
            )
        reviews: dict[str, Any] = self._state["reviews"]
        missing = set(REQUIRED_LENSES) - set(reviews)
        if missing:
            raise OrchestrationViolation(
                "release refused — lens(es) without a review: " + ", ".join(sorted(missing))
            )
        if "a11y" not in self._state["browser_suites"]:
            raise OrchestrationViolation(
                "release refused — no executed accessibility suite in this run"
            )
        if not self._state["preview_recorded"]:
            raise OrchestrationViolation("release refused — no verified preview evidence")
        integrity_by_lens = {lens: reviews[lens]["integrity"] for lens in REQUIRED_LENSES}
        integrity = (
            INTEGRITY_VALID
            if all(s == INTEGRITY_VALID for s in integrity_by_lens.values())
            else "degraded"
        )
        if verdict == "PROCEED" and integrity != INTEGRITY_VALID:
            raise OrchestrationViolation(
                "PROCEED refused — verification integrity is degraded "
                "(a reviewer-integrity proof is infrastructure-invalid); "
                "only HOLD or INSUFFICIENT_EVIDENCE may be issued"
            )
        self.ledger.record(
            stage="release_report",
            agent=_CORE,
            action="report",
            input_digests={"candidate": self.candidate_digest},
            verdict=verdict,
            detail=f"integrity={integrity}",
        )
        self._state["release_verdict"] = verdict
        self._state["release_integrity"] = integrity
        self._save()
        return ReleaseReport(
            product_verdict=verdict,
            verification_integrity=integrity,
            integrity_by_lens=integrity_by_lens,
            lenses_reviewed=REQUIRED_LENSES,
        )

    # -- internals -----------------------------------------------------------

    def _require_candidate(self) -> None:
        if not self.candidate_digest:
            raise OrchestrationViolation("no frozen candidate yet — freeze first")

    def _save(self) -> None:
        (self.run_dir / _STATE_FILE).write_text(json.dumps(self._state, indent=2) + "\n")
