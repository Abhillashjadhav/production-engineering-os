"""Deterministic synthetic starters for all governed workflow packs."""

from __future__ import annotations

import random
from copy import deepcopy
from pathlib import Path
from typing import Any

from pmpe.contracts.authoring import write_json_atomic
from pmpe.contracts.canonical import canonical_digest
from pmpe.personal.catalog import GENERIC_WORKFLOW_CATALOG
from pmpe.personal.planner import WORKFLOW_ORDER

_RESULT_COLLECTIONS = (
    "release_checks",
    "acceptance_checks",
    "verification_checks",
    "security_checks",
    "monitoring_checks",
    "tests",
)


def _source(
    source_id: str, kind: str, title: str, content: Any, *, observed_at: str
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "kind": kind,
        "title": title,
        "uri": f"synthetic://personal/{source_id.lower()}",
        "observed_at": observed_at,
        "content": content,
        "content_digest": canonical_digest(content),
    }


def _extended_pack_content(workflow_id: str, source_id: str) -> dict[str, Any]:
    """Return pack-specific admitted evidence that fixed verifiers can evaluate."""

    content: dict[str, dict[str, Any]] = {
        "prd-architecture-task-compiler": {
            "requirements": [{"requirement_id": "REQ-001", "text": "Preserve evidence provenance"}],
            "architecture_components": ["governed-worker", "approval-outbox"],
            "tasks": [{"task_id": "TASK-001", "requirement_ids": ["REQ-001"]}],
            "traceability_complete": True,
        },
        "release-readiness-room": {
            "release_checks": [{"check_id": "CI", "status": "PASS"}],
            "risk_owners_complete": True,
            "rollback_ready": True,
        },
        "experiment-to-decision": {
            "hypothesis": "Guided review reduces incomplete handoffs.",
            "decision_rule": "Ship when the frozen acceptance threshold passes.",
            "instrumentation_verified": True,
            "sample_size": 30,
            "decision": "SHIP",
        },
        "incident-to-prevention": {
            "timeline": ["Detection", "Containment", "Recovery"],
            "root_cause": "A release gate did not bind the approval payload.",
            "prevention_actions": [
                {"owner": "engineering-owner", "verification_check": "regression-test"}
            ],
        },
        "migration-impact-planner": {
            "dependencies": ["contract-registry", "approval-receipts"],
            "owners_complete": True,
            "rollback_conditions": ["digest mismatch", "failed smoke test"],
            "acceptance_checks": [{"check_id": "MIGRATION-SMOKE", "status": "PASS"}],
        },
        "docs-runbook-drift-maintainer": {
            "drift_items": [
                {
                    "observed": "The CLI runs all selected workflow packs.",
                    "documented": "The CLI runs three packs.",
                    "evidence_source_ids": [source_id],
                }
            ],
            "proposed_repairs": ["Correct the documented workflow count."],
            "publish_status": "DRAFT",
        },
        "customer-research-synthesis": {
            "quotes": [{"text": "Review takes too long.", "source_ids": [source_id]}],
            "themes": [{"theme": "approval latency", "source_ids": [source_id]}],
            "contradictions": [],
        },
        "competitive-market-watch": {
            "changes": [
                {
                    "change": "A competitor added approval-gated actions.",
                    "observed_at": "2026-08-19T12:00:00+05:30",
                    "source_ids": [source_id],
                }
            ],
            "freshness_cutoff": "2026-07-20T00:00:00+05:30",
            "conflicts": [],
        },
        "verified-executive-update": {
            "claims": [{"claim": "The governed synthetic run passed.", "source_ids": [source_id]}],
            "unverified_claim_count": 0,
        },
        "research-to-prototype": {
            "hypothesis": "A visible approval outbox improves trust.",
            "source_ids": [source_id],
            "prototype_scope": ["local review UI", "no external writes"],
            "verification_checks": [{"check_id": "PROTOTYPE-SMOKE", "status": "PASS"}],
        },
        "idea-to-deploy-starter": {
            "starter_files": ["app.py", "README.md"],
            "cost_budget_inr": 500,
            "security_checks": [{"check_id": "SECRETS", "status": "PASS"}],
            "monitoring_checks": [{"check_id": "HEALTH", "status": "PASS"}],
            "rollback_steps": ["Restore the prior immutable release."],
        },
        "data-to-small-tool": {
            "input_schema": {"columns": ["ticket_id", "priority"]},
            "transformations": ["group by priority"],
            "tests": [{"check_id": "FIXTURE", "status": "PASS"}],
        },
        "repo-doctor": {
            "command_runs": [
                {
                    "command": "python -m pytest",
                    "exit_code": 0,
                    "evidence_source_ids": [source_id],
                    "output_digest": canonical_digest({"stdout": "1599 passed"}),
                }
            ],
            "repair_plan": ["Preserve the reproducible test command."],
            "verification_commands": ["python -m pytest"],
        },
        "learning-to-build-coach": {
            "tasks": [
                {
                    "task": "Implement one evidence-bound validator.",
                    "success_check": "The planted invalid input fails closed.",
                }
            ],
            "feedback_loop": "Run the check, explain the failure, then retry.",
            "answers_pre_generated": False,
        },
        "career-proof-pack": {
            "readme_outline": ["Problem", "Decision", "Verification"],
            "demo_outline": ["Input", "Action", "Verified output"],
            "case_study": {"outcome": "A governed workflow completed."},
            "evidence_source_ids": [source_id],
        },
    }
    pack = content[workflow_id]
    for collection in _RESULT_COLLECTIONS:
        for item in pack.get(collection, []):
            item["evidence_source_ids"] = [source_id]
            item["result_digest"] = canonical_digest(
                {
                    "check_id": item["check_id"],
                    "collection": collection,
                    "status": item["status"],
                    "workflow_id": workflow_id,
                }
            )
    return pack


def synthetic_personal_context(
    seed: int = 2026, *, workflow_ids: tuple[str, ...] = WORKFLOW_ORDER
) -> dict[str, Any]:
    randomizer = random.Random(seed)
    suffix = randomizer.choice(("A", "B", "C"))
    candidate_digest = canonical_digest({"candidate": f"voice-pilot-{suffix}", "version": 1})
    sources = [
        _source(
            "SRC-PRODUCT-DECISION",
            "product-decision",
            "Approved voice-support product decision",
            {
                "acceptance_results": [
                    {
                        "candidate_digest": candidate_digest,
                        "check_id": "CHECK-PRODUCT-TRUTH",
                        "status": "PASS",
                    }
                ],
                "decision": "Pilot agent assist with synthetic cases",
                "status": "APPROVED",
            },
            observed_at="2026-08-19T09:00:00+05:30",
        ),
        _source(
            "SRC-ACCEPTANCE",
            "test-report",
            "Acceptance and regression checks",
            {
                "acceptance_results": [
                    {
                        "candidate_digest": candidate_digest,
                        "check_id": "CHECK-SCENARIOS",
                        "status": "PASS",
                    }
                ],
                "checks": ["scenario-suite", "privacy-boundary", "rollback"],
            },
            observed_at="2026-08-19T10:00:00+05:30",
        ),
        _source(
            "SRC-EVAL-RUN",
            "eval-run",
            "Frozen AI candidate evaluation",
            {
                "candidate": f"voice-pilot-{suffix}",
                "cases": 3,
                "evaluation_results": [
                    {
                        "actual": actual,
                        "candidate_id": f"VOICE-CANDIDATE-{suffix}",
                        "case_id": case_id,
                        "cost_usd": cost_usd,
                        "expected": expected,
                        "latency_ms": latency_ms,
                        "safety_pass": True,
                    }
                    for case_id, expected, actual, latency_ms, cost_usd in (
                        (
                            "GOLDEN-DELAY",
                            "Escalate delayed delivery with evidence.",
                            "Escalate delayed delivery with evidence.",
                            420,
                            0.012,
                        ),
                        (
                            "GOLDEN-REFUND",
                            "Request approval before refund action.",
                            "Request approval before refund action.",
                            480,
                            0.014,
                        ),
                        (
                            "GOLDEN-POLICY",
                            "Cite the current policy source.",
                            "Cite the current policy source.",
                            510,
                            0.013,
                        ),
                    )
                ],
            },
            observed_at="2026-08-19T10:15:00+05:30",
        ),
        _source(
            "SRC-CALENDAR",
            "calendar-snapshot",
            "Weekly calendar snapshot",
            {"events": ["pilot-review", "dependency-review", "research-synthesis"]},
            observed_at="2026-08-19T08:00:00+05:30",
        ),
        _source(
            "SRC-COMMITMENTS",
            "commitment-register",
            "Open commitments",
            {"open": 3, "high_impact": 2},
            observed_at="2026-08-19T08:05:00+05:30",
        ),
        _source(
            "SRC-MESSAGES",
            "message-snapshot",
            "Action-request messages",
            {"messages": 2},
            observed_at="2026-08-19T08:10:00+05:30",
        ),
        _source(
            "SRC-MEETING-NOTES",
            "meeting-notes",
            "Voice pilot decision meeting notes",
            {"decisions": 2, "actions": 2},
            observed_at="2026-08-18T17:00:00+05:30",
        ),
        _source(
            "SRC-CUSTOMER-SIGNALS",
            "customer-research",
            "Synthetic customer support signals",
            {"signals": ["slow triage", "policy lookup", "refund risk"]},
            observed_at="2026-08-18T16:00:00+05:30",
        ),
        _source(
            "SRC-ISSUE-119",
            "github-issue",
            "Tier-1 workflow packs issue",
            {"issue": 119, "status": "APPROVED_FOR_IMPLEMENTATION"},
            observed_at="2026-08-19T11:00:00+05:30",
        ),
        _source(
            "SRC-CI-RUN",
            "ci-run",
            "Deterministic checks for issue candidate",
            {"pytest": "PASS", "ruff": "PASS"},
            observed_at="2026-08-19T11:15:00+05:30",
        ),
    ]
    source_by_id = {str(source["source_id"]): source for source in sources}
    source_by_id["SRC-CUSTOMER-SIGNALS"]["content"]["roadmap_release_results"] = [
        {
            "approved_option_id": "OPTION-ASSIST",
            "check_id": "CHECK-ROADMAP-EVIDENCE",
            "status": "PASS",
        }
    ]
    source_by_id["SRC-CUSTOMER-SIGNALS"]["content_digest"] = canonical_digest(
        source_by_id["SRC-CUSTOMER-SIGNALS"]["content"]
    )
    source_by_id["SRC-ACCEPTANCE"]["content"]["roadmap_release_results"] = [
        {
            "approved_option_id": "OPTION-ASSIST",
            "check_id": "CHECK-ROADMAP-RELEASE",
            "status": "PASS",
        }
    ]
    source_by_id["SRC-ACCEPTANCE"]["content_digest"] = canonical_digest(
        source_by_id["SRC-ACCEPTANCE"]["content"]
    )
    source_by_id["SRC-CI-RUN"]["content"]["candidate_check_results"] = [
        {"candidate_digest": candidate_digest, "check_id": check_id, "status": "PASS"}
        for check_id in ("CHECK-PYTEST", "CHECK-RUFF")
    ]
    source_by_id["SRC-CI-RUN"]["content_digest"] = canonical_digest(
        source_by_id["SRC-CI-RUN"]["content"]
    )
    generic_source_ids: dict[str, str] = {}
    for index, (workflow_id, entry) in enumerate(GENERIC_WORKFLOW_CATALOG.items(), start=1):
        source_id = f"SRC-PACK-{index:02d}"
        generic_source_ids[workflow_id] = source_id
        source_content: dict[str, Any] = {
            "problem_solved": entry["problem_solved"],
            "objective": entry["objective"],
            "observed_state": "synthetic verified input",
        }
        pack_content = _extended_pack_content(workflow_id, source_id)
        check_results = [
            {
                "check_id": item["check_id"],
                "collection": collection,
                "result_digest": item["result_digest"],
                "status": item["status"],
                "workflow_id": workflow_id,
            }
            for collection in _RESULT_COLLECTIONS
            for item in pack_content.get(collection, [])
        ]
        if check_results:
            source_content["check_results"] = check_results
        if workflow_id == "repo-doctor":
            source_content["command_results"] = [
                {
                    "command": "python -m pytest",
                    "exit_code": 0,
                    "output_digest": canonical_digest({"stdout": "1599 passed"}),
                }
            ]
        sources.append(
            _source(
                source_id,
                "workflow-evidence",
                f"Evidence for {workflow_id}",
                source_content,
                observed_at="2026-08-19T12:00:00+05:30",
            )
        )
    inputs: dict[str, Any] = {
        "goal-to-verified-release": {
            "evidence_source_ids": ["SRC-PRODUCT-DECISION", "SRC-ACCEPTANCE"],
            "goal_id": f"GOAL-VOICE-{suffix}",
            "release_candidate_digest": candidate_digest,
            "release_target": "voice-support-pilot",
            "acceptance_checks": [
                {
                    "check_id": "CHECK-SCENARIOS",
                    "description": "Synthetic support scenarios pass.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-ACCEPTANCE"],
                },
                {
                    "check_id": "CHECK-PRODUCT-TRUTH",
                    "description": "Candidate conforms to the approved product decision.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-PRODUCT-DECISION"],
                },
            ],
        },
        "ai-eval-release-gate": {
            "evidence_source_ids": ["SRC-EVAL-RUN"],
            "candidate_id": f"VOICE-CANDIDATE-{suffix}",
            "release_target": "voice-support-shadow",
            "golden_cases": [
                {
                    "case_id": "GOLDEN-DELAY",
                    "expected": "Escalate delayed delivery with evidence.",
                    "actual": "Escalate delayed delivery with evidence.",
                    "safety_pass": True,
                    "latency_ms": 420,
                    "cost_usd": 0.012,
                    "evidence_source_ids": ["SRC-EVAL-RUN"],
                },
                {
                    "case_id": "GOLDEN-REFUND",
                    "expected": "Request approval before refund action.",
                    "actual": "Request approval before refund action.",
                    "safety_pass": True,
                    "latency_ms": 480,
                    "cost_usd": 0.014,
                    "evidence_source_ids": ["SRC-EVAL-RUN"],
                },
                {
                    "case_id": "GOLDEN-POLICY",
                    "expected": "Cite the current policy source.",
                    "actual": "Cite the current policy source.",
                    "safety_pass": True,
                    "latency_ms": 510,
                    "cost_usd": 0.013,
                    "evidence_source_ids": ["SRC-EVAL-RUN"],
                },
            ],
            "thresholds": {
                "min_pass_rate": 1.0,
                "max_p95_latency_ms": 600,
                "max_average_cost_usd": 0.02,
                "max_safety_failures": 0,
            },
        },
        "weekly-pm-command-centre": {
            "evidence_source_ids": ["SRC-CALENDAR", "SRC-COMMITMENTS", "SRC-MESSAGES"],
            "timezone": "Asia/Kolkata",
            "calendar_events": [
                {
                    "event_id": "CAL-001",
                    "start": "2026-08-20T09:30:00+05:30",
                    "end": "2026-08-20T10:00:00+05:30",
                    "title": "Voice support pilot review",
                },
                {
                    "event_id": "CAL-002",
                    "start": "2026-08-20T09:45:00+05:30",
                    "end": "2026-08-20T10:30:00+05:30",
                    "title": "Engineering dependency review",
                },
            ],
            "commitments": [
                {
                    "commitment_id": "COM-001",
                    "due": "2026-08-20T14:00:00+05:30",
                    "status": "OPEN",
                    "impact": "HIGH",
                    "text": "Approve the pilot release recommendation.",
                },
                {
                    "commitment_id": "COM-002",
                    "due": "2026-08-21T18:00:00+05:30",
                    "status": "OPEN",
                    "impact": "MEDIUM",
                    "text": "Publish verified demo evidence.",
                },
            ],
            "messages": [
                {
                    "message_id": "MSG-001",
                    "importance": 3,
                    "subject": "Pilot decision required",
                    "action_requested": "Share the go or no-go recommendation.",
                }
            ],
        },
        "meeting-to-decision": {
            "evidence_source_ids": ["SRC-MEETING-NOTES", "SRC-PRODUCT-DECISION"],
            "meeting_id": "MEET-VOICE-001",
            "title": "Voice support pilot decision",
            "scheduled_at": "2026-08-20T09:30:00+05:30",
            "agenda": ["Review eval evidence", "Confirm release boundary"],
            "prior_decisions": [
                "Use synthetic cases for the public demo.",
                "Keep refunds and production changes approval-gated.",
            ],
            "notes": ["The candidate met the frozen synthetic threshold."],
            "action_items": [
                {
                    "action_id": "ACT-001",
                    "owner": "product-owner",
                    "due": "2026-08-20",
                    "text": "Approve the release recommendation.",
                },
                {
                    "action_id": "ACT-002",
                    "owner": "engineering-owner",
                    "due": "2026-08-21",
                    "text": "Verify held-out cases.",
                },
            ],
            "follow_up_target": "voice-pilot-stakeholders",
        },
        "evidence-to-roadmap-to-release": {
            "evidence_source_ids": [
                "SRC-CUSTOMER-SIGNALS",
                "SRC-PRODUCT-DECISION",
                "SRC-ACCEPTANCE",
            ],
            "claims": [
                {
                    "claim_id": "CLAIM-TRIAGE",
                    "text": (
                        "Support triage and policy lookup are the initial workflow bottlenecks."
                    ),
                    "source_ids": ["SRC-CUSTOMER-SIGNALS"],
                },
                {
                    "claim_id": "CLAIM-BOUNDARY",
                    "text": "High-impact actions must remain approval-gated.",
                    "source_ids": ["SRC-PRODUCT-DECISION"],
                },
            ],
            "options": [
                {
                    "option_id": "OPTION-ASSIST",
                    "title": "Agent-assist pilot",
                    "pros": ["Preserves human judgment", "Supports shadow evaluation"],
                    "cons": ["Requires reviewer capacity"],
                },
                {
                    "option_id": "OPTION-AUTONOMOUS",
                    "title": "Autonomous support agent",
                    "pros": ["Higher automation ceiling"],
                    "cons": ["Exceeds the approved risk boundary"],
                },
            ],
            "approved_option_id": "OPTION-ASSIST",
            "requirements": [
                "Cite current policy evidence.",
                "Request approval before refunds or external sends.",
            ],
            "release_checks": [
                {
                    "check_id": "CHECK-ROADMAP-EVIDENCE",
                    "description": "Roadmap claims have admitted evidence.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-CUSTOMER-SIGNALS"],
                },
                {
                    "check_id": "CHECK-ROADMAP-RELEASE",
                    "description": "Release checks pass.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-ACCEPTANCE"],
                },
            ],
            "roadmap_target": "voice-support-roadmap",
        },
        "issue-to-draft-pr": {
            "evidence_source_ids": ["SRC-ISSUE-119", "SRC-CI-RUN"],
            "repository": "Abhillashjadhav/production-engineering-os",
            "issue_number": 119,
            "issue_title": "Ship six Tier-1 workflow packs",
            "issue_body": (
                "Create usable, evidence-led workflow packs without changing product truth."
            ),
            "impact_paths": ["src/pmpe/personal", "tests/unit/test_personal_execution.py"],
            "dependencies": ["Personal Execution OS runtime", "RFC 8785 digests"],
            "candidate_digest": candidate_digest,
            "checks": [
                {
                    "check_id": "CHECK-PYTEST",
                    "description": "Focused unit tests pass.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-CI-RUN"],
                },
                {
                    "check_id": "CHECK-RUFF",
                    "description": "Ruff passes.",
                    "status": "PASS",
                    "evidence_source_ids": ["SRC-CI-RUN"],
                },
            ],
            "pr_title": "feat: add six Tier-1 workflow packs",
            "pr_body": "Implements #119 with deterministic evidence and approval gates.",
        },
    }
    for index, (workflow_id, entry) in enumerate(GENERIC_WORKFLOW_CATALOG.items(), start=1):
        source_id = generic_source_ids[workflow_id]
        inputs[workflow_id] = {
            "evidence_source_ids": [source_id],
            "subject_id": f"SUBJECT-PACK-{index:02d}",
            "objective": entry["objective"],
            "records": [
                {
                    "record_id": f"RECORD-PACK-{index:02d}",
                    "title": entry["output_name"].replace("-", " ").title(),
                    "content": _extended_pack_content(workflow_id, source_id),
                    "evidence_source_ids": [source_id],
                }
            ],
            "checks": [
                {
                    "check_id": f"CHECK-PACK-{index:02d}",
                    "description": "Required source evidence and output target are present.",
                    "status": "PASS",
                    "evidence_source_ids": [source_id],
                }
            ],
            "output_target": entry["output_name"],
            "approval_actions": [
                {
                    "action_type": action_type,
                    "target": f"configured-target/{workflow_id}",
                    "operation": action_type,
                    "reason": "Publishing or applying the verified proposal is consequential.",
                    "reversibility": (
                        "The local proposal is reversible; the external action may not be."
                    ),
                }
                for action_type in entry["approvals"]
            ],
        }
    weekly_input = inputs["weekly-pm-command-centre"]
    meeting_input = inputs["meeting-to-decision"]
    roadmap_input = inputs["evidence-to-roadmap-to-release"]
    issue_input = inputs["issue-to-draft-pr"]
    eval_input = inputs["ai-eval-release-gate"]
    approved_roadmap_option = next(
        option
        for option in roadmap_input["options"]
        if option["option_id"] == roadmap_input["approved_option_id"]
    )
    source_updates: dict[str, dict[str, Any]] = {
        "SRC-EVAL-RUN": {
            "evaluation_policies": [
                {
                    "candidate_id": eval_input["candidate_id"],
                    "required_case_ids": sorted(
                        str(item["case_id"]) for item in eval_input["golden_cases"]
                    ),
                    "thresholds": eval_input["thresholds"],
                }
            ]
        },
        "SRC-CALENDAR": {
            "calendar_snapshots": [
                {
                    "events": weekly_input["calendar_events"],
                    "timezone": weekly_input["timezone"],
                }
            ]
        },
        "SRC-COMMITMENTS": {"commitment_snapshots": [{"commitments": weekly_input["commitments"]}]},
        "SRC-MESSAGES": {"message_snapshots": [{"messages": weekly_input["messages"]}]},
        "SRC-MEETING-NOTES": {
            "meeting_records": [
                {
                    "action_items": meeting_input["action_items"],
                    "agenda": meeting_input["agenda"],
                    "meeting_id": meeting_input["meeting_id"],
                    "notes": meeting_input["notes"],
                    "prior_decisions": meeting_input["prior_decisions"],
                    "scheduled_at": meeting_input["scheduled_at"],
                    "title": meeting_input["title"],
                }
            ]
        },
        "SRC-CUSTOMER-SIGNALS": {
            "roadmap_claims": [roadmap_input["claims"][0]],
        },
        "SRC-PRODUCT-DECISION": {
            "roadmap_claims": [roadmap_input["claims"][1]],
            "roadmap_decisions": [
                {
                    "approved_option": approved_roadmap_option,
                    "requirements": roadmap_input["requirements"],
                }
            ],
        },
        "SRC-ISSUE-119": {
            "issue_contracts": [
                {
                    "dependencies": issue_input["dependencies"],
                    "impact_paths": issue_input["impact_paths"],
                    "issue_body": issue_input["issue_body"],
                    "issue_number": issue_input["issue_number"],
                    "issue_title": issue_input["issue_title"],
                    "pr_body": issue_input["pr_body"],
                    "pr_title": issue_input["pr_title"],
                    "repository": issue_input["repository"],
                }
            ]
        },
    }
    for source_id, updates in source_updates.items():
        content = source_by_id[source_id]["content"]
        if not isinstance(content, dict):
            raise TypeError(f"synthetic source {source_id} content must be an object")
        content.update(deepcopy(updates))
        source_by_id[source_id]["content_digest"] = canonical_digest(content)
    selected = tuple(workflow_ids)
    return {
        "schema_version": "1.0.0",
        "request_id": f"PERSONAL-ALL-TIERS-{suffix}",
        "problem": "PMs and builders can generate artifacts but cannot reliably complete work.",
        "hypothesis": "Governed outcome packs will reduce rework and incomplete handoffs.",
        "proposed_answer": "Run role-specific packs on one evidence and approval runtime.",
        "target_outcome": "Each selected workflow returns a verified outcome and safe next action.",
        "deadline": "2026-08-29T18:00:00+05:30",
        "success": {
            "north_star": (
                "Percentage of accepted work contracts completed with verified evidence "
                "by deadline."
            ),
            "leading": [
                "Time to first verified outcome",
                "First-pass deliverable acceptance",
                "Percentage of selected workflows with complete provenance",
            ],
            "guardrails": [
                "Zero unauthorized external writes",
                "Zero silent failures presented as completed work",
                "Every material result links to admitted evidence",
            ],
        },
        "trade_off": "More approval latency in exchange for verifiable high-impact actions.",
        "scope": [
            "Tier-1, Tier-2 and Tier-3 local workflow packs",
            "Synthetic and user-supplied JSON inputs",
        ],
        "non_goals": ["Sending messages", "Merging code", "Deploying production"],
        "workflow_ids": list(selected),
        "approved_by": "synthetic-demo-user",
        "evidence_sources": sources,
        "workflow_inputs": {workflow_id: inputs[workflow_id] for workflow_id in selected},
    }


def write_synthetic_personal_context(
    root: Path,
    seed: int = 2026,
    *,
    workflow_ids: tuple[str, ...] = WORKFLOW_ORDER,
) -> Path:
    output = Path(root) / "synthetic-workflow-request.json"
    write_json_atomic(output, synthetic_personal_context(seed, workflow_ids=workflow_ids))
    return output
