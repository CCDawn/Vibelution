#!/usr/bin/env python3
"""Deterministic loopback OpenAI-compatible server for MCP acceptance only."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

MODEL_ID = "mcp-acceptance-model"
MAX_REQUEST_BYTES = 2 * 1024 * 1024


class FixtureState:
    def __init__(self, *, state_path: Path, long_delay_seconds: float) -> None:
        self.state_path = state_path.resolve()
        self.long_delay_seconds = max(0.0, min(float(long_delay_seconds), 120.0))
        self._lock = threading.Lock()
        self._sequence = 0

    def next_id(self) -> str:
        with self._lock:
            self._sequence += 1
            return f"chatcmpl-mcp-acceptance-{self._sequence:06d}"

    def record(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self.state_path.open(
            "a", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(line + "\n")


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, dict):
                chunks.append(_content_text(item.get("text") or item.get("content")))
        return "\n".join(chunks)
    return ""


def _tool_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in payload.get("tools") or []:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _tool_arguments(tool_name: str) -> dict[str, Any]:
    if tool_name == "python_lint_tool":
        return {"target": "core/external_agent", "max_issues": 1}
    return {}


def _completion(
    state: FixtureState,
    *,
    message: dict[str, Any],
    finish_reason: str,
) -> dict[str, Any]:
    return {
        "id": state.next_id(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 16,
            "completion_tokens": 8,
            "total_tokens": 24,
        },
    }


def _handler_for(state: FixtureState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "VibelutionMcpAcceptanceLLM/1.0"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send_json(200, {"status": "ok", "model": MODEL_ID})
                return
            if path == "/v1/models":
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "data": [
                            {
                                "id": MODEL_ID,
                                "object": "model",
                                "owned_by": "vibelution-acceptance",
                                "context_window": 65536,
                            }
                        ],
                    },
                )
                return
            self._send_json(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/v1/chat/completions":
                self._send_json(404, {"error": {"message": "not found"}})
                return
            try:
                content_length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                content_length = 0
            if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": {"message": "invalid request size"}})
                return
            try:
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": {"message": "invalid json"}})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": {"message": "invalid payload"}})
                return

            messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
            prompt_text = "\n".join(
                _content_text(item.get("content"))
                for item in messages
                if isinstance(item, dict)
            )
            has_tool_result = any(
                isinstance(item, dict) and str(item.get("role") or "") == "tool"
                for item in messages
            )
            tool_names = _tool_names(payload)
            scenario = "success"
            if "[VIBELUTION_ACCEPTANCE_APPROVAL]" in prompt_text:
                scenario = "approval"
            elif "[VIBELUTION_ACCEPTANCE_LONG]" in prompt_text:
                scenario = "long"

            state.record(
                {
                    "kind": "chat_completion",
                    "scenario": scenario,
                    "messageCount": len(messages),
                    "toolNames": tool_names,
                    "toolResultSeen": has_tool_result,
                }
            )

            if scenario == "long" and not has_tool_result:
                time.sleep(state.long_delay_seconds)

            if scenario == "approval" and not has_tool_result:
                tool_name = (
                    "python_lint_tool"
                    if "python_lint_tool" in tool_names
                    else (tool_names[0] if tool_names else "")
                )
                if not tool_name:
                    self._send_json(
                        400,
                        {"error": {"message": "approval scenario requires tools"}},
                    )
                    return
                tool_call_id = "call-mcp-acceptance-approval-1"
                self._send_json(
                    200,
                    _completion(
                        state,
                        message={
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tool_call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(
                                            _tool_arguments(tool_name),
                                            ensure_ascii=False,
                                            separators=(",", ":"),
                                        ),
                                    },
                                }
                            ],
                        },
                        finish_reason="tool_calls",
                    ),
                )
                return

            final_text = (
                "结论：MCP显式审批验收通过。验证：python_lint_tool 已完成；未修改文件。"
                if scenario == "approval"
                else "MCP隔离验收通过。"
            )
            self._send_json(
                200,
                _completion(
                    state,
                    message={"role": "assistant", "content": final_text},
                    finish_reason="stop",
                ),
            )

    return Handler


def create_server(
    *,
    host: str,
    port: int,
    state_path: Path,
    long_delay_seconds: float,
) -> ThreadingHTTPServer:
    if str(host or "").strip() != "127.0.0.1":
        raise ValueError("acceptance LLM fixture must bind to IPv4 loopback")
    state = FixtureState(
        state_path=Path(state_path),
        long_delay_seconds=long_delay_seconds,
    )
    return ThreadingHTTPServer((host, int(port)), _handler_for(state))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--long-delay-seconds", type=float, default=45.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    server = create_server(
        host=args.host,
        port=args.port,
        state_path=args.state_file,
        long_delay_seconds=args.long_delay_seconds,
    )
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
