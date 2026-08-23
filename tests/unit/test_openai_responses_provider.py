from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _provider_module() -> ModuleType:
    path = Path(__file__).parents[2] / "examples" / "barebones" / "openai-responses-provider.py"
    spec = importlib.util.spec_from_file_location("pmpe_openai_responses_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _message(purpose: str = "code") -> dict[str, Any]:
    return {
        "purpose": purpose,
        "request": {
            "request_digest": "sha256:" + "1" * 64,
            "contract": {"contract_id": "PMOS-E1"},
            "plan": {"plan_digest": "sha256:" + "2" * 64},
            "files": {"product.py": "def health(): return {}\n"},
            "findings": [{"code": "ASSERTION_FAILED", "subject_id": "AC-001"}],
        },
    }


def _api_response(generated: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "model": "gpt-test-2026-01-01",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(generated)}],
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    }


def test_request_uses_stateless_strict_structured_output() -> None:
    provider = _provider_module()

    body = provider._request_body(_message(), "gpt-test")

    assert body["store"] is False
    assert body["max_output_tokens"] == 16_384
    assert body["model"] == "gpt-test"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    assert "Do not propose commands or dependencies" in body["instructions"]


def test_redirects_are_rejected_before_authorization_can_be_forwarded() -> None:
    provider = _provider_module()

    assert (
        provider._RejectRedirects().redirect_request(
            req=object(),
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="https://example.invalid/capture",
        )
        is None
    )


def test_code_output_is_adapted_to_digest_bound_file_mapping() -> None:
    provider = _provider_module()
    message = _message()

    result = provider._provider_response(
        message,
        _api_response(
            {
                "files": [
                    {
                        "path": "product.py",
                        "content": "def health():\n    return {'status': 'ok'}\n",
                    }
                ]
            }
        ),
        "gpt-test",
    )

    assert result["request_digest"] == message["request"]["request_digest"]
    assert result["files"] == {"product.py": "def health():\n    return {'status': 'ok'}\n"}
    assert result["provider_metadata"] == {
        "provider": "openai-responses",
        "model": "gpt-test-2026-01-01",
        "prompt_version": "pmpe-barebones-openai-v1",
        "response_id": "resp_test",
    }
    assert result["usage"]["total_tokens"] == 120


def test_configured_token_prices_record_estimated_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    monkeypatch.setenv("PMPE_OPENAI_INPUT_USD_PER_MILLION", "2.0")
    monkeypatch.setenv("PMPE_OPENAI_OUTPUT_USD_PER_MILLION", "8.0")

    result = provider._provider_response(
        _message(),
        _api_response({"files": []}),
        "gpt-test",
    )

    assert result["usage"]["estimated_cost_usd"] == pytest.approx(0.00036)
    assert result["usage"]["pricing"] == {
        "input_usd_per_million_tokens": 2.0,
        "output_usd_per_million_tokens": 8.0,
        "source": "operator_environment",
    }


def test_advisory_output_remains_non_blocking_and_bound() -> None:
    provider = _provider_module()
    message = _message("advisory_review")

    result = provider._provider_response(
        message,
        _api_response({"summary": "Checks passed; a human may inspect the candidate."}),
        "gpt-test",
    )

    assert result["request_digest"] == message["request"]["request_digest"]
    assert result["summary"] == "Checks passed; a human may inspect the candidate."


def test_duplicate_generated_paths_fail_closed() -> None:
    provider = _provider_module()

    with pytest.raises(SystemExit):
        provider._provider_response(
            _message(),
            _api_response(
                {
                    "files": [
                        {"path": "product.py", "content": "first"},
                        {"path": "product.py", "content": "second"},
                    ]
                }
            ),
            "gpt-test",
        )


def test_incomplete_api_response_fails_closed() -> None:
    provider = _provider_module()
    response = _api_response({"files": []})
    response["status"] = "incomplete"
    response["incomplete_details"] = {"reason": "max_output_tokens"}

    with pytest.raises(SystemExit):
        provider._provider_response(_message(), response, "gpt-test")
