"""Preview deployment evidence (PD-V3-06/14): a preview claim is believable
only when the served artifacts are bound to the exact reviewed source tree.

- ``record_preview`` writes ``preview-evidence.json`` binding the source tree
  digest (the same digest family a candidate freeze records), the artifact
  fingerprints, the deployment kind, and the journey results. Structurally
  incoherent evidence is refused and nothing is written; a FAILED journey is
  honest evidence and records fine — verification is where it blocks.
- ``verify_preview`` fails closed: no record, unreadable record, digest
  mismatch, cloud (or unknown) deployment claims, missing artifacts, and any
  journey that did not pass are all named refusals.

Cloud kinds are refused everywhere: this system never claims a cloud deploy
it cannot verify (PD-V3-14) — the seam for one is the deployment_target of
the FullStackProductContract, not this module.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

ALLOWED_PREVIEW_KINDS = ("local_preview", "containerized_preview")
_JOURNEY_RESULTS = ("passed", "failed")


class PreviewViolation(ValueError):  # noqa: N818 — deliberate: it is a violation
    """The preview evidence is structurally incoherent or dishonest."""


@dataclass(frozen=True)
class PreviewEvidence:
    source_digest: str
    deployment_kind: str
    artifacts: dict[str, str]
    journeys: dict[str, str]
    recorded_at: str


def _structural_problems(evidence: PreviewEvidence) -> list[str]:
    problems: list[str] = []
    if not evidence.source_digest.strip():
        problems.append("a preview must bind a non-empty source tree digest")
    if evidence.deployment_kind not in ALLOWED_PREVIEW_KINDS:
        problems.append(
            f"deployment kind '{evidence.deployment_kind}' is not a verifiable preview — "
            "cloud (or unknown) claims are refused; allowed: " + ", ".join(ALLOWED_PREVIEW_KINDS)
        )
    if not evidence.artifacts:
        problems.append("a preview must record at least one artifact fingerprint")
    for name, fingerprint in evidence.artifacts.items():
        if not fingerprint.strip():
            problems.append(f"artifact '{name}' has a blank fingerprint")
    if not evidence.journeys:
        problems.append("a preview must record at least one journey result")
    for name, result in evidence.journeys.items():
        if result not in _JOURNEY_RESULTS:
            problems.append(
                f"journey '{name}' result '{result}' is not in the vocabulary "
                f"({', '.join(_JOURNEY_RESULTS)}); only executed outcomes count as passed"
            )
    return problems


def record_preview(
    path: Path,
    *,
    source_digest: str,
    deployment_kind: str,
    artifacts: dict[str, str],
    journeys: dict[str, str],
    recorded_at: str,
) -> PreviewEvidence:
    """Write the evidence record, refusing structural incoherence (nothing is
    written on refusal)."""
    evidence = PreviewEvidence(
        source_digest=source_digest,
        deployment_kind=deployment_kind,
        artifacts=dict(artifacts),
        journeys=dict(journeys),
        recorded_at=recorded_at,
    )
    problems = _structural_problems(evidence)
    if problems:
        raise PreviewViolation("; ".join(problems))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n")
    return evidence


def verify_preview(path: Path, *, expected_source_digest: str) -> list[str]:
    """Named problems ([] = the preview evidence verifies against the reviewed
    tree). Every failure path is closed: absent, unreadable, mismatched,
    unallowed, or unpassed evidence never verifies."""
    path = Path(path)
    if not path.exists():
        return [f"no preview evidence at {path}"]
    try:
        data = json.loads(path.read_text())
        evidence = PreviewEvidence(
            source_digest=str(data["source_digest"]),
            deployment_kind=str(data["deployment_kind"]),
            artifacts={str(k): str(v) for k, v in dict(data["artifacts"]).items()},
            journeys={str(k): str(v) for k, v in dict(data["journeys"]).items()},
            recorded_at=str(data["recorded_at"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return [f"unreadable preview evidence at {path} — re-record it"]
    problems = _structural_problems(evidence)
    if evidence.source_digest != expected_source_digest:
        problems.append(
            "the previewed source digest does not match the reviewed tree — "
            f"previewed {evidence.source_digest[:19]}…, reviewed "
            f"{expected_source_digest[:19]}…; rebuild the preview from the reviewed tree"
        )
    for name, result in evidence.journeys.items():
        if result == "failed":
            problems.append(f"journey '{name}' failed in the preview — not releasable evidence")
    return problems
