"""Read-only collection runs outside the product's generation process."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .binding import EnvelopeBinder
from .cli import load_envelope, queue_run, write_private
from .models import RunEnvelope


def collect_exports(directory: Path, settings: Path | None, outbox: Path) -> dict[str, int]:
    result = {"queued": 0, "invalid": 0, "incomplete": 0}
    for path in sorted(directory.glob("*.normalized.json")):
        try:
            if path.is_symlink():
                raise ValueError("export must not be a symlink")
            queue_run(outbox, load_envelope(path, settings))
            result["queued"] += 1
        except (ValueError, OSError):
            result["invalid"] += 1
    return result


def collect_linkedin(
    repo: Path, context_path: Path, settings: Path, outbox: Path
) -> dict[str, int]:
    """Export only folders with a completed HTML/JSON set; never call drafting.

    The operator supplies version labels. Per-run comparison identities may be
    provided in monitoring-identity.json; a shared template may not impose a case
    identity across unrelated inputs.
    """
    result = {"queued": 0, "invalid": 0, "incomplete": 0}
    if context_path.stat().st_size > 64 * 1024:
        raise ValueError("context template exceeds the size limit")
    template = json.loads(context_path.read_bytes())
    if not isinstance(template, dict):
        raise TypeError("context template must be an object")
    if {"case_id", "input_fingerprint", "comparison_sha256"} & set(template):
        raise ValueError(
            "put comparison identity in the individual run folder, not the shared template"
        )
    repo = repo.resolve()
    private = repo / "data" / "private"
    collected: list[RunEnvelope] = []
    for html in sorted(private.glob("**/eval-dashboard.html")):
        folder = html.parent
        try:
            run_file = folder / "run-dashboard.json"
            if run_file.is_symlink() or run_file.stat().st_size > 5 * 1024 * 1024:
                raise TypeError("invalid run dashboard")
            run = json.loads(run_file.read_bytes())
            if not isinstance(run, dict):
                raise TypeError("invalid run dashboard")
            if run.get("outcome") not in {"PASS", "FAIL", "BLOCKED", "COMPLETED_WITH_WARNINGS"}:
                result["incomplete"] += 1
                continue
            run_id = run.get("run_id")
            if (
                not isinstance(run_id, str)
                or not run_id
                or any(
                    c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                    for c in run_id
                )
            ):
                raise ValueError("invalid run identifier")
            observed = datetime.fromtimestamp(run_file.stat().st_mtime, UTC).isoformat()
            context = dict(
                template, run_id=run_id, observed_at=observed, since=observed, through=observed
            )
            identity = folder / "monitoring-identity.json"
            if identity.exists():
                if identity.is_symlink() or identity.stat().st_size > 64 * 1024:
                    raise ValueError("invalid per-run identity")
                identity_data = json.loads(identity.read_bytes())
                if not isinstance(identity_data, dict) or set(identity_data) - {
                    "case_id",
                    "input_fingerprint",
                    "comparison_run_id",
                    "comparison_sha256",
                }:
                    raise ValueError("invalid per-run identity fields")
                context.update(identity_data)
            context_file = folder / "monitoring-export-context.json"
            encoded = (json.dumps(context, sort_keys=True, indent=2) + "\n").encode()
            if not context_file.exists():
                write_private(context_file, encoded)
            elif context_file.is_symlink() or context_file.read_bytes() != encoded:
                raise ValueError("completed run context changed; review it before re-export")
            exported = private / "v1-evals" / f"monitoring-dashboard-v2-{run_id}.normalized.json"
            if not exported.exists():
                completed = subprocess.run(
                    [
                        str(repo / "bin" / "linkedin-os"),
                        "export-monitoring",
                        "--context",
                        str(context_file),
                        "--run-folder",
                        str(folder),
                        "--allow-monitoring-export",
                    ],
                    cwd=repo,
                    capture_output=True,
                    timeout=30,
                    check=False,
                    env={**os.environ, "CI": "1"},
                )
                if completed.returncode != 0:
                    raise ValueError("local export failed; native run is untouched")
            envelope = load_envelope(exported, settings)
            if envelope.run_id != run_id:
                raise ValueError("export belongs to another run")
            eval_file = folder / "eval-dashboard.json"
            if eval_file.is_symlink() or eval_file.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("invalid eval dashboard")
            evaluation = json.loads(eval_file.read_bytes())
            snapshot = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps([run, evaluation], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            )
            if not any(
                f.contract == "dashboard_snapshot"
                and any(e.sha256 == snapshot for e in f.evidence_refs)
                for f in envelope.source_facts
            ):
                raise ValueError("export does not match the completed native dashboards")
            collected.append(envelope)
        except (ValueError, TypeError, OSError, subprocess.TimeoutExpired):
            result["invalid"] += 1

    # Resolve against fully bound envelopes, not raw exports: B's baseline
    # binding is part of the B digest that C must reference.
    def load_named(run_id: str) -> RunEnvelope | None:
        if any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
            for c in run_id
        ):
            raise ValueError("invalid baseline identifier")
        path = private / "v1-evals" / f"monitoring-dashboard-v2-{run_id}.normalized.json"
        return load_envelope(path, settings) if path.exists() else None

    binder = EnvelopeBinder(outbox, load_named)
    for envelope in collected:
        try:
            queue_run(outbox, binder.bind(envelope))
            result["queued"] += 1
        except (ValueError, OSError):
            result["invalid"] += 1
    return result
