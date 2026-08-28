"""Local append-only JSONL history with a rebuildable SQLite index."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path

from .models import OVERVIEW_TREND_RUNS_PER_PRODUCT, RunEnvelope


class MonitoringStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.log_path = data_dir / "observations.jsonl"
        self.index_path = data_dir / "observations.sqlite3"
        self.lock_path = data_dir / "observations.lock"
        self._lock = threading.Lock()
        data_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.touch(exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        self._initialize_index()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def _exclusive_store_lock(self) -> Iterator[None]:
        """Serialize history operations across threads, instances, and workers."""

        with self._lock, self.lock_path.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _initialize_index(self) -> None:
        with self._exclusive_store_lock():
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
                    CREATE INDEX IF NOT EXISTS runs_product_observed
                        ON runs(product_id, environment, observed_at DESC, run_id DESC);
                    """
                )
            self._reconcile_index_unlocked()

    def _reconcile_index_unlocked(self) -> None:
        with self._connect() as connection:
            indexed, indexed_end = connection.execute(
                "SELECT COUNT(*), COALESCE(MAX(byte_offset + byte_length), 0) FROM runs"
            ).fetchone()
        log_size = self.log_path.stat().st_size
        if (indexed == 0 and log_size) or indexed_end != log_size:
            self._rebuild_index_unlocked()

    @staticmethod
    def _run_key(run: RunEnvelope) -> str:
        # JSON string escaping makes this tuple encoding injective even when an
        # identity component contains a control character or delimiter.
        return json.dumps(
            [run.product.id, run.product.environment, run.run_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _canonical_line(run: RunEnvelope) -> bytes:
        payload = run.model_dump(mode="json")
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    def _truncate_log(self, byte_offset: int) -> None:
        """Durably roll the canonical log back to a known record boundary."""

        with self.log_path.open("r+b") as handle:
            handle.truncate(byte_offset)
            handle.flush()
            os.fsync(handle.fileno())

    def append(self, run: RunEnvelope) -> bool:
        """Append one immutable run. Return False for an exact duplicate.

        Reusing a run identity with different bytes is rejected rather than
        silently replacing history.
        """

        line = self._canonical_line(run)
        digest = hashlib.sha256(line).hexdigest()
        run_key = self._run_key(run)
        with self._exclusive_store_lock():
            self._reconcile_index_unlocked()
            connection = self._connect()
            rollback_offset: int | None = None
            try:
                with connection:
                    existing = connection.execute(
                        """SELECT sha256 FROM runs
                           WHERE product_id = ? AND environment = ? AND run_id = ?""",
                        (run.product.id, run.product.environment, run.run_id),
                    ).fetchone()
                    if existing:
                        if existing[0] != digest:
                            raise ValueError("run identity already exists with different evidence")
                        return False
                    with self.log_path.open("ab") as handle:
                        rollback_offset = handle.tell()
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
                            run.observed_at.astimezone(UTC).isoformat(),
                            rollback_offset,
                            len(line),
                            digest,
                        ),
                    )
            except BaseException:
                if rollback_offset is not None:
                    try:
                        self._truncate_log(rollback_offset)
                    except BaseException as rollback_error:
                        raise RuntimeError(
                            "failed monitoring append could not be rolled back; "
                            "the log and index must be reconciled before retrying"
                        ) from rollback_error
                raise
            finally:
                connection.close()
        return True

    def rebuild_index(self) -> None:
        with self._exclusive_store_lock():
            self._rebuild_index_unlocked()

    def _rebuild_index_unlocked(self) -> None:
        records: list[tuple[RunEnvelope, int, int, str]] = []
        offset = 0
        log_size = self.log_path.stat().st_size
        torn_offset: int | None = None
        with self.log_path.open("rb") as handle:
            for line in handle:
                length = len(line)
                if not line.endswith(b"\n"):
                    if handle.tell() != log_size:
                        raise ValueError(
                            f"unterminated monitoring log record before byte {handle.tell()}"
                        )
                    torn_offset = offset
                    break
                try:
                    run = RunEnvelope.model_validate_json(line)
                except ValueError as exc:
                    raise ValueError(
                        f"completed monitoring log record is invalid at byte {offset}"
                    ) from exc
                records.append((run, offset, length, hashlib.sha256(line).hexdigest()))
                offset += length
        if torn_offset is not None:
            with self.log_path.open("r+b") as handle:
                handle.truncate(torn_offset)
                handle.flush()
                os.fsync(handle.fileno())
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
                        run.observed_at.astimezone(UTC).isoformat(),
                        byte_offset,
                        byte_length,
                        digest,
                    ),
                )

    def _read_rows(self, rows: list[tuple[int, int, str]]) -> list[RunEnvelope]:
        runs: list[RunEnvelope] = []
        with self.log_path.open("rb") as handle:
            for offset, length, expected_digest in rows:
                handle.seek(offset)
                line = handle.read(length)
                if hashlib.sha256(line).hexdigest() != expected_digest:
                    raise ValueError("stored monitoring evidence failed its digest check")
                runs.append(RunEnvelope.model_validate_json(line))
        return runs

    def list_runs(self) -> list[RunEnvelope]:
        with self._exclusive_store_lock():
            self._reconcile_index_unlocked()
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT byte_offset, byte_length, sha256 FROM runs ORDER BY observed_at, run_id"
                ).fetchall()
            return self._read_rows(rows)

    def list_runs_for_overview(
        self,
        *,
        trend_limit_per_product: int = OVERVIEW_TREND_RUNS_PER_PRODUCT,
    ) -> list[RunEnvelope]:
        """Load a bounded trend window plus each latest run's comparison."""

        if trend_limit_per_product < 1:
            raise ValueError("trend_limit_per_product must be at least one")
        with self._exclusive_store_lock():
            self._reconcile_index_unlocked()
            return self._list_runs_for_overview_unlocked(trend_limit_per_product)

    def _list_runs_for_overview_unlocked(
        self,
        trend_limit_per_product: int,
    ) -> list[RunEnvelope]:
        with self._connect() as connection:
            trend_rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT byte_offset, byte_length, sha256, observed_at,
                           product_id, environment, run_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY product_id, environment
                               ORDER BY observed_at DESC, run_id DESC
                           ) AS recency_rank
                    FROM runs
                )
                SELECT byte_offset, byte_length, sha256
                FROM ranked
                WHERE recency_rank <= ?
                ORDER BY observed_at, product_id, environment, run_id
                """,
                (trend_limit_per_product,),
            ).fetchall()
        trend_runs = self._read_rows(trend_rows)
        latest: dict[tuple[str, str], RunEnvelope] = {}
        selected_identities: set[tuple[str, str, str]] = set()
        for run in trend_runs:
            product_identity = (run.product.id, run.product.environment)
            run_identity = (*product_identity, run.run_id)
            selected_identities.add(run_identity)
            current = latest.get(product_identity)
            if current is None or (run.observed_at, run.run_id) > (
                current.observed_at,
                current.run_id,
            ):
                latest[product_identity] = run

        comparison_rows: list[tuple[int, int, str]] = []
        seen_comparisons: set[tuple[str, str, str]] = set()
        with self._connect() as connection:
            for run in latest.values():
                identity = (
                    run.product.id,
                    run.product.environment,
                    run.comparison.run_id,
                )
                if identity in selected_identities or identity in seen_comparisons:
                    continue
                seen_comparisons.add(identity)
                row = connection.execute(
                    """
                    SELECT byte_offset, byte_length, sha256
                    FROM runs
                    WHERE product_id = ? AND environment = ? AND run_id = ?
                    """,
                    identity,
                ).fetchone()
                if row is not None:
                    comparison_rows.append(row)

        combined = {
            (run.product.id, run.product.environment, run.run_id): run
            for run in [*trend_runs, *self._read_rows(comparison_rows)]
        }
        return sorted(
            combined.values(),
            key=lambda run: (
                run.observed_at,
                run.product.id,
                run.product.environment,
                run.run_id,
            ),
        )
