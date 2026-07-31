"""Versioned, deterministic stack adapters for repository evidence."""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from pmpe.repository.models import BoundaryCandidate, EvidenceItem, Finding


@dataclass(frozen=True)
class TrackedFile:
    path: str
    mode: str
    object_id: str
    digest: str
    content: bytes | None
    binary: bool
    oversized: bool = False


@dataclass(frozen=True)
class AdapterContext:
    files: tuple[TrackedFile, ...]

    def matching(self, patterns: tuple[str, ...]) -> tuple[TrackedFile, ...]:
        return tuple(
            item
            for item in self.files
            if any(fnmatch.fnmatch(item.path, pattern) for pattern in patterns)
        )


@dataclass(frozen=True)
class AdapterResult:
    items: tuple[tuple[str, EvidenceItem], ...] = ()
    findings: tuple[Finding, ...] = ()
    boundaries: tuple[BoundaryCandidate, ...] = ()


AdapterEvaluator = Callable[[AdapterContext], AdapterResult]


@dataclass(frozen=True)
class RepositoryAdapter:
    adapter_id: str
    version: str
    file_patterns: tuple[str, ...]
    supported_categories: tuple[str, ...]
    evaluator: AdapterEvaluator
    failure_behavior: str = "VISIBLE_PARTIAL_OR_BLOCKED"
    detection_logic: str = "TRACKED_PATH_AND_SAFE_STRUCTURE_ONLY"
    evidence_emitted: str = "DIGEST_BOUND_FILE_EVIDENCE"
    confidence_semantics: str = "HIGH_EXACT_MEDIUM_HEURISTIC_LOW_SIGNAL"


def repository_adapter(
    *,
    adapter_id: str,
    version: str,
    file_patterns: tuple[str, ...],
    supported_categories: tuple[str, ...],
) -> Callable[[AdapterEvaluator], RepositoryAdapter]:
    """Declare an immutable adapter with visible failure semantics."""

    def decorate(evaluator: AdapterEvaluator) -> RepositoryAdapter:
        return RepositoryAdapter(
            adapter_id=adapter_id,
            version=version,
            file_patterns=file_patterns,
            supported_categories=supported_categories,
            evaluator=evaluator,
        )

    return decorate


def _item(
    file: TrackedFile,
    kind: str,
    detector: str,
    version: str = "1.0.0",
    *,
    confidence: str = "HIGH",
) -> EvidenceItem:
    return EvidenceItem(
        kind=kind,
        path=file.path,
        file_digest=file.digest,
        detector_id=detector,
        detector_version=version,
        confidence=confidence,
    )


def _finding(
    code: str,
    category: str,
    explanation: str,
    evidence: tuple[str, ...],
    detector: str,
    *,
    severity: str = "MEDIUM",
    confidence: str = "HIGH",
    blocking: bool = False,
) -> Finding:
    return Finding(
        code=code,
        category=category,
        severity=severity,
        confidence=confidence,
        explanation=explanation,
        evidence_refs=evidence,
        detector_id=detector,
        detector_version="1.0.0",
        blocking=blocking,
    )


def _test_signal_kind(path: str) -> str | None:
    """Classify conventional test paths/names as medium-confidence signals only."""

    pure = PurePosixPath(path)
    lowered_parts = tuple(part.lower() for part in pure.parts)
    name = pure.name.lower()
    in_test_area = any(part in {"test", "tests", "__tests__"} for part in lowered_parts[:-1])
    named_test = (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec."))
    )
    if not (in_test_area or named_test):
        return None
    if "unit" in lowered_parts:
        return "UNIT_TEST_FILE_SIGNAL"
    if "integration" in lowered_parts:
        return "INTEGRATION_TEST_FILE_SIGNAL"
    if "e2e" in lowered_parts or "end_to_end" in lowered_parts:
        return "E2E_TEST_FILE_SIGNAL"
    if "contract" in lowered_parts or "contract" in name:
        return "CONTRACT_TEST_FILE_SIGNAL"
    if "security" in lowered_parts or "security" in name:
        return "SECURITY_TEST_FILE_SIGNAL"
    if any(token in lowered_parts for token in ("performance", "perf", "benchmarks")):
        return "PERFORMANCE_TEST_FILE_SIGNAL"
    if "mutation" in lowered_parts or "mutation" in name:
        return "MUTATION_TEST_FILE_SIGNAL"
    return "TEST_FILE_SIGNAL"


@repository_adapter(
    adapter_id="core.repository-topology",
    version="1.0.0",
    file_patterns=("**/*", "*"),
    supported_categories=(
        "repository_topology",
        "architecture_boundaries",
        "documentation_governance",
        "debt_risk",
    ),
)
def _topology(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    boundaries: list[BoundaryCandidate] = []
    for file in context.files:
        name = PurePosixPath(file.path).name
        lowered = file.path.lower()
        if file.mode == "160000":
            kind = "SUBMODULE"
        elif file.mode == "120000":
            kind = "SYMLINK"
        elif file.binary:
            kind = "BINARY_FILE"
        elif any(part in {"vendor", "vendored", "node_modules"} for part in file.path.split("/")):
            kind = "VENDORED_AREA"
        elif "generated" in file.path.lower() or file.path.endswith("_generated.py"):
            kind = "GENERATED_AREA"
        elif name == ".gitignore":
            kind = "IGNORE_POLICY"
        elif name == ".gitmodules":
            kind = "SUBMODULE_CONFIG"
        elif name in {"package.json", "pyproject.toml", "Cargo.toml", "go.mod"}:
            kind = "PACKAGE_BOUNDARY_MANIFEST"
        else:
            kind = "TRACKED_FILE"
        items.append(("repository_topology", _item(file, kind, "core.repository-topology")))

        if file.path in {"README.md", "CONTRIBUTING.md", "SECURITY.md"}:
            items.append(
                (
                    "documentation_governance",
                    _item(file, "POLICY_DOCUMENT", "core.repository-topology"),
                )
            )
        if lowered.startswith("docs/adr/") or "/adr/" in lowered:
            items.append(
                ("documentation_governance", _item(file, "ADR", "core.repository-topology"))
            )
        if file.path in {".github/CODEOWNERS", "CODEOWNERS"}:
            items.append(
                ("documentation_governance", _item(file, "CODEOWNERS", "core.repository-topology"))
            )
            items.append(
                ("security_privacy", _item(file, "OWNERSHIP_CONTROL", "core.repository-topology"))
            )
        if lowered.startswith(".github/issue_template/"):
            items.append(
                (
                    "documentation_governance",
                    _item(file, "ISSUE_TEMPLATE", "core.repository-topology"),
                )
            )
        if lowered in {".github/pull_request_template.md", "pull_request_template.md"}:
            items.append(
                (
                    "documentation_governance",
                    _item(file, "PR_TEMPLATE", "core.repository-topology"),
                )
            )
        if any(token in lowered for token in ("/alerts", "/slo", "/metrics", "/traces")):
            items.append(
                (
                    "observability_operations",
                    _item(
                        file,
                        "OBSERVABILITY_CONFIG_SIGNAL",
                        "core.repository-topology",
                        confidence="MEDIUM",
                    ),
                )
            )
        if any(
            token in lowered
            for token in ("security", "dependabot", "codeql", "secret-scan", "permissions")
        ):
            items.append(
                (
                    "security_privacy",
                    _item(
                        file,
                        "SECURITY_CONTROL_SIGNAL",
                        "core.repository-topology",
                        confidence="MEDIUM",
                    ),
                )
            )
        if any(token in lowered for token in ("terraform", "kubernetes", "helm", "/deploy")):
            items.append(
                (
                    "delivery_environments",
                    _item(
                        file,
                        "DEPLOYMENT_DEFINITION_SIGNAL",
                        "core.repository-topology",
                        confidence="MEDIUM",
                    ),
                )
            )

    roots: dict[tuple[str, str], set[str]] = {}
    for file in context.files:
        parts = PurePosixPath(file.path).parts
        if len(parts) >= 2 and parts[0] in {
            "src",
            "packages",
            "services",
            "apps",
            "libraries",
            "workers",
        }:
            root = "/".join(parts[:2])
            if parts[0] == "services":
                kind = "SERVICE"
            elif (
                parts[0] == "apps"
                or parts[0] == "packages"
                and any(candidate.path == f"{root}/package.json" for candidate in context.files)
            ):
                kind = "APPLICATION"
            else:
                kind = "PACKAGE"
            roots.setdefault((kind, root), set()).add(file.path)
    for (kind, root), paths in sorted(roots.items()):
        boundaries.append(
            BoundaryCandidate(
                kind=kind,
                name=root,
                evidence_paths=tuple(sorted(paths)),
                confidence="MEDIUM",
                detector_id="core.repository-topology",
                detector_version="1.0.0",
            )
        )
    return AdapterResult(items=tuple(items), boundaries=tuple(boundaries))


@repository_adapter(
    adapter_id="stack.python",
    version="1.0.0",
    file_patterns=("**/*.py", "pyproject.toml", "**/requirements*.txt", ".python-version"),
    supported_categories=("languages_build_ecosystems", "tests_quality", "debt_risk"),
)
def _python(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    for file in context.files:
        if file.path.endswith(".py"):
            test_kind = _test_signal_kind(file.path)
            if test_kind is None:
                items.append(
                    (
                        "languages_build_ecosystems",
                        _item(file, "PYTHON_SOURCE", "stack.python"),
                    )
                )
            else:
                items.append(
                    (
                        "tests_quality",
                        _item(
                            file,
                            test_kind,
                            "stack.python",
                            confidence="MEDIUM",
                        ),
                    )
                )
        elif PurePosixPath(file.path).name == "pyproject.toml" or file.path.endswith(
            "requirements.txt"
        ):
            items.append(
                ("languages_build_ecosystems", _item(file, "PYTHON_MANIFEST", "stack.python"))
            )
            if PurePosixPath(file.path).name == "pyproject.toml" and file.content is not None:
                try:
                    parsed = tomllib.loads(file.content.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError
                except (tomllib.TOMLDecodeError, UnicodeDecodeError, ValueError):
                    findings.append(
                        _finding(
                            "MANIFEST.MALFORMED",
                            "languages_build_ecosystems",
                            "A tracked Python manifest cannot be parsed deterministically.",
                            (file.path,),
                            "stack.python",
                            severity="HIGH",
                            blocking=True,
                        )
                    )
        elif file.path == ".python-version":
            items.append(
                ("languages_build_ecosystems", _item(file, "RUNTIME_VERSION", "stack.python"))
            )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="stack.node-web",
    version="1.0.0",
    file_patterns=(
        "**/*.js",
        "**/*.jsx",
        "**/*.ts",
        "**/*.tsx",
        "**/package.json",
        "**/package-lock.json",
        "**/yarn.lock",
        "**/pnpm-lock.yaml",
    ),
    supported_categories=("languages_build_ecosystems", "tests_quality", "debt_risk"),
)
def _node(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    lock_paths: dict[str, list[str]] = {}
    runtime_declarations: dict[str, str] = {}
    for file in context.files:
        name = PurePosixPath(file.path).name
        if name == "package.json":
            items.append(
                ("languages_build_ecosystems", _item(file, "NODE_MANIFEST", "stack.node-web"))
            )
            if file.content is not None:
                try:
                    package = json.loads(file.content)
                    engine = package.get("engines", {}).get("node")
                    if isinstance(engine, str):
                        runtime_declarations[file.path] = engine
                except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                    findings.append(
                        _finding(
                            "MANIFEST.MALFORMED",
                            "languages_build_ecosystems",
                            "A tracked Node manifest cannot be parsed deterministically.",
                            (file.path,),
                            "stack.node-web",
                            severity="HIGH",
                            blocking=True,
                        )
                    )
        elif name in {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"}:
            lock_paths.setdefault(name, []).append(file.path)
            items.append(("languages_build_ecosystems", _item(file, "LOCKFILE", "stack.node-web")))
        elif file.path.endswith((".js", ".jsx", ".ts", ".tsx")):
            test_kind = _test_signal_kind(file.path)
            if test_kind is None:
                items.append(
                    (
                        "languages_build_ecosystems",
                        _item(file, "NODE_SOURCE", "stack.node-web"),
                    )
                )
            else:
                items.append(
                    (
                        "tests_quality",
                        _item(
                            file,
                            test_kind,
                            "stack.node-web",
                            confidence="MEDIUM",
                        ),
                    )
                )
    if len(lock_paths) > 1:
        findings.append(
            _finding(
                "DEPENDENCY.MULTIPLE_LOCK_ECOSYSTEMS",
                "debt_risk",
                "Multiple Node lockfile ecosystems are tracked; this is a drift signal, "
                "not proof of a defect.",
                tuple(sorted(path for paths in lock_paths.values() for path in paths)),
                "stack.node-web",
                confidence="MEDIUM",
            )
        )
    if len(set(runtime_declarations.values())) > 1:
        findings.append(
            _finding(
                "RUNTIME.VERSION_DRIFT_SIGNAL",
                "debt_risk",
                "Multiple declared Node runtime constraints were observed.",
                tuple(sorted(runtime_declarations)),
                "stack.node-web",
                confidence="MEDIUM",
            )
        )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="stack.docker-compose",
    version="1.0.0",
    file_patterns=("**/Dockerfile", "**/Dockerfile.*", "**/compose.y*ml", "**/docker-compose.y*ml"),
    supported_categories=(
        "languages_build_ecosystems",
        "delivery_environments",
        "observability_operations",
    ),
)
def _containers(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    for file in context.files:
        name = PurePosixPath(file.path).name.lower()
        if "dockerfile" in name:
            items.append(
                (
                    "languages_build_ecosystems",
                    _item(file, "CONTAINER_BUILD", "stack.docker-compose"),
                )
            )
            items.append(
                (
                    "delivery_environments",
                    _item(file, "CONTAINER_DEFINITION", "stack.docker-compose"),
                )
            )
            if file.content and b"HEALTHCHECK" in file.content:
                items.append(
                    (
                        "observability_operations",
                        _item(file, "HEALTH_CHECK", "stack.docker-compose"),
                    )
                )
        elif "compose" in name:
            items.append(
                ("delivery_environments", _item(file, "LOCAL_COMPOSE", "stack.docker-compose"))
            )
            if file.content is not None:
                try:
                    parsed = yaml.safe_load(file.content)
                    if not isinstance(parsed, dict):
                        raise ValueError
                except (yaml.YAMLError, UnicodeDecodeError, ValueError):
                    findings.append(
                        _finding(
                            "MANIFEST.MALFORMED",
                            "delivery_environments",
                            "A tracked Compose manifest cannot be parsed deterministically.",
                            (file.path,),
                            "stack.docker-compose",
                            severity="HIGH",
                            blocking=True,
                        )
                    )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="delivery.github-actions",
    version="1.0.0",
    file_patterns=(".github/workflows/*.yml", ".github/workflows/*.yaml"),
    supported_categories=("delivery_environments", "tests_quality", "security_privacy"),
)
def _github_actions(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    workflows = [file for file in context.files if file.path.startswith(".github/workflows/")]
    for file in workflows:
        workflow_kind = (
            "RELEASE_WORKFLOW"
            if any(token in file.path.lower() for token in ("release", "deploy", "publish"))
            else "CI_WORKFLOW"
        )
        items.append(
            (
                "delivery_environments",
                _item(file, workflow_kind, "delivery.github-actions"),
            )
        )
        if file.content and re.search(rb"\b(pytest|vitest|playwright|test)\b", file.content, re.I):
            items.append(
                ("tests_quality", _item(file, "CI_TEST_MAPPING", "delivery.github-actions"))
            )
        if file.content is not None:
            try:
                parsed = yaml.safe_load(file.content)
                if not isinstance(parsed, dict):
                    raise ValueError
            except (yaml.YAMLError, UnicodeDecodeError, ValueError):
                findings.append(
                    _finding(
                        "WORKFLOW.MALFORMED",
                        "delivery_environments",
                        "A tracked workflow cannot be parsed deterministically.",
                        (file.path,),
                        "delivery.github-actions",
                        severity="HIGH",
                        blocking=True,
                    )
                )
        if file.content and re.search(rb"\b(audit|bandit|secret|security)\b", file.content, re.I):
            items.append(
                ("security_privacy", _item(file, "SECURITY_GATE", "delivery.github-actions"))
            )
        if file.content and re.search(rb"\b(rollback|revert)\b", file.content, re.I):
            items.append(
                (
                    "delivery_environments",
                    _item(file, "ROLLBACK_MECHANISM", "delivery.github-actions"),
                )
            )
    if not workflows:
        findings.append(
            _finding(
                "DELIVERY.CI_ABSENT",
                "delivery_environments",
                "No tracked GitHub Actions workflow was observed.",
                ("repository:tracked-tree",),
                "delivery.github-actions",
            )
        )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="interface.schema-api",
    version="1.0.0",
    file_patterns=(
        "**/*openapi*",
        "**/*asyncapi*",
        "**/*.proto",
        "**/*.graphql",
        "**/*.gql",
        "**/*.gen.*",
        "**/schemas/**",
        "**/migrations/**",
        "**/generate*",
        "scripts/**",
    ),
    supported_categories=("apis_data", "languages_build_ecosystems"),
)
def _interfaces(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    for file in context.files:
        lowered = file.path.lower()
        if "openapi" in lowered:
            kind = "OPENAPI"
        elif "asyncapi" in lowered:
            kind = "EVENT_CONTRACT"
        elif lowered.endswith((".proto", ".graphql", ".gql")):
            kind = "INTERFACE_DEFINITION"
        elif "/migrations/" in f"/{lowered}":
            kind = "MIGRATION"
        elif "generate" in PurePosixPath(lowered).name:
            kind = "CODE_GENERATOR"
        elif ".gen." in lowered or "generated_client" in lowered:
            kind = "GENERATED_CLIENT"
        elif "/schemas/" in f"/{lowered}" or lowered.endswith(".schema.json"):
            kind = "SCHEMA"
        else:
            continue
        items.append(("apis_data", _item(file, kind, "interface.schema-api")))
    return AdapterResult(items=tuple(items))


@repository_adapter(
    adapter_id="repository.pmpe",
    version="1.0.0",
    file_patterns=("src/pmpe/**", "state/**", "docs/**"),
    supported_categories=("architecture_boundaries", "documentation_governance", "debt_risk"),
)
def _pmpe(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    for file in context.files:
        if file.path.startswith("src/pmpe/"):
            items.append(("architecture_boundaries", _item(file, "PMPE_MODULE", "repository.pmpe")))
        elif file.path.startswith("state/"):
            items.append(
                ("documentation_governance", _item(file, "DURABLE_STATE", "repository.pmpe"))
            )
    return AdapterResult(items=tuple(items))


def default_adapters() -> tuple[RepositoryAdapter, ...]:
    return tuple(
        sorted(
            (
                _topology,
                _python,
                _node,
                _containers,
                _github_actions,
                _interfaces,
                _pmpe,
            ),
            key=lambda adapter: adapter.adapter_id,
        )
    )
