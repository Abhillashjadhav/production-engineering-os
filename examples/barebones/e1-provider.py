#!/usr/bin/env python3
"""Deterministic E1 fixture, not a production model provider."""

import json
import sys

message = json.load(sys.stdin)
request = message["request"]
metadata = {
    "provider": "scripted-fixture",
    "model": "deterministic-e1",
    "prompt_version": "e1-v1",
}
if message["purpose"] == "code":
    response = {
        "request_digest": request["request_digest"],
        "provider_metadata": metadata,
        "files": {
            "product.py": (
                '"""E1 health product."""\n\n'
                "def health() -> dict[str, str]:\n"
                '    return {"status": "ok"}\n'
            )
        },
    }
else:
    response = {
        "request_digest": request["request_digest"],
        "summary": "Deterministic evidence passed; human may release.",
        "provider_metadata": metadata,
    }
json.dump(response, sys.stdout)
