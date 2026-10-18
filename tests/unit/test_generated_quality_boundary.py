from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from pmpe.quality import generated_python as quality


def test_candidate_filename_cannot_inject_mypy_plugin(tmp_path: Path) -> None:
    marker = tmp_path / "plugin-executed"
    payload = (
        "from pathlib import Path\n"
        f'Path({str(marker)!r}).write_text("executed")\n'
        "def plugin(version: str) -> type:\n    return object\n"
    ).encode()
    report = quality.check_python_candidate(
        {
            "--config-file=evil.py": b"",
            "evil.py": b"[mypy]\nplugins = payload.py\n",
            "payload.py": payload,
        }
    )
    assert not marker.exists(), "candidate configuration executed a plugin"
    assert not report.passed


def test_static_analysis_never_parses_candidate_in_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("candidate AST reached supervisor")

    with monkeypatch.context() as context:
        context.setattr(ast, "parse", forbidden)
        report = quality.check_python_candidate(
            {"product.py": b"def health() -> int:\n    return 1\n"}
        )
    assert report.passed


def test_static_analysis_complexity_is_bounded() -> None:
    start = time.monotonic()
    report = quality.check_python_candidate({"product.py": b"x=" + b"+1" * 20000})
    assert not report.passed
    assert time.monotonic() - start < 10


def test_checker_subprocess_output_is_bounded(tmp_path: Path) -> None:
    result = quality._run_bounded(
        'import os\nfor _ in range(100000): os.write(1,b"x"*8192)\n',
        (),
        b"",
        tmp_path,
        time.monotonic() + 5,
    )
    assert result[0] != 0 or len(result[1]) <= quality._OUTPUT_LIMIT
    assert len(result[1]) + len(result[2]) <= quality._OUTPUT_LIMIT


def test_checker_subprocess_wall_timeout_cleans_process(tmp_path: Path) -> None:
    start = time.monotonic()
    result = quality._run_bounded("import time\ntime.sleep(30)\n", (), b"", tmp_path, start + 0.1)
    assert result[0] != 0
    assert time.monotonic() - start < 3


def test_checker_never_signals_group_after_external_child_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    signalled: list[int] = []

    def reaped(_kind: int, pid: int, _options: int) -> None:
        os.waitpid(pid, 0)
        raise ChildProcessError("host reaped checker")

    monkeypatch.setattr(os, "waitid", reaped)
    monkeypatch.setattr(os, "killpg", lambda pid, _signal: signalled.append(pid))
    result = quality._run_bounded('print("done")\n', (), b"", tmp_path, time.monotonic() + 5)
    assert result[0] != 0
    assert signalled == []


def test_checker_admits_base_interpreter_site_roots_without_inherited_pythonpath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import sys
    import sysconfig

    captured: list[list[str]] = []
    expected = {
        str(
            Path(
                sysconfig.get_path(
                    key, vars={"base": sys.base_prefix, "platbase": sys.base_exec_prefix}
                )
            ).resolve()
        )
        for key in ("purelib", "platlib")
    }
    monkeypatch.setenv("PYTHONPATH", "/candidate-controlled-library")

    def capture(
        script: str, arguments: tuple[str, ...], payload: bytes, root: Path, deadline: float
    ) -> tuple[int, bytes, bytes]:
        captured.append(json.loads(arguments[0]))
        return 0, b"", b""

    monkeypatch.setattr(quality, "_run_bounded", capture)
    assert quality._run_tool("mypy", ["--version"], tmp_path, time.monotonic() + 5)[0] == "PASS"
    assert len(captured) == 1
    assert expected <= set(captured[0])
    assert "/candidate-controlled-library" not in captured[0]
