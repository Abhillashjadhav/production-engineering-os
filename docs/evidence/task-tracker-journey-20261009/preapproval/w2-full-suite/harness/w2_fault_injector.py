"""W2 DIAGNOSTIC-ONLY fault injector (installed only into scratch --copies venvs).

Loaded at interpreter start via a .pth line in the scratch venv's site-packages, so
it also runs inside the production proof runner (`python -I -c _PROOF_RUNNER cap`)
and the app children it spawns -- without touching src/pmpe/support_package.py,
the canonical app bytes, or the test.

It is inert unless the control file exists. When active it widens -- it does not
create -- the window that `Path.write_text` already has between creating the
port file (open O_CREAT|O_TRUNC) and writing the port number into it: exactly
what a scheduler preemption of the app between those two syscalls does under load.
The bytes written are unchanged.

Control file (JSON): {"capability": "low_confidence", "target": "documented-port",
                      "delay_s": 0.5}
"""

from __future__ import annotations

import json
import os
import sys
import time

_CONTROL = (
    "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2/demo-control.json"
)
_LOG = "/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2/logs/fault-injector.log"


def _log(message: str) -> None:
    with open(_LOG, "a", encoding="utf-8") as handle:
        handle.write(f"{time.time():.3f} pid={os.getpid()} {message}\n")


def _install() -> None:
    if getattr(sys, "_w2_fault_injector_loaded", False):  # .pth is seen twice (lib64 link)
        return
    sys._w2_fault_injector_loaded = True  # type: ignore[attr-defined]
    try:
        with open(_CONTROL, encoding="utf-8") as handle:
            control = json.load(handle)
    except OSError:
        return
    argv = list(sys.argv)
    # Role 1: the production proof runner, argv == ['-c', <capability>].
    if len(argv) == 2 and argv[0] == "-c" and control["capability"] in (argv[1], "*"):
        os.environ["W2_DEMO_DELAY"] = str(control["delay_s"])
        os.environ["W2_DEMO_TARGET"] = str(control["target"])
        _log(f"runner capability={argv[1]} arming app children target={control['target']}")
        return
    # Role 2: the canonical app spawned by that runner (inherits the runner's env).
    delay = os.environ.get("W2_DEMO_DELAY")
    target_name = os.environ.get("W2_DEMO_TARGET")
    if not (delay and target_name and argv[:1] == ["app.py"] and "--port-file" in argv):
        return
    port_file = argv[argv.index("--port-file") + 1]
    if os.path.basename(port_file) != target_name:
        return
    import pathlib

    original = pathlib.Path.write_text

    def write_text(self, data, encoding=None, errors=None, newline=None):  # type: ignore[no-untyped-def]
        if os.fspath(self) != port_file:
            return original(self, data, encoding=encoding, errors=errors, newline=newline)
        with open(self, "w", encoding=encoding, errors=errors, newline=newline) as handle:
            _log(f"app port-file created EMPTY {port_file}; holding {delay}s before write")
            time.sleep(float(delay))
            return handle.write(data)

    pathlib.Path.write_text = write_text  # type: ignore[method-assign]


_install()
