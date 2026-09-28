"""对实例后端的写操作助手（POST/PATCH，控制令牌 + JSON body）。

GET 口径见 ``instance_registry.fetch_json``；这里补齐写动词，供 arrange 阶段
用 API 造数（POST /api/sessions、POST /api/sessions/{id}/messages、
POST /api/agents 等），避免为准备数据走 UI 向导。端点与 payload 形状均以
``core/web/routes`` 为准（实测于 2026-09-25，head=5eeb54a40）。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from tests.e2e.helpers.instance_registry import InstanceRegistryError, control_token

# 与 instance_registry 的令牌头同口径（该常量为其模块私有，这里按值对齐）。
_CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"


def _http_write_json(
    method: str,
    port: int,
    path: str,
    payload: dict[str, Any] | None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}{path}"
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            _CONTROL_TOKEN_HEADER: control_token(port),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except OSError:
            pass
        raise InstanceRegistryError(f"{method} {path} 返回 HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise InstanceRegistryError(f"{method} {path} 不可达: {url} ({exc})") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise InstanceRegistryError(f"{method} {path} 响应非 JSON: body[:200]={raw[:200]!r}") from exc


def post_json(
    port: int,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """POST JSON（携带控制令牌）并解析 JSON 响应。"""
    return _http_write_json("POST", port, path, payload, timeout_seconds=timeout_seconds)


def patch_json(
    port: int,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """PATCH JSON（携带控制令牌）并解析 JSON 响应。"""
    return _http_write_json("PATCH", port, path, payload, timeout_seconds=timeout_seconds)
