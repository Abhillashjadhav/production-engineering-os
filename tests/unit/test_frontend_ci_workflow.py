"""Static policy tests for the stable product-frontend GitHub Actions job."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
APPLICABLE_LABEL = "APPLICABLE — full frontend security and validation suite executed"
NOT_APPLICABLE_LABEL = "NOT APPLICABLE — no frontend-affecting paths changed"
FULL_SUITE_CONDITION = (
    "steps.frontend-paths.outcome != 'success' || "
    "steps.frontend-paths.outputs.applicable != 'false'"
)


def test_workflow_keeps_stable_job_and_all_frontend_gates() -> None:
    workflow = CI_WORKFLOW.read_text()
    assert "\n  product-frontend:\n" in workflow
    assert "npm ci" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "npm run generate:api-types" in workflow
    assert "git diff --exit-code src/lib/api-types" in workflow
    assert "npx tsc --noEmit" in workflow
    assert "npx vitest run" in workflow
    assert "npm run build" in workflow
    assert workflow.count(FULL_SUITE_CONDITION) == 7


def test_workflow_always_starts_classifier_and_reports_exact_decision() -> None:
    workflow = CI_WORKFLOW.read_text()
    assert "fetch-depth: 0" in workflow
    assert "scripts/ci/classify_frontend_ci.py" in workflow
    assert "continue-on-error: true" in workflow
    assert APPLICABLE_LABEL in workflow
    assert NOT_APPLICABLE_LABEL in workflow
    assert "paths-ignore:" not in workflow


def test_workflow_has_daily_fail_closed_security_schedule() -> None:
    workflow = CI_WORKFLOW.read_text()
    assert "\n  schedule:\n" in workflow
    assert 'cron: "23 3 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
