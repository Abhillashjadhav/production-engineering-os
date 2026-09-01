"""Durable product-side outbox for monitoring receipts and run envelopes."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.client import HTTPMessage
from pathlib import Path
from typing import IO

MAX_OUTBOX_ITEM_BYTES = 5 * 1024 * 1024
MAX_SENT_MARKERS = 10_000
_SENT_MARKER_VERSION = "0.1"
_TEMPORARY_ITEM = re.compile(r"^\.[0-9a-f]{64}\.[0-9a-f]{16}\.tmp$")
_SHARED_OUTBOX_ROOTS = frozenset(
    path.resolve(strict=False) for path in (Path("/private/tmp"), Path("/var/tmp"))
)


def canonical_outbox_identity(kind: str, *components: str) -> str:
    """Return an injective identity for a typed outbox item."""
    return json.dumps([kind, *components], ensure_ascii=False, separators=(",", ":"))


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> None:
        return None


def http_post_sender(base_url: str, token: str) -> Callable[[str, dict[str, object]], None]:
    """Build a sender that acknowledges only a direct 2xx ingestion response."""
    opener = urllib.request.build_opener(_RejectRedirects())

    def send(route: str, payload: dict[str, object]) -> None:
        request = urllib.request.Request(
            base_url.rstrip("/") + route,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with opener.open(request, timeout=30) as response:
                if response.status // 100 != 2:
                    raise RuntimeError(f"monitoring delivery failed with HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(
                "monitoring delivery failed; evidence remains in the outbox"
            ) from exc

    return send


def _validate_outbox_root(outbox_dir: Path) -> None:
    resolved = outbox_dir.resolve(strict=False)
    if resolved == Path("/") or resolved.parent == Path("/") or resolved in _SHARED_OUTBOX_ROOTS:
        raise ValueError("monitoring outbox must not use a shared system root")
    if not outbox_dir.exists():
        return
    if outbox_dir.is_symlink() or not outbox_dir.is_dir():
        raise ValueError("monitoring outbox must be a real directory")
    directory_stat = outbox_dir.stat(follow_symlinks=False)
    if directory_stat.st_uid != os.getuid() or stat.S_IMODE(directory_stat.st_mode) != 0o700:
        raise ValueError("existing monitoring outbox must be owner-only mode 0700")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sent_marker(data: bytes) -> bytes:
    marker = {
        "evidence_sha256": hashlib.sha256(data).hexdigest(),
        "outbox_sent_version": _SENT_MARKER_VERSION,
    }
    return (json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sent_matches(path: Path, data: bytes) -> bool:
    stored = _read_private_file(path)
    if stored == data:
        return True
    try:
        marker = json.loads(stored)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return (
        isinstance(marker, dict)
        and set(marker) == {"evidence_sha256", "outbox_sent_version"}
        and marker.get("outbox_sent_version") == _SENT_MARKER_VERSION
        and marker.get("evidence_sha256") == hashlib.sha256(data).hexdigest()
    )


def _read_private_file(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("monitoring outbox item must be a regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > MAX_OUTBOX_ITEM_BYTES:
                raise ValueError("monitoring outbox item exceeds the 5 MB limit")
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


def _publish_sent_marker(
    outbox_dir: Path, pending_path: Path, sent_path: Path, data: bytes
) -> None:
    marker = _sent_marker(data)
    digest = pending_path.name.split(".", 1)[0]
    temporary = outbox_dir / f".{digest}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        try:
            view = memoryview(marker)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short outbox marker write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, sent_path)
        pending_path.unlink()
    finally:
        temporary.unlink(missing_ok=True)
        _fsync_directory(outbox_dir)


def _prune_sent_markers(outbox_dir: Path) -> None:
    markers = sorted(
        outbox_dir.glob("*.sent.json"),
        key=lambda path: (path.stat(follow_symlinks=False).st_mtime_ns, path.name),
    )
    removed = False
    for path in markers[:-MAX_SENT_MARKERS]:
        if path.is_symlink() or not path.is_file():
            raise ValueError("monitoring outbox sent marker must be a regular file")
        path.unlink()
        removed = True
    if removed:
        _fsync_directory(outbox_dir)


def _reconcile_temporary_items(outbox_dir: Path) -> None:
    removed = False
    for path in outbox_dir.iterdir():
        if _TEMPORARY_ITEM.fullmatch(path.name):
            path.unlink(missing_ok=True)
            removed = True
    if removed:
        _fsync_directory(outbox_dir)


def enqueue(outbox_dir: Path, *, route: str, identity: str, payload: object) -> Path:
    _validate_outbox_root(outbox_dir)
    missing_directories: list[Path] = []
    cursor = outbox_dir
    while not cursor.exists():
        missing_directories.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing_directories):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            _validate_outbox_root(directory)
        else:
            os.chmod(directory, 0o700)
            _fsync_directory(directory.parent)
    if not outbox_dir.exists():
        raise ValueError("monitoring outbox disappeared during initialization")
    _validate_outbox_root(outbox_dir)
    _fsync_directory(outbox_dir.parent)
    item = {"outbox_version": "0.1", "route": route, "payload": payload}
    canonical = (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(canonical) > MAX_OUTBOX_ITEM_BYTES:
        raise ValueError("monitoring outbox item exceeds the 5 MB limit")
    digest = hashlib.sha256(identity.encode()).hexdigest()
    with _exclusive_outbox_lock(outbox_dir):
        _reconcile_temporary_items(outbox_dir)
        _prune_sent_markers(outbox_dir)
        target = outbox_dir / f"{digest}.pending.json"
        sent_target = outbox_dir / f"{digest}.sent.json"
        if sent_target.exists():
            if not _sent_matches(sent_target, canonical):
                raise ValueError("outbox identity already exists with different evidence")
            if target.exists():
                if _read_private_file(target) != canonical:
                    raise ValueError("outbox identity already exists with different evidence")
                target.unlink()
                _fsync_directory(outbox_dir)
            return sent_target
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
    _validate_outbox_root(outbox_dir)
    if not outbox_dir.exists():
        return 0
    sent = 0
    with _exclusive_outbox_lock(outbox_dir):
        _reconcile_temporary_items(outbox_dir)
        _prune_sent_markers(outbox_dir)
        for path in sorted(outbox_dir.glob("*.pending.json")):
            data = _read_private_file(path)
            payload = json.loads(data)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"outbox_version", "route", "payload"}
                or payload.get("outbox_version") != "0.1"
                or not isinstance(payload.get("route"), str)
                or not isinstance(payload.get("payload"), dict)
            ):
                raise ValueError("monitoring outbox item has an invalid schema")
            sent_path = path.with_name(path.name.replace(".pending.json", ".sent.json"))
            if sent_path.exists():
                if not _sent_matches(sent_path, data):
                    raise ValueError("outbox identity already exists with different evidence")
                path.unlink()
                _fsync_directory(outbox_dir)
                continue
            sender(payload["route"], payload["payload"])
            _publish_sent_marker(outbox_dir, path, sent_path, data)
            sent += 1
        _prune_sent_markers(outbox_dir)
    return sent
