"""Fail closed unless GitHub exposes a clean Codex advisory result for this PR head."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

BOT = "chatgpt-codex-connector[bot]"


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


def _all_thread_comments(thread: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch all comments in one review thread before treating it as clean."""
    comments = list(thread["comments"]["nodes"])
    page_info = thread["comments"].get("pageInfo", {"hasNextPage": False})
    while page_info["hasNextPage"]:
        query = (
            "query($id:ID!,$after:String){node(id:$id){... on PullRequestReviewThread"
            "{comments(first:100,after:$after){nodes{author{login} body}"
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
        "after:$after){nodes{id isOutdated isResolved comments(first:100){nodes{author{login} body}"
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


def main() -> int:
    expected = os.environ["EXPECTED_HEAD"]
    number = os.environ["PR_NUMBER"]
    repository = os.environ["GITHUB_REPOSITORY"]
    marker = f"**Reviewed commit:** `{expected[:10]}`"
    deadline = time.monotonic() + int(os.environ.get("CODEX_EVIDENCE_WAIT_SECONDS", "0"))
    while True:
        pr = _gh("api", f"repos/{repository}/pulls/{number}")
        if pr["head"]["sha"] != expected:
            raise SystemExit("current PR head changed during Codex evidence verification")
        comments = _all_issue_comments(repository, number)
        clean = any(
            comment["user"]["login"] == BOT
            and "Codex Review: Didn't find any major issues." in comment["body"]
            and marker in comment["body"]
            for comment in comments
        )
        if clean:
            break
        if time.monotonic() >= deadline:
            raise SystemExit("missing clean exact-head Codex advisory evidence")
        time.sleep(10)
    threads = _all_review_threads(repository, number)
    if _has_current_blocker(threads):
        raise SystemExit("current Codex P0/P1/P2 finding blocks admission")
    print(f"CODEX ADVISORY REVIEW — CLEAN — EXACT HEAD {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
