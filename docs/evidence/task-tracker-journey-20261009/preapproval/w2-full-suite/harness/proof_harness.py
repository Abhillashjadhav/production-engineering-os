"""Scratch diagnostic harness for the PEOS support-package proof runner.

Runs the *exact* production proof invocation used by
pmpe.support_package._run_reference_verification (same interpreter resolution,
-I -c <_PROOF_RUNNER> <capability>, same restricted environment, same stdin
payload, start_new_session, 60 s communicate timeout) but KEEPS stderr, exit
code and wall time so a failing proof child can be classified.

Nothing here modifies the clone: the runner/app strings are taken from the
imported module and optionally transformed in memory for diagnosis only.

Usage: python proof_harness.py --iterations N --parallel P [--runner original|fixed|diag|fixed-diag]
       [--app original|delay-documented|delay-verified|delay-both] [--delay S]
       [--startup-timeout S] [--capabilities a,b,c] [--jsonl out.jsonl]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pmpe.support_package as sp
from pmpe.contracts.canonical import canonical_json_bytes

ORIGINAL_DOC_LINE = (
    '                        documented_url = "http://127.0.0.1:" + handle.read() + "/health"\n'
)
FIXED_DOC_LINE = (
    '                        documented_url = "http://127.0.0.1:" + str(int(handle.read())) + "/health"\n'
)
# Diagnostic-only addition: report what the documented loop cached right before the
# production assertion.  It writes to stderr only and changes no control flow.
DIAG_ANCHOR = '        assert documented_health == {"status":"healthy"}\n'
DIAG_LINE = (
    '        sys.stderr.write("DIAG documented_url=%r documented_health=%r\\n" '
    "% (documented_url, documented_health))\n"
)

ORIGINAL_PORT_WRITE = (
    '        Path(args.port_file).write_text(str(server.server_address[1]), encoding="utf-8")\n'
)


def runner_variant(name: str) -> str:
    runner = sp._PROOF_RUNNER
    assert runner.count(ORIGINAL_DOC_LINE) == 1, "runner text changed; harness anchors stale"
    assert runner.count(DIAG_ANCHOR) == 1
    if name in ("fixed", "fixed-diag"):
        runner = runner.replace(ORIGINAL_DOC_LINE, FIXED_DOC_LINE)
    if name in ("diag", "fixed-diag"):
        runner = runner.replace(DIAG_ANCHOR, DIAG_LINE + DIAG_ANCHOR)
    return runner


def app_variant(name: str, delay: float) -> str:
    app = sp._APP_SOURCE
    assert app.count(ORIGINAL_PORT_WRITE) == 1, "app text changed; harness anchors stale"
    if name == "original":
        return app
    selector = {
        "delay-documented": 'args.port_file.endswith("documented-port")',
        "delay-verified": 'args.port_file.endswith("verified-port")',
        "delay-both": "True",
    }[name]
    # Same bytes reach the file, but the create (open) and the write are separated by
    # `delay` seconds, i.e. the window Path.write_text normally has (microseconds)
    # is widened deterministically.
    replacement = (
        "        handle = open(args.port_file, \"w\", encoding=\"utf-8\")\n"
        f"        if {selector}:\n"
        f"            time.sleep({delay!r})\n"
        "        handle.write(str(server.server_address[1]))\n"
        "        handle.close()\n"
    )
    return app.replace(ORIGINAL_PORT_WRITE, replacement)


def proof_input(app_source: str, startup_timeout: float) -> bytes:
    return canonical_json_bytes(
        {
            "app_source": app_source,
            "corpus": sp._RECORDED_CORPUS,
            "policy": {"additional_confidence_below": 0.75, "max_processing_seconds": 30},
            "startup_timeout_seconds": startup_timeout,
        }
    )


def run_one(runner: str, capability: str, payload: bytes) -> dict[str, object]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    started = time.monotonic()
    proof = subprocess.Popen(
        [os.fspath(Path(sys.executable).resolve()), "-I", "-c", runner, capability],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = proof.communicate(payload, timeout=sp._PROOF_PROCESS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proof.pid, signal.SIGKILL)
        stdout, stderr = proof.communicate()
    elapsed = time.monotonic() - started
    expected = f"PMPE_PROOF_COMPLETE:{capability}".encode()
    ok = (not timed_out) and proof.returncode == 0 and stdout == expected
    return {
        "capability": capability,
        "ok": ok,
        "returncode": proof.returncode,
        "timed_out": timed_out,
        "elapsed_s": round(elapsed, 3),
        "stdout": stdout.decode("utf-8", "replace"),
        "stderr": stderr.decode("utf-8", "replace")[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--runner", default="original")
    parser.add_argument("--app", default="original")
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--startup-timeout", type=float, default=sp._PROOF_CHILD_STARTUP_TIMEOUT_SECONDS)
    parser.add_argument(
        "--capabilities",
        default="autonomous_refund_payment,credential_collection,ordinary_ticket,low_confidence,policy_draft",
    )
    parser.add_argument("--jsonl", default=None)
    args = parser.parse_args()
    runner = runner_variant(args.runner)
    payload = proof_input(app_variant(args.app, args.delay), args.startup_timeout)
    capabilities = args.capabilities.split(",")
    jobs = [capabilities[i % len(capabilities)] for i in range(args.iterations)]
    out = open(args.jsonl, "a") if args.jsonl else None
    counts: dict[str, int] = {}
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for result in pool.map(lambda cap: run_one(runner, cap, payload), jobs):
            key = "PASS" if result["ok"] else f"FAIL rc={result['returncode']} timeout={result['timed_out']}"
            counts[key] = counts.get(key, 0) + 1
            result.update(runner=args.runner, app=args.app, startup_timeout=args.startup_timeout)
            if out:
                out.write(json.dumps(result, sort_keys=True) + "\n")
                out.flush()
            if not result["ok"]:
                last = [line for line in str(result["stderr"]).splitlines() if line.strip()][-4:]
                print(f"FAIL {result['capability']} rc={result['returncode']} "
                      f"elapsed={result['elapsed_s']}s stderr_tail={last}", flush=True)
    summary = {
        "runner": args.runner,
        "app": args.app,
        "delay": args.delay,
        "startup_timeout": args.startup_timeout,
        "iterations": args.iterations,
        "parallel": args.parallel,
        "counts": counts,
        "wall_s": round(time.monotonic() - t0, 1),
    }
    print("SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
    if out:
        out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
