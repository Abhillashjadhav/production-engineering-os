from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr-review.yml"


def test_workflow_is_codex_only_and_runs_the_exact_head_evidence_gate() -> None:
    workflow = WORKFLOW.read_text()

    assert "anthropics/claude-code-action" not in workflow
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in workflow
    assert "Verify Codex exact-head evidence" in workflow
    assert "scripts/verify_codex_review.py" in workflow
    assert "CODEX_EVIDENCE_WAIT_SECONDS: 180" in workflow
    assert "contents: read" in workflow
    assert "pull-requests: read" in workflow
    assert "issues: read" in workflow


def test_workflow_supersedes_stale_verifiers_and_does_not_mutate_candidates() -> None:
    workflow = WORKFLOW.read_text()

    assert "group: pr-review-${{ github.event.pull_request.number }}" in workflow
    assert "cancel-in-progress: true" in workflow
    assert 'test "$CURRENT_HEAD" = "$EXPECTED_HEAD"' in workflow
    assert "contents: write" not in workflow
    assert "commit_files" not in workflow


def test_gate_waits_boundedly_for_asynchronous_codex_evidence() -> None:
    verifier = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify_codex_review.py"
    ).read_text()

    assert "CODEX_EVIDENCE_WAIT_SECONDS" in verifier
    assert "time.monotonic()" in verifier
    assert "time.sleep(10)" in verifier
