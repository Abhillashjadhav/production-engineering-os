"""File-backed artifact store for one pipeline run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pmpe.domain.serialize import jsonable


class ArtifactStore:
    """Writes artifacts under <run_dir>/artifacts and maintains an index.

    Writes are atomic (tmp + rename) so a crash never leaves a torn artifact.
    """

    def __init__(self, run_dir: Path) -> None:
        self.root = run_dir / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(path)

    def write_json(self, name: str, obj: Any) -> Path:
        path = self.root / name
        self._atomic_write(path, json.dumps(jsonable(obj), indent=2, sort_keys=True) + "\n")
        self._index(name)
        return path

    def write_text(self, name: str, content: str) -> Path:
        path = self.root / name
        self._atomic_write(path, content)
        self._index(name)
        return path

    def read_json(self, name: str) -> Any:
        return json.loads((self.root / name).read_text())

    def read_text(self, name: str) -> str:
        return (self.root / name).read_text()

    def exists(self, name: str) -> bool:
        return (self.root / name).exists()

    def _index(self, name: str) -> None:
        index_path = self.root / "index.json"
        entries: list[str] = []
        if index_path.exists():
            entries = json.loads(index_path.read_text())
        if name not in entries:
            entries.append(name)
            self._atomic_write(index_path, json.dumps(sorted(entries), indent=2) + "\n")
