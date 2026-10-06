#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回合准备开销修复的缓存语义测试（turn-prepare-cost）。

覆盖三块新增缓存：
- 微压缩 anchor：按 ledger 文件签名 (mtime_ns, size) 复用，文件变化即失效；
- llm_key_env 持久化读取 TTL：窗口内不重读，过期重读，reader 身份隔离；
- prompt 动态章节短 TTL：窗口内不重算（计数器断言）、过期重算、失效即重算。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from config import llm_key_env
from core.chat import microcompact_anchor
from core.chat.microcompact_anchor import load_provider_usage_anchor, reset_anchor_cache
from core.llm.usage_ledger import UsageLedgerEvent, record_usage_event
from core.prompt_manager import SystemPromptCache, SystemPromptSection
from core.prompt_manager import builder as prompt_builder
from core.prompt_manager.prompt_manager import PromptManager


# ---------------------------------------------------------------------------
# 微压缩 anchor：ledger 文件签名缓存
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_anchor_cache_between_tests():
    reset_anchor_cache()
    yield
    reset_anchor_cache()


def _record_provider_usage(root: Path, conversation_id: str, total_tokens: int) -> None:
    record_usage_event(
        UsageLedgerEvent(
            recorded_at="2026-10-06T00:00:00Z",
            source="provider_usage",
            scope_kind="chat_session",
            session_id=conversation_id,
            conversation_id=conversation_id,
            input_tokens=total_tokens - 100,
            output_tokens=100,
            total_tokens=total_tokens,
        ),
        project_root=root,
    )


def _ledger_path(root: Path) -> Path:
    return microcompact_anchor.usage_ledger_path(root)


def _touch_ledger_with_new_row(root: Path, conversation_id: str, total_tokens: int) -> None:
    """追加一行 provider usage，保证文件签名（mtime/size）变化。"""

    before = _ledger_path(root).stat().st_size
    for _ in range(50):
        _record_provider_usage(root, conversation_id, total_tokens)
        if _ledger_path(root).stat().st_size > before:
            break


def test_anchor_cache_hits_within_same_file_signature(tmp_path):
    root = tmp_path / "project"
    _record_provider_usage(root, "conv-a", 12_345)

    first = load_provider_usage_anchor(conversation_id="conv-a", project_root=root)
    assert first is not None and first["totalTokens"] == 12_345

    key = (
        ("conv-a",),
        str(_ledger_path(root)),
        _ledger_path(root).stat().st_mtime_ns,
        _ledger_path(root).stat().st_size,
    )
    assert key in microcompact_anchor._ANCHOR_CACHE
    second = load_provider_usage_anchor(conversation_id="conv-a", project_root=root)
    assert second == first


def test_anchor_cache_requeries_when_ledger_file_changes(tmp_path):
    root = tmp_path / "project"
    _record_provider_usage(root, "conv-b", 1_000)
    first = load_provider_usage_anchor(conversation_id="conv-b", project_root=root)
    assert first is not None and first["totalTokens"] == 1_000

    _touch_ledger_with_new_row(root, "conv-b", 2_000)
    second = load_provider_usage_anchor(conversation_id="conv-b", project_root=root)
    assert second is not None and second["totalTokens"] == 2_000


def test_anchor_cache_keys_by_conversation_id(tmp_path):
    root = tmp_path / "project"
    _record_provider_usage(root, "conv-keep", 7_000)

    missing = load_provider_usage_anchor(conversation_id="conv-absent", project_root=root)
    assert missing is None
    found = load_provider_usage_anchor(conversation_id="conv-keep", project_root=root)
    assert found is not None and found["totalTokens"] == 7_000
    # None 结果也按 key 缓存：同 key 再查不触发重查，也不同 key 串值。
    assert load_provider_usage_anchor(conversation_id="conv-absent", project_root=root) is None


def test_anchor_cache_does_not_cache_transient_query_failure(tmp_path, monkeypatch):
    root = tmp_path / "project"
    _record_provider_usage(root, "conv-c", 5_000)

    original_connect = sqlite3.connect
    calls = {"n": 0}

    def flaky_connect(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            # 第一次查询：ro 连接与回退连接都因锁失败
            raise sqlite3.OperationalError("database is locked")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(microcompact_anchor.sqlite3, "connect", flaky_connect)
    assert load_provider_usage_anchor(conversation_id="conv-c", project_root=root) is None
    anchor = load_provider_usage_anchor(conversation_id="conv-c", project_root=root)
    assert anchor is not None and anchor["totalTokens"] == 5_000
    assert calls["n"] == 3  # 失败未缓存：第二次调用真实重连重查


def test_anchor_cache_returns_copy_not_shared_dict(tmp_path):
    root = tmp_path / "project"
    _record_provider_usage(root, "conv-d", 3_000)
    first = load_provider_usage_anchor(conversation_id="conv-d", project_root=root)
    assert first is not None
    first["totalTokens"] = -999
    second = load_provider_usage_anchor(conversation_id="conv-d", project_root=root)
    assert second is not None and second["totalTokens"] == 3_000


# ---------------------------------------------------------------------------
# llm_key_env：持久化读取 TTL 缓存
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_llm_key_env_cache_between_tests():
    llm_key_env.reset_llm_key_env_read_cache()
    yield
    llm_key_env.reset_llm_key_env_read_cache()


def _sync_payload(env_names: list[str]) -> dict:
    return {
        "llm": {
            "model_library": {
                name: {"api_key_env": name} for name in env_names
            }
        }
    }


def test_llm_key_env_ttl_cache_skips_rereads_within_window(monkeypatch):
    env_name = "VIBELUTION_TTL_PROBE_KEY"
    reads = {"n": 0}

    def reader(name: str) -> str:
        reads["n"] += 1
        return "secret-value"

    payload = llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=reader,
        persisted_read_ttl_seconds=60.0,
    )
    assert payload["syncedCount"] == 1
    monkeypatch.delenv(env_name, raising=False)
    second = llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=reader,
        persisted_read_ttl_seconds=60.0,
    )
    assert second["syncedCount"] == 1
    assert reads["n"] == 1  # 窗口内命中缓存，不重读


def test_llm_key_env_ttl_cache_rereads_after_expiry(monkeypatch):
    env_name = "VIBELUTION_TTL_PROBE_EXPIRY"
    reads = {"n": 0}

    def reader(name: str) -> str:
        reads["n"] += 1
        return "secret-value"

    llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=reader,
        persisted_read_ttl_seconds=60.0,
    )
    monkeypatch.delenv(env_name, raising=False)
    # 把缓存改成已过期
    with llm_key_env._PERSISTED_READ_CACHE_LOCK:
        expires, value, cached_reader = llm_key_env._PERSISTED_READ_CACHE[env_name]
        llm_key_env._PERSISTED_READ_CACHE[env_name] = (expires - 61.0, value, cached_reader)
    llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=reader,
        persisted_read_ttl_seconds=60.0,
    )
    assert reads["n"] == 2  # 过期后重读


def test_llm_key_env_ttl_cache_never_shares_across_readers(monkeypatch):
    env_name = "VIBELUTION_TTL_PROBE_READER_ID"
    monkeypatch.delenv(env_name, raising=False)

    llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=lambda name: "from-reader-one",
        persisted_read_ttl_seconds=60.0,
    )
    monkeypatch.delenv(env_name, raising=False)
    payload = llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
        persisted_reader=lambda name: "from-reader-two",
        persisted_read_ttl_seconds=60.0,
    )
    assert payload["syncedCount"] == 1
    import os as _os

    assert _os.environ[env_name] == "from-reader-two"  # 不串另一个 reader 的值


def test_llm_key_env_ttl_zero_disables_cache(monkeypatch):
    env_name = "VIBELUTION_TTL_PROBE_DISABLED"
    reads = {"n": 0}

    def reader(name: str) -> str:
        reads["n"] += 1
        return "secret-value"

    for _ in range(2):
        llm_key_env.sync_llm_key_env_from_persisted_user_env(
            context="test",
            public_config=_sync_payload([env_name]),
            persisted_reader=reader,
            persisted_read_ttl_seconds=0,
        )
        monkeypatch.delenv(env_name, raising=False)
    assert reads["n"] == 2
    assert not llm_key_env._PERSISTED_READ_CACHE


def test_llm_key_env_default_reader_path_caches_by_reader_identity(monkeypatch):
    """默认路径（不传 reader）按调用时模块级 reader 身份缓存并跨调用复用。"""

    env_name = "VIBELUTION_TTL_PROBE_DEFAULT_READER"
    reads = {"n": 0}

    def module_reader(name: str) -> str:
        reads["n"] += 1
        return "registry-value"

    monkeypatch.setattr(llm_key_env, "read_persisted_user_env_var", module_reader)
    monkeypatch.delenv(env_name, raising=False)
    payload = llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
    )
    assert payload["syncedCount"] == 1
    assert reads["n"] == 1

    monkeypatch.delenv(env_name, raising=False)
    llm_key_env.sync_llm_key_env_from_persisted_user_env(
        context="test",
        public_config=_sync_payload([env_name]),
    )
    assert reads["n"] == 1  # 同一 reader 对象，窗口内复用
    assert env_name in llm_key_env._PERSISTED_READ_CACHE


# ---------------------------------------------------------------------------
# prompt 动态章节 TTL 缓存
# ---------------------------------------------------------------------------


class _FakeMonotonic:
    def __init__(self, start: float = 1000.0):
        self.value = start

    def __call__(self) -> float:
        return self.value


@pytest.fixture()
def fake_monotonic(monkeypatch):
    fake = _FakeMonotonic()
    monkeypatch.setattr("core.prompt_manager.section_cache.time.monotonic", fake)
    yield fake


class TestSystemPromptCacheTtl:
    def test_ttl_window_hit_does_not_recompute(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("A", "v1", ttl_seconds=60.0)
        fake_monotonic.value += 30
        hit, value = cache.get_with_ttl("A")
        assert hit is True and value == "v1"

    def test_ttl_expiry_recomputes(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("A", "v1", ttl_seconds=60.0)
        fake_monotonic.value += 61
        hit, value = cache.get_with_ttl("A")
        assert hit is False and value is None
        # 过期条目被丢弃
        cache.set_with_ttl("A", "v2", ttl_seconds=60.0)
        hit, value = cache.get_with_ttl("A")
        assert hit is True and value == "v2"

    def test_ttl_invalidate_clears_entry(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("A", "v1", ttl_seconds=60.0)
        cache.invalidate("A")
        hit, _ = cache.get_with_ttl("A")
        assert hit is False

    def test_ttl_layer_is_separate_from_static_layer(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("DYN", "dyn-value", ttl_seconds=60.0)
        assert cache.has("DYN") is False  # 静态层看不到 TTL 条目
        assert cache.get("DYN") is None

    def test_ttl_zero_does_not_store(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("A", "v", ttl_seconds=0)
        hit, _ = cache.get_with_ttl("A")
        assert hit is False

    def test_ttl_stats_counters(self, fake_monotonic):
        cache = SystemPromptCache()
        cache.set_with_ttl("A", "v", ttl_seconds=60.0)
        cache.get_with_ttl("A")  # hit
        cache.get_with_ttl("B")  # miss
        stats = cache.stats
        assert stats["ttl_hits"] == 1
        assert stats["ttl_misses"] == 1
        assert stats["ttl_sections"] == ["A"]


def _make_counting_section(pm: PromptManager, name: str, counter: dict, content: str) -> None:
    def compute():
        counter["n"] += 1
        return content

    pm.register(SystemPromptSection(name=name, compute=compute, cache_break=True, priority=45))


def test_builder_ttl_section_computes_once_within_window(tmp_path, monkeypatch, fake_monotonic):
    pm = PromptManager()
    counter = {"n": 0}
    _make_counting_section(pm, "TTL_PROBE", counter, "TTL probe content")
    monkeypatch.setitem(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS, "TTL_PROBE", 60.0)

    first = pm.build(include=["TTL_PROBE"])
    second = pm.build(include=["TTL_PROBE"])
    assert counter["n"] == 1  # 窗口内不重算
    assert "TTL probe content" in prompt_builder.to_string(first)
    assert prompt_builder.to_string(second) == prompt_builder.to_string(first)
    sources = {item["name"]: item["source"] for item in pm.get_last_index()}
    assert sources.get("TTL_PROBE") == "ttl_cache"


def test_builder_ttl_section_recomputes_after_expiry(tmp_path, monkeypatch, fake_monotonic):
    pm = PromptManager()
    counter = {"n": 0}
    _make_counting_section(pm, "TTL_PROBE", counter, "TTL probe content")
    monkeypatch.setitem(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS, "TTL_PROBE", 60.0)

    pm.build(include=["TTL_PROBE"])
    fake_monotonic.value += 61
    pm.build(include=["TTL_PROBE"])
    assert counter["n"] == 2  # 过期后重算


def test_builder_ttl_section_invalidate_forces_recompute(tmp_path, monkeypatch, fake_monotonic):
    pm = PromptManager()
    counter = {"n": 0}
    _make_counting_section(pm, "TTL_PROBE", counter, "TTL probe content")
    monkeypatch.setitem(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS, "TTL_PROBE", 60.0)

    pm.build(include=["TTL_PROBE"])
    pm.invalidate_cache("TTL_PROBE")
    pm.build(include=["TTL_PROBE"])
    assert counter["n"] == 2


def test_builder_unttlled_section_recomputes_every_build(tmp_path, monkeypatch, fake_monotonic):
    """会话/任务状态类章节不注册 TTL，语义保持每轮重算。"""

    pm = PromptManager()
    counter = {"n": 0}
    _make_counting_section(pm, "SESSION_STATE_PROBE", counter, "state content")
    monkeypatch.delitem(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS, "SESSION_STATE_PROBE", raising=False)

    pm.build(include=["SESSION_STATE_PROBE"])
    pm.build(include=["SESSION_STATE_PROBE"])
    assert counter["n"] == 2


def test_env_info_ttl_aligns_to_five_minute_bucket_boundary():
    bucket = 300.0
    for _ in range(20):
        ttl = prompt_builder.dynamic_section_ttl_seconds("ENV_INFO")
        assert ttl is not None
        assert 0.05 <= ttl <= bucket
        boundary = time.time() + ttl
        # 到期点落在 5 分钟取整网格上（浮点余量 <1ms）
        phase = boundary - int(boundary // bucket) * bucket
        assert min(phase, bucket - phase) < 0.001
        time.sleep(0.002)


def test_codebase_map_section_ttl_skips_map_io_within_window(tmp_path, monkeypatch, fake_monotonic):
    """CODEBASE_MAP 命中 TTL 时不重复做地图文件读/should_rescan 全仓遍历。"""

    from core.prompt_manager import codebase_map_builder

    calls = {"n": 0}

    def fake_get_codebase_map(force_refresh: bool = False, *, current_goal=None, state_memory=None):
        calls["n"] += 1
        return "## 全局骨架摘要\n- stub map"

    monkeypatch.setattr(codebase_map_builder, "get_codebase_map", fake_get_codebase_map)

    pm = PromptManager()
    pm.build(include=["CODEBASE_MAP"])
    pm.build(include=["CODEBASE_MAP"])
    assert calls["n"] == 1  # 窗口内不重算（不重读地图文件）

    fake_monotonic.value += 61
    pm.build(include=["CODEBASE_MAP"])
    assert calls["n"] == 2


def test_runtime_log_index_ttl_caches_across_builds(tmp_path, monkeypatch, fake_monotonic):
    from core.web.services import runtime_scene_service

    calls = {"n": 0}

    def fake_index(limit: int = 3) -> str:
        calls["n"] += 1
        return "## RUNTIME_LOG_INDEX\n- fake index"

    monkeypatch.setattr(runtime_scene_service, "build_runtime_scene_prompt_index", fake_index)
    monkeypatch.setitem(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS, "RUNTIME_LOG_INDEX", 60.0)

    pm = PromptManager()
    pm.build(include=["RUNTIME_LOG_INDEX"])
    pm.build(include=["RUNTIME_LOG_INDEX"])
    assert calls["n"] == 1  # 窗口内复用，不再列目录/读包

    fake_monotonic.value += 61
    pm.build(include=["RUNTIME_LOG_INDEX"])
    assert calls["n"] == 2


def test_dynamic_section_ttl_registry_only_contains_descriptive_sections():
    allowed_fixed = {"CODEBASE_MAP", "RUNTIME_LOG_INDEX"}
    allowed_bucket = {"ENV_INFO"}
    assert set(prompt_builder._DYNAMIC_SECTION_TTL_SECONDS) == allowed_fixed
    assert set(prompt_builder._DYNAMIC_SECTION_BUCKET_SECONDS) == allowed_bucket
