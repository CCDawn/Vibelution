# -*- coding: utf-8 -*-
"""
LLM Provider Adapters (LLM 适配器)

提供各个 LLM Provider 的适配器实现，将不同 API 格式统一为标准接口。

当前支持：
- MiniMax OpenAI 兼容 API

快速开始：
    from config.adapters import MiniMaxOpenAIAdapter, MiniMaxResponse

    adapter = MiniMaxOpenAIAdapter(
        model="xxx",
        api_key="xxx",
        base_url="https://api.minimax.chat/v1",
        timeout=httpx.Timeout(600, connect=30),
    )
    response = adapter.invoke(messages)
"""

from __future__ import annotations

import json
import httpx
from typing import Any, List, Dict, Optional

from langchain_core.messages import HumanMessage


# ============================================================================
# MiniMax Response Wrapper
# ============================================================================

class MiniMaxResponse:
    """
    MiniMax OpenAI 响应包装器，提供与 LangChain AIMessage 兼容的接口。
    """

    def __init__(self, raw_response):
        self.raw_response = raw_response
        self.type = "ai"

        choice = raw_response.choices[0]
        message = choice.message

        self.content = message.content or ""

        # reasoning_details 字段（reasoning_split=True 时有）
        self.reasoning_details = []
        if hasattr(message, "reasoning_details") and message.reasoning_details:
            self.reasoning_details = message.reasoning_details

        # tool_calls
        self.tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                self.tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "args": tc.function.arguments,
                })

        self.usage_metadata = {
            "input_tokens": raw_response.usage.prompt_tokens if hasattr(raw_response.usage, "prompt_tokens") else 0,
            "output_tokens": raw_response.usage.completion_tokens if hasattr(raw_response.usage, "completion_tokens") else 0,
        }


# ============================================================================
# MiniMax OpenAI Adapter
# ============================================================================

class MiniMaxOpenAIAdapter:
    """
    MiniMax OpenAI 兼容 API 适配器。

    使用 OpenAI SDK 调用 MiniMax 的 OpenAI 兼容端点。
    提供与 LangChain ChatOpenAI 类似的双工工具调用模式（bind_tools + invoke）。

    Example:
        adapter = MiniMaxOpenAIAdapter(
            model="MiniMax-Text-01",
            api_key="your-api-key",
            base_url="https://api.minimax.chat/v1",
            timeout=httpx.Timeout(600, connect=30),
        )
        # 绑定工具
        adapter_with_tools = adapter.bind_tools(tools)
        # 调用
        response = adapter_with_tools.invoke(messages)
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: httpx.Timeout,
        max_tokens: int = 8192,
        temperature: float = 1.0,
    ):
        """
        初始化 MiniMax 适配器

        Args:
            model: 模型名称
            api_key: API 密钥
            base_url: API 端点
            timeout: 超时配置
            max_tokens: 最大生成 token 数
            temperature: 温度参数
        """
        from openai import OpenAI

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._tools = None
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(
                timeout=timeout.read,
                connect=timeout.connect,
            ),
            http_client=httpx.Client(),
        )

    def bind_tools(self, tools: list) -> "MiniMaxOpenAIAdapter":
        """
        绑定工具，返回绑定后的实例副本

        Args:
            tools: LangChain BaseTool 列表

        Returns:
            绑定工具后的适配器实例副本
        """
        adapter = MiniMaxOpenAIAdapter(
            model=self.model,
            api_key=self._client.api_key,
            base_url=str(self._client.base_url),
            timeout=httpx.Timeout(
                self._client.timeout.read or 600,
                connect=self._client.timeout.connect or 30,
            ),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        adapter._tools = [self._convert_tool(t) for t in tools]
        return adapter

    @staticmethod
    def _convert_tool(tool: Any) -> dict:
        """
        将 LangChain BaseTool 转换为 OpenAI 工具格式。

        Args:
            tool: LangChain BaseTool 实例

        Returns:
            OpenAI 工具格式的字典
        """
        from typing import List, Dict

        name = getattr(tool, "name", str(tool))
        description = getattr(tool, "description", "") or ""
        schema = getattr(tool, "args_schema", None)
        if schema is None:
            input_schema = getattr(tool, "input_schema", None)
            schema = input_schema

        parameters = {}
        if schema:
            try:
                if hasattr(schema, "model_fields") and hasattr(schema.model_fields, 'items'):
                    for field_name, field in schema.model_fields.items():
                        ftype = "string"
                        if field.annotation:
                            ann = field.annotation
                            if ann == int or ann == "int":
                                ftype = "integer"
                            elif ann == float or ann == "number":
                                ftype = "number"
                            elif ann == bool:
                                ftype = "boolean"
                            elif ann == list or ann == List:
                                ftype = "array"
                            elif ann == dict or ann == Dict:
                                ftype = "object"
                        desc = ""
                        if hasattr(field, "description") and field.description:
                            desc = field.description
                        parameters[field_name] = {"type": ftype, "description": desc}
                elif hasattr(schema, "schema"):
                    schema_result = schema.schema()
                    props = schema_result.get("properties", {}) if isinstance(schema_result, dict) else {}
                    for fname, fval in props.items():
                        parameters[fname] = {
                            "type": fval.get("type", "string"),
                            "description": fval.get("description", ""),
                        }
            except Exception:
                pass

        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": parameters, "required": list(parameters.keys())},
            },
        }

    def invoke(self, messages) -> MiniMaxResponse:
        """
        调用 MiniMax API。

        Args:
            messages: 消息列表，可以是字符串或 List[HumanMessage|AIMessage|ToolMessage]

        Returns:
            MiniMaxResponse 对象，包含 .content 属性，兼容 LangChain 处理方式
        """
        from langchain_core.messages import HumanMessage

        if isinstance(messages, str):
            messages = [HumanMessage(content=messages)]

        # 转换消息格式：提取 system，转换 role
        openai_messages = []
        for msg in messages:
            role = getattr(msg, "type", "user") or "user"
            content = getattr(msg, "content", "") or ""

            if role == "system":
                # system message 直接拼入第一个消息的 content 前面
                continue
            elif role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"

            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif hasattr(block, "type") and block.type == "text":
                        text_parts.append(getattr(block, "text", ""))
                content = "\n".join(text_parts)

            if not content and hasattr(msg, "tool_calls") and msg.tool_calls:
                # assistant message 带 tool_calls 时，保留 tool_calls 但 content 可为空
                pass

            msg_dict = {"role": role, "content": content}

            # 携带 tool_calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tc_list = []
                for tc in msg.tool_calls:
                    if isinstance(tc, dict):
                        tc_list.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["args"] if isinstance(tc["args"], str) else tc["args"],
                            },
                        })
                    elif hasattr(tc, "id"):
                        args = getattr(tc, "args", "{}")
                        if isinstance(args, str):
                            args = args
                        else:
                            args = json.dumps(args)
                        tc_list.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": getattr(tc, "name", ""),
                                "arguments": args,
                            },
                        })
                if tc_list:
                    msg_dict["tool_calls"] = tc_list

            # 携带 tool_call_id（ToolMessage）
            if hasattr(msg, "tool_call_id") and msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id

            openai_messages.append(msg_dict)

        # 提取 system prompt
        system_prompt = ""
        for msg in messages:
            if getattr(msg, "type", None) == "system":
                content = getattr(msg, "content", "") or ""
                system_prompt = content
                break

        # 构建 API 参数
        api_kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "extra_body": {"reasoning_split": True},
        }
        if system_prompt:
            api_kwargs["messages"] = [{"role": "system", "content": system_prompt}] + openai_messages
        if self.max_tokens:
            api_kwargs["max_tokens"] = self.max_tokens
        if self.temperature > 0:
            api_kwargs["temperature"] = self.temperature
        if self._tools:
            api_kwargs["tools"] = self._tools

        response = self._client.chat.completions.create(**api_kwargs)
        return MiniMaxResponse(response)


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "MiniMaxOpenAIAdapter",
    "MiniMaxResponse",
]