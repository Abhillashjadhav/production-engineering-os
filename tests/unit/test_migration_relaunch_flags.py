"""The migration's source-only relaunch keeps the caller's interpreter options (Codex #227).

`-E`/`-I` make Python ignore PYTHONPATH. If the relaunch dropped them, the child would
import whatever `pmpe` the environment points at instead of the isolated one.
"""

from __future__ import annotations

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
    assert result.returncode != 7, result.stdout + result.stderr
