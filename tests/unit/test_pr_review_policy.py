"""Issue #122: exact-head review evidence is mandatory before release readiness."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pull_request_template_requires_exact_head_review_evidence() -> None:
    template = (ROOT / ".github" / "pull_request_template.md").read_text()

    assert "Current head SHA recorded" in template
    assert "PR Review Agent / review" in template
    assert "No unresolved current P0/P1/P2" in template
    assert "Named human release owner" in template


def test_review_policy_names_required_check_and_pr117_regression() -> None:
    policy = (ROOT / "docs" / "pull-request-review-policy.md").read_text()

    assert "PR Review Agent / review" in policy
    assert "PR #117" in policy
    assert "green CI plus zero reviews" in policy
    assert "REVIEW_REQUIRED" in policy


def test_trusted_review_workflow_still_fails_closed_on_missing_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pr-review.yml").read_text()

    assert "pull_request_target:" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "Verify Codex exact-head evidence" in workflow
    assert "scripts/verify_codex_review.py" in workflow
    assert "if: github.event.pull_request.draft == false" not in workflow
    assert "Refuse skipped review admission" in workflow
    assert "HEAD_REPOSITORY" in workflow
