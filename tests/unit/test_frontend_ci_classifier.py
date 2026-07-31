"""Deterministic tests for the monorepo frontend CI path classifier."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.ci.classify_frontend_ci import (
    APPLICABLE_LABEL,
    NOT_APPLICABLE_LABEL,
    classify_changed_paths,
    classify_event,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ci-test@localhost")
    _git(repo, "config", "user.name", "CI test")
    return repo


def _commit(repo: Path, path: str, content: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", f"change {path}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "path",
    [
        "products/pm-evals-web/frontend/src/app/page.tsx",
        "products/pm-evals-web/frontend/package.json",
        "products/pm-evals-web/frontend/package-lock.json",
        "products/pm-evals-web/frontend/src/lib/api-types.gen.ts",
        "products/pm-evals-web/frontend/Dockerfile",
        "products/pm-evals-web/e2e/tests/journey.spec.ts",
        "products/pm-evals-web/backend/openapi.json",
        "products/pm-evals-web/backend/scripts/export_openapi.py",
        "products/pm-evals-web/docker-compose.yml",
        "products/pm-evals-web/scripts/preview.sh",
        ".github/workflows/ci.yml",
        "scripts/ci/classify_frontend_ci.py",
        "tests/unit/test_frontend_ci_classifier.py",
    ],
)
def test_frontend_affecting_path_is_applicable(path: str) -> None:
    decision = classify_changed_paths([path])
    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert decision.changed_paths == (path,)


@pytest.mark.parametrize(
    "path",
    [
        "schemas/pmos_contract_bundle.schema.json",
        "src/pmpe/schemas/pmos_contract_manifest.schema.json",
        "tests/fixtures/pmos/v1/valid_bundle.json",
        "tests/unit/test_pmos_contract_schema.py",
        "products/pm-evals-web/backend/src/pm_evals_compare/report.py",
        "products/pm-evals-web/backend/tests/test_compare.py",
        "docs/TARGET-ARCHITECTURE.md",
        "README.md",
    ],
)
def test_unrelated_path_is_not_applicable(path: str) -> None:
    decision = classify_changed_paths([path])
    assert decision.applicable is False
    assert decision.label == NOT_APPLICABLE_LABEL
    assert decision.changed_paths == (path,)


@pytest.mark.parametrize("event_name", ["schedule", "workflow_dispatch"])
def test_non_diff_security_event_is_always_applicable(
    event_name: str,
    tmp_path: Path,
) -> None:
    decision = classify_event(event_name, "", "", tmp_path)
    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert event_name in decision.reason


def test_unknown_event_fails_closed(tmp_path: Path) -> None:
    decision = classify_event("repository_dispatch", "", "", tmp_path)
    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert "unknown event" in decision.reason


@pytest.mark.parametrize(
    ("event_name", "base_sha", "head_sha"),
    [
        ("pull_request", "", "a" * 40),
        ("pull_request", "a" * 40, ""),
        ("pull_request", "not-a-sha", "a" * 40),
        ("push", "", "a" * 40),
        ("push", "a" * 40, "not-a-sha"),
        ("push", "0" * 40, "a" * 40),
    ],
)
def test_missing_invalid_or_zero_comparison_data_fails_closed(
    event_name: str,
    base_sha: str,
    head_sha: str,
    tmp_path: Path,
) -> None:
    decision = classify_event(event_name, base_sha, head_sha, tmp_path)
    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert "fail closed" in decision.reason


def test_pull_request_compares_base_to_head_and_can_be_not_applicable(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    base = _commit(repo, "README.md", "base\n")
    head = _commit(repo, "schemas/pmos_contract_bundle.schema.json", "{}\n")

    decision = classify_event("pull_request", base, head, repo)

    assert decision.applicable is False
    assert decision.label == NOT_APPLICABLE_LABEL
    assert decision.changed_paths == ("schemas/pmos_contract_bundle.schema.json",)


def test_push_compares_before_to_after_and_detects_frontend_change(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    before = _commit(repo, "README.md", "base\n")
    after = _commit(repo, "products/pm-evals-web/frontend/src/app/page.tsx", "export {};\n")

    decision = classify_event("push", before, after, repo)

    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert decision.changed_paths == ("products/pm-evals-web/frontend/src/app/page.tsx",)


def test_git_error_fails_closed(tmp_path: Path) -> None:
    decision = classify_event("pull_request", "a" * 40, "b" * 40, tmp_path)
    assert decision.applicable is True
    assert decision.label == APPLICABLE_LABEL
    assert "git comparison failed" in decision.reason
