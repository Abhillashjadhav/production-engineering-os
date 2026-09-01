"""Durable product-side outbox for monitoring receipts and run envelopes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

MAX_OUTBOX_ITEM_BYTES = 5 * 1024 * 1024
_TEMPORARY_ITEM = re.compile(r"^\.[0-9a-f]{64}\.[0-9a-f]{16}\.tmp$")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_private_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("monitoring outbox item must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_outbox_lock(outbox_dir: Path) -> Iterator[None]:
    lock_path = outbox_dir / ".outbox.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("monitoring outbox lock must be a regular file")
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        _fsync_directory(outbox_dir)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reconcile_temporary_items(outbox_dir: Path) -> None:
    removed = False
    for path in outbox_dir.iterdir():
        if _TEMPORARY_ITEM.fullmatch(path.name):
            path.unlink(missing_ok=True)
            removed = True
    if removed:
        _fsync_directory(outbox_dir)


def enqueue(outbox_dir: Path, *, route: str, identity: str, payload: object) -> Path:
    missing_directories: list[Path] = []
    cursor = outbox_dir
    while not cursor.exists():
        missing_directories.append(cursor)
        cursor = cursor.parent
    outbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for directory in reversed(missing_directories):
        os.chmod(directory, 0o700)
        _fsync_directory(directory.parent)
    os.chmod(outbox_dir, 0o700)
    item = {"outbox_version": "0.1", "route": route, "payload": payload}
    canonical = (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(canonical) > MAX_OUTBOX_ITEM_BYTES:
        raise ValueError("monitoring outbox item exceeds the 5 MB limit")
    digest = hashlib.sha256(identity.encode()).hexdigest()
    with _exclusive_outbox_lock(outbox_dir):
        _reconcile_temporary_items(outbox_dir)
        target = outbox_dir / f"{digest}.pending.json"
        if target.exists():
            if _read_private_file(target) != canonical:
                raise ValueError("outbox identity already exists with different evidence")
            _fsync_directory(outbox_dir)
            return target
        temporary = outbox_dir / f".{digest}.{secrets.token_hex(8)}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            try:
                view = memoryview(canonical)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("short outbox write")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.link(temporary, target, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
            _fsync_directory(outbox_dir)
        return target


def flush(
    outbox_dir: Path,
    *,
    sender: Callable[[str, dict[str, object]], None],
) -> int:
    sent = 0
    for path in sorted(outbox_dir.glob("*.pending.json")):
        data = path.read_bytes()
        if len(data) > MAX_OUTBOX_ITEM_BYTES:
            raise ValueError("monitoring outbox item exceeds the 5 MB limit")
        payload = json.loads(data)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"outbox_version", "route", "payload"}
            or payload.get("outbox_version") != "0.1"
            or not isinstance(payload.get("route"), str)
            or not isinstance(payload.get("payload"), dict)
        ):
            raise ValueError("monitoring outbox item has an invalid schema")
        sender(payload["route"], payload["payload"])
        sent_path = path.with_name(path.name.replace(".pending.json", ".sent.json"))
        os.replace(path, sent_path)
        _fsync_directory(outbox_dir)
        sent += 1
    return sent
