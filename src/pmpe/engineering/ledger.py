"""The evidence ledger: the run's system of record (never a chat transcript).

Structured JSONL, one event per stage action, carrying artifact digests so
trajectory evals can verify ordering, identity, and digest constancy after the
fact.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

from pmpe.contracts.digest import canonical_digest
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
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        identity_payload = {
            "run_id": self.run_id,
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
            "idempotency_key": idempotency_key,
        }
        recorded_at = utc_now()
        event = {
            **identity_payload,
            "event_id": canonical_digest(
                identity_payload if idempotency_key else {**identity_payload, "ts": recorded_at}
            ),
            "ts": recorded_at,
        }
        lock_path = self.path.with_suffix(".lock")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            existing = self._read_all(repair_truncated_tail=bool(idempotency_key))
            if idempotency_key:
                prior = next(
                    (item for item in existing if item.get("idempotency_key") == idempotency_key),
                    None,
                )
                if prior is not None:
                    comparable = {key: prior.get(key) for key in identity_payload}
                    if comparable != identity_payload:
                        raise ValueError("idempotency key was reused for different evidence")
                    return prior
            with self.path.open("a") as fh:
                fh.write(json.dumps(event, sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return event

    def read_all(self) -> list[dict[str, Any]]:
        lock_path = self.path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            return self._read_all(repair_truncated_tail=False)

    def _read_all(self, *, repair_truncated_tail: bool) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        lines = raw.splitlines(keepends=True)
        events: list[dict[str, Any]] = []
        valid_bytes = 0
        for index, encoded in enumerate(lines):
            complete = encoded.endswith((b"\n", b"\r"))
            if not encoded.strip():
                valid_bytes += len(encoded)
                continue
            try:
                events.append(json.loads(encoded))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                if repair_truncated_tail and index == len(lines) - 1 and not complete:
                    with self.path.open("r+b") as stream:
                        stream.truncate(valid_bytes)
                        stream.flush()
                        os.fsync(stream.fileno())
                    break
                raise ValueError("evidence ledger contains an invalid JSON event") from exc
            valid_bytes += len(encoded)
            if repair_truncated_tail and index == len(lines) - 1 and not complete:
                with self.path.open("ab") as stream:
                    stream.write(b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
        return events
