"""Versioned, deterministic stack adapters for repository evidence."""

from __future__ import annotations

import configparser
import fnmatch
import json
import posixpath
import re
import shlex
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from pmpe.repository.models import BoundaryCandidate, EvidenceItem, Finding

DETECTOR_VERSION = "1.13.0"

_PACKAGE_BOUNDARY_MANIFEST_NAMES = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "Pipfile",
        "setup.cfg",
        "setup.py",
    }
)


def _is_package_boundary_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in _PACKAGE_BOUNDARY_MANIFEST_NAMES or (
        name.startswith("requirements") and name.endswith(".txt")
    )


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
    repository_files: tuple[TrackedFile, ...] = ()

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
    detector_version: str = DETECTOR_VERSION
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
            detector_version=DETECTOR_VERSION,
        )

    return decorate


def _item(
    file: TrackedFile,
    kind: str,
    detector: str,
    version: str = DETECTOR_VERSION,
    *,
    confidence: str = "HIGH",
    location: str = "file",
) -> EvidenceItem:
    return EvidenceItem(
        kind=kind,
        path=file.path,
        file_digest=file.digest,
        detector_id=detector,
        detector_version=version,
        location=location,
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
        detector_version=DETECTOR_VERSION,
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


def _test_configuration_kind(path: str) -> str | None:
    """Classify explicit test and coverage configuration without executing it."""

    name = PurePosixPath(path).name.lower()
    if name in {"pytest.ini", "tox.ini", "noxfile.py", "conftest.py"} or any(
        fnmatch.fnmatch(name, pattern)
        for pattern in (
            "jest.config.*",
            "karma.conf.*",
            "playwright.config.*",
            "vitest.config.*",
        )
    ):
        return "TEST_CONFIGURATION"
    if name in {".coveragerc", ".nycrc", "coverage.ini", "coverage.toml"} or any(
        fnmatch.fnmatch(name, pattern) for pattern in (".codecov.*", "codecov.*", "nyc.config.*")
    ):
        return "COVERAGE_CONFIGURATION"
    return None


def _entry_point_signal_kind(path: str) -> str | None:
    """Return a bounded conventional entry-point signal, never a recommendation."""

    name = PurePosixPath(path).name.lower()
    if name in {"__main__.py", "app.py", "cli.py", "main.py", "manage.py", "server.py"}:
        return "ENTRY_POINT_FILE_SIGNAL"
    return None


def _manifest_relative_path(manifest_path: str, declared_path: str) -> str | None:
    """Resolve a simple manifest-relative path without allowing root escape."""

    if (
        not declared_path
        or "\0" in declared_path
        or "\\" in declared_path
        or PurePosixPath(declared_path).is_absolute()
    ):
        return None
    parent = str(PurePosixPath(manifest_path).parent)
    resolved = posixpath.normpath(posixpath.join(parent, declared_path))
    if resolved in {"", ".", ".."} or resolved.startswith("../"):
        return None
    return resolved


def _openapi_typescript_relationship(command: str) -> tuple[str, str] | None:
    """Parse the supported data-only openapi-typescript invocation shape."""

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None
    if tokens[:1] == ["npx"]:
        tokens = tokens[1:]
    if not tokens or tokens[0] != "openapi-typescript":
        return None
    if any(token in {"&&", "||", ";", "|", ">", ">>"} for token in tokens):
        return None
    output: str | None = None
    positional: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-o", "--output"}:
            if output is not None or index + 1 >= len(tokens):
                return None
            output = tokens[index + 1]
            index += 2
            continue
        if token.startswith("-"):
            return None
        positional.append(token)
        index += 1
    if len(positional) != 1 or output is None:
        return None
    return positional[0], output


def _api_declaration_kind(path: str) -> str | None:
    """Return a declaration kind only for supported API document filenames."""

    name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(name).suffix
    if suffix not in {".json", ".yaml", ".yml"}:
        return None
    stem = name[: -len(suffix)]
    if stem == "openapi" or stem.endswith(".openapi"):
        return "OPENAPI"
    if stem == "asyncapi" or stem.endswith(".asyncapi"):
        return "EVENT_CONTRACT"
    return None


@repository_adapter(
    adapter_id="core.repository-topology",
    version="1.5.0",
    file_patterns=("**/*", "*"),
    supported_categories=(
        "repository_topology",
        "architecture_boundaries",
        "delivery_environments",
        "documentation_governance",
        "debt_risk",
        "observability_operations",
        "security_privacy",
        "tests_quality",
    ),
)
def _topology(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    boundaries: list[BoundaryCandidate] = []
    findings: list[Finding] = []
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
        elif _is_package_boundary_manifest(file.path):
            kind = "PACKAGE_BOUNDARY_MANIFEST"
        else:
            kind = "TRACKED_FILE"
        items.append(("repository_topology", _item(file, kind, "core.repository-topology")))

        test_configuration_kind = _test_configuration_kind(file.path)
        if test_configuration_kind is not None:
            items.append(
                (
                    "tests_quality",
                    _item(file, test_configuration_kind, "core.repository-topology"),
                )
            )
        entry_point_kind = _entry_point_signal_kind(file.path)
        if entry_point_kind is not None:
            items.append(
                (
                    "architecture_boundaries",
                    _item(
                        file,
                        entry_point_kind,
                        "core.repository-topology",
                        confidence="MEDIUM",
                    ),
                )
            )

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
            if file.content is not None:
                try:
                    for line in file.content.decode("utf-8").splitlines():
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        codeowners_parts = stripped.split()
                        if len(codeowners_parts) < 2:
                            findings.append(
                                _finding(
                                    "OWNERSHIP.CODEOWNERS_MALFORMED",
                                    "architecture_boundaries",
                                    "A CODEOWNERS rule has no declared owner.",
                                    (file.path,),
                                    "core.repository-topology",
                                    severity="HIGH",
                                    blocking=True,
                                )
                            )
                            continue
                        boundaries.append(
                            BoundaryCandidate(
                                kind="OWNERSHIP_AREA",
                                name=codeowners_parts[0],
                                evidence_paths=(file.path,),
                                confidence="HIGH",
                                detector_id="core.repository-topology",
                                detector_version=DETECTOR_VERSION,
                            )
                        )
                except UnicodeDecodeError:
                    findings.append(
                        _finding(
                            "OWNERSHIP.CODEOWNERS_MALFORMED",
                            "architecture_boundaries",
                            "CODEOWNERS is not valid UTF-8.",
                            (file.path,),
                            "core.repository-topology",
                            severity="HIGH",
                            blocking=True,
                        )
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
        if any(
            token in lowered
            for token in (
                "/alerts",
                "/slo",
                "/metrics",
                "/traces",
                "prometheus",
                "grafana",
                "opentelemetry",
                "otel",
            )
        ):
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
        if any(
            token in lowered
            for token in ("privacy", "data-retention", "data_retention", "gdpr", "pii")
        ):
            items.append(
                (
                    "security_privacy",
                    _item(
                        file,
                        "PRIVACY_CONTROL_SIGNAL",
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
        if name == ".env" or name.startswith(".env."):
            items.append(
                (
                    "delivery_environments",
                    _item(file, "ENVIRONMENT_CONFIGURATION_SHAPE", "core.repository-topology"),
                )
            )
            items.append(
                (
                    "security_privacy",
                    _item(file, "SECRET_CONFIGURATION_BOUNDARY", "core.repository-topology"),
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
    boundary_roots = {root for _kind, root in roots}
    for file in context.files:
        if not _is_package_boundary_manifest(file.path):
            continue
        parent = PurePosixPath(file.path).parent
        root = "." if str(parent) == "." else str(parent)
        matching = next((key for key in roots if key[1] == root), None)
        if matching is not None:
            roots[matching].add(file.path)
        elif root not in boundary_roots:
            roots[("PACKAGE", root)] = {file.path}
            boundary_roots.add(root)
    for (kind, root), paths in sorted(roots.items()):
        evidence_paths = tuple(sorted(paths))
        confidence = (
            "HIGH"
            if evidence_paths
            and all(_is_package_boundary_manifest(path) for path in evidence_paths)
            else "MEDIUM"
        )
        boundaries.append(
            BoundaryCandidate(
                kind=kind,
                name=root,
                evidence_paths=evidence_paths,
                confidence=confidence,
                detector_id="core.repository-topology",
                detector_version=DETECTOR_VERSION,
            )
        )
    return AdapterResult(items=tuple(items), findings=tuple(findings), boundaries=tuple(boundaries))


@repository_adapter(
    adapter_id="stack.python",
    version="1.6.0",
    file_patterns=(
        "*.py",
        "**/*.py",
        "*.pyi",
        "**/*.pyi",
        "pyproject.toml",
        "**/pyproject.toml",
        "requirements*.txt",
        "**/requirements*.txt",
        "requirements*.lock",
        "**/requirements*.lock",
        "Pipfile",
        "**/Pipfile",
        "Pipfile.lock",
        "**/Pipfile.lock",
        "poetry.lock",
        "**/poetry.lock",
        "setup.cfg",
        "**/setup.cfg",
        "setup.py",
        "**/setup.py",
        "uv.lock",
        "**/uv.lock",
        ".python-version",
        "**/.python-version",
    ),
    supported_categories=(
        "languages_build_ecosystems",
        "architecture_boundaries",
        "tests_quality",
        "debt_risk",
    ),
)
def _python(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    for file in context.files:
        name = PurePosixPath(file.path).name
        is_requirement_manifest = name.startswith("requirements") and name.endswith(
            (".txt", ".lock")
        )
        if name in {"Pipfile.lock", "poetry.lock", "uv.lock"} or (
            is_requirement_manifest and name.endswith(".lock")
        ):
            items.append(
                ("languages_build_ecosystems", _item(file, "PYTHON_LOCKFILE", "stack.python"))
            )
        elif name in {"Pipfile", "pyproject.toml", "setup.cfg", "setup.py"} or (
            is_requirement_manifest and name.endswith(".txt")
        ):
            items.append(
                ("languages_build_ecosystems", _item(file, "PYTHON_MANIFEST", "stack.python"))
            )
            if name in {"Pipfile", "pyproject.toml"} and file.content is not None:
                try:
                    parsed = tomllib.loads(file.content.decode("utf-8"))
                    if not isinstance(parsed, dict):
                        raise ValueError
                    project = parsed.get("project", {})
                    if isinstance(project, dict) and any(
                        isinstance(project.get(key), dict) and project[key]
                        for key in ("scripts", "gui-scripts", "entry-points")
                    ):
                        items.append(
                            (
                                "architecture_boundaries",
                                _item(file, "DECLARED_ENTRY_POINT", "stack.python"),
                            )
                        )
                    dynamic = project.get("dynamic", []) if isinstance(project, dict) else []
                    if isinstance(dynamic, list) and any(
                        item in {"scripts", "gui-scripts", "entry-points"} for item in dynamic
                    ):
                        findings.append(
                            _finding(
                                "ARCHITECTURE.DYNAMIC_ENTRY_POINTS_UNSUPPORTED",
                                "architecture_boundaries",
                                "Dynamic Python entry-point declarations are not executed or "
                                "inferred by the read-only scanner.",
                                (file.path,),
                                "stack.python",
                                severity="HIGH",
                                blocking=True,
                            )
                        )
                    tool = parsed.get("tool", {})
                    if isinstance(tool, dict):
                        pytest_configuration = tool.get("pytest")
                        if isinstance(pytest_configuration, dict) and pytest_configuration:
                            items.append(
                                (
                                    "tests_quality",
                                    _item(file, "TEST_CONFIGURATION", "stack.python"),
                                )
                            )
                        coverage_configuration = tool.get("coverage")
                        if isinstance(coverage_configuration, dict) and coverage_configuration:
                            items.append(
                                (
                                    "tests_quality",
                                    _item(file, "COVERAGE_CONFIGURATION", "stack.python"),
                                )
                            )
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
            if name == "setup.cfg" and file.content is not None:
                try:
                    configuration = configparser.ConfigParser(interpolation=None)
                    configuration.read_string(file.content.decode("utf-8"))
                    sections = {section.lower() for section in configuration.sections()}
                    if "options.entry_points" in sections:
                        items.append(
                            (
                                "architecture_boundaries",
                                _item(file, "DECLARED_ENTRY_POINT", "stack.python"),
                            )
                        )
                    if sections & {"pytest", "tool:pytest"}:
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "TEST_CONFIGURATION", "stack.python"),
                            )
                        )
                    if any(section.startswith("coverage:") for section in sections):
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "COVERAGE_CONFIGURATION", "stack.python"),
                            )
                        )
                except (configparser.Error, UnicodeDecodeError):
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
            if name == "setup.py":
                findings.append(
                    _finding(
                        "ARCHITECTURE.DYNAMIC_ENTRY_POINTS_UNSUPPORTED",
                        "architecture_boundaries",
                        "Executable setup.py entry-point declarations are not executed or "
                        "inferred by the read-only scanner.",
                        (file.path,),
                        "stack.python",
                        severity="HIGH",
                        blocking=True,
                    )
                )
        elif file.path.endswith((".py", ".pyi")):
            items.append(
                (
                    "languages_build_ecosystems",
                    _item(file, "PYTHON_SOURCE", "stack.python"),
                )
            )
            test_kind = _test_signal_kind(file.path)
            if test_kind is not None:
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
        elif name == ".python-version":
            items.append(
                ("languages_build_ecosystems", _item(file, "RUNTIME_VERSION", "stack.python"))
            )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="stack.node-web",
    version="1.4.0",
    file_patterns=(
        "**/*.js",
        "*.js",
        "**/*.mjs",
        "*.mjs",
        "**/*.cjs",
        "*.cjs",
        "**/*.jsx",
        "*.jsx",
        "**/*.ts",
        "*.ts",
        "**/*.tsx",
        "*.tsx",
        "package.json",
        "**/package.json",
        "package-lock.json",
        "**/package-lock.json",
        "yarn.lock",
        "**/yarn.lock",
        "pnpm-lock.yaml",
        "**/pnpm-lock.yaml",
    ),
    supported_categories=(
        "languages_build_ecosystems",
        "architecture_boundaries",
        "tests_quality",
        "debt_risk",
    ),
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
                    if not isinstance(package, dict):
                        raise AttributeError
                    engine = package.get("engines", {}).get("node")
                    if isinstance(engine, str):
                        runtime_declarations[file.path] = engine
                    if any(
                        package.get(key) not in (None, "", {}, [])
                        for key in ("bin", "main", "module", "exports")
                    ):
                        items.append(
                            (
                                "architecture_boundaries",
                                _item(file, "DECLARED_ENTRY_POINT", "stack.node-web"),
                            )
                        )
                    scripts = package.get("scripts", {})
                    if isinstance(scripts, dict) and isinstance(scripts.get("start"), str):
                        items.append(
                            (
                                "architecture_boundaries",
                                _item(file, "DECLARED_RUN_ENTRY_POINT", "stack.node-web"),
                            )
                        )
                    if isinstance(scripts, dict) and any(
                        isinstance(command, str) and (name == "test" or name.startswith("test:"))
                        for name, command in scripts.items()
                    ):
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "DECLARED_TEST_COMMAND", "stack.node-web"),
                            )
                        )
                    if isinstance(scripts, dict) and any(
                        isinstance(command, str) and "coverage" in name.lower()
                        for name, command in scripts.items()
                    ):
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "DECLARED_COVERAGE_COMMAND", "stack.node-web"),
                            )
                        )
                    if any(
                        isinstance(package.get(key), dict) and package[key]
                        for key in ("ava", "jest", "mocha", "playwright", "vitest")
                    ):
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "TEST_CONFIGURATION", "stack.node-web"),
                            )
                        )
                    if isinstance(package.get("nyc"), dict) and package["nyc"]:
                        items.append(
                            (
                                "tests_quality",
                                _item(file, "COVERAGE_CONFIGURATION", "stack.node-web"),
                            )
                        )
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
        elif file.path.endswith((".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")):
            items.append(
                (
                    "languages_build_ecosystems",
                    _item(file, "NODE_SOURCE", "stack.node-web"),
                )
            )
            test_kind = _test_signal_kind(file.path)
            if test_kind is not None:
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
    adapter_id="integration.manifest-declarations",
    version="1.2.0",
    file_patterns=(
        "pyproject.toml",
        "**/pyproject.toml",
        "package.json",
        "**/package.json",
        "*openapi*.json",
        "**/*openapi*.json",
        "*openapi*.yaml",
        "*openapi*.yml",
        "**/*openapi*.yaml",
        "**/*openapi*.yml",
    ),
    supported_categories=("integrations",),
)
def _integration_declarations(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    for file in context.files:
        if file.content is None or file.binary:
            continue
        name = PurePosixPath(file.path).name
        try:
            if name == "pyproject.toml":
                payload = tomllib.loads(file.content.decode("utf-8"))
                dependencies = payload.get("project", {}).get("dependencies", [])
                if isinstance(dependencies, list):
                    for index, dependency in enumerate(dependencies):
                        if isinstance(dependency, str):
                            items.append(
                                (
                                    "integrations",
                                    _item(
                                        file,
                                        "EXTERNAL_DEPENDENCY_DECLARATION",
                                        "integration.manifest-declarations",
                                        confidence="LOW",
                                        location=f"project.dependencies[{index}]",
                                    ),
                                )
                            )
            elif name == "package.json":
                payload = json.loads(file.content)
                for group in ("dependencies", "optionalDependencies", "peerDependencies"):
                    dependencies = payload.get(group, {})
                    if isinstance(dependencies, dict):
                        for dependency in sorted(dependencies):
                            items.append(
                                (
                                    "integrations",
                                    _item(
                                        file,
                                        "EXTERNAL_DEPENDENCY_DECLARATION",
                                        "integration.manifest-declarations",
                                        confidence="LOW",
                                        location=f"{group}.{dependency}",
                                    ),
                                )
                            )
            elif "openapi" in name.lower():
                text = file.content.decode("utf-8")
                payload = json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
                servers = payload.get("servers", []) if isinstance(payload, dict) else []
                if isinstance(servers, list):
                    for index, server in enumerate(servers):
                        if isinstance(server, dict) and isinstance(server.get("url"), str):
                            items.append(
                                (
                                    "integrations",
                                    _item(
                                        file,
                                        "EXTERNAL_API_SERVER_DECLARATION",
                                        "integration.manifest-declarations",
                                        confidence="MEDIUM",
                                        location=f"servers[{index}]",
                                    ),
                                )
                            )
        except (json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeDecodeError, yaml.YAMLError):
            findings.append(
                _finding(
                    "INTEGRATION.DECLARATION_MALFORMED",
                    "integrations",
                    "A tracked integration declaration cannot be parsed; no integration "
                    "evidence was inferred from it.",
                    (file.path,),
                    "integration.manifest-declarations",
                    severity="HIGH",
                    blocking=True,
                )
            )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="stack.docker-compose",
    version="1.1.0",
    file_patterns=(
        "Dockerfile",
        "Dockerfile.*",
        "compose.y*ml",
        "docker-compose.y*ml",
        "**/Dockerfile",
        "**/Dockerfile.*",
        "**/compose.y*ml",
        "**/docker-compose.y*ml",
    ),
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
            health_instructions = (
                tuple(
                    line.lstrip().upper()
                    for line in file.content.splitlines()
                    if line.lstrip().upper().startswith(b"HEALTHCHECK ")
                )
                if file.content
                else ()
            )
            if any(line != b"HEALTHCHECK NONE" for line in health_instructions):
                items.append(
                    (
                        "observability_operations",
                        _item(file, "HEALTH_CHECK", "stack.docker-compose"),
                    )
                )
            elif health_instructions:
                items.append(
                    (
                        "observability_operations",
                        _item(
                            file,
                            "HEALTH_CHECK_DISABLED_SIGNAL",
                            "stack.docker-compose",
                            confidence="MEDIUM",
                        ),
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
    adapter_id="delivery.ci",
    version="1.2.0",
    file_patterns=(
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        ".gitlab-ci.yml",
        ".circleci/config.yml",
        "azure-pipelines.yml",
        "bitbucket-pipelines.yml",
        "Jenkinsfile",
    ),
    supported_categories=("delivery_environments", "tests_quality", "security_privacy"),
)
def _ci_workflows(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    workflows = list(context.files)
    verified_workflows = 0
    for file in workflows:
        parsed: object | None = None
        if file.content is not None and file.path.endswith((".yml", ".yaml")):
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
                        "delivery.ci",
                        severity="HIGH",
                        blocking=True,
                    )
                )
                continue
        if parsed is None or not _valid_ci_structure(file.path, parsed):
            items.append(
                (
                    "delivery_environments",
                    _item(
                        file,
                        "CI_CONFIGURATION_SIGNAL",
                        "delivery.ci",
                        confidence="MEDIUM",
                    ),
                )
            )
            findings.append(
                _finding(
                    "WORKFLOW.STRUCTURE_UNPROVEN",
                    "delivery_environments",
                    "A tracked CI configuration could not be proven to contain the required "
                    "provider structure; it remains a signal, not a verified workflow.",
                    (file.path,),
                    "delivery.ci",
                    confidence="MEDIUM",
                )
            )
            continue
        verified_workflows += 1
        items.append(
            (
                "delivery_environments",
                _item(file, "CI_WORKFLOW", "delivery.ci"),
            )
        )
        if any(token in file.path.lower() for token in ("release", "deploy", "publish")):
            items.append(
                (
                    "delivery_environments",
                    _item(
                        file,
                        "RELEASE_WORKFLOW_SIGNAL",
                        "delivery.ci",
                        confidence="MEDIUM",
                    ),
                )
            )
        try:
            signals = _structured_text(parsed)
        except ValueError:
            findings.append(
                _finding(
                    "WORKFLOW.STRUCTURE_BUDGET_EXCEEDED",
                    "delivery_environments",
                    "Parsed workflow structure exceeded the deterministic adapter budget.",
                    (file.path,),
                    "delivery.ci",
                    severity="HIGH",
                    blocking=True,
                )
            )
            continue
        if re.search(r"\b(pytest|vitest|playwright|test)\b", signals, re.I):
            items.append(
                (
                    "tests_quality",
                    _item(
                        file,
                        "CI_TEST_MAPPING_SIGNAL",
                        "delivery.ci",
                        confidence="MEDIUM",
                        location="parsed-workflow",
                    ),
                )
            )
        if re.search(r"\b(audit|bandit|secret|security)\b", signals, re.I):
            items.append(
                (
                    "security_privacy",
                    _item(
                        file,
                        "SECURITY_CONTROL_SIGNAL",
                        "delivery.ci",
                        confidence="MEDIUM",
                        location="parsed-workflow",
                    ),
                )
            )
        if re.search(r"\b(rollback|revert)\b", signals, re.I):
            items.append(
                (
                    "delivery_environments",
                    _item(
                        file,
                        "ROLLBACK_SIGNAL",
                        "delivery.ci",
                        confidence="MEDIUM",
                        location="parsed-workflow",
                    ),
                )
            )
    if not verified_workflows:
        findings.append(
            _finding(
                "DELIVERY.CI_ABSENT",
                "delivery_environments",
                "No tracked supported CI workflow was observed.",
                ("repository:tracked-tree",),
                "delivery.ci",
            )
        )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


def _structured_text(value: object) -> str:
    """Return only parsed keys/scalars; comments and unparsed source never become controls."""

    pending = [value]
    strings: list[str] = []
    seen: set[int] = set()
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > 50_000:
            raise ValueError("workflow structure budget exceeded")
        if isinstance(current, dict):
            if id(current) in seen:
                continue
            seen.add(id(current))
            for key, item in current.items():
                strings.append(str(key))
                pending.append(item)
        elif isinstance(current, list):
            if id(current) in seen:
                continue
            seen.add(id(current))
            pending.extend(current)
        elif isinstance(current, (str, int, float, bool)):
            strings.append(str(current))
    return "\n".join(strings)


def _valid_ci_structure(path: str, value: object) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    lowered = path.lower()
    if lowered.startswith(".github/workflows/"):
        event_declared = "on" in value or True in value
        return event_declared and isinstance(value.get("jobs"), dict) and bool(value["jobs"])
    if lowered == ".gitlab-ci.yml":
        return any(isinstance(item, dict) for item in value.values())
    if lowered == ".circleci/config.yml":
        return "version" in value and any(key in value for key in ("jobs", "workflows"))
    if lowered == "azure-pipelines.yml":
        return any(key in value for key in ("jobs", "stages", "steps"))
    if lowered == "bitbucket-pipelines.yml":
        return isinstance(value.get("pipelines"), dict) and bool(value["pipelines"])
    return False


@repository_adapter(
    adapter_id="interface.schema-api",
    version="1.4.0",
    file_patterns=(
        "package.json",
        "**/package.json",
        "*openapi*",
        "**/*openapi*",
        "*asyncapi*",
        "**/*asyncapi*",
        "*.proto",
        "**/*.proto",
        "*.graphql",
        "**/*.graphql",
        "*.gql",
        "**/*.gql",
        "*.sql",
        "**/*.sql",
        "*.gen.*",
        "**/*.gen.*",
        "schemas/**",
        "**/schemas/**",
        "migrations/**",
        "**/migrations/**",
        "generate*",
        "**/generate*",
        "scripts/**",
        "**/scripts/**",
    ),
    supported_categories=("apis_data", "languages_build_ecosystems"),
)
def _interfaces(context: AdapterContext) -> AdapterResult:
    items: list[tuple[str, EvidenceItem]] = []
    findings: list[Finding] = []
    files_by_path = {file.path: file for file in (context.repository_files or context.files)}
    for file in context.files:
        lowered = file.path.lower()
        confidence = "HIGH"
        location = "file"
        if PurePosixPath(lowered).name == "package.json":
            if file.content is None or file.binary:
                continue
            try:
                manifest = json.loads(file.content)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            scripts = manifest.get("scripts") if isinstance(manifest, dict) else None
            if not isinstance(scripts, dict):
                continue
            for script_name, command in sorted(scripts.items()):
                if not isinstance(script_name, str) or not isinstance(command, str):
                    continue
                codegen_relevant = "openapi-typescript" in command or (
                    "api" in script_name.lower() and "generat" in script_name.lower()
                )
                if not codegen_relevant:
                    continue
                relationship = _openapi_typescript_relationship(command)
                if relationship is None:
                    findings.append(
                        _finding(
                            "INTERFACE.CODEGEN_RELATIONSHIP_UNSUPPORTED",
                            "apis_data",
                            "A tracked API-client generation declaration cannot be represented "
                            "by the supported deterministic command grammar.",
                            (file.path,),
                            "interface.schema-api",
                            severity="HIGH",
                            blocking=True,
                        )
                    )
                    continue
                raw_input, raw_output = relationship
                input_path = _manifest_relative_path(file.path, raw_input)
                output_path = _manifest_relative_path(file.path, raw_output)
                if (
                    input_path is None
                    or output_path is None
                    or input_path not in files_by_path
                    or output_path not in files_by_path
                ):
                    findings.append(
                        _finding(
                            "INTERFACE.CODEGEN_RELATIONSHIP_INCOMPLETE",
                            "apis_data",
                            "A tracked API-client generation declaration does not bind one "
                            "existing tracked input to one existing tracked output.",
                            (file.path,),
                            "interface.schema-api",
                            severity="HIGH",
                            blocking=True,
                        )
                    )
                    continue
                relationship_location = f"{file.path}#scripts.{script_name}"
                for related, kind in (
                    (file, "CODE_GENERATION_DECLARATION"),
                    (files_by_path[input_path], "CODE_GENERATION_INPUT"),
                    (files_by_path[output_path], "CODE_GENERATION_OUTPUT"),
                ):
                    items.append(
                        (
                            "apis_data",
                            _item(
                                related,
                                kind,
                                "interface.schema-api",
                                location=relationship_location,
                            ),
                        )
                    )
            continue
        if lowered == "scripts/export_openapi.py" or lowered.endswith("/scripts/export_openapi.py"):
            target_path = str(PurePosixPath(file.path).parent.parent / "openapi.json")
            target = files_by_path.get(target_path)
            content = (
                file.content.decode("utf-8", errors="strict")
                if file.content is not None and not file.binary
                else ""
            )
            if target is None or "openapi.json" not in content or "write_text" not in content:
                findings.append(
                    _finding(
                        "INTERFACE.CODEGEN_RELATIONSHIP_INCOMPLETE",
                        "apis_data",
                        "The tracked OpenAPI export entry point does not bind to its expected "
                        "tracked OpenAPI output using a supported deterministic signal.",
                        tuple(sorted({file.path, target_path})),
                        "interface.schema-api",
                        severity="HIGH",
                        blocking=True,
                    )
                )
                continue
            location = f"{file.path}#export"
            items.extend(
                (
                    (
                        "apis_data",
                        _item(
                            file,
                            "CODE_GENERATOR_SIGNAL",
                            "interface.schema-api",
                            confidence="MEDIUM",
                            location=location,
                        ),
                    ),
                    (
                        "apis_data",
                        _item(
                            target,
                            "CODE_GENERATION_OUTPUT",
                            "interface.schema-api",
                            location=location,
                        ),
                    ),
                )
            )
            continue
        declaration_kind = _api_declaration_kind(lowered)
        if declaration_kind is not None:
            kind = declaration_kind
        elif lowered.endswith((".proto", ".graphql", ".gql")):
            kind = "INTERFACE_DEFINITION_SIGNAL"
            confidence = "MEDIUM"
        elif "/migrations/" in f"/{lowered}":
            kind = "MIGRATION_SIGNAL"
            confidence = "MEDIUM"
        elif lowered.endswith(".sql"):
            kind = "DATABASE_SCHEMA_SIGNAL"
            confidence = "MEDIUM"
        elif "generate" in PurePosixPath(lowered).name:
            kind = "CODE_GENERATOR_SIGNAL"
            confidence = "MEDIUM"
        elif ".gen." in lowered or "generated_client" in lowered:
            kind = "GENERATED_CLIENT_SIGNAL"
            confidence = "MEDIUM"
        elif "/schemas/" in f"/{lowered}" or lowered.endswith(".schema.json"):
            kind = "SCHEMA_SIGNAL"
            confidence = "MEDIUM"
        else:
            continue
        if kind in {"OPENAPI", "EVENT_CONTRACT"}:
            if file.content is None or file.binary:
                continue
            try:
                text = file.content.decode("utf-8")
                payload = json.loads(text) if lowered.endswith(".json") else yaml.safe_load(text)
                version_key = "openapi" if kind == "OPENAPI" else "asyncapi"
                info = payload.get("info") if isinstance(payload, dict) else None
                if (
                    not isinstance(payload, dict)
                    or not isinstance(payload.get(version_key), str)
                    or not isinstance(info, dict)
                    or not isinstance(info.get("title"), str)
                    or not info["title"].strip()
                    or not isinstance(info.get("version"), str)
                    or not info["version"].strip()
                ):
                    raise ValueError
                declared_version = str(payload[version_key])
                supported_version = (
                    re.fullmatch(r"3\.(?:0|1)\.\d+(?:[-+][0-9A-Za-z.-]+)?", declared_version)
                    if kind == "OPENAPI"
                    else re.fullmatch(
                        r"(?:2\.\d+\.\d+|3\.0\.\d+)(?:[-+][0-9A-Za-z.-]+)?",
                        declared_version,
                    )
                )
                if supported_version is None:
                    raise ValueError
                if kind == "OPENAPI":
                    paths = payload.get("paths")
                    if not isinstance(paths, dict) or any(
                        not isinstance(path, str)
                        or not path.startswith("/")
                        or not isinstance(operation, dict)
                        for path, operation in paths.items()
                    ):
                        raise ValueError
                elif not isinstance(payload.get("channels"), dict):
                    raise ValueError
            except (json.JSONDecodeError, UnicodeDecodeError, yaml.YAMLError, ValueError):
                findings.append(
                    _finding(
                        "INTERFACE.DECLARATION_INVALID",
                        "apis_data",
                        "A tracked API declaration is malformed or lacks required structural "
                        "identity; no API evidence was inferred from it.",
                        (file.path,),
                        "interface.schema-api",
                        severity="HIGH",
                        blocking=True,
                    )
                )
                continue
        elif lowered.endswith(".schema.json"):
            if file.content is None or file.binary:
                continue
            try:
                schema = json.loads(file.content)
                if not isinstance(schema, dict) or not isinstance(schema.get("$schema"), str):
                    raise ValueError
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                findings.append(
                    _finding(
                        "INTERFACE.DECLARATION_INVALID",
                        "apis_data",
                        "A tracked JSON Schema declaration is malformed or lacks a dialect.",
                        (file.path,),
                        "interface.schema-api",
                        severity="HIGH",
                        blocking=True,
                    )
                )
                continue
            kind = "JSON_SCHEMA"
            confidence = "HIGH"
        items.append(
            (
                "apis_data",
                _item(
                    file,
                    kind,
                    "interface.schema-api",
                    confidence=confidence,
                    location=location,
                ),
            )
        )
    return AdapterResult(items=tuple(items), findings=tuple(findings))


@repository_adapter(
    adapter_id="repository.pmpe",
    version="1.1.0",
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
                _integration_declarations,
                _containers,
                _ci_workflows,
                _interfaces,
                _pmpe,
            ),
            key=lambda adapter: adapter.adapter_id,
        )
    )
