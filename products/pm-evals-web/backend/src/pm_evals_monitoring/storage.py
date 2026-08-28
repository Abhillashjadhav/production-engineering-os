"""Local append-only JSONL history with a rebuildable SQLite index."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from .models import RunEnvelope


class MonitoringStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.log_path = data_dir / "observations.jsonl"
        self.index_path = data_dir / "observations.sqlite3"
        self._lock = threading.Lock()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.touch(exist_ok=True)
        self._initialize_index()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize_index(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    byte_offset INTEGER NOT NULL,
                    byte_length INTEGER NOT NULL,
                    sha256 TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS runs_identity
                    ON runs(product_id, environment, run_id);
                """
            )
            indexed, indexed_end = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(byte_offset + byte_length), 0) FROM runs"
            ).fetchone()
        log_size = self.log_path.stat().st_size
        if (indexed == 0 and log_size) or indexed_end != log_size:
            self.rebuild_index()

    @staticmethod
    def _run_key(run: RunEnvelope) -> str:
        return f"{run.product.id}\x1f{run.product.environment}\x1f{run.run_id}"

    @staticmethod
    def _canonical_line(run: RunEnvelope) -> bytes:
        payload = run.model_dump(mode="json")
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def append(self, run: RunEnvelope) -> bool:
        """Append one immutable run. Return False for an exact duplicate.

        Reusing a run identity with different bytes is rejected rather than
        silently replacing history.
        """

        line = self._canonical_line(run)
        digest = hashlib.sha256(line).hexdigest()
        run_key = self._run_key(run)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT sha256 FROM runs WHERE run_key = ?", (run_key,)
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("run identity already exists with different evidence")
                return False
            with self.log_path.open("ab") as handle:
                offset = handle.tell()
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            connection.execute(
                """INSERT INTO runs
                   (run_key, run_id, product_id, environment, observed_at,
                    byte_offset, byte_length, sha256)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_key,
                    run.run_id,
                    run.product.id,
                    run.product.environment,
                    run.observed_at.isoformat(),
                    offset,
                    len(line),
                    digest,
                ),
            )
        return True

    def rebuild_index(self) -> None:
        records: list[tuple[RunEnvelope, int, int, str]] = []
        offset = 0
        with self.log_path.open("rb") as handle:
            for line in handle:
                length = len(line)
                run = RunEnvelope.model_validate_json(line)
                records.append((run, offset, length, hashlib.sha256(line).hexdigest()))
                offset += length
        with self._connect() as connection:
            connection.execute("DELETE FROM runs")
            for run, byte_offset, byte_length, digest in records:
                connection.execute(
                    """INSERT INTO runs
                       (run_key, run_id, product_id, environment, observed_at,
                        byte_offset, byte_length, sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._run_key(run),
                        run.run_id,
                        run.product.id,
                        run.product.environment,
                        run.observed_at.isoformat(),
                        byte_offset,
                        byte_length,
                        digest,
                    ),
                )

    def list_runs(self) -> list[RunEnvelope]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT byte_offset, byte_length, sha256 FROM runs ORDER BY observed_at, run_id"
            ).fetchall()
        runs: list[RunEnvelope] = []
        with self.log_path.open("rb") as handle:
            for offset, length, expected_digest in rows:
                handle.seek(offset)
                line = handle.read(length)
                if hashlib.sha256(line).hexdigest() != expected_digest:
                    raise ValueError("stored monitoring evidence failed its digest check")
                runs.append(RunEnvelope.model_validate_json(line))
        return runs
