"""The migration's source-only relaunch keeps the caller's interpreter options (Codex #227).

`-E`/`-I` make Python ignore PYTHONPATH. If the relaunch dropped them, the child would
import whatever `pmpe` the environment points at instead of the isolated one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "r3_task_store_migration.py"


@pytest.mark.parametrize("option", ["-E", "-I"])
def test_relaunch_preserves_environment_isolation(tmp_path: Path, option: str) -> None:
    decoy = tmp_path / "decoy"
    (decoy / "pmpe").mkdir(parents=True)
    (decoy / "pmpe" / "__init__.py").write_text(
        "import sys\nprint('DECOY PMPE IMPORTED')\nraise SystemExit(7)\n"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}
    }
    environment["PYTHONPATH"] = str(decoy)
    result = subprocess.run(
        [sys.executable, option, str(SCRIPT), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert "DECOY PMPE IMPORTED" not in result.stdout, result.stdout + result.stderr
    assert "DECOY PMPE IMPORTED" not in result.stderr, result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout
    assert "Traceback" not in result.stderr


def test_relaunch_keeps_the_option_terminator_last(tmp_path: Path) -> None:
    """`python -- script` is valid; source-only flags must go before `--` (Codex #227)."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}
    }
    environment["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "--", str(SCRIPT), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout


@pytest.mark.parametrize("option", ["-E", "-I"])
def test_ignored_prefix_environment_still_relaunches_source_only(option: str) -> None:
    """Capture execv without running a child when Python ignored the advertised prefix."""
    witness = f"""
import json, os, runpy, sys
sys.path.insert(0, {str(ROOT / "src")!r})
sys.path.insert(0, {str(ROOT / "scripts")!r})
class Captured(Exception): pass
record = {{}}
def capture(path, argv):
    record.update(path=path, argv=argv)
    raise Captured()
os.execv = capture
sys.orig_argv = [sys.executable, '-B', {option!r}, {str(SCRIPT)!r}, '--help']
sys.argv = [{str(SCRIPT)!r}, '--help']
try:
    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')
except (Captured, SystemExit):
    pass
print('TEST-ONLY-CAPTURE ' + json.dumps({{'argv': record.get('argv'),
    'effective_prefix': sys.pycache_prefix, 'ignore_environment': sys.flags.ignore_environment}}))
"""
    environment = dict(os.environ)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["PYTHONPYCACHEPREFIX"] = "/tmp/TEST-ONLY-ignored-prefix"
    result = subprocess.run(
        [sys.executable, "-B", option, "-c", witness],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    row = json.loads(result.stdout.split("TEST-ONLY-CAPTURE ")[-1])
    assert row["effective_prefix"] is None
    assert row["ignore_environment"] == 1
    assert row["argv"] is not None
    assert option in row["argv"]
    assert "-X" in row["argv"]
