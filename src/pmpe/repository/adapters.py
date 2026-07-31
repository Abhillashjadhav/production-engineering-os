"""Versioned, deterministic stack adapters for repository evidence."""

from __future__ import annotations

import fnmatch
import json
import re
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


def _item(file: TrackedFile, kind: str, detector: str, version: str = "1.0.0") -> EvidenceItem:
    return EvidenceItem(
        kind=kind,
        path=file.path,
        file_digest=file.digest,
        detector_id=detector,
        detector_version=version,
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
    for file in context.files:
        if file.path.endswith(".py"):
            category = (
                "tests_quality"
                if "/test" in f"/{file.path}" or file.path.startswith("tests/")
                else "languages_build_ecosystems"
            )
            kind = "PYTHON_TEST" if category == "tests_quality" else "PYTHON_SOURCE"
            items.append((category, _item(file, kind, "stack.python")))
        elif file.path == "pyproject.toml" or file.path.endswith("requirements.txt"):
            items.append(
                ("languages_build_ecosystems", _item(file, "PYTHON_MANIFEST", "stack.python"))
            )
        elif file.path == ".python-version":
            items.append(
                ("languages_build_ecosystems", _item(file, "RUNTIME_VERSION", "stack.python"))
            )
    return AdapterResult(items=tuple(items))


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
    lock_types: set[str] = set()
    runtime_versions: set[str] = set()
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
                        runtime_versions.add(engine)
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
            lock_types.add(name)
            items.append(("languages_build_ecosystems", _item(file, "LOCKFILE", "stack.node-web")))
        elif file.path.endswith((".js", ".jsx", ".ts", ".tsx")):
            category = (
                "tests_quality"
                if "test" in name or "spec" in name
                else "languages_build_ecosystems"
            )
            kind = "NODE_TEST" if category == "tests_quality" else "NODE_SOURCE"
            items.append((category, _item(file, kind, "stack.node-web")))
    if len(lock_types) > 1:
        findings.append(
            _finding(
                "DEPENDENCY.MULTIPLE_LOCK_ECOSYSTEMS",
                "debt_risk",
                "Multiple Node lockfile ecosystems are tracked; this is a drift signal, "
                "not proof of a defect.",
                tuple(sorted(lock_types)),
                "stack.node-web",
                confidence="MEDIUM",
            )
        )
    if len(runtime_versions) > 1:
        findings.append(
            _finding(
                "RUNTIME.VERSION_DRIFT_SIGNAL",
                "debt_risk",
                "Multiple declared Node runtime constraints were observed.",
                tuple(sorted(runtime_versions)),
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
    return AdapterResult(items=tuple(items))


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
        items.append(("tests_quality", _item(file, "CI_TEST_MAPPING", "delivery.github-actions")))
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
        elif "/migrations/" in f"/{lowered}":
            kind = "MIGRATION"
        elif "generate" in PurePosixPath(lowered).name:
            kind = "CODE_GENERATOR"
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
