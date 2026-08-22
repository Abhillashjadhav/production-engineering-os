"""Deterministic acceptance-criteria compilation for the bare-bones core."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import canonical_digest


class AcceptanceCompileError(ValueError):
    """The product contract cannot be compiled without guessing."""

    def __init__(self, diagnostics: Sequence[AcceptanceDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(f"{item.code}:{item.subject_id}" for item in diagnostics))


class Operator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


@dataclass(frozen=True)
class AcceptanceDiagnostic:
    code: str
    subject_id: str
    message: str


@dataclass(frozen=True)
class PropertyAssertion:
    path: str
    operator: Operator
    value: Any = None


@dataclass(frozen=True)
class ActionCall:
    action: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class HumanTest:
    path: str
    node_id: str
    command: tuple[str, ...]
    file_digest: str


@dataclass(frozen=True)
class TemplateProof:
    template_version: str
    test_id: str
    file_digest: str


@dataclass(frozen=True)
class CompiledCriterion:
    criterion_id: str
    requirement_refs: tuple[str, ...]
    form: str
    given: tuple[PropertyAssertion, ...] = ()
    when: ActionCall | None = None
    then: tuple[PropertyAssertion, ...] = ()
    measure: str = ""
    operator: Operator | None = None
    value: Any = None
    minimum_sample: int | None = None
    human_test: HumanTest | None = None
    template_proof: TemplateProof | None = None


@dataclass(frozen=True)
class BuildTask:
    task_id: str
    requirement_id: str


@dataclass(frozen=True)
class AcceptanceBuildPlan:
    contract_digest: str
    requirements: tuple[str, ...]
    tasks: tuple[BuildTask, ...]
    criteria: tuple[CompiledCriterion, ...]
    trusted_test_digests: tuple[tuple[str, str], ...]
    plan_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _assertions(
    value: Any,
    *,
    criterion_id: str,
    field: str,
    diagnostics: list[AcceptanceDiagnostic],
) -> tuple[PropertyAssertion, ...]:
    if not isinstance(value, list) or not value:
        diagnostics.append(
            AcceptanceDiagnostic(
                "INVALID_ASSERTION_LIST",
                criterion_id,
                f"{field} must be a non-empty assertion list",
            )
        )
        return ()
    compiled: list[PropertyAssertion] = []
    for index, raw in enumerate(value):
        item = _mapping(raw)
        if item is None or not isinstance(item.get("path"), str) or not item["path"]:
            diagnostics.append(
                AcceptanceDiagnostic(
                    "INVALID_ASSERTION_PATH",
                    criterion_id,
                    f"{field}[{index}] requires a path",
                )
            )
            continue
        try:
            operator = Operator(str(item.get("operator", "")))
        except ValueError:
            diagnostics.append(
                AcceptanceDiagnostic(
                    "UNKNOWN_ASSERTION_OPERATOR",
                    criterion_id,
                    f"{field}[{index}] uses an unregistered operator",
                )
            )
            continue
        unary = {Operator.IS_TRUE, Operator.IS_FALSE, Operator.IS_NULL, Operator.NOT_NULL}
        if operator not in unary and "value" not in item:
            diagnostics.append(
                AcceptanceDiagnostic(
                    "MISSING_ASSERTION_VALUE",
                    criterion_id,
                    f"{field}[{index}] requires an explicit value",
                )
            )
            continue
        assertion_value = item.get("value")
        if operator is Operator.MATCHES:
            try:
                if not isinstance(assertion_value, str):
                    raise re.error("pattern must be a string")
                re.compile(assertion_value)
            except re.error:
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "INVALID_REGEX_ASSERTION",
                        criterion_id,
                        f"{field}[{index}] requires a valid string regex",
                    )
                )
                continue
        ordered = {Operator.LT, Operator.LTE, Operator.GT, Operator.GTE}
        if operator in ordered and (
            isinstance(assertion_value, bool) or not isinstance(assertion_value, (int, float, str))
        ):
            diagnostics.append(
                AcceptanceDiagnostic(
                    "INVALID_ORDERED_ASSERTION_VALUE",
                    criterion_id,
                    f"{field}[{index}] requires a number or string value",
                )
            )
            continue
        compiled.append(PropertyAssertion(str(item["path"]), operator, assertion_value))
    for path in sorted({item.path for item in compiled}):
        if _assertion_set_contradictory(tuple(item for item in compiled if item.path == path)):
            diagnostics.append(
                AcceptanceDiagnostic(
                    "CONTRADICTORY_ASSERTIONS",
                    criterion_id,
                    f"{field} contains incompatible assertions for {path}",
                )
            )
            return tuple(compiled)
    return tuple(compiled)


def _ordered_comparison(left: Any, operator: Operator, right: Any) -> bool | None:
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    numeric = (int, float)
    compatible = (
        isinstance(left, numeric)
        and isinstance(right, numeric)
        or isinstance(left, str)
        and isinstance(right, str)
    )
    if not compatible:
        return None
    operations = {
        Operator.LT: lambda: left < right,
        Operator.LTE: lambda: left <= right,
        Operator.GT: lambda: left > right,
        Operator.GTE: lambda: left >= right,
    }
    try:
        return bool(operations[operator]())
    except (KeyError, TypeError):
        return None


def _literal_satisfies(assertion: PropertyAssertion, value: Any) -> bool:
    if assertion.operator is Operator.EQ:
        return canonical_digest(value) == canonical_digest(assertion.value)
    if assertion.operator is Operator.NE:
        return canonical_digest(value) != canonical_digest(assertion.value)
    if assertion.operator in {Operator.LT, Operator.LTE, Operator.GT, Operator.GTE}:
        return _ordered_comparison(value, assertion.operator, assertion.value) is True
    if assertion.operator is Operator.MATCHES:
        return isinstance(value, str) and bool(re.search(assertion.value, value))
    if assertion.operator in {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        if isinstance(value, list):
            present = any(
                canonical_digest(item) == canonical_digest(assertion.value) for item in value
            )
        elif isinstance(assertion.value, str) and isinstance(value, (str, Mapping)):
            present = assertion.value in value
        else:
            return False
        return present if assertion.operator is Operator.CONTAINS else not present
    unary = {
        Operator.IS_TRUE: value is True,
        Operator.IS_FALSE: value is False,
        Operator.IS_NULL: value is None,
        Operator.NOT_NULL: value is not None,
    }
    return unary[assertion.operator]


def _assertion_set_contradictory(assertions: tuple[PropertyAssertion, ...]) -> bool:
    for index, left in enumerate(assertions):
        if any(_contradictory(left, right) for right in assertions[index + 1 :]):
            return True

    exact_values = [item.value for item in assertions if item.operator is Operator.EQ]
    exact_values.extend(
        {
            Operator.IS_TRUE: True,
            Operator.IS_FALSE: False,
            Operator.IS_NULL: None,
        }[item.operator]
        for item in assertions
        if item.operator in {Operator.IS_TRUE, Operator.IS_FALSE, Operator.IS_NULL}
    )
    lower = [item for item in assertions if item.operator is Operator.GTE]
    upper = [item for item in assertions if item.operator is Operator.LTE]
    for floor in lower:
        for ceiling in upper:
            if canonical_digest(floor.value) == canonical_digest(ceiling.value):
                exact_values.append(floor.value)
    return any(
        any(not _literal_satisfies(assertion, value) for assertion in assertions)
        for value in exact_values
    )


def _contradictory(left: PropertyAssertion, right: PropertyAssertion) -> bool:
    containment = {Operator.CONTAINS, Operator.NOT_CONTAINS}
    if (
        left.operator is Operator.MATCHES
        and right.operator in containment
        and not isinstance(right.value, str)
        or right.operator is Operator.MATCHES
        and left.operator in containment
        and not isinstance(left.value, str)
    ):
        return True
    if left.operator is Operator.EQ and right.operator is Operator.EQ:
        return canonical_digest(left.value) != canonical_digest(right.value)
    if {left.operator, right.operator} == {Operator.EQ, Operator.NE}:
        return canonical_digest(left.value) == canonical_digest(right.value)
    if {left.operator, right.operator} == {Operator.CONTAINS, Operator.NOT_CONTAINS}:
        return canonical_digest(left.value) == canonical_digest(right.value)
    opposite_unary = {
        (Operator.IS_TRUE, Operator.IS_FALSE),
        (Operator.IS_FALSE, Operator.IS_TRUE),
        (Operator.IS_NULL, Operator.NOT_NULL),
        (Operator.NOT_NULL, Operator.IS_NULL),
    }
    if (left.operator, right.operator) in opposite_unary:
        return True
    exact_unary = {
        Operator.IS_TRUE: True,
        Operator.IS_FALSE: False,
        Operator.IS_NULL: None,
    }
    if left.operator in exact_unary:
        return not _literal_satisfies(right, exact_unary[left.operator])
    if right.operator in exact_unary:
        return not _literal_satisfies(left, exact_unary[right.operator])
    equality = {Operator.EQ, Operator.NE}
    unary = {Operator.IS_TRUE, Operator.IS_FALSE, Operator.IS_NULL, Operator.NOT_NULL}
    equality_assertion = left if left.operator in equality else right
    unary_assertion = left if left.operator in unary else right
    if equality_assertion.operator in equality and unary_assertion.operator in unary:
        unary_matches = {
            Operator.IS_TRUE: equality_assertion.value is True,
            Operator.IS_FALSE: equality_assertion.value is False,
            Operator.IS_NULL: equality_assertion.value is None,
            Operator.NOT_NULL: equality_assertion.value is not None,
        }[unary_assertion.operator]
        if equality_assertion.operator is Operator.EQ:
            return not unary_matches
        return unary_assertion.operator is not Operator.NOT_NULL and unary_matches
    ordered = {Operator.LT, Operator.LTE, Operator.GT, Operator.GTE}
    if (
        left.operator in ordered
        and right.operator in ordered
        and _ordered_comparison(left.value, Operator.GT, right.value) is None
    ):
        return True
    if left.operator is Operator.EQ and right.operator in ordered:
        result = _ordered_comparison(left.value, right.operator, right.value)
        return result is not True
    if right.operator is Operator.EQ and left.operator in ordered:
        result = _ordered_comparison(right.value, left.operator, left.value)
        return result is not True
    lower = left if left.operator in {Operator.GT, Operator.GTE} else right
    upper = right if right.operator in {Operator.LT, Operator.LTE} else left
    if lower.operator not in {Operator.GT, Operator.GTE} or upper.operator not in {
        Operator.LT,
        Operator.LTE,
    }:
        return False
    greater = _ordered_comparison(lower.value, Operator.GT, upper.value)
    if greater is None or greater:
        return True
    return lower.value == upper.value and (
        lower.operator is Operator.GT or upper.operator is Operator.LT
    )


def _human_test(
    raw: Mapping[str, Any],
    *,
    criterion_id: str,
    repository_root: Path,
    diagnostics: list[AcceptanceDiagnostic],
) -> HumanTest | None:
    path_value = raw.get("path")
    node_id = raw.get("node_id")
    command = raw.get("command")
    if (
        not isinstance(path_value, str)
        or not path_value.startswith("tests/")
        or Path(path_value).is_absolute()
        or any(part in {".", ".."} for part in path_value.split("/"))
        or not isinstance(node_id, str)
        or not node_id
        or not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        diagnostics.append(
            AcceptanceDiagnostic(
                "INVALID_HUMAN_TEST_REFERENCE",
                criterion_id,
                "human test must bind a safe tests/ path, node ID, and argv",
            )
        )
        return None
    path = repository_root / path_value
    if not path.is_file():
        diagnostics.append(
            AcceptanceDiagnostic(
                "HUMAN_TEST_MISSING",
                criterion_id,
                f"human test does not exist: {path_value}",
            )
        )
        return None
    target = f"{path_value}::{node_id}"
    is_pytest = Path(command[0]).name.startswith("pytest") or (
        len(command) >= 3 and command[1:3] == ["-m", "pytest"]
    )
    if not is_pytest or target not in command:
        diagnostics.append(
            AcceptanceDiagnostic(
                "HUMAN_TEST_COMMAND_MISMATCH",
                criterion_id,
                "human test command must run pytest against its exact bound node",
            )
        )
        return None
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return HumanTest(path_value, node_id, tuple(command), digest)


def compile_acceptance_plan(
    contract: Mapping[str, Any],
    *,
    repository_root: Path,
    registered_actions: frozenset[str],
    template_version: str,
    template_test_digests: Mapping[str, str],
    registered_measures: frozenset[str] = frozenset(),
    trusted_test_digests: Mapping[str, str] | None = None,
) -> AcceptanceBuildPlan:
    """Compile typed criteria and prove task/test coverage before any build."""

    diagnostics: list[AcceptanceDiagnostic] = []
    requirements_raw = _mapping(contract.get("functional_requirements"))
    criteria_raw = _mapping(contract.get("acceptance_criteria"))
    if not requirements_raw:
        diagnostics.append(
            AcceptanceDiagnostic(
                "REQUIREMENTS_MISSING", "contract", "functional requirements are required"
            )
        )
        requirements_raw = {}
    if not criteria_raw:
        diagnostics.append(
            AcceptanceDiagnostic("CRITERIA_MISSING", "contract", "acceptance criteria are required")
        )
        criteria_raw = {}

    requirements = tuple(sorted(str(item) for item in requirements_raw))
    requirement_set = frozenset(requirements)
    covered: set[str] = set()
    compiled: list[CompiledCriterion] = []

    for criterion_id, raw in sorted(criteria_raw.items(), key=lambda item: str(item[0])):
        cid = str(criterion_id)
        item = _mapping(raw)
        if item is None:
            diagnostics.append(
                AcceptanceDiagnostic("INVALID_CRITERION", cid, "criterion must be an object")
            )
            continue
        refs_raw = item.get("requirement_refs")
        if (
            not isinstance(refs_raw, list)
            or not refs_raw
            or not all(isinstance(ref, str) and ref for ref in refs_raw)
        ):
            diagnostics.append(
                AcceptanceDiagnostic(
                    "REQUIREMENT_REFS_MISSING", cid, "criterion needs requirement_refs"
                )
            )
            continue
        refs = tuple(sorted(set(refs_raw)))
        unknown = sorted(set(refs) - requirement_set)
        if unknown:
            diagnostics.append(
                AcceptanceDiagnostic("UNKNOWN_REQUIREMENT_REF", cid, ", ".join(unknown))
            )
            continue
        covered.update(refs)

        forms = {
            "given_when_then": all(key in item for key in ("given", "when", "then")),
            "measure": all(key in item for key in ("measure", "operator", "value")),
            "human_test": "human_test" in item,
            "satisfied_by_template": "satisfied_by_template" in item,
        }
        selected = [name for name, present in forms.items() if present]
        if len(selected) != 1:
            diagnostics.append(
                AcceptanceDiagnostic(
                    "CRITERION_FORM_INVALID",
                    cid,
                    "criterion must select exactly one executable form",
                )
            )
            continue
        form = selected[0]
        if form == "given_when_then":
            when_raw = _mapping(item.get("when"))
            action = "" if when_raw is None else str(when_raw.get("action", ""))
            arguments = {} if when_raw is None else when_raw.get("arguments", {})
            if action not in registered_actions or not isinstance(arguments, Mapping):
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "ACTION_NOT_REGISTERED", cid, "when.action is not registered"
                    )
                )
                continue
            given = _assertions(
                item.get("given"), criterion_id=cid, field="given", diagnostics=diagnostics
            )
            then = _assertions(
                item.get("then"), criterion_id=cid, field="then", diagnostics=diagnostics
            )
            if given and then:
                compiled.append(
                    CompiledCriterion(
                        cid,
                        refs,
                        form,
                        given=given,
                        when=ActionCall(action, dict(arguments)),
                        then=then,
                    )
                )
        elif form == "measure":
            try:
                operator = Operator(str(item.get("operator", "")))
            except ValueError:
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "UNKNOWN_ASSERTION_OPERATOR", cid, "measure operator is unregistered"
                    )
                )
                continue
            measure = item.get("measure")
            sample = _mapping(item.get("sample")) or {}
            minimum = sample.get("minimum")
            if (
                not isinstance(measure, str)
                or not measure
                or measure not in registered_measures
                or isinstance(minimum, bool)
                or not isinstance(minimum, int)
                or minimum <= 0
            ):
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "MEASURE_INVALID",
                        cid,
                        "measure needs a registered source and positive sample.minimum",
                    )
                )
                continue
            assertion_value = item.get("value")
            if operator is Operator.MATCHES:
                try:
                    if not isinstance(assertion_value, str):
                        raise re.error("pattern must be a string")
                    re.compile(assertion_value)
                except re.error:
                    diagnostics.append(
                        AcceptanceDiagnostic(
                            "INVALID_REGEX_ASSERTION",
                            cid,
                            "measure requires a valid string regex",
                        )
                    )
                    continue
            if operator in {Operator.LT, Operator.LTE, Operator.GT, Operator.GTE} and (
                isinstance(assertion_value, bool)
                or not isinstance(assertion_value, (int, float, str))
            ):
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "INVALID_ORDERED_ASSERTION_VALUE",
                        cid,
                        "measure requires a number or string value",
                    )
                )
                continue
            compiled.append(
                CompiledCriterion(
                    cid,
                    refs,
                    form,
                    measure=measure,
                    operator=operator,
                    value=assertion_value,
                    minimum_sample=minimum,
                )
            )
        elif form == "human_test":
            human_raw = _mapping(item.get("human_test"))
            human = (
                None
                if human_raw is None
                else _human_test(
                    human_raw,
                    criterion_id=cid,
                    repository_root=repository_root,
                    diagnostics=diagnostics,
                )
            )
            if human is not None:
                compiled.append(CompiledCriterion(cid, refs, form, human_test=human))
        else:
            proof_raw = _mapping(item.get("satisfied_by_template"))
            version = "" if proof_raw is None else str(proof_raw.get("template_version", ""))
            test_id = "" if proof_raw is None else str(proof_raw.get("test_id", ""))
            proof_digest = template_test_digests.get(test_id)
            if version != template_version or proof_digest is None:
                diagnostics.append(
                    AcceptanceDiagnostic(
                        "TEMPLATE_PROOF_INVALID",
                        cid,
                        "template proof does not match the pinned template",
                    )
                )
                continue
            compiled.append(
                CompiledCriterion(
                    cid,
                    refs,
                    form,
                    template_proof=TemplateProof(version, test_id, proof_digest),
                )
            )

    for requirement_id in sorted(requirement_set - covered):
        diagnostics.append(
            AcceptanceDiagnostic(
                "REQUIREMENT_UNCOVERED",
                requirement_id,
                "requirement has no executable criterion",
            )
        )
    if diagnostics:
        raise AcceptanceCompileError(diagnostics)

    tasks = tuple(
        BuildTask(f"TASK-{index:03d}", item) for index, item in enumerate(requirements, 1)
    )
    trusted_digests = trusted_test_digests or {}
    shell = {
        "contract_digest": canonical_digest(contract),
        "requirements": requirements,
        "tasks": [asdict(item) for item in tasks],
        "criteria": [asdict(item) for item in compiled],
        "trusted_test_digests": sorted(trusted_digests.items()),
    }
    return AcceptanceBuildPlan(
        contract_digest=str(shell["contract_digest"]),
        requirements=requirements,
        tasks=tasks,
        criteria=tuple(compiled),
        trusted_test_digests=tuple(sorted(trusted_digests.items())),
        plan_digest=canonical_digest(shell),
    )
