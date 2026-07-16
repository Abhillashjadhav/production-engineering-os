"""The evidence ledger: the run's system of record (never a chat transcript).

Structured JSONL, one event per stage action, carrying artifact digests so
trajectory evals can verify ordering, identity, and digest constancy after the
fact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.domain.serialize import jsonable
from pmpe.telemetry.events import utc_now


class EvidenceLedger:
    def __init__(self, run_dir: Path, *, run_id: str) -> None:
        self.run_id = run_id
        self.path = Path(run_dir) / "ledger.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        stage: str,
        agent: str,
        action: str,
        input_digests: dict[str, str] | None = None,
        output_digests: dict[str, str] | None = None,
        tool: str = "",
        verdict: str = "",
        escalation: str = "",
        next_state: str = "",
        detail: str = "",
        cost: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "run_id": self.run_id,
            "ts": utc_now(),
            "stage": stage,
            "agent": agent,
            "action": action,
            "input_digests": jsonable(input_digests or {}),
            "output_digests": jsonable(output_digests or {}),
            "tool": tool,
            "verdict": verdict,
            "escalation": escalation,
            "next_state": next_state,
            "detail": detail,
            "cost": jsonable(cost) if cost is not None else None,
        }
        with self.path.open("a") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
