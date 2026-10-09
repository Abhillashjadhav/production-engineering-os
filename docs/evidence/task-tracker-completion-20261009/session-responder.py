#!/usr/bin/env python3
"""Deliver this session's pre-authored model responses to the file-handoff shim.

The session (the model) authored product.py before launch; this script only
watches OUTPUT/handoff/call-*/request.json and writes the adjacent response.json
with the same request_digest. It is transport, not generation. It records every
delivered call in deliveries.jsonl for the evidence trail.
"""
import json, os, sys, time, pathlib

handoff = pathlib.Path(sys.argv[1]); product = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
log = pathlib.Path(sys.argv[3]); deadline = time.monotonic() + float(sys.argv[4]) if len(sys.argv) > 4 else None
mode = sys.argv[5] if len(sys.argv) > 5 else "normal"
done = set()
while deadline is None or time.monotonic() < deadline:
    for call in sorted(handoff.glob("call-*")) if handoff.exists() else []:
        req = call / "request.json"; resp = call / "response.json"
        if call.name in done or not req.exists() or resp.exists():
            continue
        message = json.loads(req.read_text(encoding="utf-8"))
        digest = message["request"]["request_digest"]
        if message["purpose"] == "code":
            response = {"request_digest": digest, "files": {"product.py": product}}
        else:
            response = {"request_digest": digest, "annotation": (
                "Same-session advisory, non-blocking and not independent review: the candidate "
                "implements PMOS-TASK-TRACKER-001 with manual argument parsing so every error "
                "path emits documented JSON; create is intentionally non-idempotent; concurrent "
                "writers and crash durability remain out of approved scope.")}
        if mode == "bad-digest":
            response["request_digest"] = "sha256:" + "0" * 64
        if mode == "silent":
            done.add(call.name); continue
        tmp = call / "response.tmp"
        tmp.write_text(json.dumps(response, sort_keys=True) + "\n", encoding="utf-8"); os.replace(tmp, resp)
        with log.open("a") as stream:
            stream.write(json.dumps({"call": call.name, "purpose": message["purpose"], "request_digest": digest, "mode": mode, "at": time.time()}) + "\n")
        done.add(call.name); print("responded", call.name, message["purpose"], flush=True)
    time.sleep(0.2)
