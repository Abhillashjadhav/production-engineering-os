"""The engineering run engine: deterministic admission over agent-proposed artifacts.

PD-11 division of labour: Claude agents produce the generative artifacts
(architecture packs, plans, routings, code, reviews); this Python core is the
only authority over state transitions, validation, and gates. Every accepted
artifact leaves a digest-bound event in the evidence ledger using exactly the
grammar the trajectory evals consume — a run the engine drives is auditable by
``evaluate_trajectory`` with no translation layer.

Resume model: ``run-state.json`` is the single persisted state document; loading
it re-verifies the locked contract (fail closed on mutation) and appends nothing
to the ledger, so an interrupted run continues exactly where it stopped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.agents.permissions import REVIEWER_NAMES, ReadOnlyViolation
from pmpe.agents.registry import AgentRegistry
from pmpe.assurance.findings import FindingsStore
from pmpe.assurance.readonly_guard import tree_digest, verify_unmodified
from pmpe.assurance.reconcile import OwnerDecision, ReconciliationResult, reconcile
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.contracts.digest import canonical_digest
from pmpe.contracts.model import load_contract
from pmpe.contracts.store import ContractStore
from pmpe.deployment.policy import (
    DeploymentDecision,
    DeploymentPolicy,
    ProductionApproval,
    load_production_approval,
    write_production_approval,
)
from pmpe.deployment.simulated import SimulatedDeployOutcome, simulate_production_deploy
from pmpe.domain.errors import PmpeError, SpecError
from pmpe.domain.serialize import atomic_write_json, jsonable
from pmpe.engineering.candidate import Candidate, freeze_candidate
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.engineering.submissions import VALIDATORS, validate_routing_submission
from pmpe.evals.registry import stage_of
from pmpe.telemetry.events import utc_now

STAGES = (
    "contract_lock",
    "assessment",
    "architecture",
    "plan",
    "route",
    "implement",
    "integrate",
    "freeze",
    "review",
    "reconcile",
    "fix",
    "retest",
    "refreeze",
    "verify",
    "draft_pr",
    "deploy",
    "release_report",
    "complete",
)

_CORE = "pmpe-core"
_STATE_FILE = "run-state.json"


class SubmissionRejected(SpecError):  # noqa: N818 — named for the admission outcome
    """The artifact failed deterministic admission; nothing was recorded."""


class DeploymentBlocked(PmpeError):  # noqa: N818 — named for the gate outcome
    """The deployment policy refused the requested environment."""


class EngineeringRun:
    """A single engineering run rooted at ``run_dir`` (its system of record)."""

    def __init__(self, run_dir: Path, state: dict[str, Any]) -> None:
        self.run_dir = Path(run_dir)
        self._state = state
        self.ledger = EvidenceLedger(self.run_dir, run_id=str(state["run_id"]))
        self._registry = AgentRegistry(Path(str(state["agents_dir"])))

    # --- lifecycle -------------------------------------------------------------------

    @classmethod
    def start(cls, contract_path: Path, run_dir: Path, *, agents_dir: Path) -> EngineeringRun:
        run_dir = Path(run_dir)
        if (run_dir / _STATE_FILE).exists():
            raise PmpeError(
                f"a run already exists at {run_dir} — resume it instead of starting over"
            )
        record = ContractStore(run_dir / "registry").lock_for_run(Path(contract_path), run_dir)
        contract = load_contract(run_dir / "contract.json")
        state: dict[str, Any] = {
            "run_id": f"eng-{record.contract_id.lower()}-v{record.version}",
            "stage": "assessment",
            "agents_dir": str(agents_dir),
            "contract": {
                "contract_id": record.contract_id,
                "contract_version": record.version,
                "digest": record.digest,
            },
            "requirement_ids": contract.requirement_ids(),
            "components": [],
            "tasks": [],
            "assignments": {},
            "implemented": [],
            "artifact_digests": {},
            "candidate_digest": "",
            "reviews_submitted": [],
            "readonly_clean": [],
            "accepted_findings": [],
            "product_findings": [],
            "fixed_findings": [],
            "verified_findings": [],
            "gates_passed": False,
            "draft_pr": "",
            "deployments": [],
            "release_verdict": "",
        }
        run = cls(run_dir, state)
        run.ledger.record(
            stage="contract_lock",
            agent=_CORE,
            action="lock",
            output_digests={"contract": record.digest},
        )
        run._save()
        return run

    @classmethod
    def load(cls, run_dir: Path) -> EngineeringRun:
        """Resume: re-read state, fail closed if the locked contract was touched."""
        run_dir = Path(run_dir)
        path = run_dir / _STATE_FILE
        if not path.exists():
            raise PmpeError(f"no engineering run at {run_dir} (missing {_STATE_FILE})")
        state: dict[str, Any] = json.loads(path.read_text())
        ContractStore(run_dir / "registry").verify_unchanged(run_dir)
        return cls(run_dir, state)

    @property
    def stage(self) -> str:
        return str(self._state["stage"])

    @property
    def contract_digest(self) -> str:
        return str(self._state["contract"]["digest"])

    def status(self) -> dict[str, Any]:
        pending_tasks = sorted(set(self._state["assignments"]) - set(self._state["implemented"]))
        return {
            "run_id": self._state["run_id"],
            "stage": self.stage,
            "contract": dict(self._state["contract"]),
            "candidate_digest": self._state["candidate_digest"],
            "tasks": [str(t.get("id")) for t in self._state["tasks"]],
            "pending_tasks": pending_tasks,
            "reviews_submitted": list(self._state["reviews_submitted"]),
            "accepted_findings": list(self._state["accepted_findings"]),
            "product_findings": list(self._state["product_findings"]),
            "gates_passed": bool(self._state["gates_passed"]),
            "draft_pr": self._state["draft_pr"],
            "deployments": list(self._state["deployments"]),
            "release_verdict": self._state["release_verdict"],
        }

    # --- engine-owned stage actions -------------------------------------------------

    def record_assessment(self, summary: dict[str, Any]) -> None:
        self._require_stage("assessment")
        self._write_artifact("assessment", "production-engineer-skill", summary)
        self.ledger.record(
            stage="assessment",
            agent="production-engineer-skill",
            action="assess",
            input_digests={"contract": self.contract_digest},
        )
        self._advance("architecture")

    def freeze(self, repo: Path) -> Candidate:
        first = self.stage == "freeze"
        self._require_stage("freeze", "refreeze")
        candidate = freeze_candidate(repo, self.run_dir, contract_digest=self.contract_digest)
        self.ledger.record(
            stage="freeze",
            agent="v2-integration-engineer",
            action="freeze",
            output_digests={"candidate": candidate.tree_digest},
        )
        self._state["candidate_digest"] = candidate.tree_digest
        if first:
            self._state["reviews_submitted"] = []
            self._state["readonly_clean"] = []
            self._advance("review")
        else:
            self._advance("verify")
        return candidate

    def begin_review(self, reviewer: str, repo: Path) -> None:
        self._require_stage("review")
        self._require_reviewer(reviewer)
        snapshots = self.run_dir / "review-snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        atomic_write_json(snapshots / f"{reviewer}.json", tree_digest(Path(repo)))

    def end_review(self, reviewer: str, repo: Path) -> None:
        """Record the runtime read-only proof; fail closed on any modification."""
        self._require_stage("review")
        self._require_reviewer(reviewer)
        snapshot_path = self.run_dir / "review-snapshots" / f"{reviewer}.json"
        if not snapshot_path.exists():
            raise PmpeError(f"no pre-review snapshot for '{reviewer}' — call begin_review first")
        before: dict[str, str] = json.loads(snapshot_path.read_text())
        violations = verify_unmodified(Path(repo), before)
        verdict = "clean" if not violations else "modified: " + "; ".join(violations[:5])
        self.ledger.record(stage="review", agent=reviewer, action="readonly_check", verdict=verdict)
        if violations:
            raise ReadOnlyViolation(
                f"reviewer '{reviewer}' modified the workspace during review: "
                + "; ".join(violations[:5])
            )
        if reviewer not in self._state["readonly_clean"]:
            self._state["readonly_clean"].append(reviewer)
        self._save()
        self._maybe_finish_review()

    def reconcile_findings(
        self, decisions: dict[str, OwnerDecision], *, owner: str
    ) -> ReconciliationResult:
        """Re-runnable until every finding is decided; only then does the run advance."""
        self._require_stage("reconcile")
        contract = self._state["contract"]
        result = reconcile(
            FindingsStore(self.run_dir),
            decisions=decisions,
            pcr_store=ChangeRequestStore(self.run_dir),
            contract_id=str(contract["contract_id"]),
            contract_version=int(contract["contract_version"]),
            decision_owner=owner,
        )
        if result.undecided:
            return result
        self._state["accepted_findings"] = sorted(result.accepted)
        self._state["product_findings"] = sorted(result.product_decisions)
        self.ledger.record(
            stage="reconcile",
            agent=_CORE,
            action="reconcile",
            detail=(
                f"accepted={','.join(sorted(result.accepted))};"
                f"product_decisions={','.join(sorted(result.product_decisions))}"
            ),
        )
        for finding_id in sorted(result.product_decisions):
            self.ledger.record(
                stage="reconcile",
                agent=_CORE,
                action="change_request_created",
                detail=finding_id,
            )
        # the executed-test gate (retest) runs on EVERY path — a clean review
        # round earns nothing by fiat
        self._advance("fix" if result.accepted else "retest")
        return result

    def record_gates(self, *, passed: bool, detail: str) -> None:
        self._require_stage("retest")
        self.ledger.record(
            stage="retest",
            agent=_CORE,
            action="gates",
            verdict="pass" if passed else "fail",
            detail=detail,
        )
        if passed:
            self._state["gates_passed"] = True
            # only a run that actually fixed something has fixes to re-freeze and verify
            self._advance("refreeze" if self._state["accepted_findings"] else "draft_pr")
        else:
            self._save()

    def record_fix_verification(self, finding_id: str, *, verifier: str) -> None:
        self._require_stage("verify")
        self._require_reviewer(verifier)
        finding = FindingsStore(self.run_dir).get(finding_id)
        already_recorded = finding_id in self._state["verified_findings"]
        if finding.status == "FIXED":
            FindingsStore(self.run_dir).record_verified(finding_id, verifier=verifier)
            self.ledger.record(stage="fix", agent=verifier, action="verify_fix", detail=finding_id)
        elif (
            finding.status == "VERIFIED"
            and not already_recorded
            and finding.verified_by == verifier
        ):
            # crash recovery: the store transition landed before run-state was
            # saved — adopt it without a duplicate ledger event
            pass
        else:
            raise PmpeError(f"{finding_id} is already {finding.status}")
        if finding_id not in self._state["verified_findings"]:
            self._state["verified_findings"].append(finding_id)
        self._save()
        if set(self._state["verified_findings"]) >= set(self._state["accepted_findings"]):
            self._advance("draft_pr")

    def record_draft_pr(self, reference: str) -> None:
        self._require_stage("draft_pr")
        self.ledger.record(
            stage="draft_pr",
            agent=_CORE,
            action="record",
            input_digests={"candidate": str(self._state["candidate_digest"])},
            detail=reference,
        )
        self._state["draft_pr"] = reference
        self._advance("deploy")

    def approve_production(self, *, owner: str, reason: str) -> ProductionApproval:
        candidate = str(self._state["candidate_digest"])
        if not candidate:
            raise PmpeError("no frozen candidate to approve — production approval is digest-bound")
        approval = ProductionApproval(
            owner=owner,
            reason=reason,
            target="production",
            candidate_digest=candidate,
            approved_at=utc_now(),
        )
        write_production_approval(self.run_dir, approval)
        return approval

    def deploy(
        self, environment: str, *, canary_healthy: bool = True
    ) -> DeploymentDecision | SimulatedDeployOutcome:
        self._require_stage("deploy")
        candidate = str(self._state["candidate_digest"])
        approval = load_production_approval(self.run_dir) if environment == "production" else None
        decision = DeploymentPolicy().authorize(
            environment,
            required_checks_passed=bool(self._state["gates_passed"]),
            # the deploy stage is only reachable through review, reconciliation,
            # and fix verification — the state machine is the assurance proof
            assurance_gates_passed=True,
            candidate_digest=candidate,
            approval=approval,
        )
        if not decision.allowed:
            raise DeploymentBlocked(
                f"deployment to {environment} blocked: " + "; ".join(decision.reasons)
            )
        input_digests = {"candidate": candidate}
        if approval is not None:
            input_digests["approval"] = canonical_digest(jsonable(approval))
        if environment == "production":
            outcome = simulate_production_deploy(decision, canary_healthy=canary_healthy)
            self.ledger.record(
                stage="deploy",
                agent=_CORE,
                action="deploy",
                input_digests=input_digests,
                verdict="ready" if outcome.ready else "rolled_back",
                detail=environment,
            )
            self._state["deployments"].append(environment)
            self._save()
            return outcome
        self.ledger.record(
            stage="deploy",
            agent=_CORE,
            action="deploy",
            input_digests=input_digests,
            detail=environment,
        )
        self._state["deployments"].append(environment)
        self._save()
        return decision

    def record_release_report(self, verdict: str) -> None:
        self._require_stage("deploy")
        self.ledger.record(stage="release_report", agent=_CORE, action="report", verdict=verdict)
        self._state["release_verdict"] = verdict
        self._advance("complete")

    # --- agent artifact admission -----------------------------------------------------

    def submit(self, agent: str, artifact: dict[str, Any]) -> None:
        """Validate an agent-proposed artifact and, only if admitted, record it."""
        agent_stage = stage_of(agent)
        if not agent_stage:
            raise SubmissionRejected(f"no stage admits agent '{agent}'")
        if agent_stage != self.stage:
            raise SubmissionRejected(
                f"'{agent}' acts at stage '{agent_stage}', but this run is at stage '{self.stage}'"
            )
        context = self._context_for(agent)
        if agent == "v2-engineer-router":
            errors = validate_routing_submission(artifact, context, self._registry)
        else:
            errors = VALIDATORS[agent](artifact, context)
        if errors:
            raise SubmissionRejected(f"'{agent}' artifact rejected at admission", errors)
        self._admit(agent, artifact)

    def _context_for(self, agent: str) -> dict[str, Any]:
        if agent == "v2-system-architect":
            return {
                "contract_digest": self.contract_digest,
                "requirement_ids": list(self._state["requirement_ids"]),
            }
        if agent == "v2-implementation-planner":
            return {
                "contract_digest": self.contract_digest,
                "requirement_ids": list(self._state["requirement_ids"]),
                "components": list(self._state["components"]),
            }
        if agent == "v2-engineer-router":
            return {"tasks": list(self._state["tasks"])}
        if agent in REVIEWER_NAMES:
            return {"reviewer": agent, "candidate_digest": self._state["candidate_digest"]}
        if agent == "v2-approved-findings-fixer":
            return {"accepted_finding_ids": list(self._state["accepted_findings"])}
        if agent == "v2-integration-engineer":
            return {}
        assignments: dict[str, str] = self._state["assignments"]
        return {"assigned_tasks": [t for t, owner in assignments.items() if owner == agent]}

    def _admit(self, agent: str, artifact: dict[str, Any]) -> None:
        digest = canonical_digest(artifact)
        contract = {"contract": self.contract_digest}

        if agent == "v2-system-architect":
            self._write_artifact("architecture", agent, artifact)
            self.ledger.record(
                stage="architecture",
                agent=agent,
                action="submit_architecture",
                input_digests=contract,
                output_digests={"architecture_pack": digest},
            )
            self._state["components"] = [str(c.get("name")) for c in artifact.get("components", [])]
            self._state["artifact_digests"]["architecture_pack"] = digest
            self._advance("plan")

        elif agent == "v2-implementation-planner":
            self._write_artifact("plan", agent, artifact)
            self.ledger.record(
                stage="plan",
                agent=agent,
                action="submit_plan",
                input_digests={
                    "architecture_pack": self._state["artifact_digests"]["architecture_pack"],
                    **contract,
                },
                output_digests={"plan": digest},
            )
            self._state["tasks"] = list(artifact.get("tasks", []))
            self._state["artifact_digests"]["plan"] = digest
            self._advance("route")

        elif agent == "v2-engineer-router":
            assignments = {
                str(task): str(entry.get("agent"))
                for entry in artifact.get("selected", [])
                for task in entry.get("tasks", [])
            }
            selected = ",".join(sorted(set(assignments.values())))
            self._write_artifact("route", agent, artifact)
            self.ledger.record(
                stage="route",
                agent=agent,
                action="submit_routing",
                input_digests={"plan": self._state["artifact_digests"]["plan"]},
                output_digests={"routing": digest},
                detail=f"selected={selected}",
            )
            self._state["assignments"] = assignments
            self._advance("implement")

        elif agent == "v2-integration-engineer":
            self._write_artifact("integrate", agent, artifact)
            self.ledger.record(
                stage="integrate",
                agent=agent,
                action="integrate",
                input_digests=contract,
                output_digests={"integration_result": digest},
            )
            self._advance("freeze")

        elif agent in REVIEWER_NAMES:
            if agent in self._state["reviews_submitted"]:
                raise SubmissionRejected(f"'{agent}' already submitted a review for this candidate")
            candidate = str(self._state["candidate_digest"])
            FindingsStore(self.run_dir).intake(
                agent, candidate, list(artifact.get("findings") or [])
            )
            self.ledger.record(
                stage="review",
                agent=agent,
                action="submit_review",
                input_digests={"candidate": candidate, **contract},
                output_digests={"review": digest},
            )
            self._state["reviews_submitted"].append(agent)
            self._save()
            self._maybe_finish_review()

        elif agent == "v2-approved-findings-fixer":
            store = FindingsStore(self.run_dir)
            self._write_artifact("fix", agent, artifact)
            for entry in artifact.get("fixed", []):
                finding_id = str(entry.get("finding_id"))
                finding = store.get(finding_id)
                if finding.status == "ACCEPTED":
                    store.record_fixed(
                        finding_id,
                        fixer=agent,
                        commits=[str(c) for c in entry.get("commits", [])],
                    )
                    self.ledger.record(stage="fix", agent=agent, action="fix", detail=finding_id)
                elif finding.status == "FIXED" and finding_id not in self._state["fixed_findings"]:
                    # crash recovery: the store transition landed before run-state
                    # was saved — adopt it without a duplicate ledger event
                    pass
                else:
                    raise SubmissionRejected(f"'{finding_id}' is already {finding.status}")
                if finding_id not in self._state["fixed_findings"]:
                    self._state["fixed_findings"].append(finding_id)
            self._save()
            if set(self._state["fixed_findings"]) >= set(self._state["accepted_findings"]):
                self._advance("retest")

        else:  # a routed specialist reporting one task's result
            task_id = str(artifact.get("task_id"))
            if task_id in self._state["implemented"]:
                raise SubmissionRejected(f"task '{task_id}' already has an admitted result")
            self._write_artifact("implement", f"{agent}--{task_id}", artifact)
            self.ledger.record(
                stage="implement",
                agent=agent,
                action="task_tests",
                input_digests=contract,
                detail=task_id,
            )
            self.ledger.record(
                stage="implement",
                agent=agent,
                action="task_implementation",
                output_digests={"result": digest},
                detail=task_id,
            )
            self._state["implemented"].append(task_id)
            self._save()
            if set(self._state["implemented"]) >= set(self._state["assignments"]):
                self._advance("integrate")

    # --- internals ---------------------------------------------------------------------

    def _maybe_finish_review(self) -> None:
        required = set(REVIEWER_NAMES)
        if (
            set(self._state["reviews_submitted"]) >= required
            and set(self._state["readonly_clean"]) >= required
        ):
            self._advance("reconcile")

    def _require_stage(self, *stages: str) -> None:
        if self.stage not in stages:
            raise PmpeError(
                f"action requires stage {' or '.join(stages)}, but the run is at '{self.stage}'"
            )

    def _require_reviewer(self, name: str) -> None:
        if name not in REVIEWER_NAMES:
            raise PmpeError(f"'{name}' is not one of the independent reviewers (PD-06)")

    def _advance(self, stage: str) -> None:
        self._state["stage"] = stage
        self._save()

    def _save(self) -> None:
        atomic_write_json(self.run_dir / _STATE_FILE, self._state)

    def _write_artifact(self, stage: str, name: str, artifact: dict[str, Any]) -> None:
        artifacts = self.run_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        atomic_write_json(artifacts / f"{stage}--{name}.json", artifact)
