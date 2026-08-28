"""UX architecture validation (PD-V3-16): journey, screens, and states must be
coherent before implementation, and the validated record is the fail-closed
precondition later stages verify.

Rules (each refusal names the offending ids):
- every journey step's screen exists;
- every screen is reachable from the journey (an unreachable screen is dead UX);
- every screen's declared states are drawn from the contract's vocabulary;
- every screen declares an ``error`` state (a screen that cannot show failure
  hides it — error/recovery is mandatory);
- every vocabulary state is declared by at least one screen (an unused state is
  an unimplementable promise).
"""

from __future__ import annotations

import json
from pathlib import Path

from pmpe.domain.errors import PmpeError
from pmpe.domain.serialize import atomic_write_json
from pmpe.fullstack.contract import FullStackProductContract
from pmpe.telemetry.events import utc_now

_RECORD_NAME = "ux-architecture.json"


class JourneyNotValidated(PmpeError):  # noqa: N818 — deliberate: it is a violation
    """The UX architecture is incoherent, unrecorded, or for another contract."""


def validate_ux_architecture(contract: FullStackProductContract) -> list[str]:
    """Problems ([] = the journey/screen/state inventory is coherent)."""
    problems: list[str] = []
    screen_ids = {s.screen_id for s in contract.screens}
    vocabulary = set(contract.ui_states)

    reached: set[str] = set()
    for step in contract.primary_journey:
        if step.screen_id not in screen_ids:
            problems.append(
                f"journey step {step.step_id} points at screen '{step.screen_id}', "
                "which does not exist"
            )
        else:
            reached.add(step.screen_id)

    for screen in contract.screens:
        if screen.screen_id not in reached:
            problems.append(
                f"screen {screen.screen_id} ('{screen.name}') is unreachable from "
                "the primary journey — dead UX is not deliverable"
            )
        unknown = [s for s in screen.states if s not in vocabulary]
        if unknown:
            problems.append(
                f"screen {screen.screen_id} declares state(s) outside the "
                "contract vocabulary: " + ", ".join(unknown)
            )
        if "error" not in screen.states:
            problems.append(
                f"screen {screen.screen_id} declares no 'error' state — error and "
                "recovery states are mandatory"
            )

    declared_anywhere = {state for screen in contract.screens for state in screen.states}
    unused = sorted(vocabulary - declared_anywhere)
    if unused:
        problems.append(
            "vocabulary state(s) no screen declares: "
            + ", ".join(unused)
            + " — an unused state is an unimplementable promise"
        )
    return problems


def record_validated_journey(run_dir: Path, contract: FullStackProductContract) -> Path:
    """Validate and persist the UX architecture record. Refuses, fail closed,
    to record an incoherent journey — nothing is written on refusal."""
    problems = validate_ux_architecture(contract)
    if problems:
        raise JourneyNotValidated(
            "UX architecture is not coherent; refusing to record: " + "; ".join(problems)
        )
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / _RECORD_NAME
    atomic_write_json(
        path,
        {
            "contract_digest": contract.digest,
            "validated_at": utc_now(),
            "journey": [
                {"step_id": s.step_id, "screen_id": s.screen_id, "description": s.description}
                for s in contract.primary_journey
            ],
            "screens": [
                {
                    "screen_id": s.screen_id,
                    "name": s.name,
                    "purpose": s.purpose,
                    "states": list(s.states),
                }
                for s in contract.screens
            ],
            "ui_states": list(contract.ui_states),
        },
    )
    return path


def require_validated_journey(run_dir: Path, contract_digest: str) -> None:
    """Fail closed unless a validated UX architecture exists for exactly this
    contract. Implementation before a validated journey is the planted failure
    class TRAJ-FS will also watch for (PD-V3-16)."""
    path = Path(run_dir) / _RECORD_NAME
    if not path.exists():
        raise JourneyNotValidated(
            f"no validated UX architecture at {path} — the journey must be "
            "validated before implementation (PD-V3-16)"
        )
    record = json.loads(path.read_text())
    if record.get("contract_digest") != contract_digest:
        raise JourneyNotValidated(
            "the validated UX architecture belongs to a different contract "
            f"({record.get('contract_digest')} != {contract_digest}) — revalidate"
        )
