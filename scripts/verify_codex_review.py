"""Fail closed unless GitHub exposes a clean Codex advisory result for this PR head."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

BOT = "chatgpt-codex-connector[bot]"


def _gh(*args: str) -> Any:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main() -> int:
    expected = os.environ["EXPECTED_HEAD"]
    number = os.environ["PR_NUMBER"]
    repository = os.environ["GITHUB_REPOSITORY"]
    pr = _gh("api", f"repos/{repository}/pulls/{number}")
    if pr["head"]["sha"] != expected:
        raise SystemExit("current PR head changed during Codex evidence verification")
    comments = _gh("api", f"repos/{repository}/issues/{number}/comments")
    marker = f"**Reviewed commit:** `{expected[:10]}`"
    clean = any(
        comment["user"]["login"] == BOT
        and "Codex Review: Didn't find any major issues." in comment["body"]
        and marker in comment["body"]
        for comment in comments
    )
    if not clean:
        raise SystemExit("missing clean exact-head Codex advisory evidence")
    query = (
        "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name)"
        "{pullRequest(number:$number){reviewThreads(first:100){nodes{isOutdated comments(first:20)"
        "{nodes{author{login} body}}}}}}}"
    )
    threads = _gh(
        "api",
        "graphql",
        "-f",
        f"query={query}",
        "-F",
        f"owner={repository.split('/', 1)[0]}",
        "-F",
        f"name={repository.split('/', 1)[1]}",
        "-F",
        f"number={number}",
    )["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    for thread in threads:
        if thread["isOutdated"]:
            continue
        for comment in thread["comments"]["nodes"]:
            if (
                comment["author"]
                and comment["author"]["login"] == BOT
                and any(badge in comment["body"] for badge in ("P1 Badge", "P2 Badge"))
            ):
                raise SystemExit("current Codex P1/P2 finding blocks admission")
    print(f"CODEX ADVISORY REVIEW — CLEAN — EXACT HEAD {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
