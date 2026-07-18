"""Broad, read-only repository scanner (M2).

Derives *mechanical, observable* signals from repository snapshots — never
model output, never the network, never a judgment. Secret values are never
emitted; a detected secret is recorded only as ``(rule, path, line)`` with a
redaction marker (PD-PA-06). Signals feed risk selection (M3), deep
inspection (M4), and the AI-slop classifier (M5); the scanner itself decides
nothing.

Determinism: every list is deterministically ordered, the clock is the
``now`` parameter (an unparseable or absent ``now`` degrades the age to
"unknown", never to a wall-clock read), and repeated scans of the same
snapshots are byte-identical.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from pmpe.contracts.digest import canonical_digest
from pmpe.portfolio.datasource import RepositorySource
from pmpe.portfolio.models import RepoVisibility

SCANNER_VERSION = "pa-scanner-1"


def snapshot_digest(meta: dict[str, Any], tree: list[str], files: dict[str, str]) -> str:
    """Canonical content digest of one repository snapshot.

    Shared by the scanner and the deep inspector so a scan and an
    inspection provably describe the same snapshot (M4 review, TOCTOU).
    """
    return canonical_digest({"metadata": meta, "tree": sorted(tree), "files": files})


REDACTED = "***REDACTED***"

# --- signal dataclasses ----------------------------------------------------


@dataclass
class SecretHit:
    rule: str
    path: str
    line: int
    redacted: str = REDACTED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SecretHit:
        return cls(
            rule=str(d["rule"]),
            path=str(d["path"]),
            line=int(d["line"]),
            redacted=str(d.get("redacted", REDACTED)),
        )


@dataclass
class MechanicalClaim:
    text: str
    category: str
    location: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MechanicalClaim:
        return cls(text=str(d["text"]), category=str(d["category"]), location=str(d["location"]))


@dataclass
class ReadmeSignals:
    has_readme: bool
    length_chars: int
    heading_count: int
    has_install_section: bool
    has_usage_section: bool
    has_badges: bool
    code_fence_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReadmeSignals:
        return cls(
            has_readme=bool(d["has_readme"]),
            length_chars=int(d["length_chars"]),
            heading_count=int(d["heading_count"]),
            has_install_section=bool(d["has_install_section"]),
            has_usage_section=bool(d["has_usage_section"]),
            has_badges=bool(d["has_badges"]),
            code_fence_count=int(d["code_fence_count"]),
        )


@dataclass
class DocsSignals:
    has_docs_dir: bool
    doc_file_count: int
    has_contributing: bool
    has_code_of_conduct: bool
    has_changelog: bool
    has_license_file: bool
    license_name: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DocsSignals:
        return cls(
            has_docs_dir=bool(d["has_docs_dir"]),
            doc_file_count=int(d["doc_file_count"]),
            has_contributing=bool(d["has_contributing"]),
            has_code_of_conduct=bool(d["has_code_of_conduct"]),
            has_changelog=bool(d["has_changelog"]),
            has_license_file=bool(d["has_license_file"]),
            license_name=(None if d.get("license_name") is None else str(d["license_name"])),
        )


@dataclass
class TestCiSignals:
    has_tests: bool
    test_file_count: int
    has_ci: bool
    ci_workflow_count: int
    ci_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TestCiSignals:
        return cls(
            has_tests=bool(d["has_tests"]),
            test_file_count=int(d["test_file_count"]),
            has_ci=bool(d["has_ci"]),
            ci_workflow_count=int(d["ci_workflow_count"]),
            ci_files=[str(f) for f in d.get("ci_files", [])],
        )


@dataclass
class SecuritySignals:
    has_security_md: bool
    has_lockfile: bool
    lockfile_kinds: list[str]
    dependency_manifests: list[str]
    declared_dependency_count: int
    pinned_dependencies: bool | None
    secret_hits: list[SecretHit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_security_md": self.has_security_md,
            "has_lockfile": self.has_lockfile,
            "lockfile_kinds": list(self.lockfile_kinds),
            "dependency_manifests": list(self.dependency_manifests),
            "declared_dependency_count": self.declared_dependency_count,
            "pinned_dependencies": self.pinned_dependencies,
            "secret_hits": [h.to_dict() for h in self.secret_hits],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SecuritySignals:
        return cls(
            has_security_md=bool(d["has_security_md"]),
            has_lockfile=bool(d["has_lockfile"]),
            lockfile_kinds=[str(k) for k in d.get("lockfile_kinds", [])],
            dependency_manifests=[str(m) for m in d.get("dependency_manifests", [])],
            declared_dependency_count=int(d["declared_dependency_count"]),
            pinned_dependencies=(
                None if d.get("pinned_dependencies") is None else bool(d["pinned_dependencies"])
            ),
            secret_hits=[SecretHit.from_dict(h) for h in d.get("secret_hits", [])],
        )


@dataclass
class PackagingSignals:
    has_dockerfile: bool
    has_pyproject_or_setup: bool
    has_package_json: bool
    has_makefile: bool
    install_commands: list[str] = field(default_factory=list)
    entrypoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PackagingSignals:
        return cls(
            has_dockerfile=bool(d["has_dockerfile"]),
            has_pyproject_or_setup=bool(d["has_pyproject_or_setup"]),
            has_package_json=bool(d["has_package_json"]),
            has_makefile=bool(d["has_makefile"]),
            install_commands=[str(c) for c in d.get("install_commands", [])],
            entrypoints=[str(e) for e in d.get("entrypoints", [])],
        )


@dataclass
class FreshnessSignals:
    created_at: str
    pushed_at: str
    days_since_pushed: int | None
    archived: bool
    is_fork: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FreshnessSignals:
        return cls(
            created_at=str(d["created_at"]),
            pushed_at=str(d["pushed_at"]),
            days_since_pushed=(
                None if d.get("days_since_pushed") is None else int(d["days_since_pushed"])
            ),
            archived=bool(d["archived"]),
            is_fork=bool(d["is_fork"]),
        )


@dataclass
class RepoScan:
    owner: str
    name: str
    visibility: RepoVisibility
    description: str
    topics: list[str]
    default_branch: str
    stars: int
    forks: int
    languages: list[str]
    stack: list[str]
    readme: ReadmeSignals
    docs: DocsSignals
    tests_ci: TestCiSignals
    security: SecuritySignals
    packaging: PackagingSignals
    freshness: FreshnessSignals
    mechanical_claims: list[MechanicalClaim]
    snapshot_digest: str = ""
    scanner_version: str = SCANNER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "name": self.name,
            "visibility": self.visibility.value,
            "description": self.description,
            "topics": list(self.topics),
            "default_branch": self.default_branch,
            "stars": self.stars,
            "forks": self.forks,
            "languages": list(self.languages),
            "stack": list(self.stack),
            "readme": self.readme.to_dict(),
            "docs": self.docs.to_dict(),
            "tests_ci": self.tests_ci.to_dict(),
            "security": self.security.to_dict(),
            "packaging": self.packaging.to_dict(),
            "freshness": self.freshness.to_dict(),
            "mechanical_claims": [c.to_dict() for c in self.mechanical_claims],
            "snapshot_digest": self.snapshot_digest,
            "scanner_version": self.scanner_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepoScan:
        return cls(
            owner=str(d["owner"]),
            name=str(d["name"]),
            visibility=RepoVisibility(d["visibility"]),
            description=str(d["description"]),
            topics=[str(t) for t in d.get("topics", [])],
            default_branch=str(d["default_branch"]),
            stars=int(d["stars"]),
            forks=int(d["forks"]),
            languages=[str(x) for x in d.get("languages", [])],
            stack=[str(x) for x in d.get("stack", [])],
            readme=ReadmeSignals.from_dict(d["readme"]),
            docs=DocsSignals.from_dict(d["docs"]),
            tests_ci=TestCiSignals.from_dict(d["tests_ci"]),
            security=SecuritySignals.from_dict(d["security"]),
            packaging=PackagingSignals.from_dict(d["packaging"]),
            freshness=FreshnessSignals.from_dict(d["freshness"]),
            mechanical_claims=[
                MechanicalClaim.from_dict(c) for c in d.get("mechanical_claims", [])
            ],
            snapshot_digest=str(d.get("snapshot_digest", "")),
            scanner_version=str(d.get("scanner_version", SCANNER_VERSION)),
        )


# --- detection tables ------------------------------------------------------

_EXT_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".json": "JSON",
    ".html": "HTML",
    ".css": "CSS",
}

_LOCKFILES = {
    "poetry.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
}

_DEP_MANIFESTS = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "package.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "Gemfile",
    "composer.json",
}

_SECRET_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("stripe_secret_key", re.compile(r"sk_live_[A-Za-z0-9]{16,}")),
    (
        "generic_secret_assignment",
        re.compile(
            r"""(?i)(?:api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['"][A-Za-z0-9_\-]{12,}['"]"""
        ),
    ),
    (
        # Catches secrets under arbitrary *key names (awsKey, accessKey,
        # STRIPE_KEY); the 16+ char quoted value keeps false positives on
        # short key-named vars low.
        "key_named_assignment",
        re.compile(r"""(?i)\w*key\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]"""),
    ),
]

_CLAIM_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "production_readiness",
        re.compile(r"(?i)production[- ]ready|battle[- ]tested|enterprise[- ]grade"),
    ),
    (
        "scale",
        re.compile(r"(?i)infinitely scalable|scales? to|scalable|zero downtime|billions?"),
    ),
    ("metric", re.compile(r"\d+(?:\.\d+)?\s*%|\b\d+x\b|\b\d+\s?ms\b|\b99\.9+\b")),
    (
        "adoption",
        re.compile(r"(?i)used by|trusted by|millions of (?:developers|users)|fortune\s?500"),
    ),
    (
        "superlative",
        re.compile(
            r"(?i)state[- ]of[- ]the[- ]art|\bsota\b|best[- ]in[- ]class|"
            r"industry[- ]leading|blazing fast"
        ),
    ),
]


#: Credential-in-URL (https://user:token@host) — a common install-command
#: pattern the assignment-shaped rules cannot see.
_URL_CREDENTIAL_RE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _find_readme(files: dict[str, str]) -> str | None:
    """Deterministic README selection: shallowest path, then lexicographic.

    Multiple READMEs (``README.md`` + ``docs/README.md``) must never make
    the chosen one depend on ``files()`` iteration order (AC-PA-002).
    """
    candidates = [path for path in files if _basename(path).lower().startswith("readme")]
    if not candidates:
        return None
    best = min(candidates, key=lambda p: (p.count("/"), p.lower()))
    return files[best]


def redact_text(text: str) -> str:
    """Replace every secret-shaped span in ``text`` with the redaction marker.

    Output fields that copy repository text verbatim (claim text, install
    commands, descriptions) MUST pass through here — redaction is holistic,
    not a property of the secret_hits subsystem alone (PD-PA-06).
    """
    for _, pattern in _SECRET_RULES:
        text = pattern.sub(REDACTED, text)
    return _URL_CREDENTIAL_RE.sub(f"://{REDACTED}@", text)


def detect_secrets(files: dict[str, str]) -> list[SecretHit]:
    """Mechanical secret detection. Records rule/path/line only — never the value."""
    hits: list[SecretHit] = []
    for path in sorted(files):
        content = files[path]
        for rule, pattern in _SECRET_RULES:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                hits.append(SecretHit(rule=rule, path=path, line=line))
    return hits


def extract_mechanical_claims(
    readme_text: str, location_file: str = "README.md"
) -> list[MechanicalClaim]:
    """Pull candidate claim sentences from a README for later accuracy grading.

    Redaction happens BEFORE truncation: truncating first could clip a
    secret so the pattern no longer matches while most of the value
    survives in the kept prefix.
    """
    claims: list[MechanicalClaim] = []
    for lineno, raw in enumerate(readme_text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        for category, pattern in _CLAIM_RULES:
            if pattern.search(line):
                claims.append(
                    MechanicalClaim(
                        text=redact_text(line)[:200],
                        category=category,
                        location=f"{location_file}:{lineno}",
                    )
                )
    return claims


_VERSION_OP_RE = re.compile(r"(==|>=|<=|~=|!=|===|>|<|~|\^|=)")


def _version_part(spec: str) -> str:
    """Strip a leading distribution name (and markers), leaving the version.

    A distribution name may contain ``x``/``X`` (``lxml``, ``sphinx``,
    ``openpyxl``); evaluating the whole ``name==version`` string for wildcard
    characters would mis-flag exactly-pinned packages, so the version
    specifier is isolated first.
    """
    spec = spec.strip().split(";", 1)[0].strip()
    m = _VERSION_OP_RE.search(spec)
    return spec[m.start() :].strip() if m else spec


def _is_exact_spec(spec: str) -> bool:
    version = _version_part(spec)
    if not version or version in {"*", "latest", "x", "X"}:
        return False
    if any(op in version for op in ("^", "~", ">", "<", "*", "!", "||", " - ")):
        return False
    if re.search(r"(?:^|\.)[xX](?:\.|$)", version):  # wildcard version like 4.x
        return False
    if version.startswith("=="):
        return True
    return bool(re.fullmatch(r"v?\d+(?:\.\d+)*", version))


def _python_req_specs(content: str) -> list[str]:
    specs: list[str] = []
    for raw in content.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            specs.append(line)
    return specs


def _pyproject_dep_specs(content: str) -> list[str]:
    block = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if not block:
        return []
    return re.findall(r"['\"]([^'\"]+)['\"]", block.group(1))


def _package_json_deps(content: str) -> dict[str, str]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    deps: dict[str, str] = {}
    for key in ("dependencies", "devDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            for name, spec in section.items():
                deps[str(name)] = str(spec)
    return deps


def _dependency_signals(files: dict[str, str]) -> tuple[int, bool | None]:
    """Return (declared_dependency_count, pinned_dependencies|None)."""
    count = 0
    exact_flags: list[bool] = []
    if "requirements.txt" in files:
        specs = _python_req_specs(files["requirements.txt"])
        count += len(specs)
        exact_flags += [_is_exact_spec(s) for s in specs]
    if "pyproject.toml" in files:
        specs = _pyproject_dep_specs(files["pyproject.toml"])
        count += len(specs)
        exact_flags += [_is_exact_spec(s) for s in specs]
    if "package.json" in files:
        deps = _package_json_deps(files["package.json"])
        count += len(deps)
        exact_flags += [_is_exact_spec(v) for v in deps.values()]
    pinned: bool | None = all(exact_flags) if exact_flags else None
    return count, pinned


_INSTALL_CMD = re.compile(
    r"(?i)^\s*(?:\$\s*)?((?:sudo\s+)?(?:python3?\s+-m\s+pip|pip3?|pipx|npm|yarn|pnpm|poetry|"
    r"pipenv|docker|make|cargo|go|apt-get|brew)\b.*)$"
)


def _install_commands(readme_text: str) -> list[str]:
    cmds: list[str] = []
    in_fence = False
    for raw in readme_text.splitlines():
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        m = _INSTALL_CMD.match(raw)
        if m:
            # Install commands routinely embed registry credentials
            # (--extra-index-url https://user:token@host) — redact before copy.
            cmds.append(redact_text(m.group(1).strip()))
    return cmds


def _entrypoints(files: dict[str, str]) -> list[str]:
    entry: list[str] = []
    if "pyproject.toml" in files:
        block = re.search(
            r"\[project\.scripts\](.*?)(?:\n\[|\Z)", files["pyproject.toml"], re.DOTALL
        )
        if block:
            entry += re.findall(r"^\s*([\w.-]+)\s*=", block.group(1), re.MULTILINE)
    if "package.json" in files:
        try:
            data = json.loads(files["package.json"])
        except (json.JSONDecodeError, ValueError):
            data = {}
        binsection = data.get("bin") if isinstance(data, dict) else None
        if isinstance(binsection, dict):
            entry += [str(k) for k in binsection]
        elif isinstance(binsection, str):
            entry.append(str(data.get("name", "")))
    return [e for e in entry if e]


def _languages(tree: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for path in tree:
        base = _basename(path)
        idx = base.rfind(".")
        if idx <= 0:
            continue
        lang = _EXT_LANG.get(base[idx:].lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [lang for lang, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def _stack(tree_set: set[str], languages: list[str]) -> list[str]:
    tokens: set[str] = set()
    if (
        "Python" in languages
        or {"pyproject.toml", "setup.py", "requirements.txt", "Pipfile"} & tree_set
    ):
        tokens.add("python")
    if "JavaScript" in languages or "TypeScript" in languages or "package.json" in tree_set:
        tokens.add("node")
    if "Go" in languages or "go.mod" in tree_set:
        tokens.add("go")
    if "Rust" in languages or "Cargo.toml" in tree_set:
        tokens.add("rust")
    if "Java" in languages or {"pom.xml", "build.gradle"} & tree_set:
        tokens.add("java")
    if "Ruby" in languages or "Gemfile" in tree_set:
        tokens.add("ruby")
    if any(_basename(p) == "Dockerfile" for p in tree_set):
        tokens.add("containerized")
    return sorted(tokens)


def _is_test_path(path: str) -> bool:
    lower = path.lower()
    if lower.startswith(("tests/", "test/")) or "/tests/" in lower or "/test/" in lower:
        return True
    base = _basename(lower)
    return bool(
        re.match(r"test_.*\.py$", base)
        or re.match(r".*_test\.(py|go)$", base)
        or re.match(r".*\.(test|spec)\.(js|ts|jsx|tsx)$", base)
        or re.match(r".*test\.java$", base)
    )


def _ci_files(tree: list[str]) -> list[str]:
    ci: list[str] = []
    for path in tree:
        lower = path.lower()
        if (
            (lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml")))
            or lower
            in {".gitlab-ci.yml", ".circleci/config.yml", "azure-pipelines.yml", "jenkinsfile"}
            or _basename(path) == "Jenkinsfile"
        ):
            ci.append(path)
    return sorted(ci)


def _days_since(now: str | None, pushed_at: str) -> int | None:
    if not now:
        return None
    try:
        now_dt = datetime.fromisoformat(now)
        pushed_dt = datetime.fromisoformat(pushed_at)
        return (now_dt - pushed_dt).days
    except (ValueError, TypeError):
        # Unparseable timestamp or naive/aware mismatch degrades to "unknown"
        # rather than aborting the whole scan or reading a wall clock.
        return None


# --- top-level scan --------------------------------------------------------


def scan_repository(
    source: RepositorySource, owner: str, name: str, now: str | None = None
) -> RepoScan:
    """Produce mechanical signals for one repository (read-only)."""
    meta = source.metadata(owner, name)
    tree = source.tree(owner, name)
    files = source.files(owner, name)
    tree_set = set(tree)

    languages = _languages(tree)
    readme_text = _find_readme(files)

    return RepoScan(
        owner=owner,
        name=name,
        visibility=RepoVisibility(str(meta.get("visibility", "PUBLIC"))),
        description=redact_text(str(meta.get("description") or "")),
        topics=[str(t) for t in meta.get("topics", [])],
        default_branch=str(meta.get("default_branch", "main")),
        stars=int(meta.get("stargazers_count", 0)),
        forks=int(meta.get("forks_count", 0)),
        languages=languages,
        stack=_stack(tree_set, languages),
        readme=_readme_signals(readme_text),
        docs=_docs_signals(tree, meta),
        tests_ci=_tests_ci_signals(tree),
        security=_security_signals(tree_set, files),
        packaging=_packaging_signals(tree_set, files, readme_text),
        freshness=FreshnessSignals(
            created_at=str(meta.get("created_at", "")),
            pushed_at=str(meta.get("pushed_at", "")),
            days_since_pushed=_days_since(now, str(meta.get("pushed_at", ""))),
            archived=bool(meta.get("archived", False)),
            is_fork=bool(meta.get("is_fork", False)),
        ),
        mechanical_claims=extract_mechanical_claims(readme_text) if readme_text else [],
        snapshot_digest=snapshot_digest(meta, tree, files),
    )


def scan_portfolio(source: RepositorySource, owner: str, now: str | None = None) -> list[RepoScan]:
    """Broadly scan every discovered repository, sorted by name for determinism."""
    return [
        scan_repository(source, owner, name, now=now) for name in sorted(source.discover(owner))
    ]


def _readme_signals(readme_text: str | None) -> ReadmeSignals:
    if not readme_text:
        return ReadmeSignals(False, 0, 0, False, False, False, 0)
    lowered = readme_text.lower()
    headings = sum(1 for ln in readme_text.splitlines() if ln.lstrip().startswith("#"))
    has_install = bool(re.search(r"(?im)^#{1,6}.*install", readme_text)) or (
        "pip install" in lowered or "npm install" in lowered or "npm i " in lowered
    )
    has_usage = bool(
        re.search(r"(?im)^#{1,6}.*(usage|example|quickstart|getting started)", readme_text)
    )
    return ReadmeSignals(
        has_readme=True,
        length_chars=len(readme_text),
        heading_count=headings,
        has_install_section=has_install,
        has_usage_section=has_usage,
        has_badges="![" in readme_text or "shields.io" in lowered,
        code_fence_count=readme_text.count("```") // 2,
    )


def _docs_signals(tree: list[str], meta: dict[str, Any]) -> DocsSignals:
    bases = {_basename(p) for p in tree}
    license_meta = meta.get("license")
    return DocsSignals(
        has_docs_dir=any(p.lower().startswith("docs/") for p in tree),
        doc_file_count=sum(1 for p in tree if p.lower().endswith((".md", ".rst"))),
        has_contributing=any(b.upper().startswith("CONTRIBUTING") for b in bases),
        has_code_of_conduct=any(b.upper().startswith("CODE_OF_CONDUCT") for b in bases),
        has_changelog=any(b.upper().startswith("CHANGELOG") for b in bases),
        has_license_file=any(b.upper().startswith(("LICENSE", "LICENCE")) for b in bases),
        license_name=(None if license_meta in (None, "", "UNLICENSED") else str(license_meta)),
    )


def _tests_ci_signals(tree: list[str]) -> TestCiSignals:
    test_files = [p for p in tree if _is_test_path(p)]
    ci = _ci_files(tree)
    return TestCiSignals(
        has_tests=bool(test_files),
        test_file_count=len(test_files),
        has_ci=bool(ci),
        ci_workflow_count=len(ci),
        ci_files=ci,
    )


def _security_signals(tree_set: set[str], files: dict[str, str]) -> SecuritySignals:
    bases = {_basename(p) for p in tree_set}
    dep_count, pinned = _dependency_signals(files)
    return SecuritySignals(
        has_security_md=any(b.upper().startswith("SECURITY.") for b in bases),
        has_lockfile=bool(_LOCKFILES & bases),
        lockfile_kinds=sorted(_LOCKFILES & bases),
        dependency_manifests=sorted(_DEP_MANIFESTS & bases),
        declared_dependency_count=dep_count,
        pinned_dependencies=pinned,
        secret_hits=detect_secrets(files),
    )


def _packaging_signals(
    tree_set: set[str], files: dict[str, str], readme_text: str | None
) -> PackagingSignals:
    bases = {_basename(p) for p in tree_set}
    return PackagingSignals(
        has_dockerfile="Dockerfile" in bases,
        has_pyproject_or_setup=bool({"pyproject.toml", "setup.py", "setup.cfg"} & bases),
        has_package_json="package.json" in bases,
        has_makefile="Makefile" in bases,
        install_commands=_install_commands(readme_text) if readme_text else [],
        entrypoints=_entrypoints(files),
    )
