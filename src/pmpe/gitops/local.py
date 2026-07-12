"""Local git adapter: a real git repository inside the build workspace.

The interface (GitAdapter) is the seam for a GitHub adapter in V2 (ADR-004).
Commits are authored by a fixed bot identity configured locally so runs are
isolated from the user's global git configuration.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pmpe.domain.errors import GitError

_BOT_NAME = "pmpe-bot"
_BOT_EMAIL = "pmpe-bot@localhost"


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str


class GitAdapter(Protocol):
    def init(self) -> None: ...

    def commit_all(self, message: str) -> str: ...

    def create_branch(self, name: str) -> None: ...

    def checkout(self, name: str) -> None: ...

    def current_branch(self) -> str: ...

    def log(self) -> list[Commit]: ...

    def diff_stat(self, base: str) -> str: ...

    def merge_to_main(self, branch: str) -> str: ...


class LocalGitAdapter:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def _run(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
                "GIT_AUTHOR_NAME": _BOT_NAME,
                "GIT_AUTHOR_EMAIL": _BOT_EMAIL,
                "GIT_COMMITTER_NAME": _BOT_NAME,
                "GIT_COMMITTER_EMAIL": _BOT_EMAIL,
                "HOME": str(self.workspace),
                "PATH": _path_env(),
            },
        )
        if proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def init(self) -> None:
        self._run("init", "--quiet", "--initial-branch=main")
        self._run("config", "user.name", _BOT_NAME)
        self._run("config", "user.email", _BOT_EMAIL)

    def commit_all(self, message: str) -> str:
        self._run("add", "-A")
        self._run("commit", "--quiet", "--no-verify", "-m", message)
        return self._run("rev-parse", "HEAD")

    def create_branch(self, name: str) -> None:
        self._run("checkout", "--quiet", "-b", name)

    def checkout(self, name: str) -> None:
        self._run("checkout", "--quiet", name)

    def current_branch(self) -> str:
        return self._run("branch", "--show-current")

    def log(self) -> list[Commit]:
        out = self._run("log", "--pretty=%H%x09%s")
        commits: list[Commit] = []
        for line in out.splitlines():
            sha, _, subject = line.partition("\t")
            commits.append(Commit(sha=sha, subject=subject))
        return commits  # newest first

    def diff_stat(self, base: str) -> str:
        return self._run("diff", "--stat", f"{base}...HEAD")

    def merge_to_main(self, branch: str) -> str:
        self._run("checkout", "--quiet", "main")
        self._run("merge", "--quiet", "--no-ff", branch, "-m", f"merge: {branch}")
        return self._run("rev-parse", "HEAD")

    def last_author(self) -> str:
        return self._run("log", "-1", "--pretty=%an <%ae>")


def _path_env() -> str:
    import os

    return os.environ.get("PATH", "/usr/bin:/bin")
