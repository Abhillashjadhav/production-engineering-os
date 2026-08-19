"""Versioned catalogue for reusable Tier-2 and Tier-3 outcome workflow packs."""

from __future__ import annotations

from typing import TypedDict


class CatalogEntry(TypedDict):
    tier: int
    problem_solved: str
    objective: str
    output_name: str
    allowed: tuple[str, ...]
    done: tuple[str, ...]
    budget: str
    approvals: tuple[str, ...]
    verifier: str


TIER_1_WORKFLOWS = (
    "goal-to-verified-release",
    "ai-eval-release-gate",
    "weekly-pm-command-centre",
    "meeting-to-decision",
    "evidence-to-roadmap-to-release",
    "issue-to-draft-pr",
)

TIER_2_WORKFLOWS = (
    "prd-architecture-task-compiler",
    "release-readiness-room",
    "experiment-to-decision",
    "incident-to-prevention",
    "migration-impact-planner",
    "docs-runbook-drift-maintainer",
    "customer-research-synthesis",
    "competitive-market-watch",
    "verified-executive-update",
)

TIER_3_WORKFLOWS = (
    "research-to-prototype",
    "idea-to-deploy-starter",
    "data-to-small-tool",
    "repo-doctor",
    "learning-to-build-coach",
    "career-proof-pack",
)


def _entry(
    *,
    tier: int,
    problem: str,
    objective: str,
    output: str,
    allowed: tuple[str, ...],
    approvals: tuple[str, ...],
    verifier: str,
) -> CatalogEntry:
    return {
        "tier": tier,
        "problem_solved": problem,
        "objective": objective,
        "output_name": output,
        "allowed": allowed,
        "done": (
            "Every material claim is bound to admitted evidence.",
            "Every declared deterministic check passes before a positive verdict.",
            "Consequential actions remain exact approval payloads.",
        ),
        "budget": "20 minutes or 12000 tokens; no unauthorized external writes",
        "approvals": approvals,
        "verifier": verifier,
    }


TIER_1_WORKFLOW_CATALOG: dict[str, CatalogEntry] = {
    "goal-to-verified-release": _entry(
        tier=1,
        problem="Goals reach implementation without a digest-bound acceptance verdict.",
        objective="Bind a release candidate to acceptance evidence and a human release decision.",
        output="verified-release-record",
        allowed=("evidence.read", "artifact.write", "codex.task.prepare"),
        approvals=("git.merge", "production.deploy"),
        verifier="release-evidence-reviewer",
    ),
    "ai-eval-release-gate": _entry(
        tier=1,
        problem="AI candidates ship without frozen quality, latency, cost, and safety gates.",
        objective="Evaluate one candidate against a frozen golden set and thresholds.",
        output="ai-eval-release-record",
        allowed=("evidence.read", "eval.calculate", "artifact.write"),
        approvals=("model.release",),
        verifier="eval-integrity-reviewer",
    ),
    "weekly-pm-command-centre": _entry(
        tier=1,
        problem="Commitments, messages, and calendar conflicts remain fragmented.",
        objective="Produce a bounded weekly operating plan and exact action drafts.",
        output="weekly-command-plan",
        allowed=("calendar.read", "messages.read", "commitments.read", "artifact.write"),
        approvals=("calendar.write", "message.send"),
        verifier="weekly-plan-reviewer",
    ),
    "meeting-to-decision": _entry(
        tier=1,
        problem="Meetings end without preserved decisions, owners, deadlines, and closure.",
        objective="Produce an evidence-bound decision record and owner-complete actions.",
        output="meeting-decision-record",
        allowed=("evidence.read", "calendar.read", "artifact.write"),
        approvals=("task.create", "message.send"),
        verifier="decision-record-reviewer",
    ),
    "evidence-to-roadmap-to-release": _entry(
        tier=1,
        problem="Customer evidence loses provenance before roadmap and release decisions.",
        objective="Bind sourced claims and a human-selected option to a release plan.",
        output="roadmap-release-plan",
        allowed=("evidence.read", "roadmap.draft", "artifact.write"),
        approvals=("roadmap.update", "release.publish"),
        verifier="product-conformance-reviewer",
    ),
    "issue-to-draft-pr": _entry(
        tier=1,
        problem="Approved issues do not reliably become test-bound, reviewable changes.",
        objective="Produce an exact draft-PR payload bound to issue scope and checks.",
        output="draft-pr-payload",
        allowed=("repository.read", "tests.read", "artifact.write", "codex.task.prepare"),
        approvals=("git.pr.create", "git.merge"),
        verifier="independent-code-reviewer",
    ),
}


GENERIC_WORKFLOW_CATALOG: dict[str, CatalogEntry] = {
    "prd-architecture-task-compiler": _entry(
        tier=2,
        problem="Approved intent is repeatedly reinterpreted across product and engineering.",
        objective=(
            "Compile approved intent into a traceable PRD, architecture brief, and task graph."
        ),
        output="compiled-delivery-packet",
        allowed=("evidence.read", "artifact.write", "taskgraph.compile"),
        approvals=("task.publish",),
        verifier="contract-traceability-reviewer",
    ),
    "release-readiness-room": _entry(
        tier=2,
        problem="Release decisions are fragmented across checks, owners, risks, and evidence.",
        objective="Produce an evidence-bound go/no-go recommendation without releasing.",
        output="release-readiness-record",
        allowed=("evidence.read", "checks.evaluate", "artifact.write"),
        approvals=("release.publish",),
        verifier="release-readiness-reviewer",
    ),
    "experiment-to-decision": _entry(
        tier=2,
        problem="Experiments produce metrics without a clear decision or provenance.",
        objective="Bind hypothesis, instrumentation, results, and decision criteria.",
        output="experiment-decision-record",
        allowed=("evidence.read", "metrics.calculate", "artifact.write"),
        approvals=("experiment.decision.publish",),
        verifier="experiment-integrity-reviewer",
    ),
    "incident-to-prevention": _entry(
        tier=2,
        problem="Incident reviews stop at narrative postmortems instead of verified prevention.",
        objective="Convert incident evidence into owned prevention work and verification checks.",
        output="incident-prevention-pack",
        allowed=("evidence.read", "timeline.reconcile", "artifact.write"),
        approvals=("task.publish",),
        verifier="incident-evidence-reviewer",
    ),
    "migration-impact-planner": _entry(
        tier=2,
        problem=(
            "Migrations miss dependencies, owners, rollback conditions, and acceptance evidence."
        ),
        objective="Produce a dependency-bound migration and rollback plan.",
        output="migration-impact-plan",
        allowed=("evidence.read", "dependency.analyze", "artifact.write"),
        approvals=("migration.schedule",),
        verifier="migration-risk-reviewer",
    ),
    "docs-runbook-drift-maintainer": _entry(
        tier=2,
        problem="Documentation and runbooks drift away from verified system behavior.",
        objective="Propose evidence-backed documentation repairs without publishing them.",
        output="documentation-drift-report",
        allowed=("evidence.read", "docs.compare", "artifact.write"),
        approvals=("docs.publish",),
        verifier="documentation-evidence-reviewer",
    ),
    "customer-research-synthesis": _entry(
        tier=2,
        problem="Customer research loses quote-level provenance and contradictory evidence.",
        objective="Synthesize sourced themes while preserving conflicts and exact evidence.",
        output="customer-research-synthesis",
        allowed=("evidence.read", "themes.cluster", "artifact.write"),
        approvals=("research.publish",),
        verifier="research-provenance-reviewer",
    ),
    "competitive-market-watch": _entry(
        tier=2,
        problem="Competitive updates are stale, duplicated, or presented without source authority.",
        objective="Produce a freshness-aware market change report with conflicts exposed.",
        output="market-watch-report",
        allowed=("evidence.read", "freshness.evaluate", "artifact.write"),
        approvals=("market-update.publish",),
        verifier="market-evidence-reviewer",
    ),
    "verified-executive-update": _entry(
        tier=2,
        problem="Executive updates overstate progress because they are drafted from memory.",
        objective="Generate an executive update only from verified delivery state.",
        output="verified-executive-update",
        allowed=("evidence.read", "artifact.write"),
        approvals=("message.send",),
        verifier="executive-accuracy-reviewer",
    ),
    "research-to-prototype": _entry(
        tier=3,
        problem="Builders jump from an idea to code without evidence, hypothesis, or tests.",
        objective="Turn sourced research into a bounded prototype contract and verification plan.",
        output="prototype-contract",
        allowed=("evidence.read", "prototype.plan", "artifact.write"),
        approvals=("prototype.publish",),
        verifier="prototype-evidence-reviewer",
    ),
    "idea-to-deploy-starter": _entry(
        tier=3,
        problem="Idea-to-app tools hide cost, security, monitoring, and rollback requirements.",
        objective="Prepare a deployable starter and release checklist without deploying it.",
        output="deploy-starter-pack",
        allowed=("evidence.read", "starter.generate", "artifact.write"),
        approvals=("production.deploy",),
        verifier="starter-release-reviewer",
    ),
    "data-to-small-tool": _entry(
        tier=3,
        problem="Users cannot reliably turn a small dataset or API shape into a tested utility.",
        objective=(
            "Compile structured input into a small-tool contract, transformations, and tests."
        ),
        output="small-tool-specification",
        allowed=("evidence.read", "data.inspect", "artifact.write"),
        approvals=("tool.publish",),
        verifier="data-tool-reviewer",
    ),
    "repo-doctor": _entry(
        tier=3,
        problem="Abandoned repositories lack a reproducible path to install, test, and understand.",
        objective="Diagnose a repository and propose bounded repairs with verification commands.",
        output="repository-recovery-plan",
        allowed=("repository.read", "tests.read", "artifact.write"),
        approvals=("git.pr.create",),
        verifier="repository-recovery-reviewer",
    ),
    "learning-to-build-coach": _entry(
        tier=3,
        problem="Learners receive generated answers instead of sequenced practice and feedback.",
        objective="Create bounded learning tasks, checks, and explanations of observed failures.",
        output="learning-build-plan",
        allowed=("evidence.read", "curriculum.plan", "artifact.write"),
        approvals=("task.publish",),
        verifier="learning-plan-reviewer",
    ),
    "career-proof-pack": _entry(
        tier=3,
        problem="Completed work is not translated into verifiable portfolio evidence.",
        objective=(
            "Turn verified build evidence into a README, demo outline, and case-study proof pack."
        ),
        output="career-proof-pack",
        allowed=("evidence.read", "artifact.write"),
        approvals=("portfolio.publish",),
        verifier="portfolio-evidence-reviewer",
    ),
}


ALL_EXTENDED_WORKFLOWS = TIER_2_WORKFLOWS + TIER_3_WORKFLOWS
ALL_WORKFLOW_CATALOG = {**TIER_1_WORKFLOW_CATALOG, **GENERIC_WORKFLOW_CATALOG}

_TIER_1_REQUIRED_INPUTS = {
    "goal-to-verified-release": [
        "evidence_source_ids",
        "goal_id",
        "release_candidate_digest",
        "acceptance_checks",
        "release_target",
    ],
    "ai-eval-release-gate": [
        "evidence_source_ids",
        "candidate_id",
        "golden_cases",
        "thresholds",
        "release_target",
    ],
    "weekly-pm-command-centre": [
        "evidence_source_ids",
        "timezone",
        "calendar_events",
        "commitments",
        "messages",
    ],
    "meeting-to-decision": [
        "evidence_source_ids",
        "meeting_id",
        "agenda",
        "prior_decisions",
        "action_items",
    ],
    "evidence-to-roadmap-to-release": [
        "evidence_source_ids",
        "claims",
        "options",
        "approved_option_id",
        "release_checks",
    ],
    "issue-to-draft-pr": [
        "evidence_source_ids",
        "repository",
        "issue_number",
        "impact_paths",
        "candidate_digest",
        "checks",
    ],
}


def workflow_catalog_payload() -> dict[str, object]:
    """Stable PMOS-facing catalogue with declared product and control metadata."""

    return {
        "schema_version": "1.0.0",
        "workflows": [
            {
                "workflow_id": workflow_id,
                **ALL_WORKFLOW_CATALOG[workflow_id],
                "required_inputs": _TIER_1_REQUIRED_INPUTS.get(workflow_id)
                or [
                    "evidence_source_ids",
                    "subject_id",
                    "objective",
                    "records",
                    "checks",
                    "output_target",
                    "approval_actions",
                ],
                "recovery": (
                    "Repair the rejected input or failed check and rerun. No external action "
                    "occurs before exact approval."
                ),
            }
            for workflow_id in TIER_1_WORKFLOWS + ALL_EXTENDED_WORKFLOWS
        ],
    }
