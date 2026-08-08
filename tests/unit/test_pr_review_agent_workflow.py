from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr-review.yml"


def test_review_agent_fails_before_invocation_when_oauth_credential_is_missing() -> None:
    workflow = WORKFLOW.read_text()

    assert "Verify reviewer credential" in workflow
    assert "CLAUDE_CODE_OAUTH_TOKEN is required" in workflow
    assert "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}" in workflow
    assert "if: github.event.pull_request.draft == false" in workflow


def test_review_agent_only_reviews_exact_non_draft_candidates() -> None:
    workflow = WORKFLOW.read_text()

    assert "types: [ready_for_review, synchronize]" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" in workflow
    assert (
        "group: pr-review-${{ github.event.pull_request.number }}-"
        "${{ github.event.pull_request.head.sha }}" in workflow
    )
    assert "EXPECTED_HEAD: ${{ github.event.pull_request.head.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"' in workflow
