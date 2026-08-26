from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "real-e1.yml"


def test_real_e1_workflow_is_manual_read_only_and_evidence_preserving() -> None:
    workflow = WORKFLOW.read_text()

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "schedule:" not in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "confirm_paid_run" in workflow
    assert "RUN_REAL_E1" in workflow

    assert "secrets.OPENAI_API_KEY" in workflow
    assert "gpt-5.6-sol" in workflow
    assert 'PMPE_OPENAI_INPUT_USD_PER_MILLION: "4"' in workflow
    assert 'PMPE_OPENAI_OUTPUT_USD_PER_MILLION: "20"' in workflow
    assert "bubblewrap util-linux" in workflow
    assert "apparmor_parser" in workflow

    assert "pmpe barebones run" in workflow
    assert "examples/barebones/openai-responses-provider.py" in workflow
    assert "pmpe barebones status" in workflow
    assert "pmpe barebones evidence" in workflow
    assert "pmpe barebones inspect" in workflow
    assert "sha256sum" in workflow

    assert "actions/upload-artifact@v4" in workflow
    assert "if: always()" in workflow
    assert "include-hidden-files: true" in workflow
    assert "if-no-files-found: error" in workflow
    assert "retention-days: 30" in workflow

    forbidden = ("git push", "gh pr merge", "pmpe legacy deploy", "kubectl", "terraform")
    assert all(command not in workflow for command in forbidden)
