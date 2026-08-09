from __future__ import annotations

import importlib.util
import json
import threading
import urllib.request
from pathlib import Path


def _load_fixture_module():
    script_path = Path(__file__).parent / "fixtures" / "mcp_acceptance_llm_server.py"
    spec = importlib.util.spec_from_file_location(
        "mcp_acceptance_llm_server_under_test", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer fixture-secret-must-not-be-logged",
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def _serve(module, tmp_path: Path):
    state_path = tmp_path / "fixture-events.jsonl"
    server = module.create_server(
        host="127.0.0.1",
        port=0,
        state_path=state_path,
        long_delay_seconds=0.01,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, state_path


def test_fixture_serves_models_and_success_without_logging_prompt_or_secret(tmp_path):
    module = _load_fixture_module()
    server, thread, state_path = _serve(module, tmp_path)
    try:
        base_url = f"http://127.0.0.1:{server.server_port}/v1"
        models = _request_json(f"{base_url}/models")
        response = _request_json(
            f"{base_url}/chat/completions",
            method="POST",
            payload={
                "model": "mcp-acceptance-model",
                "messages": [
                    {
                        "role": "user",
                        "content": "sensitive prompt that must not be logged",
                    }
                ],
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert models["data"][0]["id"] == "mcp-acceptance-model"
    assert models["data"][0]["context_window"] == 65536
    assert response["choices"][0]["message"]["content"] == "MCP隔离验收通过。"
    evidence = state_path.read_text(encoding="utf-8")
    assert "sensitive prompt" not in evidence
    assert "fixture-secret" not in evidence
    event = json.loads(evidence.splitlines()[-1])
    assert event["scenario"] == "success"
    assert event["messageCount"] == 1


def test_fixture_returns_approval_tool_call_then_success_after_tool_result(tmp_path):
    module = _load_fixture_module()
    server, thread, _state_path = _serve(module, tmp_path)
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        request_payload = {
            "model": "mcp-acceptance-model",
            "messages": [
                {"role": "user", "content": "[VIBELUTION_ACCEPTANCE_APPROVAL]"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "python_lint_tool",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "max_issues": {"type": "integer"},
                            },
                        },
                    },
                }
            ],
        }
        first = _request_json(url, method="POST", payload=request_payload)
        tool_call = first["choices"][0]["message"]["tool_calls"][0]
        second_payload = dict(request_payload)
        second_payload["messages"] = [
            *request_payload["messages"],
            first["choices"][0]["message"],
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": '{"status":"ok","issues":[]}',
            },
        ]
        second = _request_json(url, method="POST", payload=second_payload)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert tool_call["function"]["name"] == "python_lint_tool"
    assert json.loads(tool_call["function"]["arguments"]) == {
        "target": "core/external_agent",
        "max_issues": 1,
    }
    assert second["choices"][0]["message"]["content"] == (
        "结论：MCP显式审批验收通过。验证：python_lint_tool 已完成；未修改文件。"
    )


def test_fixture_rejects_non_loopback_bind_address(tmp_path):
    module = _load_fixture_module()

    try:
        module.create_server(
            host="0.0.0.0",
            port=0,
            state_path=tmp_path / "events.jsonl",
            long_delay_seconds=0,
        )
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback fixture bind should fail closed")
