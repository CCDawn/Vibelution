"""Value 级统一 secret 脱敏（纯函数）。

对齐全局红线「不记录 secrets」：key 级脱敏（runtime_scene 的
``SENSITIVE_FIELD_KEYWORDS``、``safe_payload`` 的 shape+hash）依赖各写入点自律，
拦不住常量折叠 / 动态拼接出来的敏感 key，也不保护 message 正文里的凭据。
本模块提供单点 value 级扫描器，作为 key 级脱敏的外层补充，不替代、不改动
现有 key 级脱敏与长度/深度钳制。

取舍（借鉴 ZCode ``telemetryRedaction.ts``）：

- **只作用于持久化/上报副本**：DebugLogger 本地诊断日志与崩溃归档继续用原值，
  本模块不被本地调试面引用。
- **有界扫描**：单值先截 4KB 再跑正则，防止无界 CPU；递归深度/条目钳制对齐
  runtime_scene ``_normalize_telemetry_fields`` 现行限制（depth 5 / items 24）。
- **误伤控制**：模式全部锚定英文关键字与 ASCII 结构（``:``、``=``、``&``、
  PEM 边界、已知凭据前缀），凭据值只认 ASCII 凭据字符集；中文正文既不是关键
  字也不满足 ASCII 值形态，不会被误替换。
- **fail-closed**：处理异常时保守替换为 ``[REDACTED:error]``，而不是原样放行
  ——红线优先：宁可日志少一段内容，也不能让 secret 落盘。该语义由单测锁定。
"""

from __future__ import annotations

import re
from typing import Any

# 单值扫描上限：先截断再正则，保证长字符串不会拖垮 CPU。
SCAN_LIMIT = 4_096

# 递归深度上限，对齐 runtime_scene _normalize_structured_telemetry_value 的 depth>=5 钳制。
MAX_REDACTION_DEPTH = 5

# 每层 dict/list 的条目上限，对齐 MAX_TELEMETRY_FIELD_ITEMS。
MAX_REDACTION_ITEMS = 24

_PLACEHOLDER_PREFIX = "[REDACTED:"
# 上游 key 级脱敏 / 钳制产物：已是占位符的值跳过重复扫描（幂等）。
_PASSTHROUGH_SENTINELS = frozenset({"[redacted]", "[truncated]"})


# PEM 私钥块（含 END 边界的完整块优先替换）。
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?"
    r"-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
)
# 只有 BEGIN 头没有 END（截断/残留）时，保守吞掉到窗口末尾。
_PEM_OPEN_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*")

# authorization / proxy-authorization 头的值（允许 Bearer/Basic 前缀）。
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b((?:proxy-)?authorization\b[\"']?\s*[:=]\s*)"
    r"(?:(?:bearer|basic|token)\s+)?[A-Za-z0-9+/=._~\-]{4,}"
)

# 任意位置出现的 Bearer/Basic scheme 凭据。
_BEARER_BASIC_RE = re.compile(
    r"(?i)\b(bearer|basic)(\s+)([A-Za-z0-9._~+/=-]{8,})"
)

# URL query 中的敏感参数值。
_URL_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|token|secret|client[_-]?secret|password|passwd|"
    r"sig(?:nature)?|session(?:id)?|sid|cookie|authorization)=)[^&\s'\"]+"
)

# 「敏感 key: value」/「敏感 key = value」赋值对。value 只认 ASCII 凭据字符集，
# 是中文正文不误伤的关键锚点（中文既当不了 key 也不满足值形态）。
_KV_ASSIGN_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|client[_-]?secret|secret|token|password|passwd|pwd|"
    r"credential|credentials|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
    r"([A-Za-z0-9+/=._~\-]{4,})"
)

# 高置信凭据字面量形态（各家 key 前缀）。
_TOKEN_SHAPE_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,})"
)


def redact_sensitive_text(text: str) -> str:
    """对单个字符串做 value 级 secret 扫描，命中替换为 ``[REDACTED:<kind>]``。

    输入先截到 :data:`SCAN_LIMIT` 再匹配；已是占位符的值原样返回（幂等）。
    任何处理异常 fail-closed 为 ``[REDACTED:error]``。
    """
    if not isinstance(text, str):
        return text
    if not text or text.startswith(_PLACEHOLDER_PREFIX) or text in _PASSTHROUGH_SENTINELS:
        return text
    bounded = text[:SCAN_LIMIT]
    try:
        bounded = _PEM_BLOCK_RE.sub("[REDACTED:privatekey]", bounded)
        bounded = _PEM_OPEN_RE.sub("[REDACTED:privatekey]", bounded)
        bounded = _AUTH_HEADER_RE.sub(r"\g<1>[REDACTED:auth]", bounded)
        bounded = _BEARER_BASIC_RE.sub(r"\g<1>\g<2>[REDACTED:auth]", bounded)
        bounded = _URL_QUERY_RE.sub(r"\g<1>[REDACTED:urlparam]", bounded)
        bounded = _KV_ASSIGN_RE.sub(r"\g<1>[REDACTED:credential]", bounded)
        bounded = _TOKEN_SHAPE_RE.sub("[REDACTED:credential]", bounded)
    except Exception:  # noqa: BLE001 - fail-closed：宁可丢内容不漏 secret
        return "[REDACTED:error]"
    return bounded


def redact_sensitive_values(value: Any) -> Any:
    """递归对 str/dict/list 做 value 级脱敏，返回同构副本。

    - 标量（None/bool/int/float）原样通过；其它对象 ``str()`` 后保守扫描。
    - dict/list 条目数与递归深度按现行钳制截断，越界深层以
      ``[REDACTED:depth]`` 占位（fail-closed：深层未检内容视为不可信）。
    - 任何节点处理异常 fail-closed 为 ``[REDACTED:error]``。
    """
    try:
        return _redact_node(value, depth=0)
    except Exception:  # noqa: BLE001 - fail-closed：宁可丢内容不漏 secret
        return "[REDACTED:error]"


def _redact_node(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if depth >= MAX_REDACTION_DEPTH:
        return "[REDACTED:depth]"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_REDACTION_ITEMS:
                break
            redacted[str(key)] = _redact_node(item, depth=depth + 1)
        return redacted
    if isinstance(value, (list, tuple)):
        return [_redact_node(item, depth=depth + 1) for item in list(value)[:MAX_REDACTION_ITEMS]]
    return redact_sensitive_text(str(value))
