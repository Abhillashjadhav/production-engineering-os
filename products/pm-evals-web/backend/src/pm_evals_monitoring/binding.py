"""Resolve explicitly selected baseline chains into immutable sent envelopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .cli import write_private
from .integration import bind_baseline
from .models import RunEnvelope, canonical_run_digest
from .outbox import _validate_outbox_root, canonical_outbox_identity


class EnvelopeBinder:
    def __init__(self, outbox: Path, loader: Callable[[str], RunEnvelope | None]):
        _validate_outbox_root(outbox)
        outbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        _validate_outbox_root(outbox)
        self.directory = outbox / "bound-envelopes"
        self.loader = loader
        self.resolving: set[tuple[str, str, str]] = set()

    def bind(self, run: RunEnvelope) -> RunEnvelope:
        identity = (run.product.id, run.product.environment, run.run_id)
        if identity in self.resolving:
            raise ValueError("baseline references form a cycle")
        key = hashlib.sha256(canonical_outbox_identity("run", *identity).encode()).hexdigest()
        target = self.directory / f"{key}.json"
        source_digest = canonical_run_digest(run)
        if target.exists():
            if target.is_symlink() or target.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("invalid cached envelope")
            cached = json.loads(target.read_bytes())
            if cached.get("source_sha256") != source_digest:
                raise ValueError("already bound run inputs changed; create a new run identity")
            result = RunEnvelope.model_validate(cached["envelope"])
            if cached.get("envelope_sha256") != canonical_run_digest(result):
                raise ValueError("cached envelope digest mismatch")
            return result
        self.resolving.add(identity)
        try:
            baseline = self.loader(run.comparison.run_id)
            bound = run
            if baseline is not None:
                bound = bind_baseline(
                    run, self.bind(baseline), stored_digest=run.comparison.sha256
                )
            record = {
                "source_sha256": source_digest,
                "envelope_sha256": canonical_run_digest(bound),
                "envelope": bound.model_dump(mode="json"),
            }
            encoded = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
            try:
                write_private(target, encoded)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != encoded:
                    raise ValueError("another worker bound different evidence") from None
            return bound
        finally:
            self.resolving.remove(identity)
