"""Bounded no-follow reads for an untrusted product package directory."""

from __future__ import annotations

import os
import stat
from pathlib import Path

_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_TOTAL_BYTES = 24 * 1024 * 1024
_MAX_MANIFEST_BYTES = 512 * 1024
_MAX_BUNDLE_ENTRIES = 1500
_MAX_PATH_DEPTH = 32


class ProductPackageError(ValueError):
    """Package input or exact-artifact evidence is invalid."""


def _read_bundle_files(bundle: Path) -> dict[str, bytes]:
    """Read bounded regular files beneath no-follow directory descriptors.

    O_NONBLOCK makes a swapped-in FIFO safe before fstat rejects it. Each child
    opens relative to its parent descriptor, so changing a directory to a
    symlink cannot redirect a later source read elsewhere.
    """

    files: dict[str, bytes] = {}
    total = 0
    entries = 0
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC

    def scan(directory_fd: int, prefix: str, depth: int) -> None:
        nonlocal total, entries
        if depth > _MAX_PATH_DEPTH:
            raise ProductPackageError("package directory depth exceeds limit")
        with os.scandir(directory_fd) as children:
            for child in children:
                entries += 1
                if entries > _MAX_BUNDLE_ENTRIES:
                    raise ProductPackageError("package entry count exceeds limit")
                relative = f"{prefix}{child.name}"
                descriptor = os.open(child.name, flags, dir_fd=directory_fd)
                try:
                    mode = os.fstat(descriptor).st_mode
                    if stat.S_ISDIR(mode):
                        scan(descriptor, relative + "/", depth + 1)
                    elif stat.S_ISREG(mode):
                        limit = (
                            _MAX_MANIFEST_BYTES
                            if relative == "product-package.json"
                            else _MAX_FILE_BYTES
                        )
                        size = os.fstat(descriptor).st_size
                        remaining = _MAX_TOTAL_BYTES + _MAX_MANIFEST_BYTES - total
                        if size > limit or size > remaining:
                            raise ProductPackageError("package file exceeds size limit")
                        allowed = min(limit, remaining)
                        content = bytearray()
                        while len(content) <= allowed:
                            chunk = os.read(descriptor, min(65536, allowed + 1 - len(content)))
                            if not chunk:
                                break
                            content.extend(chunk)
                        if len(content) > allowed:
                            raise ProductPackageError("package file exceeds size limit")
                        total += len(content)
                        files[relative] = bytes(content)
                    else:
                        raise ProductPackageError("package contains unsupported filesystem entry")
                finally:
                    os.close(descriptor)

    try:
        directory_fd = os.open(bundle, flags | os.O_DIRECTORY)
        try:
            scan(directory_fd, "", 0)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ProductPackageError("package contains unsupported filesystem entry") from exc
    return files
