"""CI exports the shared private bytecode prefix only after installing packages.

pip byte-compiles installed modules even under PYTHONDONTWRITEBYTECODE=1, and it writes
them into PYTHONPYCACHEPREFIX when that is set. Exporting the prefix before the install
leaves it non-empty, so every source-only-gated test then refuses to run.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"


def test_prefix_is_exported_after_every_package_install() -> None:
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["tests"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    exports = [index for index, run in enumerate(runs) if "PYTHONPYCACHEPREFIX=" in run]
    installs = [index for index, run in enumerate(runs) if "pip install" in run]
    tests = [index for index, run in enumerate(runs) if run.startswith("pytest")]
    assert len(exports) == 1 and installs and tests
    assert max(installs) < exports[0] < min(tests)
