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
    assert "CODEX_EVIDENCE_WAIT_SECONDS: 300" in workflow
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


def test_workflow_executes_the_verifier_from_trusted_base_not_candidate_code() -> None:
    workflow = WORKFLOW.read_text()

    assert "pull_request_target:" in workflow
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in workflow


def test_gate_waits_boundedly_for_asynchronous_codex_evidence() -> None:
    verifier = (
        Path(__file__).resolve().parents[2] / "scripts" / "verify_codex_review.py"
    ).read_text()

    assert "CODEX_EVIDENCE_WAIT_SECONDS" in verifier
    assert "time.monotonic()" in verifier
    assert "time.sleep(10)" in verifier


def test_operator_recovery_is_codex_only_and_reenters_the_exact_head_cycle() -> None:
    documentation = (
        Path(__file__).resolve().parents[2] / "docs" / "PR-REVIEW-AGENT.md"
    ).read_text()

    assert "Codex GitHub integration availability/service capacity" in documentation
    assert "retry or re-enter the exact-head review cycle" in documentation
    assert "no reviewer secret or external credential is required" in documentation.lower()
    assert "updating the configured secret" not in documentation


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


def test_all_reviews_finds_exact_codex_review_on_later_rest_page(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    calls: list[tuple[str, ...]] = []
    first_page = [{"id": index} for index in range(100)]
    exact_review = {"user": {"login": verifier_module.BOT}, "commit_id": "a" * 40}

    def fake_gh(*args: str):
        calls.append(args)
        if args[-1].endswith("page=1"):
            return first_page
        if args[-1].endswith("page=2"):
            return [exact_review]
        raise AssertionError(args)

    monkeypatch.setattr(verifier_module, "_gh", fake_gh)

    assert verifier_module._all_reviews("owner/repo", "99") == first_page + [exact_review]
    assert [call[-1] for call in calls] == [
        "repos/owner/repo/pulls/99/reviews?per_page=100&page=1",
        "repos/owner/repo/pulls/99/reviews?per_page=100&page=2",
    ]


def test_exact_bot_review_is_clean_evidence_only_for_the_current_head(verifier_module) -> None:
    expected = "a" * 40

    assert verifier_module._has_exact_bot_review(
        [{"user": {"login": verifier_module.BOT}, "commit_id": expected}], expected
    )
    assert not verifier_module._has_exact_bot_review(
        [{"user": {"login": verifier_module.BOT}, "commit_id": "b" * 40}], expected
    )


def test_finding_bearing_top_level_bot_review_is_not_clean_evidence(verifier_module) -> None:
    expected = "a" * 40

    assert not verifier_module._has_exact_bot_review(
        [
            {
                "user": {"login": verifier_module.BOT},
                "commit_id": expected,
                "body": "![P1 Badge] blocks admission",
            }
        ],
        expected,
    )


def test_deleted_review_author_cannot_crash_exact_review_scan(verifier_module) -> None:
    expected = "a" * 40

    assert verifier_module._has_exact_bot_review(
        [
            {"user": None, "commit_id": expected, "body": ""},
            {"user": {"login": verifier_module.BOT}, "commit_id": expected, "body": ""},
        ],
        expected,
    )


def test_any_exact_head_bot_review_with_a_blocker_rejects_the_evidence_set(verifier_module) -> None:
    expected = "a" * 40
    reviews = [
        {"user": {"login": verifier_module.BOT}, "commit_id": expected, "body": ""},
        {
            "user": {"login": verifier_module.BOT},
            "commit_id": expected,
            "body": "![P1 Badge] conflicting blocker",
        },
    ]

    assert not verifier_module._has_exact_bot_review(reviews, expected)


def test_exact_head_review_body_blocker_is_detected_independently_of_clean_evidence(
    verifier_module,
) -> None:
    expected = "a" * 40

    assert verifier_module._has_exact_bot_review_blocker(
        [
            {
                "user": {"login": verifier_module.BOT},
                "commit_id": expected,
                "body": "![P2 Badge] must block even with a clean comment",
            }
        ],
        expected,
    )


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


def test_resolved_current_codex_thread_does_not_block_admission(verifier_module) -> None:
    resolved_p1 = {
        "isOutdated": False,
        "isResolved": True,
        "comments": {
            "nodes": [
                {
                    "author": {"login": verifier_module.BOT},
                    "body": "![P1 Badge] already remediated",
                }
            ]
        },
    }

    assert not verifier_module._has_current_blocker([resolved_p1])


def test_current_codex_p0_thread_blocks_admission(verifier_module) -> None:
    current_p0 = {
        "isOutdated": False,
        "isResolved": False,
        "comments": {
            "nodes": [
                {
                    "author": {"login": verifier_module.BOT},
                    "body": "![P0 Badge] release blocker",
                }
            ]
        },
    }

    assert verifier_module._has_current_blocker([current_p0])


def test_short_clean_marker_must_resolve_uniquely_to_the_full_head(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    expected = "a" * 40

    def fake_gh(*args: str):
        assert args == ("api", "repos/owner/repo/commits/aaaaaaaaaa")
        return {"sha": expected}

    monkeypatch.setattr(verifier_module, "_gh", fake_gh)

    assert verifier_module._comment_matches_exact_head(
        "owner/repo", expected, "**Reviewed commit:** `aaaaaaaaaa`"
    )


def test_short_clean_marker_for_a_different_full_head_fails_closed(
    monkeypatch: pytest.MonkeyPatch, verifier_module
) -> None:
    expected = "a" * 40

    monkeypatch.setattr(
        verifier_module,
        "_gh",
        lambda *_args: {"sha": "a" * 10 + "b" * 30},
    )

    assert not verifier_module._comment_matches_exact_head(
        "owner/repo", expected, "**Reviewed commit:** `aaaaaaaaaa`"
    )
