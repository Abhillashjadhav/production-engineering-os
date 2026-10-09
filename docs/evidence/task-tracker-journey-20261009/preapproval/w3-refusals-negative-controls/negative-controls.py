#!/usr/bin/env python3
"""Stage-4 negative-control harness for PMOS-TASK-TRACKER-001 (PREPARED, NOT FINAL).

Every control runs in its own fresh output directory against the real entry
(``examples/barebones/contract-file.py``), the real provider shim, or directly
against a copy of the candidate's ``product.py``; one JSON summary records the
command, exit code, failure.json/result.json content and PASS/FAIL against the
stated expectation of each control.

Two modes:

  prepare-fixture --pmos PMOS --peos PEOS --dest DIR
      Copy the PMOS-bound files into a DISPOSABLE root and regenerate a
      self-consistent freeze manifest over those copies plus PEOS's current bytes.
      This is a test fixture for harness dry runs. It is NOT an approval and it
      never touches the real packet. Prints {packet, pmos, freeze_digest}.

  --peos P --pmos M --packet K --freeze-digest D --candidate C --out O [options]
      Run the controls. For the real Stage-4 run point --pmos/--packet at the real
      PMOS checkout and packet, --freeze-digest at the owner-approved digest and
      --candidate at the fresh build's candidate directory.

Nothing here edits the packet passed in, any approval-bound file, or the candidate
passed in: every mutation is applied to a copy under --out.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PACKET_RELATIVE = Path("reviews") / "task-tracker-v1"
PMOS = "PM-agent-OS"
PEOS = "production-engineering-os"
RUN_ID = "task-tracker-live"
ZERO_DIGEST = "sha256:" + "0" * 64
DEAD = frozenset({"Z", "X"})
FILTER_FIND = 'if args.status != "all":'
FILTER_REPLACE = "if False:  # Deliberate negative-control mutation: ignore --status."
EVALUATOR_FILE = "tests/acceptance/task_tracker.py"
EVALUATOR_FIND = '"value": len(missing),'
EVALUATOR_REPLACE = '"value": 0,  # Deliberate negative-control mutation: hide missing records.'
EXPECTED_FILTER_FAILURES = [
    "AC-004",
    "AC-005",
]  # recorded for the Sept candidate (mutations/filtering)


# --------------------------------------------------------------------------- utilities


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"_unreadable": f"{type(exc).__name__}: {exc}"}


def tail(text: str, limit: int = 3000) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]


def canonical_digest(value: Any) -> str:
    try:
        from pmpe.contracts.canonical import canonical_digest as engine_digest
    except ImportError:  # RFC 8785 for the manifest's str/int/list/object subset
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return sha256_bytes(payload)
    return str(engine_digest(value))


def regenerate_manifest(base: dict[str, Any], roots: dict[str, Path], note: str) -> dict[str, Any]:
    """Self-consistent manifest over the given roots' current bytes: a fixture, never approval."""
    fixture = {
        key: value
        for key, value in base.items()
        if key not in {"artifacts", "owner_approval_quote", "status"}
    }
    fixture["status"] = "TEST_FIXTURE_NOT_APPROVAL"
    fixture["fixture_note"] = note
    artifacts = []
    for item in base["artifacts"]:
        digest = sha256_file(roots[item["repository"]] / item["path"])
        if digest is None:
            raise FileNotFoundError(f"bound artifact missing: {item['repository']}:{item['path']}")
        artifacts.append({"path": item["path"], "repository": item["repository"], "sha256": digest})
    fixture["artifacts"] = artifacts
    return fixture


def drift(manifest: dict[str, Any], roots: dict[str, Path]) -> list[str]:
    return [
        f"{item['repository']}:{item['path']}"
        for item in manifest["artifacts"]
        if sha256_file(roots[item["repository"]] / item["path"]) != item["sha256"]
    ]


# --------------------------------------------------------------------------- processes


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    sid: int
    state: str
    cmdline: str


def proc(pid: int) -> Proc | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    fields = stat[stat.rindex(")") + 2 :].split()
    cmdline = raw.replace(b"\0", b" ").decode(errors="replace").strip()
    return Proc(pid, int(fields[1]), int(fields[2]), int(fields[3]), fields[0], cmdline)


def processes() -> list[Proc]:
    found = (proc(int(entry.name)) for entry in Path("/proc").iterdir() if entry.name.isdigit())
    return [item for item in found if item is not None]


def descendants(root: int) -> list[Proc]:
    table = processes()
    found: list[Proc] = []
    frontier = [root]
    while frontier:
        parent = frontier.pop()
        children = [item for item in table if item.ppid == parent]
        found += children
        frontier += [item.pid for item in children]
    return found


def running(pid: int) -> bool:
    item = proc(pid)
    return item is not None and item.state not in DEAD


def group_members(group: int) -> list[Proc]:
    return [item for item in processes() if item.pgid == group and item.state not in DEAD]


def wait_until(condition: Callable[[], bool], timeout: float, step: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step)
    return condition()


def protected_pids() -> set[int]:
    """This harness and its ancestors: their argv names --out, but they are never targets."""
    protected = {os.getpid()}
    current = proc(os.getpid())
    while current is not None and current.ppid > 1:
        protected.add(current.ppid)
        current = proc(current.ppid)
    return protected


def marked(marker: str) -> list[Proc]:
    protected = protected_pids()
    return [
        item
        for item in processes()
        if item.state not in DEAD and marker in item.cmdline and item.pid not in protected
    ]


def kill_marked(marker: str, extra_pids: list[int] | None = None) -> list[dict[str, Any]]:
    """SIGKILL every live process whose argv names ``marker`` (plus extra pids)."""
    killed = []
    targets = {item.pid: item for item in marked(marker)}
    protected = protected_pids()
    for pid in extra_pids or []:
        item = proc(pid)
        if item is not None and item.state not in DEAD and pid not in protected:
            targets[pid] = item
    for item in targets.values():
        with contextlib.suppress(ProcessLookupError):
            os.kill(item.pid, signal.SIGKILL)
            killed.append({"pid": item.pid, "pgid": item.pgid, "cmdline": item.cmdline[:300]})
    wait_until(lambda: not [pid for pid in targets if running(pid)], 10)
    return killed


# --------------------------------------------------------------------------- context


@dataclass
class Ctx:
    peos: Path
    pmos: Path
    packet: Path
    freeze_digest: str
    candidate: Path
    out: Path
    python: str
    stale_from: Path | None
    known_products: dict[str, str]
    mutation_find: str
    mutation_replace: str
    entry: Path = field(init=False)
    shim: Path = field(init=False)
    regression: Path = field(init=False)

    def __post_init__(self) -> None:
        self.entry = self.peos / "examples" / "barebones" / "contract-file.py"
        self.shim = self.peos / "examples" / "barebones" / "session-file-provider.py"
        self.regression = self.peos / "examples" / "barebones" / "task-tracker-regression.py"

    def fresh(self, name: str) -> Path:
        directory = self.out / name
        if directory.exists():
            raise FileExistsError(f"control output already exists: {directory}")
        directory.mkdir(parents=True)
        (directory / "tmp").mkdir()
        return directory

    def product_text(self) -> str:
        return (self.candidate / "product.py").read_text(encoding="utf-8")


def entry_command(
    ctx: Ctx,
    mode: str,
    output: Path,
    *,
    candidate: Path | None = None,
    fallback: bool = True,
    digest: str | None = None,
    packet: Path | None = None,
    pmos_root: Path | None = None,
) -> list[str]:
    command = [
        ctx.python,
        str(ctx.entry),
        mode,
        "--packet",
        str(packet or ctx.packet),
        "--root",
        f"{PMOS}={pmos_root or ctx.pmos}",
        "--root",
        f"{PEOS}={ctx.peos}",
        "--freeze-digest",
        digest or ctx.freeze_digest,
        "--output",
        str(output),
    ]
    if candidate is not None:
        command += ["--candidate", str(candidate)]
    if fallback:
        command.append("--authorized-host-fallback")
    return command


def start(command: list[str], workdir: Path, label: str) -> subprocess.Popen[bytes]:
    environment = {**os.environ, "TMPDIR": str(workdir / "tmp")}
    with (
        (workdir / f"{label}.stdout").open("wb") as out,
        (workdir / f"{label}.stderr").open("wb") as err,
    ):
        return subprocess.Popen(
            command,
            cwd=workdir,
            env=environment,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )


def finish(process: subprocess.Popen[bytes], timeout: float) -> tuple[int, bool]:
    """Wait for the entry; on timeout SIGKILL its group. Returns (exit code, timed out)."""
    try:
        return process.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        return process.wait(timeout=30), True


def run_entry(
    ctx: Ctx, command: list[str], workdir: Path, label: str = "entry", timeout: float = 300
) -> dict[str, Any]:
    started = time.monotonic()
    process = start(command, workdir, label)
    tree_marker = str(workdir)
    code, timed_out = finish(process, timeout)
    leftovers = kill_marked(tree_marker)
    return {
        "command": command,
        "command_shell": shlex.join(command),
        "exit_code": code,
        "timed_out": timed_out,
        "elapsed_s": round(time.monotonic() - started, 2),
        "stdout_tail": tail((workdir / f"{label}.stdout").read_text(errors="replace")),
        "stderr_tail": tail((workdir / f"{label}.stderr").read_text(errors="replace")),
        "killed_leftovers": leftovers,
    }


def status_cli(ctx: Ctx, output: Path) -> dict[str, Any]:
    console = Path(ctx.python).with_name("pmpe")
    prefix = (
        [str(console)]
        if console.is_file()
        else [ctx.python, "-c", "import sys; from pmpe.cli import main; sys.exit(main())"]
    )
    command = [*prefix, "barebones", "status", RUN_ID, "--repository-root", str(output)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    try:
        parsed: Any = json.loads(completed.stdout)
    except ValueError:
        parsed = None
    return {
        "command_shell": shlex.join(command),
        "exit_code": completed.returncode,
        "stdout_json": parsed,
        "stderr_tail": tail(completed.stderr, 1000),
    }


def classify(ctx: Ctx, output: Path, code: int | None) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("task_tracker_regression", ctx.regression)
    if spec is None or spec.loader is None:
        return {"error": "regression classifier unavailable"}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result: dict[str, Any] = module.classify(output, code)
    return result


def collect(ctx: Ctx, run: Path, code: int | None) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "output_dir": str(run),
        "output_exists": run.exists(),
        "output_listing": sorted(item.name for item in run.iterdir()) if run.is_dir() else None,
        "result_json": read_json(run / "result.json"),
        "failure_json": read_json(run / "failure.json"),
    }
    compatibility = read_json(run / "compatibility.json")
    observed["compatibility"] = (
        {"compatible": compatibility.get("compatible"), "reasons": compatibility.get("reasons")}
        if isinstance(compatibility, dict)
        else None
    )
    ledger = run / ".pmpe" / "runs" / RUN_ID / "events.jsonl"
    if ledger.is_file():
        events = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        observed["ledger_events"] = [event["event_type"] for event in events]
        observed["ledger_terminal"] = {
            "state": events[-1].get("state"),
            "cause": (events[-1].get("payload") or {}).get("cause"),
        }
        observed["status_cli"] = status_cli(ctx, run)
    else:
        observed["ledger_events"] = None
    calls = []
    for call in sorted(run.glob("handoff/call-*")):
        request = read_json(call / "request.json")
        calls.append(
            {
                "call": call.name,
                "purpose": request.get("purpose") if isinstance(request, dict) else None,
                "request_digest": (request or {}).get("request", {}).get("request_digest")
                if isinstance(request, dict)
                else None,
                "call_json": read_json(call / "call.json"),
                "response_present": (call / "response.json").exists(),
                "output_present": (call / "output.json").exists(),
            }
        )
    observed["handoff_calls"] = calls
    records = run / "processes.jsonl"
    observed["candidate_process_records"] = (
        len([line for line in records.read_text().splitlines() if line.strip()])
        if records.is_file()
        else None
    )
    checks_path = run / "digest-checks.jsonl"
    if checks_path.is_file():
        rows = [json.loads(line) for line in checks_path.read_text().splitlines() if line.strip()]
        observed["digest_checks"] = {
            "count": len(rows),
            "with_mismatches": len([row for row in rows if row["mismatches"]]),
            "first": rows[0]["stage"] + ":" + rows[0]["subject"] if rows else None,
            "last": rows[-1]["stage"] + ":" + rows[-1]["subject"] if rows else None,
            "mismatches": [row["mismatches"] for row in rows if row["mismatches"]][:3],
        }
    else:
        observed["digest_checks"] = None
    candidate_product = run / "candidate" / "product.py"
    observed["built_product_sha256"] = sha256_file(candidate_product)
    observed["classification"] = classify(ctx, run, code) if run.is_dir() else None
    return observed


def verdict(checks: list[tuple[str, bool]]) -> dict[str, Any]:
    return {
        "verdict": "PASS" if checks and all(ok for _, ok in checks) else "FAIL",
        "checks": [{"expectation": text, "met": ok} for text, ok in checks],
    }


def failed_criteria(observed: dict[str, Any]) -> list[str] | None:
    result = observed.get("result_json")
    if not isinstance(result, dict) or "criteria" not in result:
        return None
    return sorted(key for key, value in result["criteria"].items() if value != "PASS")


def all_pass(observed: dict[str, Any]) -> bool:
    result = observed.get("result_json")
    return (
        isinstance(result, dict)
        and bool(result.get("criteria"))
        and set(result["criteria"].values()) == {"PASS"}
        and result.get("findings") == []
    )


# --------------------------------------------------------------------------- responder


class Responder(threading.Thread):
    """Scripted stand-in for the agent session answering OUTPUT/handoff/call-*/request.json."""

    def __init__(self, handoff: Path, mode: str, product: str, stale_from: Path | None) -> None:
        super().__init__(daemon=True)
        self.handoff, self.mode, self.product = handoff, mode, product
        self.stale: list[tuple[Path, dict[str, Any], bytes]] = []
        if stale_from is not None:
            for path in sorted(stale_from.glob("call-*/response.json")):
                raw = path.read_bytes()
                self.stale.append((path, json.loads(raw), raw))
        self.stop_event = threading.Event()
        self.log: list[dict[str, Any]] = []
        self.done: set[str] = set()

    def payload(self, purpose: str, digest: str) -> tuple[bytes | None, dict[str, Any]]:
        if self.mode == "silent":
            return None, {"action": "withheld (no response written)"}
        if self.mode in {"match", "wrong-digest"}:
            bound = digest if self.mode == "match" else ZERO_DIGEST
            body: dict[str, Any] = (
                {"request_digest": bound, "files": {"product.py": self.product}}
                if purpose == "code"
                else {"request_digest": bound, "annotation": "harness advisory, non-blocking"}
            )
            return json.dumps(body, sort_keys=True).encode() + b"\n", {
                "action": f"wrote {self.mode} response",
                "response_request_digest": bound,
            }
        if self.mode == "stale-other-call":
            for path, body, raw in self.stale:
                if body.get("request_digest") != digest:
                    return raw, {
                        "action": "delivered a previous call's response verbatim",
                        "source": str(path),
                        "response_request_digest": body.get("request_digest"),
                    }
            return None, {"action": "no stale response with a different digest available"}
        if self.mode == "replay":
            for path, body, raw in self.stale:
                if body.get("request_digest") == digest:
                    return raw, {
                        "action": "replayed a previous run's response to the identical request",
                        "source": str(path),
                        "response_request_digest": digest,
                    }
            return None, {"action": "no previous response for this request digest; withheld"}
        raise ValueError(f"unknown responder mode {self.mode}")

    def run(self) -> None:
        while not self.stop_event.is_set():
            calls = sorted(self.handoff.glob("call-*")) if self.handoff.is_dir() else []
            for call in calls:
                if call.name in self.done or not (call / "request.json").is_file():
                    continue
                try:
                    message = json.loads((call / "request.json").read_text())
                except (OSError, ValueError):
                    continue
                purpose = str(message.get("purpose"))
                digest = str(message["request"]["request_digest"])
                payload, info = self.payload(purpose, digest)
                self.done.add(call.name)
                record = {"call": call.name, "purpose": purpose, "request_digest": digest, **info}
                if payload is not None:
                    staging = call / "response.harness-tmp"
                    staging.write_bytes(payload)
                    os.replace(staging, call / "response.json")
                    record["response_sha256"] = sha256_bytes(payload)
                record["at"] = now()
                self.log.append(record)
            self.stop_event.wait(0.05)


def build_with_responder(
    ctx: Ctx, name: str, mode: str, timeout: float
) -> tuple[Path, dict[str, Any], dict[str, Any], Responder]:
    workdir = ctx.fresh(name)
    run = workdir / "run"
    responder = Responder(run / "handoff", mode, ctx.product_text(), ctx.stale_from)
    responder.start()
    try:
        execution = run_entry(ctx, entry_command(ctx, "build", run), workdir, timeout=timeout)
    finally:
        responder.stop_event.set()
        responder.join(timeout=5)
    observed = collect(ctx, run, execution["exit_code"])
    observed["responder_log"] = responder.log
    return run, execution, observed, responder


def halted_provider_checks(
    execution: dict[str, Any], observed: dict[str, Any]
) -> list[tuple[str, bool]]:
    result = observed.get("result_json") or {}
    return [
        ("entry exit code is 1", execution["exit_code"] == 1),
        ("result.json state is HALTED", result.get("state") == "HALTED"),
        (
            "result.json cause is MODEL_PROVIDER_FAILED",
            result.get("cause") == "MODEL_PROVIDER_FAILED",
        ),
        ("ledger ends with halted", (observed.get("ledger_events") or [None])[-1] == "halted"),
        ("no release_ready event", "release_ready" not in (observed.get("ledger_events") or [])),
        (
            "no coder_completed event",
            "coder_completed" not in (observed.get("ledger_events") or []),
        ),
        (
            "status CLI does not report RELEASE_READY",
            ((observed.get("status_cli") or {}).get("stdout_json") or {}).get("state")
            not in {"RELEASE_READY", None},
        ),
    ]


# --------------------------------------------------------------------------- controls


def control_wrong_provider_digest(ctx: Ctx) -> dict[str, Any]:
    _, execution, observed, _ = build_with_responder(
        ctx, "wrong_provider_digest", "wrong-digest", 300
    )
    errors = [((call.get("call_json") or {}).get("error")) for call in observed["handoff_calls"]]
    checks = halted_provider_checks(execution, observed)
    checks.append(
        ("shim refused with RESPONSE_DIGEST_MISMATCH", "RESPONSE_DIGEST_MISMATCH" in errors)
    )
    return {
        "layer": "engine+provider shim",
        "expected": "scripted response with a different request_digest -> shim RESPONSE_DIGEST_MISMATCH, "
        "engine HALTED/MODEL_PROVIDER_FAILED, exit 1, no RELEASE_READY",
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


def control_stale_response_other_call(ctx: Ctx) -> dict[str, Any]:
    _, execution, observed, _ = build_with_responder(
        ctx, "stale_response_other_call", "stale-other-call", 300
    )
    errors = [((call.get("call_json") or {}).get("error")) for call in observed["handoff_calls"]]
    delivered = [row for row in observed["responder_log"] if "source" in row]
    checks = halted_provider_checks(execution, observed)
    checks += [
        ("a previous call's response was delivered verbatim", bool(delivered)),
        ("shim refused with RESPONSE_DIGEST_MISMATCH", "RESPONSE_DIGEST_MISMATCH" in errors),
    ]
    return {
        "layer": "engine+provider shim",
        "expected": "a valid-looking response retained from a previous call (different request_digest) "
        "-> refused, HALTED/MODEL_PROVIDER_FAILED, exit 1",
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


def control_stale_response_identical_request_replay(ctx: Ctx) -> dict[str, Any]:
    _, execution, observed, _ = build_with_responder(
        ctx, "stale_response_identical_request_replay", "replay", 300
    )
    replayed = [row for row in observed["responder_log"] if "source" in row]
    product = observed.get("built_product_sha256")
    engine_accepted = (observed.get("result_json") or {}).get("state") == "RELEASE_READY"
    known = ctx.known_products.get(product or "")
    flagged_not_fresh = product is not None and known is not None
    finding = None
    if replayed and engine_accepted:
        finding = (
            "ENGINE_ACCEPTS_IDENTICAL_REQUEST_REPLAY: the code request_digest is a content digest of "
            "{contract, plan, skeleton files, baseline findings}; it is deterministic across runs, so a "
            "retained response from an earlier run is accepted. Freshness of a build must be established "
            "out of band (candidate digest differs from every retained candidate)."
        )
    checks = [
        (
            "a replayed response is never counted as a fresh build "
            "(engine refuses it, or the harness flags the candidate as byte-identical to a retained one)",
            (not engine_accepted) or flagged_not_fresh,
        )
    ]
    return {
        "layer": "engine+provider shim+harness freshness check",
        "expected": "replay of a previous run's response to the identical request must not be presentable "
        "as a fresh build",
        "execution": execution,
        "observed": {
            **observed,
            "replayed_calls": len(replayed),
            "engine_accepted_replay": engine_accepted,
            "built_product_matches_retained": known,
            "harness_fresh": None if product is None else not flagged_not_fresh,
        },
        "finding": finding,
        **verdict(checks),
    }


def control_missing_model_response_shim(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("missing_model_response_shim_bounded")
    handoff = workdir / "handoff"
    request = {"purpose": "code", "request": {"request_digest": "sha256:" + "1" * 64}}
    command = [ctx.python, str(ctx.shim), "--handoff-dir", str(handoff)]
    environment = {**os.environ, "PMPE_PROVIDER_TIMEOUT_SECONDS": "2"}
    started = time.monotonic()
    completed = subprocess.run(
        command,
        input=json.dumps(request).encode(),
        capture_output=True,
        timeout=60,
        env=environment,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 2)
    calls = [read_json(path) for path in sorted(handoff.glob("call-*/call.json"))]
    checks = [
        ("shim exit code is 1", completed.returncode == 1),
        ("stderr is RESPONSE_TIMEOUT", completed.stderr.decode().strip() == "RESPONSE_TIMEOUT"),
        (
            "call.json status failed/RESPONSE_TIMEOUT",
            any(
                isinstance(call, dict)
                and call.get("status") == "failed"
                and call.get("error") == "RESPONSE_TIMEOUT"
                for call in calls
            ),
        ),
        ("bounded at 0.9 x 2 s (elapsed < 10 s)", elapsed < 10),
        ("no response/output written", not list(handoff.glob("call-*/output.json"))),
    ]
    return {
        "layer": "provider shim only (engine not involved)",
        "expected": "with PMPE_PROVIDER_TIMEOUT_SECONDS=2 the shim gives up after 1.8 s: RESPONSE_TIMEOUT, exit 1",
        "execution": {
            "command_shell": "PMPE_PROVIDER_TIMEOUT_SECONDS=2 " + shlex.join(command),
            "exit_code": completed.returncode,
            "elapsed_s": elapsed,
            "stderr_tail": tail(completed.stderr.decode(errors="replace")),
        },
        "observed": {"calls": calls},
        "note": "This bounds only the shim. Through contract-file.py the engine passes "
        "PMPE_PROVIDER_TIMEOUT_SECONDS=600 (hard-coded in the entry, overriding the caller), so the "
        "end-to-end timeout control is the slow one.",
        **verdict(checks),
    }


def control_missing_model_response_engine(ctx: Ctx) -> dict[str, Any]:
    _, execution, observed, _ = build_with_responder(
        ctx, "missing_model_response_engine_slow", "silent", 900
    )
    calls = observed["handoff_calls"]
    errors = [((call.get("call_json") or {}).get("error")) for call in calls]
    elapsed_ms = [((call.get("call_json") or {}).get("elapsed_ms")) for call in calls]
    checks = halted_provider_checks(execution, observed)
    checks += [
        ("shim reported RESPONSE_TIMEOUT", "RESPONSE_TIMEOUT" in errors),
        ("no response.json was ever written", not any(call["response_present"] for call in calls)),
    ]
    return {
        "layer": "engine+provider shim (SLOW)",
        "slow": True,
        "expected": "no response -> shim RESPONSE_TIMEOUT at 0.9 x 600 s = 540 s (entry hard-codes 600), "
        "engine HALTED/MODEL_PROVIDER_FAILED, exit 1",
        "execution": execution,
        "observed": {**observed, "shim_elapsed_ms": elapsed_ms},
        **verdict(checks),
    }


def control_interruption_and_recovery(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("interruption_and_recovery")
    run = workdir / "run"
    command = entry_command(ctx, "build", run)
    started = time.monotonic()
    build = start(command, workdir, "build")
    request_path: Path | None = None

    def model_called() -> bool:
        nonlocal request_path
        found = sorted(run.glob("handoff/call-*/request.json"))
        request_path = found[0] if found else None
        return request_path is not None or build.poll() is not None

    reached = wait_until(model_called, 180)
    tree = descendants(build.pid)
    observed: dict[str, Any] = {
        "reached_model_call": request_path is not None,
        "seconds_to_model_call": round(time.monotonic() - started, 2),
        "process_tree_at_kill": [
            {"pid": p.pid, "ppid": p.ppid, "pgid": p.pgid, "sid": p.sid, "cmdline": p.cmdline[:300]}
            for p in tree
        ],
        "entry_pgid": build.pid,
    }
    with contextlib.suppress(ProcessLookupError):
        os.killpg(build.pid, signal.SIGKILL)
    code = build.wait(timeout=60)
    observed["entry_exit_code"] = code
    observed["group_gone"] = wait_until(lambda: not group_members(build.pid), 10)
    try:
        os.killpg(build.pid, 0)
        observed["killpg_probe"] = "group still exists"
    except ProcessLookupError:
        observed["killpg_probe"] = "ProcessLookupError (group gone)"
    escaped = [p for p in tree if p.pgid != build.pid and running(p.pid)]
    observed["escaped_the_group_kill"] = [
        {"pid": p.pid, "pgid": p.pgid, "sid": p.sid, "cmdline": p.cmdline[:300]} for p in escaped
    ]
    ledger = run / ".pmpe" / "runs" / RUN_ID / "events.jsonl"
    ledger_after_kill = ledger.read_bytes() if ledger.is_file() else b""
    # Late answer: a session that responds after the interruption must not resurrect the run.
    late: dict[str, Any] = {"attempted": False}
    if request_path is not None:
        message = json.loads(request_path.read_text())
        digest = message["request"]["request_digest"]
        response = {"request_digest": digest, "files": {"product.py": ctx.product_text()}}
        staging = request_path.parent / "response.harness-tmp"
        staging.write_text(json.dumps(response, sort_keys=True) + "\n")
        os.replace(staging, request_path.parent / "response.json")
        late["attempted"] = True
        late["orphans_exited"] = wait_until(lambda: not [p for p in escaped if running(p.pid)], 20)
        late["call_json_after"] = read_json(request_path.parent / "call.json")
        late["output_json_written_by_orphan"] = (request_path.parent / "output.json").exists()
        late["result_json_after_late_answer"] = (run / "result.json").exists()
        late["ledger_unchanged_after_late_answer"] = (
            ledger.read_bytes() == ledger_after_kill if ledger.is_file() else None
        )
    observed["late_answer"] = late
    observed["killed_after_late_answer"] = kill_marked(str(workdir), [p.pid for p in tree])
    observed["interrupted"] = collect(ctx, run, code)
    listing_before = sorted(str(p.relative_to(run)) for p in run.rglob("*"))
    reuse = run_entry(
        ctx, entry_command(ctx, "verify", run, candidate=ctx.candidate), workdir, label="reuse"
    )
    observed["same_output_rerun"] = {
        **reuse,
        "listing_unchanged": sorted(str(p.relative_to(run)) for p in run.rglob("*"))
        == listing_before,
        "ledger_unchanged": (ledger.read_bytes() if ledger.is_file() else b"") == ledger_after_kill,
    }
    fresh = workdir / "recovered"
    recovery = run_entry(
        ctx, entry_command(ctx, "verify", fresh, candidate=ctx.candidate), workdir, label="recovery"
    )
    observed["fresh_output_recovery"] = {
        **recovery,
        "observed": collect(ctx, fresh, recovery["exit_code"]),
    }
    interrupted = observed["interrupted"]
    status = ((interrupted.get("status_cli") or {}).get("stdout_json")) or {}
    checks = [
        (
            "build reached the model call (after meaningful RED)",
            reached and request_path is not None,
        ),
        ("entry killed by SIGKILL (exit -9)", code == -signal.SIGKILL),
        (
            "no process of the killed group survives",
            observed["group_gone"] and observed["killpg_probe"].startswith("ProcessLookupError"),
        ),
        ("no result.json", interrupted["result_json"] is None),
        (
            "ledger ends at meaningful_red_confirmed",
            interrupted.get("ledger_events") == ["contract_validated", "meaningful_red_confirmed"],
        ),
        (
            "status CLI: BUILDING / IN_PROGRESS, not RELEASE_READY",
            status.get("state") == "BUILDING" and status.get("cause") == "IN_PROGRESS",
        ),
        (
            "regression classifier labels it BLOCKED (not complete)",
            (interrupted.get("classification") or {}).get("outcome") == "BLOCKED",
        ),
        (
            "a late answer does not create result.json",
            not late.get("result_json_after_late_answer", False),
        ),
        (
            "a late answer does not change the ledger",
            late.get("ledger_unchanged_after_late_answer") in {True, None},
        ),
        (
            "same --output is refused (FileExistsError, nonzero)",
            reuse["exit_code"] != 0 and "FileExistsError" in reuse["stderr_tail"],
        ),
        (
            "refused re-run changed nothing",
            observed["same_output_rerun"]["listing_unchanged"]
            and observed["same_output_rerun"]["ledger_unchanged"],
        ),
        (
            "fresh --output verify succeeds 14/14",
            recovery["exit_code"] == 0 and all_pass(observed["fresh_output_recovery"]["observed"]),
        ),
        ("no leftover process after cleanup", not marked(str(workdir))),
    ]
    return {
        "layer": "entry+engine+shim+CLI",
        "expected": "SIGKILL during the model wait leaves no result.json, ledger stops before the model "
        "response, status IN_PROGRESS; recovery only into a fresh output directory",
        "execution": {"command_shell": shlex.join(command)},
        "observed": observed,
        **verdict(checks),
    }


def control_wrong_freeze_digest(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("wrong_freeze_digest")
    run = workdir / "run"
    execution = run_entry(
        ctx, entry_command(ctx, "verify", run, candidate=ctx.candidate, digest=ZERO_DIGEST), workdir
    )
    observed = collect(ctx, run, execution["exit_code"])
    checks = [
        ("nonzero exit", execution["exit_code"] != 0),
        ("FREEZE_DIGEST_MISMATCH reported", "FREEZE_DIGEST_MISMATCH" in execution["stderr_tail"]),
        ("no result.json", observed["result_json"] is None),
        (
            "no digest check or candidate process started",
            observed["digest_checks"] is None and observed["candidate_process_records"] is None,
        ),
    ]
    return {
        "layer": "entry (DigestGuard constructor)",
        "expected": "FREEZE_DIGEST_MISMATCH, nonzero, no result.json",
        "execution": execution,
        "observed": observed,
        "note": "The guard is constructed outside the entry's try block: the refusal is an uncaught "
        "TamperDetectedError (exit 1, traceback) and leaves NO failure.json; the regression "
        "classifier reports it as BLOCKED/NO_RESULT.",
        **verdict(checks),
    }


def control_missing_candidate(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("missing_candidate")
    run = workdir / "run"
    execution = run_entry(ctx, entry_command(ctx, "verify", run), workdir)
    observed = collect(ctx, run, execution["exit_code"])
    failure = observed["failure_json"] or {}
    checks = [
        ("exit code 2", execution["exit_code"] == 2),
        (
            "failure.json says --candidate is required",
            "--candidate is required" in str(failure.get("detail")),
        ),
        ("no result.json", observed["result_json"] is None),
        ("no candidate process ran", not observed["candidate_process_records"]),
    ]
    return {
        "layer": "entry",
        "expected": "verify without --candidate -> exit 2, failure.json '--candidate is required', no result.json",
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


def control_missing_fallback(ctx: Ctx, mode: str) -> dict[str, Any]:
    workdir = ctx.fresh(f"missing_fallback_{mode}")
    run = workdir / "run"
    command = entry_command(
        ctx, mode, run, candidate=ctx.candidate if mode == "verify" else None, fallback=False
    )
    execution = run_entry(ctx, command, workdir)
    observed = collect(ctx, run, execution["exit_code"])
    failure = observed["failure_json"] or {}
    compatibility = observed["compatibility"] or {}
    checks = [
        ("exit code 2", execution["exit_code"] == 2),
        (
            "failure.json names HOST_FALLBACK_NOT_AUTHORIZED",
            "HOST_FALLBACK_NOT_AUTHORIZED" in str(failure.get("detail")),
        ),
        ("compatibility.json compatible == false", compatibility.get("compatible") is False),
        (
            "compatibility reasons include HOST_FALLBACK_NOT_AUTHORIZED",
            any(
                str(r).startswith("HOST_FALLBACK_NOT_AUTHORIZED")
                for r in compatibility.get("reasons") or []
            ),
        ),
        ("no result.json", observed["result_json"] is None),
        ("no handoff directory", not (run / "handoff").exists()),
        (
            "no candidate process (processes.jsonl absent or empty)",
            not observed["candidate_process_records"],
        ),
    ]
    return {
        "layer": "entry (compatibility)",
        "expected": f"{mode} without --authorized-host-fallback -> exit 2, HOST_FALLBACK_NOT_AUTHORIZED, "
        "compatible false, nothing executed",
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


def copy_candidate(ctx: Ctx, destination: Path) -> Path:
    shutil.copytree(ctx.candidate, destination, ignore=shutil.ignore_patterns("__pycache__"))
    return destination


def replace_once(path: Path, find: str, replace: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if text.count(find) != 1:
        return False
    path.write_text(text.replace(find, replace), encoding="utf-8")
    return True


def control_product_mutation(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("product_mutation_status_filter_ignored")
    mutated = copy_candidate(ctx, workdir / "mutated-candidate")
    applied = replace_once(mutated / "product.py", ctx.mutation_find, ctx.mutation_replace)
    if not applied:
        return {
            "layer": "entry+evaluator",
            "verdict": "NOT_APPLICABLE",
            "note": f"mutation pattern {ctx.mutation_find!r} not found exactly once in product.py; "
            "pass --mutation-find/--mutation-replace for this candidate",
        }
    run = workdir / "run"
    execution = run_entry(ctx, entry_command(ctx, "verify", run, candidate=mutated), workdir)
    observed = collect(ctx, run, execution["exit_code"])
    failing = failed_criteria(observed)
    expected_failures = EXPECTED_FILTER_FAILURES if ctx.mutation_find == FILTER_FIND else None
    checks = [
        ("exit code 1", execution["exit_code"] == 1),
        ("at least one criterion FAILs", bool(failing)),
        ("AC-004 (status filters) FAILs", "AC-004" in (failing or [])),
    ]
    if expected_failures is not None:
        checks.append(
            (
                f"failing set equals the recorded known answer {expected_failures}",
                failing == expected_failures,
            )
        )
    return {
        "layer": "entry+evaluator",
        "expected": "list ignores --status -> the filter criteria FAIL, exit 1",
        "mutation": {
            "file": "product.py",
            "find": ctx.mutation_find,
            "replace": ctx.mutation_replace,
        },
        "execution": execution,
        "observed": {**observed, "failing_criteria": failing},
        **verdict(checks),
    }


def control_evaluator_mutation(ctx: Ctx) -> dict[str, Any]:
    workdir = ctx.fresh("evaluator_mutation_in_candidate")
    mutated = copy_candidate(ctx, workdir / "mutated-candidate")
    applied = replace_once(mutated / EVALUATOR_FILE, EVALUATOR_FIND, EVALUATOR_REPLACE)
    if not applied:
        return {
            "layer": "entry guard",
            "verdict": "NOT_APPLICABLE",
            "note": "evaluator pattern not found",
        }
    run = workdir / "run"
    execution = run_entry(ctx, entry_command(ctx, "verify", run, candidate=mutated), workdir)
    observed = collect(ctx, run, execution["exit_code"])
    failure = observed["failure_json"] or {}
    checks = [
        ("exit code 2", execution["exit_code"] == 2),
        (
            "TamperDetectedError APPROVAL_BOUND_ARTIFACT_CHANGED",
            failure.get("error") == "TamperDetectedError"
            and str(failure.get("detail")).startswith("APPROVAL_BOUND_ARTIFACT_CHANGED"),
        ),
        ("the mismatch names the evaluator", EVALUATOR_FILE in str(failure.get("detail"))),
        ("no criterion process executed", not observed["candidate_process_records"]),
        ("no result.json", observed["result_json"] is None),
    ]
    return {
        "layer": "entry guard (protected tests/ files)",
        "expected": "candidate's evaluator changed -> APPROVAL_BOUND_ARTIFACT_CHANGED before the first "
        "criterion process, exit 2",
        "mutation": {"file": EVALUATOR_FILE, "find": EVALUATOR_FIND, "replace": EVALUATOR_REPLACE},
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


def copy_packet(ctx: Ctx, destination: Path) -> tuple[Path, Path, dict[str, Any]]:
    """Copy the PMOS-bound files and the manifest bytes verbatim into a disposable root."""
    relative = ctx.packet.resolve().relative_to(ctx.pmos.resolve())
    manifest = json.loads((ctx.packet / "freeze-manifest.json").read_text())
    for item in manifest["artifacts"]:
        if item["repository"] == PMOS:
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ctx.pmos / item["path"], target)
    packet = destination / relative
    packet.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ctx.packet / "freeze-manifest.json", packet / "freeze-manifest.json")
    return destination, packet, manifest


def mutate_contract(packet: Path) -> dict[str, Any]:
    """Weaken AC-001: drop its last `then` assertion (a semantic, digest-changing edit)."""
    path = packet / "contract.approved.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    criterion = next(item for item in contract["acceptance_criteria"] if item["id"] == "AC-001")
    removed = criterion["then"].pop()
    path.write_text(
        json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return {"criterion": "AC-001", "removed_then_assertion": removed}


def control_contract_mutation(ctx: Ctx, refrozen: bool) -> dict[str, Any]:
    name = "contract_mutation_refrozen" if refrozen else "contract_mutation_after_freeze"
    workdir = ctx.fresh(name)
    root, packet, manifest = copy_packet(ctx, workdir / "pmos-copy")
    edit = mutate_contract(packet)
    digest = ctx.freeze_digest
    if refrozen:
        fixture = regenerate_manifest(
            manifest,
            {PMOS: root, PEOS: ctx.peos},
            "negative control: refrozen over a mutated contract copy; simulates an attacker who also "
            "recomputes the freeze. Not approval.",
        )
        (packet / "freeze-manifest.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n"
        )
        digest = canonical_digest(fixture)
    run = workdir / "run"
    command = entry_command(
        ctx, "verify", run, candidate=ctx.candidate, digest=digest, packet=packet, pmos_root=root
    )
    execution = run_entry(ctx, command, workdir)
    observed = collect(ctx, run, execution["exit_code"])
    failure = observed["failure_json"] or {}
    checks = [
        ("exit code 2", execution["exit_code"] == 2),
        ("no criterion executed", not observed["candidate_process_records"]),
        ("no result.json", observed["result_json"] is None),
    ]
    if refrozen:
        checks.append(
            (
                "refused by approval binding (ContractInvalidError)",
                failure.get("error") == "ContractInvalidError",
            )
        )
        expected = "contract edited and freeze recomputed -> refused by the approval receipt binding, exit 2"
    else:
        checks.append(
            (
                "APPROVAL_BOUND_ARTIFACT_CHANGED names contract.approved.json",
                str(failure.get("detail")).startswith("APPROVAL_BOUND_ARTIFACT_CHANGED")
                and "contract.approved.json" in str(failure.get("detail")),
            )
        )
        expected = (
            "contract edited under the existing freeze -> APPROVAL_BOUND_ARTIFACT_CHANGED, exit 2"
        )
    return {
        "layer": "entry guard / approval binding",
        "expected": expected,
        "mutation": edit,
        "freeze_digest_used": digest,
        "execution": execution,
        "observed": observed,
        **verdict(checks),
    }


# --------------------------------------------------------------------------- product CLI


def cap_dac_override_effective() -> bool | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("CapEff:"):
                return bool(int(line.split()[1], 16) & 0b10)
    except OSError:
        return None
    return None


def product_call(
    ctx: Ctx, workdir: Path, store: Path, arguments: list[str], prefix: list[str] | None = None
) -> dict[str, Any]:
    command = [
        *(prefix or []),
        ctx.python,
        "-I",
        "-B",
        str(workdir / "product.py"),
        "--store",
        str(store),
        *arguments,
    ]
    completed = subprocess.run(
        command, cwd=workdir, capture_output=True, text=True, timeout=20, check=False
    )
    try:
        output: Any = json.loads(completed.stdout)
    except ValueError:
        output = None
    return {
        "args": shlex.join(arguments),
        "command_shell": shlex.join(command),
        "exit_code": completed.returncode,
        "stdout_json": output,
        "stdout_tail": tail(completed.stdout, 500),
        "stderr_tail": tail(completed.stderr, 500),
    }


def product_workdir(ctx: Ctx, name: str) -> Path:
    workdir = ctx.fresh(name)
    shutil.copyfile(ctx.candidate / "product.py", workdir / "product.py")
    return workdir


def store_digest(store: Path) -> str | None:
    return sha256_file(store)


def expect_error(call: dict[str, Any], code: int, error: str) -> bool:
    return bool(call["exit_code"] == code and call["stdout_json"] == {"error": error})


def control_cli_invalid_inputs(ctx: Ctx) -> list[dict[str, Any]]:
    results = []
    # empty / whitespace title on a fresh store: INVALID_TITLE, exit 2, no store created
    for name, title in (("cli_empty_title", ""), ("cli_whitespace_title", "   ")):
        workdir = product_workdir(ctx, name)
        store = workdir / "tasks.json"
        call = product_call(ctx, workdir, store, ["create", title])
        results.append(
            {
                "name": name,
                "layer": "product CLI",
                "expected": "INVALID_TITLE, exit 2, no task and no store created",
                "calls": [call],
                **verdict(
                    [
                        ("INVALID_TITLE exit 2", expect_error(call, 2, "INVALID_TITLE")),
                        ("store not created", not store.exists()),
                    ]
                ),
            }
        )
    # invalid ids, missing id, bad status, unknown command against one existing task
    cases = [
        (
            "cli_invalid_id",
            [["complete", "0"], ["complete", "-1"], ["complete", "abc"], ["complete", "1.5"]],
            2,
            "INVALID_ID",
        ),
        ("cli_missing_id_999", [["complete", "999"]], 2, "NOT_FOUND"),
        ("cli_invalid_status", [["list", "--status", "done"]], 2, "INVALID_STATUS"),
    ]
    for name, steps, code, error in cases:
        workdir = product_workdir(ctx, name)
        store = workdir / "tasks.json"
        setup = product_call(ctx, workdir, store, ["create", "alpha"])
        before = store_digest(store)
        calls = [product_call(ctx, workdir, store, step) for step in steps]
        results.append(
            {
                "name": name,
                "layer": "product CLI",
                "expected": f"{error}, exit {code}, existing state unchanged",
                "setup": [setup],
                "calls": calls,
                **verdict(
                    [("setup create succeeded", setup["exit_code"] == 0)]
                    + [
                        (
                            f"{shlex.join(step)} -> {error} exit {code}",
                            expect_error(call, code, error),
                        )
                        for step, call in zip(steps, calls, strict=True)
                    ]
                    + [("store bytes unchanged", store_digest(store) == before)]
                ),
            }
        )
    workdir = product_workdir(ctx, "cli_unknown_command")
    store = workdir / "tasks.json"
    setup = product_call(ctx, workdir, store, ["create", "alpha"])
    before = store_digest(store)
    call = product_call(ctx, workdir, store, ["frobnicate"])
    results.append(
        {
            "name": "cli_unknown_command",
            "layer": "product CLI",
            "expected": "exit 2 (invalid input), state unchanged",
            "setup": [setup],
            "calls": [call],
            "protocol_observation": {
                "json_error_on_stdout": isinstance(call["stdout_json"], dict)
                and "error" in call["stdout_json"],
                "note": "No approved criterion covers unknown commands; the protocol line says errors return "
                "{error:CODE}. Reported, not scored.",
            },
            **verdict(
                [
                    ("exit 2", call["exit_code"] == 2),
                    ("store bytes unchanged", store_digest(store) == before),
                ]
            ),
        }
    )
    return results


def control_cli_store_failures(ctx: Ctx) -> list[dict[str, Any]]:
    results = []
    # malformed JSON store: STORE_INVALID exit 1, original bytes preserved, no silent reset
    workdir = product_workdir(ctx, "cli_malformed_store")
    store = workdir / "tasks.json"
    store.write_bytes(b"{invalid storage\n")
    before = store_digest(store)
    calls = [
        product_call(ctx, workdir, store, step)
        for step in (["list"], ["create", "beta"], ["complete", "1"])
    ]
    results.append(
        {
            "name": "cli_malformed_store",
            "layer": "product CLI",
            "expected": "STORE_INVALID, exit 1 for list/create/complete; bytes preserved",
            "calls": calls,
            **verdict(
                [
                    (
                        f"{c['args']} -> STORE_INVALID exit 1",
                        expect_error(c, 1, "STORE_INVALID"),
                    )
                    for c in calls
                ]
                + [("store bytes preserved", store_digest(store) == before)]
            ),
        }
    )
    # store path is a directory (inaccessible regardless of privileges)
    workdir = product_workdir(ctx, "cli_store_is_directory")
    store = workdir / "store-dir"
    store.mkdir()
    calls = [product_call(ctx, workdir, store, step) for step in (["list"], ["create", "beta"])]
    results.append(
        {
            "name": "cli_store_is_directory",
            "layer": "product CLI",
            "expected": "STORE_IO, exit 1, never acknowledges",
            "calls": calls,
            **verdict(
                [
                    (
                        f"{c['args']} -> STORE_IO exit 1",
                        expect_error(c, 1, "STORE_IO"),
                    )
                    for c in calls
                ]
                + [("directory left empty", not any(store.iterdir()))]
            ),
        }
    )
    # store parent is a regular file (AC-012 shape)
    workdir = product_workdir(ctx, "cli_store_parent_is_file")
    blocker = workdir / "parent-is-a-file"
    blocker.write_text("fixture\n")
    store = blocker / "tasks.json"
    calls = [product_call(ctx, workdir, store, step) for step in (["create", "beta"], ["list"])]
    results.append(
        {
            "name": "cli_store_parent_is_file",
            "layer": "product CLI",
            "expected": "STORE_IO, exit 1, never acknowledges success",
            "calls": calls,
            **verdict(
                [
                    (
                        f"{c['args']} -> STORE_IO exit 1",
                        expect_error(c, 1, "STORE_IO"),
                    )
                    for c in calls
                ]
            ),
        }
    )
    # permission-denied store: chmod 000 on the file, then on its directory
    setpriv = shutil.which("setpriv")
    drop = [setpriv, "--bounding-set=-dac_override,-dac_read_search", "--"] if setpriv else None
    for name, target_is_dir in (
        ("cli_inaccessible_store_chmod_file", False),
        ("cli_inaccessible_store_chmod_dir", True),
    ):
        workdir = product_workdir(ctx, name)
        directory = workdir / "locked"
        directory.mkdir()
        store = directory / "tasks.json"
        setup = product_call(ctx, workdir, store, ["create", "alpha"])
        locked = directory if target_is_dir else store
        original_mode = locked.stat().st_mode & 0o777
        locked.chmod(0)
        try:
            # Read-only probe: a mutating command run with a permission bypass would replace
            # the locked file (os.replace) and invalidate the control.
            as_is = [product_call(ctx, workdir, store, ["list"])]
            bypass = os.geteuid() == 0 and as_is[0]["exit_code"] == 0
            before = store_digest(store)
            scored_prefix = drop if bypass else None
            dropped = (
                [
                    product_call(ctx, workdir, store, step, prefix=scored_prefix)
                    for step in (["list"], ["create", "beta"])
                ]
                if (drop or not bypass)
                else []
            )
            after = store_digest(store)
        finally:
            locked.chmod(original_mode)
        record: dict[str, Any] = {
            "name": name,
            "layer": "product CLI",
            "expected": "STORE_IO, exit 1, store unchanged when the store cannot be read",
            "euid": os.geteuid(),
            "cap_dac_override_effective": cap_dac_override_effective(),
            "root_bypass_observed": bypass,
            "setup": [setup],
            "read_only_probe_as_current_user": as_is,
            "scored_calls": dropped,
            "scored_calls_mode": "uid 0 without CAP_DAC_OVERRIDE/CAP_DAC_READ_SEARCH (setpriv)"
            if bypass
            else "current user, permissions enforced",
            "note": (
                "Running as uid 0 with CAP_DAC_OVERRIDE: mode 000 is not enforced, so the plain run "
                "cannot exercise STORE_IO. The scored run drops CAP_DAC_OVERRIDE and "
                "CAP_DAC_READ_SEARCH with setpriv so uid 0 is subject to the mode bits."
            )
            if bypass
            else "Permission bits were enforced for the current user.",
        }
        if drop is None and bypass:
            record.update(
                {
                    "verdict": "NOT_APPLICABLE",
                    "checks": [],
                    "note": record["note"] + " setpriv unavailable; not scored.",
                }
            )
        else:
            record.update(
                verdict(
                    [("setup create succeeded", setup["exit_code"] == 0)]
                    + [
                        (
                            f"{c['args']} -> STORE_IO exit 1",
                            expect_error(c, 1, "STORE_IO"),
                        )
                        for c in dropped
                    ]
                    + [("store bytes unchanged by the scored calls", after == before)]
                )
            )
        results.append(record)
    return results


# --------------------------------------------------------------------------- driver

ENGINE_CONTROLS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "wrong_provider_digest": control_wrong_provider_digest,
    "stale_response_other_call": control_stale_response_other_call,
    "stale_response_identical_request_replay": control_stale_response_identical_request_replay,
    "missing_model_response_shim_bounded": control_missing_model_response_shim,
    "interruption_and_recovery": control_interruption_and_recovery,
    "wrong_freeze_digest": control_wrong_freeze_digest,
    "missing_candidate": control_missing_candidate,
    "missing_fallback_verify": lambda ctx: control_missing_fallback(ctx, "verify"),
    "missing_fallback_build": lambda ctx: control_missing_fallback(ctx, "build"),
    "product_mutation_status_filter_ignored": control_product_mutation,
    "evaluator_mutation_in_candidate": control_evaluator_mutation,
    "contract_mutation_after_freeze": lambda ctx: control_contract_mutation(ctx, refrozen=False),
    "contract_mutation_refrozen": lambda ctx: control_contract_mutation(ctx, refrozen=True),
}
SLOW_CONTROLS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "missing_model_response_engine_slow": control_missing_model_response_engine,
}
PRODUCT_GROUPS: dict[str, Callable[[Ctx], list[dict[str, Any]]]] = {
    "cli_invalid_inputs": control_cli_invalid_inputs,
    "cli_store_failures": control_cli_store_failures,
}


def guarded(name: str, function: Callable[[], Any]) -> list[dict[str, Any]]:
    started = time.monotonic()
    try:
        produced = function()
    except Exception as exc:  # a harness error is not a control result
        return [
            {
                "name": name,
                "verdict": "HARNESS_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-4000:],
            }
        ]
    records = produced if isinstance(produced, list) else [{"name": name, **produced}]
    for record in records:
        record.setdefault("wall_s", round(time.monotonic() - started, 2))
    return records


def global_entry_processes() -> list[dict[str, Any]]:
    """Live entry/shim processes anywhere on the host (other workers included; informational)."""
    rows = []
    for item in processes():
        if item.state in DEAD:
            continue
        if "contract-file.py" in item.cmdline or "session-file-provider.py" in item.cmdline:
            rows.append({"pid": item.pid, "pgid": item.pgid, "cmdline": item.cmdline[:300]})
    return rows


def git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return completed.stdout.strip() or "unknown"


def prepare_fixture(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="negative-controls.py prepare-fixture")
    parser.add_argument("--pmos", type=Path, required=True)
    parser.add_argument("--peos", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True, help="must not exist")
    args = parser.parse_args(arguments)
    pmos, peos, dest = args.pmos.resolve(), args.peos.resolve(), args.dest.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    root = dest / "pmos-fixture"
    active = json.loads((pmos / PACKET_RELATIVE / "freeze-manifest.json").read_text())
    for item in active["artifacts"]:
        if item["repository"] == PMOS:
            target = root / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pmos / item["path"], target)
    fixture = regenerate_manifest(
        active,
        {PMOS: root, PEOS: peos},
        "HARNESS DRY-RUN FIXTURE: regenerated over the disposable copies' and PEOS's current bytes. "
        "NOT an approval; never copy into the real packet.",
    )
    manifest_path = root / PACKET_RELATIVE / "freeze-manifest.json"
    manifest_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
    digest = canonical_digest(fixture)
    active_drift = drift(active, {PMOS: pmos, PEOS: peos})
    info = {
        "label": "DISPOSABLE FIXTURE FREEZE - NOT APPROVAL - NOT THE FRESH BUILD",
        "pmos": str(root),
        "packet": str(root / PACKET_RELATIVE),
        "freeze_digest": digest,
        "source_pmos": str(pmos),
        "source_pmos_head": git_head(pmos),
        "peos": str(peos),
        "peos_head": git_head(peos),
        "artifacts": len(fixture["artifacts"]),
        "active_freeze_digest": canonical_digest(active),
        "active_freeze_drift_on_these_bytes": active_drift,
    }
    (dest / "FIXTURE-NOT-APPROVAL.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["prepare-fixture"]:
        return prepare_fixture(argv[1:])
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--peos", type=Path, required=True)
    parser.add_argument("--pmos", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--freeze-digest", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="fresh directory for all controls")
    parser.add_argument("--summary", type=Path, help="summary path (default OUT/summary.json)")
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter for the entry/product"
    )
    parser.add_argument("--label", default="NEGATIVE CONTROLS")
    parser.add_argument("--only", default="", help="comma-separated control/group names")
    parser.add_argument("--skip", default="", help="comma-separated control/group names")
    parser.add_argument(
        "--include-slow",
        action="store_true",
        help="also run the ~9-minute engine timeout control (in a parallel thread)",
    )
    parser.add_argument(
        "--stale-from",
        type=Path,
        help="handoff dir of an earlier run (default: PEOS Sept live/handoff)",
    )
    parser.add_argument(
        "--known-candidate",
        type=Path,
        action="append",
        default=[],
        help="retained candidate dir or product.py whose bytes a fresh build must not equal",
    )
    parser.add_argument("--mutation-find", default=FILTER_FIND)
    parser.add_argument("--mutation-replace", default=FILTER_REPLACE)
    args = parser.parse_args(argv)
    peos = args.peos.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stale = (
        args.stale_from or peos / "docs/evidence/task-tracker-live-20260918/live/handoff"
    ).resolve()
    known_sources = args.known_candidate or [
        peos / "docs/evidence/task-tracker-live-20260918/live/candidate",
        peos / "docs/evidence/task-tracker-completion-20261009/session-authored-product.py",
    ]
    known: dict[str, str] = {}
    for source in known_sources:
        product = source / "product.py" if source.is_dir() else source
        digest = sha256_file(product)
        if digest:
            known[digest] = str(product)
    ctx = Ctx(
        peos=peos,
        pmos=args.pmos.resolve(),
        packet=args.packet.resolve(),
        freeze_digest=args.freeze_digest,
        candidate=args.candidate.resolve(),
        out=out,
        python=args.python,
        stale_from=stale if stale.is_dir() else None,
        known_products=known,
        mutation_find=args.mutation_find,
        mutation_replace=args.mutation_replace,
    )
    only = {item for item in args.only.split(",") if item}
    skip = {item for item in args.skip.split(",") if item}

    def wanted(name: str) -> bool:
        return (not only or name in only) and name not in skip

    summary: dict[str, Any] = {
        "label": args.label,
        "started_at": now(),
        "inputs": {
            "peos": str(peos),
            "peos_head": git_head(peos),
            "pmos": str(ctx.pmos),
            "pmos_head": git_head(ctx.pmos),
            "packet": str(ctx.packet),
            "freeze_digest": ctx.freeze_digest,
            "manifest_canonical_digest": canonical_digest(
                json.loads((ctx.packet / "freeze-manifest.json").read_text())
            ),
            "manifest_status": json.loads((ctx.packet / "freeze-manifest.json").read_text()).get(
                "status"
            ),
            "candidate": str(ctx.candidate),
            "candidate_product_sha256": sha256_file(ctx.candidate / "product.py"),
            "python": ctx.python,
            "stale_from": str(ctx.stale_from) if ctx.stale_from else None,
            "known_retained_products": known,
            "euid": os.geteuid(),
        },
        "entry_processes_on_host_before": global_entry_processes(),
    }
    records: list[dict[str, Any]] = []
    slow_records: list[dict[str, Any]] = []
    slow_threads: list[threading.Thread] = []

    def run_control(name: str, control: Callable[[Ctx], dict[str, Any]]) -> list[dict[str, Any]]:
        print(f"[{now()}] control {name}", flush=True)
        return guarded(name, lambda: control(ctx))

    def run_group(name: str, group: Callable[[Ctx], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        print(f"[{now()}] group {name}", flush=True)
        return guarded(name, lambda: group(ctx))

    def run_slow(name: str, control: Callable[[Ctx], dict[str, Any]]) -> None:
        slow_records.extend(run_control(name, control))

    for slow_name, slow_control in SLOW_CONTROLS.items():
        if args.include_slow and wanted(slow_name):
            thread = threading.Thread(target=run_slow, args=(slow_name, slow_control), daemon=True)
            thread.start()
            slow_threads.append(thread)
        elif wanted(slow_name):
            slow_records.append(
                {
                    "name": slow_name,
                    "verdict": "SKIPPED",
                    "slow": True,
                    "note": "not requested (--include-slow); design time is the 540 s shim "
                    "deadline plus RED",
                }
            )
    for control_name, control in ENGINE_CONTROLS.items():
        if wanted(control_name):
            records += run_control(control_name, control)
    for group_name, group in PRODUCT_GROUPS.items():
        if wanted(group_name):
            records += run_group(group_name, group)
    for thread in slow_threads:
        print(f"[{now()}] waiting for slow controls", flush=True)
        thread.join(timeout=1200)
    records += slow_records
    leftovers = kill_marked(str(out))
    summary.update(
        {
            "finished_at": now(),
            "controls": records,
            "totals": {
                state: len([r for r in records if r.get("verdict") == state])
                for state in ("PASS", "FAIL", "NOT_APPLICABLE", "SKIPPED", "HARNESS_ERROR")
            },
            "findings": [r["finding"] for r in records if r.get("finding")],
            "leftover_processes_under_out_killed_at_end": leftovers,
            "entry_processes_on_host_after": global_entry_processes(),
        }
    )
    destination = args.summary.resolve() if args.summary else out / "summary.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(summary, indent=2, sort_keys=False, default=str) + "\n")
    print(
        json.dumps(
            {
                "summary": str(destination),
                "totals": summary["totals"],
                "verdicts": {r.get("name"): r.get("verdict") for r in records},
            },
            indent=2,
        )
    )
    return 0 if summary["totals"]["FAIL"] == 0 and summary["totals"]["HARNESS_ERROR"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
