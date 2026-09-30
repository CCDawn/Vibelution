"""value 级统一 secret 脱敏（core/logging/value_redaction.py）单测。

覆盖：各模式命中/未命中、中文正文零误报、嵌套结构与钳制、4KB 截断边界、
fail-closed 语义、runtime_scene / unified_logger / transcript_logger 接线。
"""

from __future__ import annotations

import pytest

from core.logging import value_redaction
from core.logging.value_redaction import (
    MAX_REDACTION_DEPTH,
    MAX_REDACTION_ITEMS,
    SCAN_LIMIT,
    redact_sensitive_text,
    redact_sensitive_values,
)

# ============================================================================
# 模式命中
# ============================================================================


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("Authorization: Bearer abc123def456ghi789", "auth"),
        ('{"authorization": "Basic dXNlcjpwYXNzd29yZA=="}', "auth"),
        ("proxy-authorization: NegotiateAAAABBBBCCCC", "auth"),
        ("Bearer sk-abcdefghijklmnop1234", "auth"),
        ("https://api.example.com/v1?api_key=SECRETVALUE123&foo=bar", "urlparam"),
        ("https://host.example/path?token=zzz999yyy888&x=1", "urlparam"),
        ("api_key = abc123def456", "credential"),
        ('"password": "hunter2secret"', "credential"),
        ("token: a1b2c3d4e5f6", "credential"),
        ("client_secret=zzzz1111yyyy2222", "credential"),
        ("sk-a1b2c3d4e5f6g7h8i9j0", "credential"),
        ("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234", "credential"),
        ("AKIAIOSFODNN7EXAMPLE", "credential"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "privatekey"),
        ("-----BEGIN PRIVATE KEY-----\nMIIEow-no-end", "privatekey"),
    ],
)
def test_pattern_hits(raw: str, kind: str) -> None:
    redacted = redact_sensitive_text(raw)
    assert f"[REDACTED:{kind}]" in redacted
    # 原始凭据值不能残留
    assert "SECRETVALUE123" not in redacted
    assert "hunter2secret" not in redacted
    assert "abc123def456ghi789" not in redacted
    assert "MIIEow" not in redacted


def test_pem_block_keeps_surrounding_text() -> None:
    raw = "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----\nafter"
    redacted = redact_sensitive_text(raw)
    assert redacted == "before\n[REDACTED:privatekey]\nafter"


def test_url_query_redaction_preserves_other_params() -> None:
    redacted = redact_sensitive_text("https://api.example.com/v1?api_key=SECRETVALUE123&foo=bar&baz=qux")
    assert "foo=bar" in redacted
    assert "baz=qux" in redacted
    assert "api_key=[REDACTED:urlparam]" in redacted


# ============================================================================
# 未命中 / 中文正文零误报
# ============================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "请把密码改成八个字符以上，token 无效时请重新登录",
        "访问token=无效",  # 值非 ASCII 凭据字符集，不误伤
        "这个 token：abc123def456",  # 全角冒号不在结构锚点内
        "模型回复：你的 api_key 已失效，请重新生成",
        "Bearer 认证失败的中文提示",
        "max_tokens: 4096",  # 含 token 子串但 key 不相邻分隔符
        "The quick brown fox jumps over the lazy dog",
        "",
        "[redacted]",
        "[truncated]",
        "[REDACTED:credential] 已处理",
    ],
)
def test_no_false_positives(raw: str) -> None:
    assert redact_sensitive_text(raw) == raw


def test_placeholder_values_are_idempotent() -> None:
    once = redact_sensitive_text("api_key = abc123def456")
    assert redact_sensitive_text(once) == once


# ============================================================================
# 嵌套结构与钳制
# ============================================================================


def test_nested_structures_redacted_in_place() -> None:
    payload = {
        "note": "普通中文说明，不含凭据",
        "config": {
            "endpoint": "https://api.example.com/v1?token=SECRETVALUE123",
            "headers": ["Authorization: Bearer abc123def456ghi789", "Accept: application/json"],
        },
        "count": 3,
        "enabled": True,
        "missing": None,
        "ratio": 0.5,
    }
    redacted = redact_sensitive_values(payload)
    assert redacted["note"] == payload["note"]
    assert redacted["count"] == 3 and redacted["enabled"] is True and redacted["missing"] is None
    assert redacted["ratio"] == 0.5
    assert "token=[REDACTED:urlparam]" in redacted["config"]["endpoint"]
    assert redacted["config"]["headers"][0] == "Authorization: [REDACTED:auth]"
    assert redacted["config"]["headers"][1] == "Accept: application/json"


def test_scalars_passthrough_and_objects_stringified() -> None:
    assert redact_sensitive_values(42) == 42
    assert redact_sensitive_values(None) is None
    assert redact_sensitive_values(True) is True
    obj_with_secret = type("Obj", (), {"__str__": lambda self: "api_key = abc123def456"})()
    assert redact_sensitive_values(obj_with_secret) == "api_key = [REDACTED:credential]"


def test_depth_clamped_fail_closed() -> None:
    deep: dict = {"secret": "leaf-value"}
    for _ in range(MAX_REDACTION_DEPTH + 3):
        deep = {"next": deep}
    redacted = redact_sensitive_values(deep)
    node = redacted
    for _ in range(MAX_REDACTION_DEPTH - 1):
        node = node["next"]
    assert node["next"] == "[REDACTED:depth]"
    assert "leaf-value" not in str(redacted)


def test_item_count_clamped() -> None:
    payload = {f"key_{index}": f"api_key = value{index:04d}xxxx" for index in range(MAX_REDACTION_ITEMS + 10)}
    redacted = redact_sensitive_values(payload)
    assert len(redacted) == MAX_REDACTION_ITEMS
    assert set(redacted) == {f"key_{index}" for index in range(MAX_REDACTION_ITEMS)}


# ============================================================================
# 有界扫描：4KB 截断边界
# ============================================================================


def test_scan_limit_truncates_before_matching() -> None:
    secret_at_head = "x" * 100 + " api_key = abc123def456"
    redacted = redact_sensitive_text(secret_at_head)
    assert "[REDACTED:credential]" in redacted
    assert len(redacted) <= SCAN_LIMIT

    long_prefix = "y" * SCAN_LIMIT
    beyond = " api_key = abc123def456"
    redacted_beyond = redact_sensitive_text(long_prefix + beyond)
    assert len(redacted_beyond) <= SCAN_LIMIT
    # 边界外的内容不参与匹配，也不会出现在输出里
    assert "abc123def456" not in redacted_beyond


def test_scan_limit_constant_is_4096() -> None:
    assert SCAN_LIMIT == 4_096


# ============================================================================
# fail-closed 语义（红线优先：处理异常保守替换，不原样放行）
# ============================================================================


class _ExplodingPattern:
    def sub(self, *_args, **_kwargs):
        raise RuntimeError("boom")


def test_text_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(value_redaction, "_TOKEN_SHAPE_RE", _ExplodingPattern())
    # 原样放行会把 "sk-..." 留在日志里，因此必须替换为占位符而不是原值
    assert redact_sensitive_text("sk-abcdefghijklmnop1234") == "[REDACTED:error]"
    assert redact_sensitive_text("plain text") == "[REDACTED:error]"


def test_values_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadObj:
        def __str__(self) -> str:
            raise RuntimeError("boom")

    assert redact_sensitive_values(BadObj()) == "[REDACTED:error]"
    assert redact_sensitive_values({"ok": 1, "bad": BadObj()}) == "[REDACTED:error]"


# ============================================================================
# 接线：runtime_scene _normalize_telemetry_fields（key 级脱敏后的 value 级外层）
# ============================================================================


def test_normalize_telemetry_fields_applies_value_redaction() -> None:
    from core.web.services.runtime_scene import record as runtime_scene_record

    fields = {
        # key 级不命中（hint 非敏感 key），但 value 内嵌凭据 → value 级兜底
        "hint": "fallback api_key = abc123def456",
        # 常量折叠 key（运行时拼出来的敏感 key，keyword-in-key 照样命中 → key 级处理）
        "api_" + "key": "abc123def456",
        "note": "中文说明保持原样",
        "url": "https://api.example.com/v1?token=SECRETVALUE123",
    }
    normalized = runtime_scene_record._normalize_telemetry_fields(fields)
    assert normalized["hint"] == "fallback api_key = [REDACTED:credential]"
    assert normalized["api_key"] == "[redacted]"  # key 级脱敏产物原样保留
    assert normalized["note"] == "中文说明保持原样"
    assert "token=[REDACTED:urlparam]" in normalized["url"]


def test_normalize_telemetry_fields_keeps_existing_contract() -> None:
    from core.web.services.runtime_scene import record as runtime_scene_record

    assert runtime_scene_record._normalize_telemetry_fields(None) == {}
    assert runtime_scene_record._normalize_telemetry_fields("plain") == {"value": "plain"}


# ============================================================================
# 接线：unified_logger / transcript_logger 写入前脱敏
# ============================================================================


def test_unified_logger_log_llm_request_redacts_before_downstream(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.logging import unified_logger as unified_logger_module

    captured: dict = {}
    monkeypatch.setattr(
        unified_logger_module.UnifiedLogger,
        "__init__",
        lambda self: None,
    )

    class FakeConversation:
        def log_llm_request(self, messages, model=None, iteration=0):
            captured["messages"] = messages

    class FakeTranscript:
        pass

    logger = unified_logger_module.UnifiedLogger()
    monkeypatch.setattr(logger, "_conversation", FakeConversation())
    monkeypatch.setattr(logger, "_transcript", FakeTranscript())

    logger.log_llm_request([{"role": "user", "content": "connect with api_key = abc123def456"}])
    assert captured["messages"][0]["content"] == "connect with api_key = [REDACTED:credential]"


def test_unified_logger_log_tool_call_redacts_args_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.logging import unified_logger as unified_logger_module

    captured: dict = {}
    monkeypatch.setattr(unified_logger_module.UnifiedLogger, "__init__", lambda self: None)

    class FakeConversation:
        def log_tool_call(self, tool_name, args, result, status, tool_call_id=None):
            captured.update(args=args, result=result)

    class FakeTranscript:
        def write_tool_call(self, tool_name, args, result, status):
            captured["transcript_args"] = args
            captured["transcript_result"] = result

    logger = unified_logger_module.UnifiedLogger()
    monkeypatch.setattr(logger, "_conversation", FakeConversation())
    monkeypatch.setattr(logger, "_transcript", FakeTranscript())

    logger.log_tool_call("http", {"url": "https://h/?token=SECRETVALUE123"}, "ok Authorization: Bearer abc123def456ghi789")
    assert "[REDACTED:urlparam]" in captured["args"]["url"]
    assert captured["result"] == "ok Authorization: [REDACTED:auth]"
    assert captured["transcript_args"] == captured["args"]


def test_transcript_logger_write_llm_response_redacts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.logging.transcript_logger import TranscriptLogger

    captured: dict = {}
    instance = TranscriptLogger()
    monkeypatch.setattr(instance, "_enqueue_write", lambda content: captured.update(md=content))

    instance.write_llm_response("done", thinking="checking api_key = abc123def456")
    assert "api_key = [REDACTED:credential]" in captured["md"]
    assert "abc123def456" not in captured["md"]


def test_transcript_logger_write_error_redacts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from core.logging.transcript_logger import TranscriptLogger

    instance = TranscriptLogger()
    captured: dict = {}
    monkeypatch.setattr(instance, "_enqueue_write", lambda content: captured.update(md=content))

    instance.write_error("http_error", "GET https://h/?token=SECRETVALUE123 failed")
    assert "token=[REDACTED:urlparam]" in captured["md"]
    assert "SECRETVALUE123" not in captured["md"]
