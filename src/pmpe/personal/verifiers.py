"""Pack-specific deterministic verification for Tier-2 and Tier-3 workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, TypedDict


class VerifiedCheck(TypedDict):
    check_id: str
    passed: bool
    observed: Any
    expected: Any


Verifier = Callable[[Mapping[str, Any]], tuple[VerifiedCheck, ...]]


def _check(check_id: str, passed: bool, observed: Any, expected: Any) -> VerifiedCheck:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "expected": expected,
    }


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _all_pass(value: Any) -> bool:
    items = _items(value)
    return bool(items) and all(
        isinstance(item, Mapping) and item.get("status") == "PASS" for item in items
    )


def _all_have(value: Any, *fields: str) -> bool:
    items = _items(value)
    return bool(items) and all(
        isinstance(item, Mapping) and all(item.get(field) not in (None, "", []) for field in fields)
        for item in items
    )


def _non_empty_id_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_text(item) for item in value)


def _all_have_id_list(value: Any, *, text_fields: tuple[str, ...], ids_field: str) -> bool:
    items = _items(value)
    return bool(items) and all(
        isinstance(item, Mapping)
        and all(_text(item.get(field)) for field in text_fields)
        and _non_empty_id_list(item.get(ids_field))
        for item in items
    )


def _compile_delivery(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    requirements = _items(data.get("requirements"))
    requirement_ids = {
        str(item["requirement_id"])
        for item in requirements
        if isinstance(item, Mapping)
        and _text(item.get("requirement_id"))
        and _text(item.get("text"))
    }
    tasks = _items(data.get("tasks"))
    tasks_trace = (
        bool(tasks)
        and len(requirement_ids) == len(requirements)
        and all(
            isinstance(item, Mapping)
            and _text(item.get("task_id"))
            and _non_empty_id_list(item.get("requirement_ids"))
            and {str(value) for value in item["requirement_ids"]} <= requirement_ids
            for item in tasks
        )
    )
    return (
        _check(
            "prd-requirements-present",
            bool(requirements) and len(requirement_ids) == len(requirements),
            requirements,
            "unique requirement_id and text per requirement",
        ),
        _check(
            "architecture-components-present",
            bool(_items(data.get("architecture_components"))),
            len(_items(data.get("architecture_components"))),
            ">=1",
        ),
        _check(
            "tasks-trace-to-requirements",
            tasks_trace,
            tasks,
            "every task requirement_id resolves to a declared requirement",
        ),
        _check(
            "traceability-complete",
            data.get("traceability_complete") is True,
            data.get("traceability_complete"),
            True,
        ),
    )


def _release_readiness(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "release-checks-pass",
            _all_pass(data.get("release_checks")),
            data.get("release_checks"),
            "all PASS",
        ),
        _check(
            "risk-owners-complete",
            data.get("risk_owners_complete") is True,
            data.get("risk_owners_complete"),
            True,
        ),
        _check(
            "rollback-ready", data.get("rollback_ready") is True, data.get("rollback_ready"), True
        ),
    )


def _experiment(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    sample_size = data.get("sample_size")
    return (
        _check(
            "hypothesis-present", _text(data.get("hypothesis")), data.get("hypothesis"), "non-empty"
        ),
        _check(
            "decision-rule-present",
            _text(data.get("decision_rule")),
            data.get("decision_rule"),
            "non-empty",
        ),
        _check(
            "instrumentation-verified",
            data.get("instrumentation_verified") is True,
            data.get("instrumentation_verified"),
            True,
        ),
        _check(
            "sample-observed",
            isinstance(sample_size, int) and not isinstance(sample_size, bool) and sample_size > 0,
            sample_size,
            ">0",
        ),
        _check(
            "decision-explicit",
            data.get("decision") in {"SHIP", "ITERATE", "STOP"},
            data.get("decision"),
            ["SHIP", "ITERATE", "STOP"],
        ),
    )


def _incident(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "timeline-present",
            bool(_items(data.get("timeline"))),
            len(_items(data.get("timeline"))),
            ">=1",
        ),
        _check(
            "root-cause-present", _text(data.get("root_cause")), data.get("root_cause"), "non-empty"
        ),
        _check(
            "prevention-owned-and-verifiable",
            _all_have(data.get("prevention_actions"), "owner", "verification_check"),
            data.get("prevention_actions"),
            "owner and verification_check per action",
        ),
    )


def _migration(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "dependencies-present",
            bool(_items(data.get("dependencies"))),
            len(_items(data.get("dependencies"))),
            ">=1",
        ),
        _check(
            "owners-complete",
            data.get("owners_complete") is True,
            data.get("owners_complete"),
            True,
        ),
        _check(
            "rollback-conditions-present",
            bool(_items(data.get("rollback_conditions"))),
            len(_items(data.get("rollback_conditions"))),
            ">=1",
        ),
        _check(
            "acceptance-checks-pass",
            _all_pass(data.get("acceptance_checks")),
            data.get("acceptance_checks"),
            "all PASS",
        ),
    )


def _docs_drift(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "drift-evidence-present",
            _all_have_id_list(
                data.get("drift_items"),
                text_fields=("observed", "documented"),
                ids_field="evidence_source_ids",
            ),
            data.get("drift_items"),
            "observed/documented/evidence per item",
        ),
        _check(
            "repairs-proposed",
            bool(_items(data.get("proposed_repairs"))),
            len(_items(data.get("proposed_repairs"))),
            ">=1",
        ),
        _check(
            "publication-remains-draft",
            data.get("publish_status") == "DRAFT",
            data.get("publish_status"),
            "DRAFT",
        ),
    )


def _customer_research(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "quotes-have-source",
            _all_have_id_list(data.get("quotes"), text_fields=("text",), ids_field="source_ids"),
            data.get("quotes"),
            "text and source_ids per quote",
        ),
        _check(
            "themes-have-sources",
            _all_have_id_list(data.get("themes"), text_fields=("theme",), ids_field="source_ids"),
            data.get("themes"),
            "theme and source_ids per theme",
        ),
        _check(
            "contradictions-explicit",
            isinstance(data.get("contradictions"), list),
            data.get("contradictions"),
            "list, including empty",
        ),
    )


def _market_watch(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    changes = _items(data.get("changes"))
    cutoff_raw = data.get("freshness_cutoff")
    fresh = False
    try:
        cutoff = datetime.fromisoformat(str(cutoff_raw).replace("Z", "+00:00"))
        observed = [
            datetime.fromisoformat(str(item["observed_at"]).replace("Z", "+00:00"))
            for item in changes
            if isinstance(item, Mapping)
        ]
        fresh = (
            bool(changes)
            and len(observed) == len(changes)
            and cutoff.tzinfo is not None
            and all(item.tzinfo is not None and item >= cutoff for item in observed)
        )
    except (KeyError, TypeError, ValueError):
        fresh = False
    return (
        _check(
            "changes-have-fresh-sources",
            _all_have_id_list(
                data.get("changes"),
                text_fields=("change", "observed_at"),
                ids_field="source_ids",
            ),
            data.get("changes"),
            "change/observed_at/source_ids per item",
        ),
        _check(
            "changes-meet-freshness-cutoff",
            fresh,
            {"changes": changes, "freshness_cutoff": cutoff_raw},
            "every observed_at >= freshness_cutoff with explicit timezone",
        ),
        _check(
            "conflicts-explicit",
            isinstance(data.get("conflicts"), list),
            data.get("conflicts"),
            "list, including empty",
        ),
    )


def _executive_update(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "claims-have-sources",
            _all_have_id_list(data.get("claims"), text_fields=("claim",), ids_field="source_ids"),
            data.get("claims"),
            "claim and source_ids per item",
        ),
        _check(
            "no-unverified-claims",
            data.get("unverified_claim_count") == 0,
            data.get("unverified_claim_count"),
            0,
        ),
    )


def _prototype(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "hypothesis-present", _text(data.get("hypothesis")), data.get("hypothesis"), "non-empty"
        ),
        _check(
            "source-set-present",
            _non_empty_id_list(data.get("source_ids")),
            data.get("source_ids"),
            "non-empty ID list",
        ),
        _check(
            "prototype-scope-present",
            bool(_items(data.get("prototype_scope"))),
            len(_items(data.get("prototype_scope"))),
            ">=1",
        ),
        _check(
            "verification-checks-pass",
            _all_pass(data.get("verification_checks")),
            data.get("verification_checks"),
            "all PASS",
        ),
    )


def _deploy_starter(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    budget = data.get("cost_budget_inr")
    return (
        _check(
            "starter-files-present",
            bool(_items(data.get("starter_files"))),
            len(_items(data.get("starter_files"))),
            ">=1",
        ),
        _check(
            "cost-budget-positive",
            isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0,
            budget,
            ">0",
        ),
        _check(
            "security-checks-pass",
            _all_pass(data.get("security_checks")),
            data.get("security_checks"),
            "all PASS",
        ),
        _check(
            "monitoring-checks-pass",
            _all_pass(data.get("monitoring_checks")),
            data.get("monitoring_checks"),
            "all PASS",
        ),
        _check(
            "rollback-steps-present",
            bool(_items(data.get("rollback_steps"))),
            len(_items(data.get("rollback_steps"))),
            ">=1",
        ),
    )


def _small_tool(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "input-schema-present",
            bool(_mapping(data.get("input_schema"))),
            data.get("input_schema"),
            "non-empty object",
        ),
        _check(
            "transformations-present",
            bool(_items(data.get("transformations"))),
            len(_items(data.get("transformations"))),
            ">=1",
        ),
        _check("tests-pass", _all_pass(data.get("tests")), data.get("tests"), "all PASS"),
    )


def _repo_doctor(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    runs = _items(data.get("command_runs"))
    commands_are_structured = bool(runs) and all(
        isinstance(item, Mapping)
        and _text(item.get("command"))
        and bool(_items(item.get("evidence_source_ids")))
        and _text(item.get("output_digest"))
        for item in runs
    )
    return (
        _check(
            "command-evidence-declared",
            commands_are_structured,
            runs,
            "command + output_digest + evidence_source_ids per run",
        ),
        _check(
            "repair-plan-present",
            bool(_items(data.get("repair_plan"))),
            len(_items(data.get("repair_plan"))),
            ">=1",
        ),
        _check(
            "verification-commands-present",
            bool(_items(data.get("verification_commands"))),
            len(_items(data.get("verification_commands"))),
            ">=1",
        ),
    )


def _learning_plan(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "tasks-have-success-checks",
            _all_have(data.get("tasks"), "task", "success_check"),
            data.get("tasks"),
            "task and success_check per item",
        ),
        _check(
            "feedback-loop-present",
            _text(data.get("feedback_loop")),
            data.get("feedback_loop"),
            "non-empty",
        ),
        _check(
            "answers-not-pregenerated",
            data.get("answers_pre_generated") is False,
            data.get("answers_pre_generated"),
            False,
        ),
    )


def _career_proof(data: Mapping[str, Any]) -> tuple[VerifiedCheck, ...]:
    return (
        _check(
            "readme-outline-present",
            bool(_items(data.get("readme_outline"))),
            len(_items(data.get("readme_outline"))),
            ">=1",
        ),
        _check(
            "demo-outline-present",
            bool(_items(data.get("demo_outline"))),
            len(_items(data.get("demo_outline"))),
            ">=1",
        ),
        _check(
            "case-study-present",
            bool(_mapping(data.get("case_study"))),
            data.get("case_study"),
            "non-empty object",
        ),
        _check(
            "evidence-links-present",
            bool(_items(data.get("evidence_links"))),
            len(_items(data.get("evidence_links"))),
            ">=1",
        ),
    )


_VERIFIERS: dict[str, Verifier] = {
    "prd-architecture-task-compiler": _compile_delivery,
    "release-readiness-room": _release_readiness,
    "experiment-to-decision": _experiment,
    "incident-to-prevention": _incident,
    "migration-impact-planner": _migration,
    "docs-runbook-drift-maintainer": _docs_drift,
    "customer-research-synthesis": _customer_research,
    "competitive-market-watch": _market_watch,
    "verified-executive-update": _executive_update,
    "research-to-prototype": _prototype,
    "idea-to-deploy-starter": _deploy_starter,
    "data-to-small-tool": _small_tool,
    "repo-doctor": _repo_doctor,
    "learning-to-build-coach": _learning_plan,
    "career-proof-pack": _career_proof,
}

_RESULT_COLLECTIONS = (
    "release_checks",
    "acceptance_checks",
    "verification_checks",
    "security_checks",
    "monitoring_checks",
    "tests",
)


def verify_extended_pack(
    workflow_id: str,
    records: Sequence[Mapping[str, Any]],
    evidence_sources: Mapping[str, Mapping[str, Any]],
) -> tuple[VerifiedCheck, ...]:
    """Evaluate admitted record content with the fixed verifier for one pack."""

    merged: dict[str, Any] = {}
    conflicts: list[str] = []
    for record in records:
        content = record.get("content")
        if not isinstance(content, Mapping):
            conflicts.append(str(record.get("record_id", "unknown")))
            continue
        for key, value in content.items():
            if key in merged and merged[key] != value:
                conflicts.append(str(key))
            else:
                merged[str(key)] = value
    verifier = _VERIFIERS[workflow_id]
    checks = list(verifier(merged))
    declared_results = [
        (collection, item)
        for collection in _RESULT_COLLECTIONS
        for item in _items(merged.get(collection))
    ]
    if declared_results:
        all_results_bound = True
        for collection, item in declared_results:
            if (
                not isinstance(item, Mapping)
                or item.get("status") != "PASS"
                or not _text(item.get("check_id"))
                or not _text(item.get("result_digest"))
                or not _non_empty_id_list(item.get("evidence_source_ids"))
            ):
                all_results_bound = False
                continue
            matching = False
            for source_id in item["evidence_source_ids"]:
                source = evidence_sources.get(str(source_id), {})
                content = source.get("content") if isinstance(source, Mapping) else None
                if not isinstance(content, Mapping):
                    continue
                matching = matching or any(
                    isinstance(result, Mapping)
                    and result.get("workflow_id") == workflow_id
                    and result.get("collection") == collection
                    and result.get("check_id") == item.get("check_id")
                    and result.get("status") == item.get("status")
                    and result.get("result_digest") == item.get("result_digest")
                    for result in _items(content.get("check_results"))
                )
            if not matching:
                all_results_bound = False
        checks.append(
            _check(
                "declared-results-bound-to-admitted-artifacts",
                all_results_bound,
                [item for _collection, item in declared_results],
                "every PASS matches an admitted check-result artifact",
            )
        )
    if workflow_id == "repo-doctor":
        runs = _items(merged.get("command_runs"))
        evidence_bound = bool(runs)
        verified_commands: set[str] = set()
        for run in runs:
            if not isinstance(run, Mapping):
                evidence_bound = False
                continue
            matching_results: list[Mapping[str, Any]] = []
            for source_id in _items(run.get("evidence_source_ids")):
                source = evidence_sources.get(str(source_id), {})
                content = source.get("content") if isinstance(source, Mapping) else None
                if not isinstance(content, Mapping):
                    continue
                matching_results.extend(
                    item
                    for item in _items(content.get("command_results"))
                    if isinstance(item, Mapping)
                    and item.get("command") == run.get("command")
                    and item.get("exit_code") == run.get("exit_code") == 0
                    and item.get("output_digest") == run.get("output_digest")
                )
            if not matching_results:
                evidence_bound = False
            else:
                verified_commands.add(str(run["command"]))
        declared_verification_commands = _items(merged.get("verification_commands"))
        all_verification_commands_bound = bool(declared_verification_commands) and all(
            _text(command) and str(command) in verified_commands
            for command in declared_verification_commands
        )
        checks.append(
            _check(
                "commands-bound-to-admitted-results",
                evidence_bound,
                runs,
                "each successful command matches an admitted command-result artifact",
            )
        )
        checks.append(
            _check(
                "verification-commands-bound-to-results",
                all_verification_commands_bound,
                declared_verification_commands,
                "every verification command has matching successful admitted evidence",
            )
        )
    checks.append(
        _check(
            "record-content-unambiguous",
            not conflicts,
            sorted(set(conflicts)),
            [],
        )
    )
    return tuple(checks)
