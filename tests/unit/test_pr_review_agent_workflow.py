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

    assert "types: [opened, synchronize, reopened, ready_for_review]" in workflow
    assert "contents: read" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "group: pr-review-${{ github.event.pull_request.number }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "EXPECTED_HEAD: ${{ github.event.pull_request.head.sha }}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"' in workflow


def test_review_agent_cannot_mutate_the_candidate_or_publish_for_a_stale_head() -> None:
    workflow = WORKFLOW.read_text()

    assert "group: pr-review-${{ github.event.pull_request.number }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "contents: read" in workflow
    assert "Verify current PR head before review" in workflow
    assert 'test "$CURRENT_HEAD" = "$EXPECTED_HEAD"' in workflow
    assert "mcp__github_file_ops__commit_files" not in workflow
    assert "Read,Glob,Grep,LS" in workflow


def test_review_command_proposes_fixes_without_committing_to_the_candidate() -> None:
    command = (
        Path(__file__).resolve().parents[2] / ".claude" / "commands" / "review-pr.md"
    ).read_text()

    assert "Do NOT commit fixes, audit files, or lessons to the\nreviewed PR branch." in command
    assert "mcp__github_file_ops__commit_files" not in command


def test_reviewer_prd_requires_governed_corrections_not_reviewer_commits() -> None:
    prd = (
        Path(__file__).resolve().parents[2] / "prds" / "2026-05-24-pr-review-agent.md"
    ).read_text()

    assert "Independent read-only review" in prd
    assert "Never mutates the reviewed PR branch" in prd
    assert "writer commits fixes directly to the PR branch" not in prd
