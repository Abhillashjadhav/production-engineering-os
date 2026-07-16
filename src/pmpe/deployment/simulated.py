"""Simulated production deployment — fixture mode only (PD-09).

There is deliberately no cloud adapter in this slice. This executor proves the
policy semantics (blocked without approval, canary rollback, READY reporting)
without touching any real environment, and its report line says so explicitly
so no downstream document can honestly claim a production deployment happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from pmpe.deployment.policy import DeploymentDecision

_FIXTURE_LINE = "FIXTURE MODE: simulated production deployment — no real environment was touched"


@dataclass(frozen=True)
class SimulatedDeployOutcome:
    executed: bool
    fixture_mode: bool
    canary_passed: bool
    rolled_back: bool
    ready: bool
    report_line: str


def simulate_production_deploy(
    decision: DeploymentDecision, *, canary_healthy: bool
) -> SimulatedDeployOutcome:
    if not decision.allowed:
        return SimulatedDeployOutcome(
            executed=False,
            fixture_mode=True,
            canary_passed=False,
            rolled_back=False,
            ready=False,
            report_line=f"{_FIXTURE_LINE}; blocked: " + "; ".join(decision.reasons),
        )
    if not canary_healthy:
        return SimulatedDeployOutcome(
            executed=True,
            fixture_mode=True,
            canary_passed=False,
            rolled_back=True,
            ready=False,
            report_line=f"{_FIXTURE_LINE}; canary failed -> rolled back",
        )
    return SimulatedDeployOutcome(
        executed=True,
        fixture_mode=True,
        canary_passed=True,
        rolled_back=False,
        ready=True,
        report_line=f"{_FIXTURE_LINE}; canary passed -> READY",
    )
