#!/usr/bin/env python3
"""A retained JSON handoff to the current agent session; no model API is called.

The orchestrator reads call-*/request.json and atomically writes the adjacent
response.json. This transport needs an agent session and cannot reproduce a
model completion headlessly. It does not isolate the builder or authorize it.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LIMIT = 1_000_000
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def decode(source: bytes) -> Any:
    return json.loads(source, object_pairs_hook=unique_object)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-dir", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    call_dir: Path | None = None
    record: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "status": "waiting",
        "responder": "current-agent-session",
        "headless_reproduction": False,
    }
    try:
        outer_timeout = float(os.environ.get("PMPE_PROVIDER_TIMEOUT_SECONDS", "300"))
        if not math.isfinite(outer_timeout) or outer_timeout <= 0:
            raise ValueError("TIMEOUT_INVALID")
        deadline = started + outer_timeout * 0.9
        source = sys.stdin.buffer.read(LIMIT + 1)
        if len(source) > LIMIT:
            raise ValueError("REQUEST_TOO_LARGE")
        message = decode(source)
        if not isinstance(message, dict) or message.get("purpose") not in {
            "code", "advisory_review"
        }:
            raise ValueError("REQUEST_INVALID")
        request = message.get("request")
        digest = request.get("request_digest") if isinstance(request, dict) else None
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError("REQUEST_DIGEST_INVALID")
        args.handoff_dir.mkdir(parents=True, exist_ok=True)
        call_dir = args.handoff_dir.resolve() / ("call-" + uuid.uuid4().hex)
        call_dir.mkdir(mode=0o700)
        record.update({"request_digest": digest, "purpose": message["purpose"]})
        atomic_json(call_dir / "request.json", message)
        atomic_json(call_dir / "call.json", record)
        response_path = call_dir / "response.json"
        while not os.path.lexists(response_path):
            if time.monotonic() >= deadline:
                raise ValueError("RESPONSE_TIMEOUT")
            time.sleep(0.05)
        try:
            descriptor = os.open(response_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("response must be a regular file")
                response_bytes = stream.read(LIMIT + 1)
            if len(response_bytes) > LIMIT:
                raise ValueError("response too large")
            response = decode(response_bytes)
            if not isinstance(response, dict):
                raise ValueError("response must be an object")
        except (OSError, ValueError) as exc:
            raise ValueError("RESPONSE_INVALID") from exc
        if response.get("request_digest") != digest:
            raise ValueError("RESPONSE_DIGEST_MISMATCH")
        response["provider_metadata"] = {
            "provider": "in-session-file-handoff",
            "model": "session-model-unreported",
            "prompt_version": "session-file-v1",
        }
        output = json.dumps(response, sort_keys=True, allow_nan=False)
        if len(output.encode("utf-8")) > LIMIT:
            raise ValueError("RESPONSE_INVALID")
        atomic_json(call_dir / "output.json", response)
        record.update({"status": "completed", "elapsed_ms": (time.monotonic() - started) * 1000})
        atomic_json(call_dir / "call.json", record)
        print(output)
        return 0
    except (OSError, ValueError) as exc:
        record.update({
            "status": "failed",
            "error": str(exc),
            "elapsed_ms": (time.monotonic() - started) * 1000,
        })
        if call_dir is not None:
            atomic_json(call_dir / "call.json", record)
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
