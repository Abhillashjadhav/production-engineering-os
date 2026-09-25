"""The forbidden-capability proof must wait for a complete documented port file.

The reference app writes its port file with ``Path.write_text``, which creates the file
before writing it, so the proof can observe an empty file. This intermittently failed CI
with "forbidden-capability proof did not execute" when the proof locked in an empty port.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from pmpe import support_package as support_package_module
from tests.unit.test_support_package_v1 import _assemble

_PORT_WRITE = 'Path(args.port_file).write_text(str(server.server_address[1]), encoding="utf-8")'


def test_proof_retries_a_port_file_that_is_still_empty(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _assemble(tmp_path, bundle)
    source = support_package_module._APP_SOURCE
    assert source.count(_PORT_WRITE) == 1
    # Hold open the window in which the port file exists but is still empty.
    slow_writer = source.replace(
        _PORT_WRITE,
        'Path(args.port_file).write_text("", encoding="utf-8")\n'
        '        __import__("time").sleep(0.5)\n'
        "        " + _PORT_WRITE,
    )
    payload = {
        "app_source": slow_writer,
        "corpus": json.loads((bundle / "recorded-corpus.json").read_text()),
        "policy": json.loads((bundle / "runtime-policy.json").read_text()),
        "startup_timeout_seconds": 10.0,
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-c", support_package_module._PROOF_RUNNER, "ordinary_ticket"],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=60,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")[-2000:]
    assert completed.stdout == b"PMPE_PROOF_COMPLETE:ordinary_ticket"
