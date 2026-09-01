"""Local append-only JSONL history with a rebuildable SQLite index."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .diagnosis import diagnose_run
from .models import (
    MAX_FUTURE_CLOCK_SKEW,
    OVERVIEW_TREND_RUNS_PER_PRODUCT,
    AdjudicationRecord,
    LegacyAdjudicationRecord,
    RunEnvelope,
    RunReceipt,
    canonical_run_digest,
    canonical_run_line,
    case_incident_id,
)

_SHARED_STORE_ROOTS = frozenset(
    path.resolve(strict=False)
    for path in (Path("/"), Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"))
)


class FutureObservationError(ValueError):
    """New evidence is too far ahead of the server's current clock."""


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class MonitoringStore:
    def __init__(self, data_dir: Path) -> None:
        if data_dir.resolve(strict=False) in _SHARED_STORE_ROOTS:
            raise ValueError("monitoring data directory must not use a shared system root")
        self.data_dir = data_dir
        self.log_path = data_dir / "observations.jsonl"
        self.index_path = data_dir / "observations.sqlite3"
        self.lock_path = data_dir / "observations.lock"
        self.receipt_path = data_dir / "run-receipts.jsonl"
        self.adjudication_path = data_dir / "adjudications.jsonl"
        self._lock = threading.Lock()
        missing_directories: list[Path] = []
        cursor = data_dir
        while not cursor.exists():
            missing_directories.append(cursor)
            cursor = cursor.parent
        data_dir.mkdir(parents=True, exist_ok=True)
        if data_dir.is_symlink() or not data_dir.is_dir():
            raise ValueError("monitoring data directory must be a real directory")
        for directory in reversed(missing_directories):
            os.chmod(directory, 0o700)
            _fsync_directory(directory.parent)
        os.chmod(data_dir, 0o700)
        _fsync_directory(data_dir.parent)
        for path in (
            self.log_path,
            self.lock_path,
            self.receipt_path,
            self.adjudication_path,
            self.index_path,
        ):
            self._ensure_private_file(path)
        self._initialize_index()
        with self._exclusive_store_lock():
            self._reconcile_auxiliary_unlocked(self.receipt_path, "receipt")
            self._reconcile_auxiliary_unlocked(self.adjudication_path, "adjudication")

    @staticmethod
    def _ensure_private_file(path: Path) -> None:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        created = False
        try:
            descriptor = os.open(path, flags, 0o600)
            created = True
        except FileExistsError:
            flags &= ~os.O_EXCL
            try:
                descriptor = os.open(path, flags, 0o600)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise ValueError("monitoring ledger must not be a symlink") from exc
                raise
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("monitoring ledger must be a regular file")
            os.fchmod(descriptor, 0o600)
            if created:
                os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if created:
            _fsync_directory(path.parent)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path)
        os.chmod(self.index_path, 0o600)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _truncate_path(path: Path, byte_offset: int) -> None:
        with path.open("r+b") as handle:
            handle.truncate(byte_offset)
            handle.flush()
            os.fsync(handle.fileno())

    def _reconcile_auxiliary_unlocked(self, path: Path, kind: str) -> list[bytes]:
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            boundary = data.rfind(b"\n") + 1
            self._truncate_path(path, boundary)
            data = data[:boundary]
        lines = data.splitlines(keepends=True)
        for line in lines:
            try:
                if kind == "receipt":
                    RunReceipt.model_validate_json(line)
                else:
                    self._parse_adjudication_line(line)
            except ValueError as exc:
                raise ValueError(f"completed {kind} ledger record is invalid") from exc
        return lines

    def _parse_adjudication_line(self, line: bytes) -> AdjudicationRecord:
        try:
            return AdjudicationRecord.model_validate_json(line)
        except ValueError:
            legacy = LegacyAdjudicationRecord.model_validate_json(line)
        run = self._get_run_unlocked(
            product_id=legacy.product_id,
            environment=legacy.environment,
            run_id=legacy.run_id,
        )
        if run is None:
            raise ValueError("legacy adjudication run does not exist")
        observations = {item.observation_id: item for item in run.observations}
        observation = observations.get(legacy.observation_id)
        referenced_roots = set(legacy.predicted_root_observation_ids) | set(
            legacy.actual_root_observation_ids
        )
        if observation is None or not referenced_roots.issubset(observations):
            raise ValueError("legacy adjudication references missing observations")
        comparison = self._get_run_unlocked(
            product_id=run.product.id,
            environment=run.product.environment,
            run_id=run.comparison.run_id,
        )
        if (
            comparison is None
            or run.comparison.sha256 is None
            or canonical_run_digest(comparison) != run.comparison.sha256
        ):
            comparison = None
        diagnosis = diagnose_run(run, comparison=comparison)
        diagnosed = next(
            (item for item in diagnosis.diagnoses if item.observation_id == legacy.observation_id),
            None,
        )
        if diagnosed is None:
            raise ValueError("legacy adjudication observation is not diagnosable")
        if sorted(legacy.predicted_root_observation_ids) != sorted(diagnosed.root_observation_ids):
            raise ValueError("legacy adjudication predicted roots do not match diagnosis")
        if (
            diagnosed.attribution not in {"LIKELY_STARTING_FAILURE", "DEGRADED_CHECK"}
            and legacy.verdict != "UNRESOLVED"
        ):
            raise ValueError("legacy adjudication resolved a non-independent diagnosis")
        derived_verdict = (
            "UNRESOLVED"
            if not legacy.actual_root_observation_ids
            else "CORRECT"
            if set(diagnosed.root_observation_ids) == set(legacy.actual_root_observation_ids)
            else "INCORRECT"
        )
        if legacy.verdict != derived_verdict:
            raise ValueError("legacy adjudication verdict contradicts its root sets")
        if legacy.adjudicated_at > datetime.now(UTC) + MAX_FUTURE_CLOCK_SKEW:
            raise ValueError("legacy adjudication timestamp exceeds allowed clock skew")
        payload = legacy.model_dump(mode="python", exclude={"adjudication_version"})
        return AdjudicationRecord(
            **payload,
            case_incident_id=case_incident_id(
                product_id=legacy.product_id,
                environment=legacy.environment,
                run_id=legacy.run_id,
                case=observation.case,
            ),
        )

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
                    CREATE INDEX IF NOT EXISTS runs_product_arrival
                        ON runs(product_id, environment, observed_at DESC, byte_offset DESC);
                    CREATE TABLE IF NOT EXISTS ingest_rate (
                        product_id TEXT NOT NULL,
                        environment TEXT NOT NULL,
                        minute_epoch INTEGER NOT NULL,
                        request_count INTEGER NOT NULL,
                        PRIMARY KEY(product_id, environment, minute_epoch)
                    );
                    """
                )
            self._reconcile_index_unlocked()

    def admit_ingest(self, *, product_id: str, environment: str, limit_per_minute: int) -> bool:
        """Atomically enforce a product-scoped, store-shared ingestion limit."""

        if limit_per_minute < 1:
            raise ValueError("limit_per_minute must be positive")
        minute_epoch = int(datetime.now(UTC).timestamp()) // 60
        with self._exclusive_store_lock(), self._connect() as connection:
            connection.execute(
                "DELETE FROM ingest_rate WHERE minute_epoch < ?", (minute_epoch - 2,)
            )
            current = connection.execute(
                """SELECT request_count FROM ingest_rate
                   WHERE product_id = ? AND environment = ? AND minute_epoch = ?""",
                (product_id, environment, minute_epoch),
            ).fetchone()
            if current is not None and current[0] >= limit_per_minute:
                return False
            connection.execute(
                """INSERT INTO ingest_rate(product_id, environment, minute_epoch, request_count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(product_id, environment, minute_epoch)
                   DO UPDATE SET request_count = request_count + 1""",
                (product_id, environment, minute_epoch),
            )
        return True

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
        return canonical_run_line(run)

    def _truncate_log(self, byte_offset: int) -> None:
        """Durably roll the canonical log back to a known record boundary."""

        with self.log_path.open("r+b") as handle:
            handle.truncate(byte_offset)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _canonical_record(record: object) -> bytes:
        payload = record.model_dump(mode="json")  # type: ignore[attr-defined]
        return (
            json.dumps(payload, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()

    def _append_auxiliary_record(
        self,
        path: Path,
        *,
        identity_field: str,
        identity: str,
        record: object,
    ) -> bool:
        line = self._canonical_record(record)
        with self._exclusive_store_lock():
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValueError("auxiliary monitoring ledger exceeds the 50 MB safety limit")
            kind = "receipt" if path == self.receipt_path else "adjudication"
            for existing_line in self._reconcile_auxiliary_unlocked(path, kind):
                payload = json.loads(existing_line)
                if payload.get(identity_field) != identity:
                    continue
                if existing_line != line:
                    raise ValueError(f"{identity_field} already exists with different evidence")
                return False
            with path.open("ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        return True

    def append_receipt(self, receipt: RunReceipt) -> bool:
        receipt = RunReceipt.model_validate(receipt.model_dump(mode="python"))
        if receipt.observed_at > datetime.now(UTC) + MAX_FUTURE_CLOCK_SKEW:
            raise FutureObservationError("observed_at exceeds the allowed five-minute clock skew")
        return self._append_auxiliary_record(
            self.receipt_path,
            identity_field="receipt_id",
            identity=receipt.receipt_id,
            record=receipt,
        )

    def list_receipts(self) -> list[RunReceipt]:
        with self._exclusive_store_lock():
            return [
                RunReceipt.model_validate_json(line)
                for line in self._reconcile_auxiliary_unlocked(self.receipt_path, "receipt")
                if line.strip()
            ]

    def append_adjudication(self, record: AdjudicationRecord) -> bool:
        record = AdjudicationRecord.model_validate(record.model_dump(mode="python"))
        if record.adjudicated_at > datetime.now(UTC) + MAX_FUTURE_CLOCK_SKEW:
            raise FutureObservationError(
                "adjudicated_at exceeds the allowed five-minute clock skew"
            )
        return self._append_auxiliary_record(
            self.adjudication_path,
            identity_field="adjudication_id",
            identity=record.adjudication_id,
            record=record,
        )

    def list_adjudications(self) -> list[AdjudicationRecord]:
        with self._exclusive_store_lock():
            return [
                self._parse_adjudication_line(line)
                for line in self._reconcile_auxiliary_unlocked(
                    self.adjudication_path, "adjudication"
                )
                if line.strip()
            ]

    def append(self, run: RunEnvelope) -> bool:
        """Append one immutable run. Return False for an exact duplicate.

        Reusing a run identity with different bytes is rejected rather than
        silently replacing history.
        """

        # Revalidate model instances so callers cannot persist values introduced
        # through Pydantic's non-validating assignment/model-copy escape hatches.
        run = RunEnvelope.model_validate(run.model_dump(mode="python"))
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
                    if run.observed_at > datetime.now(UTC) + MAX_FUTURE_CLOCK_SKEW:
                        raise FutureObservationError(
                            "observed_at exceeds the allowed five-minute clock skew"
                        )
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
                    "SELECT byte_offset, byte_length, sha256 "
                    "FROM runs ORDER BY observed_at, byte_offset"
                ).fetchall()
            return self._read_rows(rows)

    def get_run(
        self,
        *,
        product_id: str,
        environment: str,
        run_id: str,
    ) -> RunEnvelope | None:
        """Load one exact stored identity after reconciling and checking its evidence."""

        with self._exclusive_store_lock():
            return self._get_run_unlocked(
                product_id=product_id,
                environment=environment,
                run_id=run_id,
            )

    def _get_run_unlocked(
        self, *, product_id: str, environment: str, run_id: str
    ) -> RunEnvelope | None:
        self._reconcile_index_unlocked()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT byte_offset, byte_length, sha256
                FROM runs
                WHERE product_id = ? AND environment = ? AND run_id = ?
                """,
                (product_id, environment, run_id),
            ).fetchone()
        return self._read_rows([row])[0] if row is not None else None

    def get_run_digest(
        self,
        *,
        product_id: str,
        environment: str,
        run_id: str,
    ) -> str | None:
        with self._exclusive_store_lock():
            self._reconcile_index_unlocked()
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT sha256 FROM runs WHERE product_id = ? AND environment = ? "
                    "AND run_id = ?",
                    (product_id, environment, run_id),
                ).fetchone()
            return f"sha256:{row[0]}" if row is not None else None

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
                               ORDER BY observed_at DESC, byte_offset DESC
                           ) AS recency_rank
                    FROM runs
                )
                SELECT byte_offset, byte_length, sha256
                FROM ranked
                WHERE recency_rank <= ?
                ORDER BY observed_at, product_id, environment, byte_offset
                """,
                (trend_limit_per_product,),
            ).fetchall()
        trend_runs = self._read_rows(trend_rows)
        selected_identities: set[tuple[str, str, str]] = set()
        for run in trend_runs:
            product_identity = (run.product.id, run.product.environment)
            run_identity = (*product_identity, run.run_id)
            selected_identities.add(run_identity)

        comparison_rows: list[tuple[int, int, str]] = []
        seen_comparisons: set[tuple[str, str, str]] = set()
        with self._connect() as connection:
            for run in trend_runs:
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

        comparison_runs = self._read_rows(comparison_rows)
        combined = {
            (run.product.id, run.product.environment, run.run_id): (run, row[0])
            for run, row in [
                *zip(trend_runs, trend_rows, strict=True),
                *zip(comparison_runs, comparison_rows, strict=True),
            ]
        }
        return [
            run
            for run, _ in sorted(
                combined.values(),
                key=lambda item: (
                    item[0].observed_at,
                    item[0].product.id,
                    item[0].product.environment,
                    item[1],
                ),
            )
        ]
