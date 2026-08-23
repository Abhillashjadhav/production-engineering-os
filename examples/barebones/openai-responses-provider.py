#!/usr/bin/env python3
"""Reference real-model provider for the bare-bones PMPE protocol.

This adapter uses the OpenAI Responses API with Structured Outputs. It reads one
PMPE provider request from stdin and writes one PMPE provider response to stdout.
Credentials are read from the environment and are never copied into the response.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, NoReturn

_RESPONSES_URL = "https://api.openai.com/v1/responses"
_PROMPT_VERSION = "pmpe-barebones-openai-v1"
_OUTPUT_LIMIT_BYTES = 1_000_000
_MAX_OUTPUT_TOKENS = 16_384


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Reject every redirect so the bearer token never reaches another URL."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl


def _fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        _fail(f"{name} is required")
    return value


def _schema(purpose: str) -> dict[str, Any]:
    if purpose == "code":
        return {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["files"],
            "additionalProperties": False,
        }
    if purpose == "advisory_review":
        return {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        }
    _fail(f"unsupported provider purpose: {purpose}")


def _instructions(purpose: str) -> str:
    shared = (
        "You are the single bounded Coder behind PMPE's deterministic compiler. "
        "The request contains a contract, compiled plan, current candidate files, "
        "and exact verifier findings. Deterministic verification—not your opinion—"
        "decides whether the candidate passes. Never modify tests, fixtures, or "
        "evidence. Do not propose commands or dependencies. Return only the requested "
        "structured output."
    )
    if purpose == "code":
        return shared + (
            " Return the smallest set of complete UTF-8 file replacements that fixes "
            "the exact findings. Paths must be repository-relative."
        )
    return shared + (
        " Deterministic checks have already passed. Return one concise, non-blocking "
        "human advisory summary; do not claim deployment or production readiness."
    )


def _request_body(message: Mapping[str, Any], model: str) -> dict[str, Any]:
    purpose = message.get("purpose")
    request = message.get("request")
    if not isinstance(purpose, str) or not isinstance(request, Mapping):
        _fail("stdin must contain purpose and request objects")
    return {
        "model": model,
        "store": False,
        "max_output_tokens": _MAX_OUTPUT_TOKENS,
        "instructions": _instructions(purpose),
        "input": json.dumps(request, sort_keys=True, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "pmpe_provider_response",
                "strict": True,
                "schema": _schema(purpose),
            }
        },
    }


def _post(body: Mapping[str, Any], *, api_key: str) -> Mapping[str, Any]:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    request = urllib.request.Request(
        _RESPONSES_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        opener = urllib.request.build_opener(_RejectRedirects)
        with opener.open(request, timeout=120) as response:  # noqa: S310
            raw = response.read(_OUTPUT_LIMIT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(8192).decode("utf-8", errors="replace")
        _fail(f"OpenAI Responses API returned HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        _fail(f"OpenAI Responses API request failed: {exc.reason}")
    if len(raw) > _OUTPUT_LIMIT_BYTES:
        _fail("OpenAI Responses API output exceeded the provider limit")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("OpenAI Responses API returned malformed JSON")
    if not isinstance(parsed, Mapping):
        _fail("OpenAI Responses API returned a non-object response")
    return parsed


def _output_text(response: Mapping[str, Any]) -> str:
    texts: list[str] = []
    output = response.get("output")
    if not isinstance(output, list):
        _fail("OpenAI response has no output items")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
            elif isinstance(part, Mapping) and part.get("type") == "refusal":
                _fail("model refused the provider request")
    if len(texts) != 1:
        _fail("OpenAI response must contain exactly one output_text item")
    return texts[0]


def _provider_response(
    message: Mapping[str, Any], api_response: Mapping[str, Any], model: str
) -> dict[str, Any]:
    request = message.get("request")
    purpose = message.get("purpose")
    assert isinstance(request, Mapping)
    assert isinstance(purpose, str)
    request_digest = request.get("request_digest")
    if not isinstance(request_digest, str):
        _fail("provider request is missing request_digest")
    if api_response.get("status") != "completed":
        detail = api_response.get("incomplete_details")
        _fail("OpenAI response did not complete" + (f": {detail}" if detail else ""))
    try:
        generated = json.loads(_output_text(api_response))
    except json.JSONDecodeError:
        _fail("structured model output was not valid JSON")
    if not isinstance(generated, Mapping):
        _fail("structured model output must be an object")

    usage = api_response.get("usage")
    metadata = {
        "provider": "openai-responses",
        "model": str(api_response.get("model") or model),
        "prompt_version": _PROMPT_VERSION,
        "response_id": str(api_response.get("id") or ""),
    }
    if purpose == "code":
        entries = generated.get("files")
        if not isinstance(entries, list):
            _fail("structured model output is missing files")
        files: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                _fail("each generated file must be an object")
            path, content = entry.get("path"), entry.get("content")
            if not isinstance(path, str) or not isinstance(content, str) or path in files:
                _fail("generated file paths must be unique strings with string content")
            files[path] = content
        result: dict[str, Any] = {"request_digest": request_digest, "files": files}
    else:
        summary = generated.get("summary")
        if not isinstance(summary, str):
            _fail("structured model output is missing summary")
        result = {"request_digest": request_digest, "summary": summary}
    result["provider_metadata"] = metadata
    if isinstance(usage, Mapping):
        recorded_usage = dict(usage)
        input_rate = os.environ.get("PMPE_OPENAI_INPUT_USD_PER_MILLION", "").strip()
        output_rate = os.environ.get("PMPE_OPENAI_OUTPUT_USD_PER_MILLION", "").strip()
        if input_rate and output_rate:
            try:
                input_cost = float(input_rate) * int(usage.get("input_tokens", 0)) / 1_000_000
                output_cost = float(output_rate) * int(usage.get("output_tokens", 0)) / 1_000_000
            except (TypeError, ValueError):
                _fail("configured OpenAI token prices must be non-negative numbers")
            if input_cost < 0 or output_cost < 0:
                _fail("configured OpenAI token prices must be non-negative numbers")
            recorded_usage["estimated_cost_usd"] = round(input_cost + output_cost, 12)
        result["usage"] = recorded_usage
    return result


def main() -> int:
    try:
        message = json.load(sys.stdin)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("stdin must be one UTF-8 JSON object")
    if not isinstance(message, Mapping):
        _fail("stdin must be one JSON object")
    model = _required_environment("PMPE_OPENAI_MODEL")
    api_key = _required_environment("OPENAI_API_KEY")
    body = _request_body(message, model)
    api_response = _post(body, api_key=api_key)
    json.dump(_provider_response(message, api_response, model), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
