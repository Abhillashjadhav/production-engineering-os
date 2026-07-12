"""SYS-09 (security gate): the built-in deterministic scanner."""

from __future__ import annotations

from pathlib import Path

from pmpe.quality.security_scan import scan_file, scan_tree

CLEAN = '''\
import hmac
import os


def check(token: str) -> bool:
    expected = os.environ.get("APP_TOKEN", "")
    return bool(expected) and hmac.compare_digest(token, expected)
'''


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
    p.write_text('import subprocess\nsubprocess.run(cmd, shell=True)\n')
    assert any(f.rule == "SEC_SHELL_TRUE" for f in scan_file(p))


def test_pickle_load_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("import pickle\nobj = pickle.loads(blob)\n")
    assert any(f.rule == "SEC_PICKLE" for f in scan_file(p))


def test_sql_string_interpolation_is_found(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text('cur.execute(f"SELECT * FROM tasks WHERE id = {task_id}")\n')
    assert any(f.rule == "SEC_SQL_FORMAT" for f in scan_file(p))


def test_scan_tree_walks_python_files_only(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(CLEAN)
    (tmp_path / "bad.py").write_text("x = eval(y)\n")
    (tmp_path / "notes.md").write_text("eval( in prose is fine\n")
    findings = scan_tree(tmp_path)
    assert {f.file for f in findings} == {str(tmp_path / "bad.py")}


def test_findings_carry_file_and_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.py"
    p.write_text("a = 1\nb = eval(x)\n")
    (finding,) = scan_file(p)
    assert finding.file == str(p)
    assert finding.line == 2
