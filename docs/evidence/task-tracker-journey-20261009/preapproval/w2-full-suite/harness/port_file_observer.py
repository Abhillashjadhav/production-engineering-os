"""Observe the UNMODIFIED canonical app's --port-file publication.

Starts the app exactly as _PROOF_RUNNER does ([sys.executable, -I, app.py, --port, 0,
--port-file <path>], cwd = a temp dir holding app.py/recorded-corpus.json/
runtime-policy.json, stdio DEVNULL) and polls the port file:
  --mode tight : no sleep between reads (maximises detection of the empty window)
  --mode runner: 0.02 s sleep between reads, i.e. the production poll cadence
For each startup it records whether an existing-but-EMPTY file was read (the H1
precondition) and whether any non-empty read was a strict prefix of the final
value (H2, partial read).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import pmpe.support_package as sp


def one(directory: str, mode: str, index: int) -> dict[str, object]:
    port_file = os.path.join(directory, f"documented-port-{index}")
    process = subprocess.Popen(
        [sys.executable, "-I", "app.py", "--port", "0", "--port-file", port_file],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    empty_reads = 0
    first_empty = last_empty = first_content = None
    reads: list[str] = []
    final = None
    deadline = time.monotonic() + 25
    try:
        while time.monotonic() < deadline:
            try:
                with open(port_file, encoding="utf-8") as handle:
                    content = handle.read()
            except FileNotFoundError:
                if mode == "runner":
                    time.sleep(0.02)
                continue
            if content == "":
                empty_reads += 1
                last_empty = time.perf_counter()
                if first_empty is None:
                    first_empty = last_empty
                if mode == "runner":
                    time.sleep(0.02)
                continue
            first_content = time.perf_counter()
            reads.append(content)
            final = content
            # read a few more times to make sure the value is stable/complete
            time.sleep(0.05)
            with open(port_file, encoding="utf-8") as handle:
                final = handle.read()
            break
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    partial = any(final is not None and r != final and final.startswith(r) for r in reads)
    window_lo = (last_empty - first_empty) if first_empty is not None else 0.0
    window_hi = (first_content - first_empty) if first_empty is not None and first_content else 0.0
    return {"window_lo_s": window_lo, "window_hi_s": window_hi, "empty_reads": empty_reads, "first_read": reads[0] if reads else None,
            "final": final, "partial": partial}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--mode", choices=["tight", "runner"], default="tight")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="w2-observer-") as directory:
        for name, content in {
            "app.py": sp._APP_SOURCE.encode(),
            "recorded-corpus.json": json.dumps(sp._RECORDED_CORPUS, sort_keys=True).encode(),
            "runtime-policy.json": json.dumps(
                {"additional_confidence_below": 0.75, "max_processing_seconds": 30},
                sort_keys=True,
            ).encode(),
        }.items():
            with open(os.path.join(directory, name), "xb") as handle:
                handle.write(content)
        startups_with_empty = 0
        total_empty_reads = 0
        partial = 0
        missing = 0
        windows: list[float] = []
        for index in range(args.iterations):
            result = one(directory, args.mode, index)
            total_empty_reads += int(result["empty_reads"])
            startups_with_empty += int(result["empty_reads"]) > 0
            partial += bool(result["partial"])
            missing += result["final"] is None
            windows.append(float(result["window_hi_s"]))
            if result["empty_reads"]:
                print(f"startup {index}: EMPTY port file observed {result['empty_reads']}x "
                      f"(window {result['window_lo_s']*1e3:.3f}-{result['window_hi_s']*1e3:.3f} ms) "
                      f"before content {result['final']!r}", flush=True)
            if result["partial"]:
                print(f"startup {index}: PARTIAL read {result['first_read']!r} -> {result['final']!r}",
                      flush=True)
    print("SUMMARY " + json.dumps({
        "mode": args.mode, "startups": args.iterations,
        "startups_with_empty_read": startups_with_empty,
        "total_empty_reads": total_empty_reads,
        "startups_with_partial_read": partial, "startups_never_published": missing,
        "window_ms_max": round(max(windows) * 1e3, 3) if windows else 0,
        "startups_window_ge_1ms": sum(w >= 0.001 for w in windows),
        "startups_window_ge_5ms": sum(w >= 0.005 for w in windows),
        "sum_window_ms": round(sum(windows) * 1e3, 3),
        "expected_runner_hits_at_20ms_poll": round(sum(min(w / 0.02, 1.0) for w in windows), 3),
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
