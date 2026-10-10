"""Checks the Claude wrapper against a local stand-in for the Messages API.

This proves the request the SDK builds and the way the response is parsed. It
does not prove the real API accepts the request; only a live call does that.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest

from sentinel.agent.prompts import FindingBatch, ObligationBatch
from sentinel.llm import ClaudeLLM, LLMRefusal


class StubApi:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.reply: dict = {}
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["content-length"])
                stub.requests.append(
                    {
                        "path": self.path,
                        "beta": self.headers.get("anthropic-beta", ""),
                        "body": json.loads(self.rfile.read(length)),
                    }
                )
                payload = json.dumps(stub.reply).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def message(self, text: str, stop_reason: str = "end_turn", **extra) -> dict:
        return {
            "id": "msg_stub",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}] if text else [],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 0,
            },
            **extra,
        }


@pytest.fixture
def api():
    stub = StubApi()
    yield stub
    stub.server.shutdown()


def _llm(api: StubApi, settings, **overrides) -> ClaudeLLM:
    client = anthropic.Anthropic(api_key="test-key", base_url=api.url, max_retries=0)
    return ClaudeLLM(settings.model_copy(update=overrides), client=client)


FINDINGS = {
    "findings": [
        {
            "file": "db.py",
            "line_start": 78,
            "line_end": 78,
            "code_quote": 'user["password"] == password',
            "regulation_quote": "shall not store a user password in plain text",
            "severity": "critical",
            "confidence": 0.9,
            "explanation": "e",
            "remediation": "r",
        }
    ]
}


def test_request_carries_schema_effort_cached_context_and_fallback(api, settings):
    api.reply = api.message(json.dumps(FINDINGS))
    llm = _llm(api, settings)

    result = llm.parse("system text", "repository source", "the obligation", FindingBatch)

    assert result.findings[0].file == "db.py" and result.findings[0].severity == "critical"
    [request] = api.requests
    body = request["body"]
    assert request["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in request["beta"]
    assert body["fallbacks"] == "default"
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == "system text"
    assert body["output_config"]["effort"] == "medium"
    schema = body["output_config"]["format"]
    assert schema["type"] == "json_schema" and "findings" in json.dumps(schema)
    # Sampling and thinking parameters are rejected by this model, so none are sent.
    assert not {"temperature", "top_p", "thinking", "tool_choice"} & set(body)

    context, task = body["messages"][0]["content"]
    assert context["text"] == "repository source"
    assert context["cache_control"] == {"type": "ephemeral"}
    assert task == {"type": "text", "text": "the obligation"}

    assert (llm.usage.calls, llm.usage.input_tokens, llm.usage.output_tokens) == (1, 120, 30)
    assert llm.usage.cache_read_tokens == 100


def test_fallbacks_can_be_switched_off(api, settings):
    api.reply = api.message(json.dumps({"obligations": []}))
    llm = _llm(api, settings, enable_fallbacks=False)

    assert llm.parse("s", "", "sections", ObligationBatch).obligations == []
    [request] = api.requests
    assert "fallbacks" not in request["body"]
    assert "server-side-fallback" not in request["beta"]
    # With no context there is a single uncached block.
    assert request["body"]["messages"][0]["content"] == [{"type": "text", "text": "sections"}]


def test_refusal_is_raised_as_its_own_error(api, settings):
    api.reply = api.message(
        "",
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )
    with pytest.raises(LLMRefusal, match="cyber"):
        _llm(api, settings).parse("s", "c", "t", FindingBatch)


def test_truncated_output_is_an_error_not_an_empty_result(api, settings):
    api.reply = api.message('{"findings": [', stop_reason="max_tokens")
    with pytest.raises(Exception, match="max_tokens|parse|JSON|valid"):
        _llm(api, settings).parse("s", "c", "t", FindingBatch)
