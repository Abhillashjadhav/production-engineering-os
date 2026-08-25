"""Fail closed unless GitHub exposes a clean Codex advisory result for this PR head."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

BOT = "chatgpt-codex-connector[bot]"
REVIEW_MARKER = "### 💡 Codex Review"


def _gh(*args: str) -> Any:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _all_issue_comments(repository: str, number: str) -> list[dict[str, Any]]:
    """Fetch every REST page: Codex's clean advisory can be on any page."""
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        current = _gh(
            "api",
            f"repos/{repository}/issues/{number}/comments?per_page=100&page={page}",
        )
        comments.extend(current)
        if len(current) < 100:
            return comments
        page += 1


def _all_reviews(repository: str, number: str) -> list[dict[str, Any]]:
    """Fetch every REST page: exact-head Codex reviews are authoritative evidence."""
    reviews: list[dict[str, Any]] = []
    page = 1
    while True:
        current = _gh(
            "api",
            f"repos/{repository}/pulls/{number}/reviews?per_page=100&page={page}",
        )
        reviews.extend(current)
        if len(current) < 100:
            return reviews
        page += 1


def _all_thread_comments(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch all comments in one review thread before treating it as clean."""
    comments = list(thread["comments"]["nodes"])
    page_info = thread["comments"].get("pageInfo", {"hasNextPage": False})
    while page_info["hasNextPage"]:
        query = (
            "query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread"
            "{comments(first:100,after:$after){nodes{id author{login} body updatedAt}"
            "pageInfo{hasNextPage endCursor}}}}}"
        )
        result = _gh(
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"id={thread['id']}",
            "-F",
            f"after={page_info['endCursor']}",
        )["data"]["node"]["comments"]
        comments.extend(result["nodes"])
        page_info = result["pageInfo"]
    return comments


def _all_review_threads(repository: str, number: str) -> list[dict[str, Any]]:
    """Follow GraphQL cursors so later Codex blockers cannot be hidden."""
    owner, name = repository.split("/", 1)
    cursor: str | None = None
    threads: list[dict[str, Any]] = []
    query = (
        "query($owner:String!,$name:String!,$number:Int!,$after:String){repository("
        "owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,"
        "after:$after){nodes{id isOutdated isResolved comments(first:100){"
        "nodes{id author{login} body updatedAt}"
        "pageInfo{hasNextPage endCursor}}}pageInfo{hasNextPage endCursor}}}}}"
    )
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor is not None:
            args.extend(("-F", f"after={cursor}"))
        result = _gh(*args)["data"]["repository"]["pullRequest"]["reviewThreads"]
        for raw_thread in result["nodes"]:
            thread = dict(raw_thread)
            thread["comments"] = {"nodes": _all_thread_comments(raw_thread)}
            threads.append(thread)
        page_info = result["pageInfo"]
        if not page_info["hasNextPage"]:
            return threads
        cursor = page_info["endCursor"]


def _has_current_blocker(threads: list[dict[str, Any]]) -> bool:
    for thread in threads:
        if thread["isOutdated"] or thread["isResolved"]:
            continue
        for comment in thread["comments"]["nodes"]:
            if (
                comment["author"]
                and comment["author"]["login"] == BOT
                and any(badge in comment["body"] for badge in ("P0 Badge", "P1 Badge", "P2 Badge"))
            ):
                return True
    return False


def _comment_matches_exact_head(repository: str, expected: str, body: str) -> bool:
    """Accept a short reviewed SHA only when GitHub resolves it to this full head."""
    if f"**Reviewed commit:** `{expected}`" in body:
        return True
    short = expected[:10]
    if f"**Reviewed commit:** `{short}`" not in body:
        return False
    resolved = _gh("api", f"repos/{repository}/commits/{short}")
    resolved_sha = resolved.get("sha")
    return isinstance(resolved_sha, str) and resolved_sha == expected


def _has_exact_bot_review(reviews: list[dict[str, Any]], expected: str) -> bool:
    """A GitHub PR review is clean evidence when it is bot-authored and exact-head bound.

    Findings are independently rejected from the complete current thread set below.
    """
    exact = [
        review
        for review in reviews
        if (review.get("user") or {}).get("login") == BOT
        and review.get("commit_id") == expected
        and review.get("state") in {"COMMENTED", "APPROVED"}
        and REVIEW_MARKER in (review.get("body") or "")
    ]
    return bool(exact) and not _has_exact_bot_review_blocker(reviews, expected)


def _has_exact_bot_review_blocker(reviews: list[dict[str, Any]], expected: str) -> bool:
    """A top-level finding blocks even when separate clean evidence exists."""
    blockers = ("P0 Badge", "P1 Badge", "P2 Badge")
    return any(
        (review.get("user") or {}).get("login") == BOT
        and review.get("commit_id") == expected
        and any(badge in (review.get("body") or "") for badge in blockers)
        for review in reviews
    )


def _review_snapshot_ids(reviews: list[dict[str, Any]]) -> tuple[str, ...]:
    """Bind review identity and mutable admission-relevant content."""
    return tuple(
        sorted(json.dumps(review, sort_keys=True, separators=(",", ":")) for review in reviews)
    )


def _surface_snapshot(
    comments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    threads: list[dict[str, Any]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Give all three GitHub review surfaces one deterministic observation identity."""

    def identities(records: list[dict[str, Any]]) -> tuple[str, ...]:
        return tuple(
            sorted(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records)
        )

    return identities(comments), _review_snapshot_ids(reviews), identities(threads)


def _has_clean_evidence(
    repository: str,
    expected: str,
    comments: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> bool:
    clean_comment = any(
        (comment.get("user") or {}).get("login") == BOT
        and "Codex Review: Didn't find any major issues." in (comment.get("body") or "")
        and _comment_matches_exact_head(repository, expected, comment.get("body") or "")
        for comment in comments
    )
    return (clean_comment or _has_exact_bot_review(reviews, expected)) and not (
        _has_exact_bot_review_blocker(reviews, expected)
    )


def main() -> int:
    expected = os.environ["EXPECTED_HEAD"]
    number = os.environ["PR_NUMBER"]
    repository = os.environ["GITHUB_REPOSITORY"]
    deadline = time.monotonic() + int(os.environ.get("CODEX_EVIDENCE_WAIT_SECONDS", "0"))
    while True:
        pr = _gh("api", f"repos/{repository}/pulls/{number}")
        if pr["head"]["sha"] != expected:
            raise SystemExit("current PR head changed during Codex evidence verification")
        comments = _all_issue_comments(repository, number)
        reviews = _all_reviews(repository, number)
        if _has_clean_evidence(repository, expected, comments, reviews):
            break
        if time.monotonic() >= deadline:
            raise SystemExit("missing clean exact-head Codex advisory evidence")
        time.sleep(10)
    # GitHub may expose a review object before its inline threads. Require a
    # full quiescence window, resetting it whenever any review surface changes.
    stability_window = max(0, int(os.environ.get("CODEX_EVIDENCE_STABILITY_SECONDS", "60")))
    poll_interval = max(0, int(os.environ.get("CODEX_EVIDENCE_POLL_SECONDS", "10")))
    stability_deadline = time.monotonic() + max(
        stability_window,
        int(os.environ.get("CODEX_EVIDENCE_STABILITY_TIMEOUT_SECONDS", "180")),
    )
    previous_snapshot: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None = None
    stable_since: float | None = None
    while True:
        comments = _all_issue_comments(repository, number)
        reviews = _all_reviews(repository, number)
        threads = _all_review_threads(repository, number)
        if _has_current_blocker(threads) or _has_exact_bot_review_blocker(reviews, expected):
            raise SystemExit("current Codex P0/P1/P2 finding blocks admission")
        if not _has_clean_evidence(repository, expected, comments, reviews):
            raise SystemExit("clean exact-head Codex evidence disappeared during stabilization")
        snapshot = _surface_snapshot(comments, reviews, threads)
        observed_at = time.monotonic()
        if previous_snapshot == snapshot:
            if stable_since is not None and observed_at - stable_since >= stability_window:
                break
        else:
            previous_snapshot = snapshot
            stable_since = observed_at
        if observed_at >= stability_deadline:
            raise SystemExit("Codex review surfaces did not stabilize before timeout")
        assert stable_since is not None
        remaining_window = stability_window - (observed_at - stable_since)
        remaining_deadline = stability_deadline - observed_at
        time.sleep(max(0, min(poll_interval, remaining_window, remaining_deadline)))

    final_pr = _gh("api", f"repos/{repository}/pulls/{number}")
    if final_pr["head"]["sha"] != expected:
        raise SystemExit("current PR head changed during Codex evidence verification")
    print(f"CODEX ADVISORY REVIEW — CLEAN — EXACT HEAD {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
