# -*- coding: utf-8 -*-
"""Session chat-state read cache: hit isolation, and every invalidation path.

TTFT 批五为 ``load_session_chat_state`` 加了 (写 epoch, 存储文件签名) 校验的
进程内读缓存。这里锁定它的行为契约：

* 命中返回与未命中完全相等的 payload，但每次都是隔离副本（调用方普遍
  read-modify-write，突变返回 dict 不得污染缓存）。
* 本模块写路径（save/mutate/save_session/legacy import）必须失效缓存。
* 进程外写（文件签名变化）必须失效缓存——用改 mtime 的方式模拟。
* 缺失会话（None）同样可缓存，且被写路径失效。
* 不同 project root 互不串。

缓存只在 store 稳定打开（live directory store / borrowed store）时生效；
测试统一用 ``borrow_chat_state_store`` 复现生产形态。
"""

import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.infrastructure import developer_sandbox
from core.ui import chat_state as chat_state_module
from core.ui.chat_state import (
    borrow_chat_state_store,
    clear_session_chat_state_cache,
    load_session_chat_state,
    mutate_chat_state,
    save_chat_state,
    save_session_chat_state,
)


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    clear_session_chat_state_cache()
    yield
    clear_session_chat_state_cache()


@contextmanager
def _stable_store(root: Path):
    """Keep one store open so reads don't open/checkpoint/close per call."""

    with borrow_chat_state_store(root):
        yield


def _seed_session(root: Path, session_id: str, title: str = "Session") -> None:
    save_chat_state(
        root,
        {
            "version": 1,
            "conversations": [
                {"conversation_id": session_id, "title": title},
            ],
        },
    )


def _store_db_path(root: Path) -> Path:
    from core.web.services.session import directory_runtime

    return directory_runtime.conversation_store_path(root)


def _counting_repository(monkeypatch):
    """Wrap ``_chat_state_repository`` and count repository acquisitions."""

    original = chat_state_module._chat_state_repository
    counter = {"count": 0}

    @contextmanager
    def counting(project_root):
        counter["count"] += 1
        with original(project_root) as repository:
            yield repository

    monkeypatch.setattr(chat_state_module, "_chat_state_repository", counting)
    return counter


def test_cache_hit_skips_repository_and_returns_equal_payload(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-cache")
    counter = _counting_repository(monkeypatch)

    with _stable_store(tmp_path):
        first = load_session_chat_state(tmp_path, "session-cache")
        second = load_session_chat_state(tmp_path, "session-cache")

    assert first == second
    assert counter["count"] == 1


def test_cache_hit_returns_isolated_copy(tmp_path):
    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        first = load_session_chat_state(tmp_path, "session-cache")
        first["title"] = "mutated-by-caller"
        first.setdefault("metadata", {})["nested"] = {"deep": True}

        second = load_session_chat_state(tmp_path, "session-cache")
        third = load_session_chat_state(tmp_path, "session-cache")

    assert second["title"] == "Session"
    assert "nested" not in (second.get("metadata") or {})
    assert second == third


def test_miss_payload_is_not_shared_with_cache(tmp_path):
    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        fresh = load_session_chat_state(tmp_path, "session-cache")
        fresh["title"] = "mutated-fresh-object"

        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "Session"


def test_save_session_chat_state_invalidates_cache(tmp_path):
    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        assert load_session_chat_state(tmp_path, "session-cache") is not None

        conversation = load_session_chat_state(tmp_path, "session-cache")
        conversation["title"] = "After Update"
        save_session_chat_state(tmp_path, "session-cache", conversation)

        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "After Update"


def test_mutate_chat_state_invalidates_cache(tmp_path):
    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "Session"

        def _rename(state):
            for item in state.get("conversations", []):
                if item.get("conversation_id") == "session-cache":
                    item["title"] = "Mutated Title"
            return state

        mutate_chat_state(tmp_path, _rename)

        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "Mutated Title"


def test_save_chat_state_invalidates_cache(tmp_path):
    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        assert load_session_chat_state(tmp_path, "session-cache") is not None

        save_chat_state(
            tmp_path,
            {
                "version": 1,
                "conversations": [
                    {"conversation_id": "session-cache", "title": "Replaced"},
                ],
            },
        )

        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "Replaced"


def test_external_store_change_invalidates_cache_via_signature(tmp_path, monkeypatch):
    """进程外写不经过本模块 epoch，必须被文件签名兜住。"""

    _seed_session(tmp_path, "session-cache")
    counter = _counting_repository(monkeypatch)

    with _stable_store(tmp_path):
        assert load_session_chat_state(tmp_path, "session-cache")["title"] == "Session"

        db_path = _store_db_path(tmp_path)
        assert db_path.exists()
        stat = db_path.stat()
        bumped_ns = stat.st_mtime_ns + 1_000_000
        os.utime(db_path, ns=(bumped_ns, bumped_ns))

        # epoch 没变，只有签名变了：仍必须重新读存储而不是吐缓存。
        load_session_chat_state(tmp_path, "session-cache")

    assert counter["count"] == 2


def test_missing_session_none_is_cached_then_invalidated_by_save(tmp_path, monkeypatch):
    counter = _counting_repository(monkeypatch)

    with _stable_store(tmp_path):
        assert load_session_chat_state(tmp_path, "session-missing") is None
        assert load_session_chat_state(tmp_path, "session-missing") is None
        assert counter["count"] == 1

        save_session_chat_state(
            tmp_path,
            "session-missing",
            {"conversation_id": "session-missing", "title": "Now Present"},
        )
        assert load_session_chat_state(tmp_path, "session-missing")["title"] == "Now Present"


def test_clear_session_chat_state_cache_forces_reload(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-cache")
    counter = _counting_repository(monkeypatch)

    with _stable_store(tmp_path):
        load_session_chat_state(tmp_path, "session-cache")
        clear_session_chat_state_cache()
        load_session_chat_state(tmp_path, "session-cache")

    assert counter["count"] == 2


def test_hit_matches_uncached_read_exactly(tmp_path):
    """行为等价闸：命中值与清缓存后的直读值完全相等。"""

    _seed_session(tmp_path, "session-cache")
    with _stable_store(tmp_path):
        cached_hits = [
            load_session_chat_state(tmp_path, "session-cache")
            for _ in range(3)
        ]
        clear_session_chat_state_cache()
        fresh = load_session_chat_state(tmp_path, "session-cache")

    for hit in cached_hits:
        assert hit == fresh


def test_standalone_reads_never_serve_stale_rows(tmp_path, monkeypatch):
    """无 borrowed store 时（每次开新 store），行为退化为直读，不缓存也不吐旧值。"""

    counter = _counting_repository(monkeypatch)
    _seed_session(tmp_path, "session-cache")

    first = load_session_chat_state(tmp_path, "session-cache")
    second = load_session_chat_state(tmp_path, "session-cache")

    assert first == second
    # seed 一次 + 两次读全部直读：没有任何读被缓存吸收。
    assert counter["count"] == 3
