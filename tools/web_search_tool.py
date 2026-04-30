# -*- coding: utf-8 -*-
"""
网络搜索工具 - 基于 AutoGLM Web Search API

调用 AutoGLM Web Search 接口进行网络搜索，返回格式化的摘要和参考来源。

API 协议（参考 C:\\Users\\17533\\.agents\\skills\\autoglm-websearch\\SKILL.md）：
- Token:  GET http://127.0.0.1:53699/get_token  →  Bearer xxx
- Search: POST https://autoglm-api.zhipuai.cn/agentdr/v1/assistant/skills/web-search
- Headers: X-Auth-Appid=100003, X-Auth-TimeStamp, X-Auth-Sign(MD5)
- Body:    {"queries": [{"query": "<搜索词>"}]}
"""

from __future__ import annotations

import os
import json
import time
import hashlib
from typing import Optional, List, Dict, Any

import httpx


# ============================================================================
# API 常量 — 从环境变量读取，避免硬编码凭据
# ============================================================================

_APP_ID = os.environ.get("AUTOGLM_APP_ID", "")
_APP_KEY = os.environ.get("AUTOGLM_APP_KEY", "")
_API_URL = "https://autoglm-api.zhipuai.cn/agentdr/v1/assistant/skills/web-search"
_TOKEN_URL = "http://127.0.0.1:53699/get_token"
_REQUEST_TIMEOUT = 30.0  # 秒


# ============================================================================
# Token 获取
# ============================================================================

def _get_bearer_token() -> str:
    """从本地服务获取 Bearer token"""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(_TOKEN_URL)
            response.raise_for_status()
            token = response.text.strip()
    except Exception as e:
        raise RuntimeError(f"无法从本地服务获取 token: {e}")

    if not token:
        raise RuntimeError("获取到的 token 为空")

    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return token


# ============================================================================
# 签名生成
# ============================================================================

def _build_headers(token: str, query: str) -> Dict[str, str]:
    """构建带签名的请求头"""
    timestamp = str(int(time.time()))
    sign_data = f"{_APP_ID}&{timestamp}&{_APP_KEY}"
    sign = hashlib.md5(sign_data.encode("utf-8")).hexdigest()

    payload = json.dumps({"queries": [{"query": query}]}).encode("utf-8")

    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "X-Auth-Appid": _APP_ID,
        "X-Auth-TimeStamp": timestamp,
        "X-Auth-Sign": sign,
    }, payload


# ============================================================================
# 响应解析
# ============================================================================

def _parse_response(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    从 API 响应中提取搜索结果

    响应结构:
    {
      "code": 0,
      "msg": "SUCCESS",
      "data": {
        "results": [
          {
            "webPages": {
              "value": [
                {"name": "...", "url": "...", "snippet": "..."}
              ]
            }
          }
        ]
      }
    }
    """
    results: List[Dict[str, str]] = []

    try:
        results_list = data.get("data", {}).get("results", [])
        for result_item in results_list:
            web_pages = result_item.get("webPages", {})
            values = web_pages.get("value", [])
            for item in values:
                results.append({
                    "name": item.get("name", "无标题"),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })
    except (KeyError, TypeError):
        pass

    return results


# ============================================================================
# 核心搜索函数
# ============================================================================

def web_search(query: str, max_results: int = 10) -> str:
    """
    执行网络搜索并返回格式化结果

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数（默认 10）

    Returns:
        格式化字符串，包含搜索摘要和参考来源列表
    """
    if not query or not query.strip():
        return "[错误] 搜索关键词不能为空"

    # 1. 获取 token
    try:
        token = _get_bearer_token()
    except RuntimeError as e:
        return f"[错误] {e}"

    # 2. 构建请求
    headers, payload = _build_headers(token, query.strip())

    # 3. 发起请求
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
            response = client.post(_API_URL, headers=headers, content=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        return f"[错误] HTTP 请求失败: {e.response.status_code} {e.response.text[:200]}"
    except httpx.RequestError as e:
        return f"[错误] 网络请求失败: {e}"
    except json.JSONDecodeError as e:
        return f"[错误] 响应 JSON 解析失败: {e}"

    # 4. 检查 API 返回码
    code = data.get("code", -1)
    if code != 0:
        msg = data.get("msg", "未知错误")
        return f"[错误] API 返回错误: code={code}, msg={msg}"

    # 5. 解析结果
    results = _parse_response(data)

    if not results:
        return f"[搜索] 未找到与「{query}」相关的结果"

    # 6. 限制结果数量
    results = results[:max_results]

    # 7. 生成摘要
    snippets = [r["snippet"] for r in results if r["snippet"]]
    if snippets:
        summary = f"关于「{query}」，搜索到 {len(results)} 条相关结果：\n\n"
        summary += " | ".join(f"• {s[:150]}{'...' if len(s) > 150 else ''}" for s in snippets[:3])
        if len(snippets) > 3:
            summary += f"\n（另有 {len(snippets) - 3} 条相关结果）"
    else:
        summary = f"[搜索] 找到 {len(results)} 条结果，但无摘要信息"

    # 8. 生成参考来源
    sources = "\n\n**参考来源：**\n"
    for i, r in enumerate(results, 1):
        if r["url"]:
            sources += f"{i}. [{r['name']}]({r['url']})\n"
        else:
            sources += f"{i}. {r['name']}\n"

    return summary + sources


# ============================================================================
# LangChain @tool 装饰器接口（供 Key_Tools.py 使用）
# ============================================================================

from langchain_core.tools import tool


@tool
def web_search_tool(query: str, max_results: int = 10) -> str:
    """
    网络搜索工具 - 基于 AutoGLM Web Search API。

    当需要获取实时信息、最新资讯、网络资料时使用此工具。
    支持联网搜索，返回网页摘要和参考来源链接。

    Args:
        query: 搜索关键词（必填），尽量具体以获得更准确的结果
        max_results: 最大返回结果数，默认 10，建议 5-20

    Returns:
        包含搜索摘要和参考来源链接的格式化字符串

    Example:
        web_search_tool(query="Python 异步编程 async await 最佳实践")
    """
    return web_search(query=query, max_results=max_results)
