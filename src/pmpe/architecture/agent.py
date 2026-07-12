"""Deterministic architecture agent for the python-stdlib-crud-api stack.

Proposes the simplest architecture that satisfies the plan, records ADRs with
explicit risk/reversibility, and escalates instead of deciding when the spec
declares a high risk or an ADR would be irreversible.
"""

from __future__ import annotations

from pmpe.domain.models import (
    Adr,
    ArchitectureDoc,
    ArchitectureOutput,
    EngineeringPlan,
    Escalation,
    MvpSpec,
    RiskLevel,
)
from pmpe.policies.engine import PolicyEngine


class ArchitectureAgent:
    def __init__(self, policy: PolicyEngine) -> None:
        self._policy = policy

    def design(self, spec: MvpSpec, plan: EngineeringPlan) -> ArchitectureOutput:
        adrs = self._adrs(spec)
        doc = self._doc(spec, plan)
        escalations = self._escalations(spec, adrs)
        return ArchitectureOutput(doc=doc, adrs=adrs, escalations=escalations)

    def _adrs(self, spec: MvpSpec) -> list[Adr]:
        entity_frs = [f.id for f in spec.functional_requirements
                      if f.capability.startswith("entity.")]
        auth_frs = [f.id for f in spec.functional_requirements
                    if f.capability == "auth.bearer_token"]
        adrs = [
            Adr(
                id="ADR-001",
                title=f"Stack: {spec.preferred_stack} single-process HTTP API",
                context=(
                    f"The spec requests target_platform '{spec.target_platform}' with "
                    f"preferred_stack '{spec.preferred_stack}'. Constraints: "
                    + ("; ".join(spec.constraints) or "none declared")
                    + "."
                ),
                decision=(
                    "Python standard library only: http.server ThreadingHTTPServer for "
                    "HTTP, no framework, no third-party runtime dependencies."
                ),
                consequences=(
                    "+ Runs and tests anywhere Python runs; zero supply-chain surface. "
                    "- Not suited to high concurrency; a framework port is a contained "
                    "rewrite of the API layer only."
                ),
                risk=RiskLevel.LOW,
                reversibility="reversible",
                requirement_ids=[f.id for f in spec.functional_requirements],
            ),
            Adr(
                id="ADR-002",
                title="Persistence: SQLite file per deployment",
                context=(
                    "Entities: "
                    + (", ".join(e.name for e in spec.entities) or "none")
                    + ". The spec requires data to survive restarts and declares a "
                    "single-user product."
                ),
                decision=(
                    "SQLite database file (path from APP_DB env var), parameterized "
                    "queries only, one writer lock around mutations."
                ),
                consequences=(
                    "+ Durable, transactional, zero external services. "
                    "- Single-node only; moving to Postgres later is a storage-adapter "
                    "swap, not a rewrite."
                ),
                risk=RiskLevel.MEDIUM,
                reversibility="reversible",
                requirement_ids=entity_frs,
            ),
            Adr(
                id="ADR-003",
                title="Auth: static bearer token injected via environment",
                context=(
                    "The spec requires bearer-token auth (capability auth.bearer_token) "
                    "for a single-user product with one token per deployment."
                ),
                decision=(
                    "APP_TOKEN environment variable, generated at deploy time, compared "
                    "with hmac.compare_digest; the token never appears in code, config "
                    "files, or logs."
                ),
                consequences=(
                    "+ No secret at rest in the repo; constant-time compare. "
                    "- Single static token: leak requires rotation (documented in the "
                    "product README); per-user auth is a V2 concern."
                ),
                risk=RiskLevel.MEDIUM,
                reversibility="reversible",
                requirement_ids=auth_frs,
            ),
            Adr(
                id="ADR-004",
                title="Deployment shape: single local process + deployable artifact",
                context=(
                    f"deployment_target is '{spec.deployment_target}'. V1 verifies "
                    "against a really-running process."
                ),
                decision=(
                    "Deploy as one local process (run.sh) with health-check and "
                    "user-journey smoke verification; emit a Dockerfile so the same "
                    "artifact can be containerized elsewhere."
                ),
                consequences=(
                    "+ Verification is real HTTP against a real process. "
                    "- No HA/scaling story; cloud targets arrive as deployment adapters."
                ),
                risk=RiskLevel.LOW,
                reversibility="reversible",
                requirement_ids=[f.id for f in spec.functional_requirements
                                 if f.capability == "health.check"],
            ),
        ]
        return adrs

    def _doc(self, spec: MvpSpec, plan: EngineeringPlan) -> ArchitectureDoc:
        components = {
            "api": "HTTP routing, request validation, JSON error contract",
            "storage": "SQLite persistence, parameterized queries, writer lock",
            "auth": "bearer-token verification (env-injected, constant-time)",
            "server": "process entrypoint, configuration from environment",
            "tests": "generated before implementation; unit + integration over real HTTP",
        }
        overview = (
            f"{spec.product_name}: a single-process JSON API ({', '.join(plan.apis)}) "
            f"with SQLite persistence and bearer-token auth. Modules: app/api.py, "
            f"app/storage.py, app/auth.py, app/server.py. Data model: "
            f"{'; '.join(plan.data_model) or 'none'}."
        )
        implications = {
            "security": (
                "Token via environment only; constant-time comparison; parameterized "
                "SQL; no eval/exec/shell; security gate scans every build."
            ),
            "scalability": (
                "ThreadingHTTPServer + SQLite serves a single-user product; scale-out "
                "requires a storage adapter and a WSGI/ASGI port (contained changes)."
            ),
            "reliability": (
                "Data on disk survives restarts; process supervised by run.sh; health "
                "endpoint enables external monitoring; rollback = stop process, restore "
                "previous artifact."
            ),
            "maintainability": (
                "Four small modules with single responsibilities; tests map 1:1 to "
                "requirements; no framework magic."
            ),
        }
        return ArchitectureDoc(overview=overview, components=components,
                               implications=implications)

    def _escalations(self, spec: MvpSpec, adrs: list[Adr]) -> list[Escalation]:
        escalations: list[Escalation] = []
        for adr in adrs:
            if adr.reversibility == "irreversible" or adr.risk is RiskLevel.HIGH:
                decision = self._policy.classify("architecture.irreversible_choice")
                escalations.append(
                    Escalation(
                        id="",  # assigned by the orchestrator
                        risk=decision.level,
                        reason=f"{adr.id} ('{adr.title}') is {adr.reversibility} with "
                               f"risk {adr.risk.value}: {decision.justification}",
                        step="architecture",
                        context={"adr": adr.id, "rule": decision.rule_id},
                    )
                )
        for risk in spec.risks:
            if risk.level is RiskLevel.HIGH:
                escalations.append(
                    Escalation(
                        id="",
                        risk=RiskLevel.HIGH,
                        reason=f"The spec declares a high risk the PM must acknowledge "
                               f"before build: {risk.description}",
                        step="architecture",
                        context={"source": "spec.risks"},
                    )
                )
        return escalations
