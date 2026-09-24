"""Stack adapter protocol and the reference full-stack stack (PD-V3-13/14).

A stack adapter is a *declaration with judgement*: it names the tool that owns
each of the seven capability surfaces a verified web delivery needs, states
which deployment kinds it honestly supports, and assesses whether it can
deliver a given FullStackProductContract — refusing, fail-closed, anything it
cannot (an adapter that accepts contracts it can't deliver would launder
unverifiable promises into the run).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pmpe.domain.errors import PmpeError
from pmpe.fullstack.contract import FullStackProductContract

CAPABILITY_SURFACES = (
    "frontend",
    "backend",
    "api_contract",
    "browser_test",
    "accessibility",
    "responsive",
    "preview",
)

# every interactive web product needs these states deliverable everywhere
_CORE_UI_STATES = ("loading", "error", "success")


@dataclass(frozen=True)
class StackCapability:
    surface: str
    tool: str
    description: str


@runtime_checkable
class FullStackAdapter(Protocol):
    """What the run engine needs from any full-stack stack."""

    @property
    def name(self) -> str: ...

    def capabilities(self) -> tuple[StackCapability, ...]: ...

    def supported_deployment_kinds(self) -> frozenset[str]: ...

    def supported_api_methods(self) -> frozenset[str]: ...

    def assess_contract(self, contract: FullStackProductContract) -> list[str]: ...


@dataclass(frozen=True)
class ReferenceWebStack:
    """Next.js + FastAPI + Playwright — the one opinionated reference stack
    (PD-V3-13). Preview kinds only; no cloud claim (PD-V3-14)."""

    @property
    def name(self) -> str:
        return "nextjs-fastapi-playwright"

    def capabilities(self) -> tuple[StackCapability, ...]:
        return (
            StackCapability(
                surface="frontend",
                tool="Next.js + TypeScript + React",
                description="Typed components, typed API client, all contract UI "
                "states, minimal component styling (no design-system dependency).",
            ),
            StackCapability(
                surface="backend",
                tool="FastAPI (Python)",
                description="Typed request/response models over a deterministic "
                "domain layer; in-memory file handling with size/format limits; "
                "no external egress.",
            ),
            StackCapability(
                surface="api_contract",
                tool="OpenAPI schema diff",
                description="The committed OpenAPI schema is the contract; client "
                "types derive from it; any mismatch between committed schema and "
                "the live app fails CI.",
            ),
            StackCapability(
                surface="browser_test",
                tool="Playwright (Chromium)",
                description="Browser E2E drives the real frontend against the real "
                "backend — no mocked backend in the delivered path.",
            ),
            StackCapability(
                surface="accessibility",
                tool="axe-core + deterministic checks",
                description="Automated accessibility scans plus keyboard-only "
                "journey completion tests with visible focus.",
            ),
            StackCapability(
                surface="responsive",
                tool="Playwright viewport matrix",
                description="Primary journey verified on desktop (>=1280px) and "
                "mobile (375px) viewports.",
            ),
            StackCapability(
                surface="preview",
                tool="Docker Compose / built-artifact runner",
                description="Containerized preview built from the frozen candidate; "
                "browser tests run against the built artifact and the preview "
                "digest is bound to the candidate digest.",
            ),
        )

    def supported_deployment_kinds(self) -> frozenset[str]:
        return frozenset({"local_preview", "containerized_preview"})

    def supported_api_methods(self) -> frozenset[str]:
        # the V3 verification tooling covers these; a contract needing more must
        # extend the stack first, not slip past it
        return frozenset({"GET", "POST"})

    def assess_contract(self, contract: FullStackProductContract) -> list[str]:
        """Problems ([] = this stack can deliver the contract). Fail closed:
        an unsupported or incomplete contract is refused with named reasons."""
        problems: list[str] = []
        kind = contract.deployment_target.kind
        if kind not in self.supported_deployment_kinds():
            problems.append(
                f"deployment_target kind '{kind}' is not supported by {self.name} "
                "(supported: local_preview, containerized_preview) — no cloud "
                "deployment is claimed (PD-V3-14)"
            )
        for entity in contract.data_entities:
            if entity.persistence == "permanent":
                problems.append(
                    f"data entity {entity.entity_id} requires permanent persistence, "
                    f"which {self.name} does not provide"
                )
        missing_states = [s for s in _CORE_UI_STATES if s not in contract.ui_states]
        if missing_states:
            problems.append(
                "ui_states vocabulary lacks core web states required by this stack: "
                + ", ".join(missing_states)
            )
        for api in contract.api_contracts:
            if api.method not in self.supported_api_methods():
                problems.append(
                    f"api contract {api.api_id} uses method {api.method}, outside "
                    f"what {self.name}'s contract verification covers "
                    f"({', '.join(sorted(self.supported_api_methods()))})"
                )
        return problems


REFERENCE_STACK = ReferenceWebStack()

_STACKS: dict[str, FullStackAdapter] = {REFERENCE_STACK.name: REFERENCE_STACK}


def get_stack(name: str) -> FullStackAdapter:
    try:
        return _STACKS[name]
    except KeyError as exc:
        raise PmpeError(
            f"no full-stack adapter named '{name}' (available: {', '.join(sorted(_STACKS))})"
        ) from exc
