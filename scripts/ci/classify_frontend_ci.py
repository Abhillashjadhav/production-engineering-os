#!/usr/bin/env python3
"""Fail-closed changed-path routing for the stable product-frontend CI job."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

APPLICABLE_LABEL = "APPLICABLE — full frontend security and validation suite executed"
NOT_APPLICABLE_LABEL = "NOT APPLICABLE — no frontend-affecting paths changed"

_SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")
_ALWAYS_APPLICABLE_EVENTS = frozenset({"schedule", "workflow_dispatch"})
_DIFF_EVENTS = frozenset({"pull_request", "push"})
_RELEVANT_PREFIXES = (
    "products/pm-evals-web/frontend/",
    "products/pm-evals-web/e2e/",
    "products/pm-evals-web/fixtures/",
)
_RELEVANT_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
        "products/pm-evals-web/backend/openapi.json",
        "products/pm-evals-web/backend/scripts/export_openapi.py",
        "products/pm-evals-web/docker-compose.yml",
        "products/pm-evals-web/scripts/preview.sh",
        "scripts/ci/classify_frontend_ci.py",
        "tests/unit/test_frontend_ci_classifier.py",
        "tests/unit/test_frontend_ci_workflow.py",
    }
)


@dataclass(frozen=True)
class Decision:
    """Auditable applicability decision for one workflow event."""

    applicable: bool
    reason: str
    changed_paths: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return APPLICABLE_LABEL if self.applicable else NOT_APPLICABLE_LABEL


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def _is_frontend_affecting(path: str) -> bool:
    return path in _RELEVANT_FILES or path.startswith(_RELEVANT_PREFIXES)


def classify_changed_paths(paths: Iterable[str]) -> Decision:
    """Classify an already discovered set of repository-relative changed paths."""

    changed_paths = tuple(
        sorted({_normalize_path(path) for path in paths if _normalize_path(path)})
    )
    relevant_paths = tuple(path for path in changed_paths if _is_frontend_affecting(path))
    if relevant_paths:
        return Decision(
            applicable=True,
            reason=f"frontend-affecting paths changed: {', '.join(relevant_paths)}",
            changed_paths=changed_paths,
        )
    return Decision(
        applicable=False,
        reason="no frontend-affecting paths changed",
        changed_paths=changed_paths,
    )


def _valid_sha(value: str) -> bool:
    return bool(_SHA1.fullmatch(value))


def _git_changed_paths(base_sha: str, head_sha: str, repo_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            base_sha,
            head_sha,
            "--",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return tuple(entry.decode("utf-8") for entry in result.stdout.split(b"\0") if entry)


def classify_event(
    event_name: str,
    base_sha: str,
    head_sha: str,
    repo_root: Path,
) -> Decision:
    """Classify one Actions event, failing closed for every uncertain state."""

    if event_name in _ALWAYS_APPLICABLE_EVENTS:
        return Decision(
            applicable=True,
            reason=f"{event_name} always runs the full frontend suite",
        )
    if event_name not in _DIFF_EVENTS:
        return Decision(
            applicable=True,
            reason=f"unknown event {event_name!r}; fail closed",
        )
    if event_name == "push" and base_sha == "0" * 40:
        return Decision(
            applicable=True,
            reason="push before SHA is all zeroes; fail closed",
        )
    if not _valid_sha(base_sha) or not _valid_sha(head_sha):
        return Decision(
            applicable=True,
            reason="missing or invalid comparison SHA; fail closed",
        )

    try:
        changed_paths = _git_changed_paths(base_sha, head_sha, repo_root)
        return classify_changed_paths(changed_paths)
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return Decision(
            applicable=True,
            reason=f"git comparison failed; fail closed: {type(exc).__name__}",
        )


def _single_line(value: str) -> str:
    return " ".join(value.splitlines())


def _emit(decision: Decision, github_output: Path | None) -> None:
    print(decision.label)
    print(f"Reason: {decision.reason}")
    if decision.changed_paths:
        print("Changed paths:")
        for path in decision.changed_paths:
            print(f"- {path}")
    if github_output is not None:
        with github_output.open("a", encoding="utf-8") as output:
            output.write(f"applicable={str(decision.applicable).lower()}\n")
            output.write(f"decision={decision.label}\n")
            output.write(f"reason={_single_line(decision.reason)}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        decision = classify_event(
            args.event_name,
            args.base_sha,
            args.head_sha,
            args.repo_root,
        )
        _emit(decision, args.github_output)
    except Exception as exc:
        # A script or output-channel failure must never become NOT APPLICABLE.
        print(APPLICABLE_LABEL)
        print(f"Reason: classifier error; fail closed: {type(exc).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
