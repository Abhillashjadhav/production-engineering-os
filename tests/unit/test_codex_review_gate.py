import importlib.util
from pathlib import Path

import pytest

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


@pytest.fixture()
def verifier_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "verify_codex_review.py"
    spec = importlib.util.spec_from_file_location("verify_codex_review", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_issue_comments_finds_exact_codex_evidence_on_later_rest_page(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    calls: list[tuple[str, ...]] = []
    first_page = [{"id": index} for index in range(100)]
    exact_bot_comment = {"user": {"login": verifier_module.BOT}, "body": "review"}

    def fake_gh(*args: str):
        calls.append(args)
        if args[-1].endswith("page=1"):
            return first_page
        if args[-1].endswith("page=2"):
            return [exact_bot_comment]
        raise AssertionError(args)

    monkeypatch.setattr(verifier_module, "_gh", fake_gh)

    assert verifier_module._all_issue_comments("owner/repo", "99") == first_page + [
        exact_bot_comment
    ]
    assert [call[-1] for call in calls] == [
        "repos/owner/repo/issues/99/comments?per_page=100&page=1",
        "repos/owner/repo/issues/99/comments?per_page=100&page=2",
    ]


def test_all_review_threads_finds_blocker_on_later_graphql_page(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    calls: list[tuple[str, ...]] = []
    first_page = {
        "nodes": [{"id": "thread-a", "isOutdated": False, "comments": {"nodes": []}}],
        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-a"},
    }
    p1_thread = {
        "id": "thread-b",
        "isOutdated": False,
        "comments": {
            "nodes": [
                {
                    "author": {"login": verifier_module.BOT},
                    "body": "![P1 Badge] blocker",
                }
            ]
        },
    }
    second_page = {
        "nodes": [p1_thread],
        "pageInfo": {"hasNextPage": False, "endCursor": None},
    }

    def fake_gh(*args: str):
        calls.append(args)
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": second_page if "after=cursor-a" in args else first_page
                    }
                }
            }
        }

    monkeypatch.setattr(verifier_module, "_gh", fake_gh)

    threads = verifier_module._all_review_threads("owner/repo", "99")

    assert threads == first_page["nodes"] + second_page["nodes"]
    assert any("after=cursor-a" in call for call in calls)


def test_all_thread_comments_finds_blocker_on_later_graphql_page(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    first_page = [{"author": None, "body": "informational"} for _ in range(100)]
    blocker = {
        "author": {"login": verifier_module.BOT},
        "body": "![P2 Badge] must block admission",
    }
    thread = {
        "id": "thread-a",
        "comments": {
            "nodes": first_page,
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-a"},
        },
    }

    def fake_gh(*args: str):
        assert "id=thread-a" in args
        assert "after=cursor-a" in args
        return {
            "data": {
                "node": {
                    "comments": {
                        "nodes": [blocker],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }

    monkeypatch.setattr(verifier_module, "_gh", fake_gh)

    assert verifier_module._all_thread_comments(thread) == first_page + [blocker]
