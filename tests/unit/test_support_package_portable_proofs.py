from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pmpe.quality.security_scan import scan_file
from tests.unit.test_support_package_v1 import _assemble


def test_generated_portable_proofs_import_app_and_catch_broken_behavior(tmp_path: Path) -> None:
    bundle = tmp_path / "portable-proof"
    _assemble(tmp_path, bundle)
    proof = bundle / "tests/test_forbidden_capabilities.py"
    assert not scan_file(proof, root=bundle)
    command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]
    good = subprocess.run(command, cwd=bundle, capture_output=True, text=True, timeout=10)
    assert good.returncode == 0, good.stderr
    assert "Ran 2 tests" in good.stderr
    (bundle / "app.py").write_text("def decide(payload):\n    return 200, {'status': 'DRAFTED'}\n")
    broken = subprocess.run(command, cwd=bundle, capture_output=True, text=True, timeout=10)
    assert broken.returncode == 1
    assert "FAILED (failures=2)" in broken.stderr
