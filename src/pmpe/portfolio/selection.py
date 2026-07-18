"""Strategic configuration, risk ranking, and deep-scan selection (M3).

The operator supplies the strategic/marketable repository list via
configuration, never source code (PD-PA-02); an absent configuration fails
loudly (AC-PA-003). Risk ranking is a deterministic pure function of
broad-scan signals — it weighs *observable risk*, it renders no verdict.
Selection composes strategy and ranking: strategy-listed repositories are
always deep-scanned (the quota bounds only risk-based additions), every
selection carries a traceable reason, and the selected/not-selected
partition is complete over the inventory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmpe.domain.errors import ConfigError
from pmpe.ingestion.schema import SchemaValidator
from pmpe.portfolio.scanner import RepoScan

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

#: Deterministic risk-factor weights. Secrets dominate by design: a leaked
#: credential is an incident, not a style problem.
_FACTOR_WEIGHTS: dict[str, float] = {
    "secret_hits": 40.0,
    "claim_to_evidence_gap": 25.0,
    "no_lockfile": 8.0,
    "unpinned_dependencies": 8.0,
    "no_tests": 10.0,
    "no_ci": 8.0,
    "no_license": 4.0,
    "stale": 10.0,
    "archived": 6.0,
    "fork": 5.0,
    "private_with_secret": 15.0,
}

_STALE_DAYS = 365


def strategy_schema_path() -> Path:
    return _SCHEMA_DIR / "portfolio_strategy.schema.json"


@dataclass(frozen=True)
class Strategy:
    """The operator's strategic configuration (PD-PA-02)."""

    strategy_version: int
    strategic_repositories: tuple[str, ...]
    marketable_repositories: tuple[str, ...]
    genai_authority_repositories: tuple[str, ...]
    deep_scan_quota: int

    def always_deep_scan(self) -> tuple[str, ...]:
        """Strategy-listed repositories, deduplicated, deterministic order."""
        seen: dict[str, None] = {}
        for name in (
            *self.strategic_repositories,
            *self.marketable_repositories,
            *self.genai_authority_repositories,
        ):
            seen.setdefault(name)
        return tuple(seen)


def load_strategy(path: Path) -> Strategy:
    """Load and validate the operator strategy config (fail-closed)."""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"cannot load strategy configuration {path}: {exc} — the operator-"
            "supplied strategic repository list is required (PD-PA-02)"
        ) from exc
    errors = SchemaValidator(strategy_schema_path()).validate(data)
    if errors:
        raise ConfigError("strategy configuration is invalid:\n  " + "\n  ".join(errors))
    quota = int(data["deep_scan_quota"])
    if quota < 1:
        raise ConfigError(f"deep_scan_quota must be >= 1, got {quota}")
    return Strategy(
        strategy_version=int(data["strategy_version"]),
        strategic_repositories=tuple(str(r) for r in data["strategic_repositories"]),
        marketable_repositories=tuple(str(r) for r in data["marketable_repositories"]),
        genai_authority_repositories=tuple(str(r) for r in data["genai_authority_repositories"]),
        deep_scan_quota=quota,
    )


@dataclass(frozen=True)
class RepoRisk:
    """Deterministic risk assessment for one repository — factors, no verdict."""

    repository: str
    score: float
    factors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "score": self.score,
            "factors": list(self.factors),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RepoRisk:
        return cls(
            repository=str(d["repository"]),
            score=float(d["score"]),
            factors=tuple(str(f) for f in d.get("factors", [])),
        )


def _risk_factors(scan: RepoScan) -> list[str]:
    factors: list[str] = []
    if scan.security.secret_hits:
        factors.append("secret_hits")
        if scan.visibility.value == "PRIVATE":
            factors.append("private_with_secret")
    if scan.mechanical_claims and not (scan.tests_ci.has_tests or scan.tests_ci.has_ci):
        factors.append("claim_to_evidence_gap")
    if scan.security.dependency_manifests and not scan.security.has_lockfile:
        factors.append("no_lockfile")
    if scan.security.pinned_dependencies is False:
        factors.append("unpinned_dependencies")
    if not scan.tests_ci.has_tests:
        factors.append("no_tests")
    if not scan.tests_ci.has_ci:
        factors.append("no_ci")
    if not scan.docs.license_name:
        factors.append("no_license")
    days = scan.freshness.days_since_pushed
    if days is not None and days > _STALE_DAYS:
        factors.append("stale")
    if scan.freshness.archived:
        factors.append("archived")
    if scan.freshness.is_fork:
        factors.append("fork")
    return factors


def rank_risks(scans: list[RepoScan]) -> list[RepoRisk]:
    """Deterministic risk ranking: highest score first, name-tiebroken."""
    risks = []
    for scan in scans:
        factors = _risk_factors(scan)
        score = round(sum(_FACTOR_WEIGHTS[f] for f in factors), 4)
        risks.append(
            RepoRisk(
                repository=f"{scan.owner}/{scan.name}",
                score=score,
                factors=tuple(factors),
            )
        )
    return sorted(risks, key=lambda r: (-r.score, r.repository))


@dataclass(frozen=True)
class SelectionEntry:
    repository: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"repository": self.repository, "reason": self.reason}


@dataclass(frozen=True)
class SelectionReport:
    """The deep-scan set plus the complete not-selected remainder."""

    selected: tuple[SelectionEntry, ...]
    not_selected: tuple[str, ...]
    quota: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": [e.to_dict() for e in self.selected],
            "not_selected": list(self.not_selected),
            "quota": self.quota,
        }


def select_for_deep_scan(
    scans: list[RepoScan], strategy: Strategy, risks: list[RepoRisk]
) -> SelectionReport:
    """Compose strategy and risk ranking into the deep-scan set.

    Strategy-listed repositories are always selected — the quota bounds only
    the risk-based additions. A strategy entry naming a repository absent
    from the inventory fails loudly rather than being silently dropped.
    """
    inventory = {f"{s.owner}/{s.name}" for s in scans}
    unknown = [name for name in strategy.always_deep_scan() if name not in inventory]
    if unknown:
        raise ConfigError(
            "strategy names repositories absent from the scanned inventory: "
            + ", ".join(sorted(unknown))
            + " — fix the strategy config or the inventory before selecting"
        )

    reasons: dict[str, str] = {}
    for name in strategy.strategic_repositories:
        reasons.setdefault(name, "strategic repository (operator-listed)")
    for name in strategy.marketable_repositories:
        reasons.setdefault(name, "marketable repository (operator-listed)")
    for name in strategy.genai_authority_repositories:
        reasons.setdefault(name, "GenAI authority repository (operator-listed)")

    slots = strategy.deep_scan_quota
    for risk in risks:  # already highest-risk-first, deterministic
        if slots == 0:
            break
        if risk.repository in reasons:
            continue
        if risk.score <= 0:
            continue
        top = ", ".join(risk.factors[:3])
        reasons[risk.repository] = f"risk rank (score {risk.score:g}: {top})"
        slots -= 1

    selected = tuple(
        SelectionEntry(repository=name, reason=reasons[name]) for name in sorted(reasons)
    )
    not_selected = tuple(sorted(inventory - set(reasons)))
    return SelectionReport(
        selected=selected, not_selected=not_selected, quota=strategy.deep_scan_quota
    )
