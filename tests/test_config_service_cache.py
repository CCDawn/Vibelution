"""Result-level cache behavior for the config workspace/summary getters.

get_config_workspace / get_config_summary cache their payloads keyed by the
config.toml + model-catalog-state.json on-disk signature with a TTL. These
tests pin: in-TTL hits, deep-copy isolation, explicit invalidation on every
config_service write path, TTL expiry, and signature-change invalidation.
"""

import copy
import json
import os
import sqlite3
import threading
import time

import pytest

from config.model_catalog import (
    empty_model_catalog_state,
    load_model_catalog_state,
    save_model_catalog_state,
)
from core.web.services import config_service
from core.web.services import model_reference_service
from core.web.services.session.directory_runtime import conversation_store_path

pytestmark = pytest.mark.serial


@pytest.fixture(autouse=True)
def _reset_config_result_cache():
    config_service._invalidate_config_result_cache()
    yield
    config_service._invalidate_config_result_cache()


def _provider(credential_ref: str) -> dict:
    return {
        "label": "Relay",
        "service_class": "relay",
        "vendor": "multi_model",
        "driver": "openai",
        "base_url": "https://relay.example/v1",
        "auth_kind": "api_key",
        "credential_ref": credential_ref,
        "requires_credential": True,
        "protocols": {
            "default": "responses",
            "allowed": ["responses", "chat_completions"],
        },
        "discovery": {
            "mode": "auto",
            "adapter": "openai_compatible",
            "cache_ttl_seconds": 3600,
        },
        "models": {},
    }


def _v2_single_provider_config() -> dict:
    provider = _provider("env:VIBELUTION_LLM_PROVIDER_RELAY_KEEP_API_KEY")
    provider["models"]["base-model"] = {
        "upstream_id": "base-model",
        "label": "Base Model",
        "enabled": True,
    }
    return {
        "llm": {
            "schema_version": 2,
            "providers": {"relay_keep": provider},
            "profiles": {
                "primary": {"model_ref": "relay_keep/base-model", "overrides": {}}
            },
            "model_aliases": {},
        }
    }


def _count_builder(monkeypatch, name: str, counters: dict) -> None:
    real = getattr(config_service, name)

    def counting(*args, **kwargs):
        counters[name] = counters.get(name, 0) + 1
        return real(*args, **kwargs)

    monkeypatch.setattr(config_service, name, counting)


def _count_loader(monkeypatch, counters: dict) -> None:
    real_load = config_service.load_public_config

    def counting_load():
        counters["load_public_config"] = counters.get("load_public_config", 0) + 1
        return real_load()

    monkeypatch.setattr(config_service, "load_public_config", counting_load)


def _warm_config_init() -> None:
    # ensure_global_config_initialized may create config.toml / catalog files
    # mid-compute on the very first read; warm both resolved locations up front
    # so counted runs see a stable on-disk signature.
    from config.paths import ensure_global_config_initialized, resolve_config_path

    ensure_global_config_initialized(resolve_config_path())
    config_service.load_public_config()


def test_config_workspace_result_cache_hits_within_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)
    _count_loader(monkeypatch, counters)

    first = config_service.get_config_workspace()
    second = config_service.get_config_workspace()

    # 有效期内涵第二次调用：不重读 config、不重算 workspace。
    assert counters == {"_build_workspace": 1, "load_public_config": 1}
    assert second is not first
    assert second == first

    # 缓存必须发深拷贝：改动返回值不得污染缓存。
    first["modelLibraryCount"] = -999
    first["sections"] = None
    third = config_service.get_config_workspace()
    assert counters == {"_build_workspace": 1, "load_public_config": 1}
    assert third == second
    assert third["modelLibraryCount"] != -999
    assert third["sections"] is not None


def test_config_summary_result_cache_hits_within_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_config_summary", counters)
    _count_loader(monkeypatch, counters)

    first = config_service.get_config_summary()
    second = config_service.get_config_summary()

    assert counters == {"_build_config_summary": 1, "load_public_config": 1}
    assert second is not first
    assert second == first

    first["modelLibraryCount"] = -999
    third = config_service.get_config_summary()
    assert third == second
    assert third["modelLibraryCount"] != -999


def test_update_language_invalidates_result_cache(monkeypatch, tmp_path):
    # 隔离必须 patch public_config 的 CONFIG_PATH 模块属性：setenv 对
    # public_config 的无参读写无效（CONFIG_PATH 是 import 期常量），会把
    # update_language 的落盘打到真实 operator config——正是 ui.language
    # 漂移事故的根因机制。保留 setenv 仅供 _warm_config_init 里动态解析
    # env 的 ensure_global_config_initialized 建出同一个 tmp 文件。
    from config import public_config as public_config_module

    config_path = tmp_path / "config.toml"
    public_config_module._reset_public_config_cache()
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(public_config_module, "CONFIG_PATH", config_path)
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)
    _count_builder(monkeypatch, "_build_config_summary", counters)

    config_service.get_config_workspace()
    config_service.get_config_summary()
    assert counters == {"_build_workspace": 1, "_build_config_summary": 1}

    summary = config_service.update_language("en")
    assert summary["language"] == "en"
    # 落盘目标必须是 tmp 隔离文件：磁盘断言钉住写入路径，防止打到真实配置。
    assert public_config_module.load_public_config(config_path)["ui"]["language"] == "en"
    # update_language 写后失效并内部重算 summary；workspace 条目也被清掉。
    assert counters == {"_build_workspace": 1, "_build_config_summary": 2}

    workspace = config_service.get_config_workspace()
    assert workspace["language"] == "en"
    fresh_summary = config_service.get_config_summary()
    assert fresh_summary["language"] == "en"
    assert counters == {"_build_workspace": 2, "_build_config_summary": 2}


def test_update_language_override_writes_language_over_stored_value(monkeypatch, tmp_path):
    """update_language 是合法语言写入方：显式 override 绕过落盘层保留语义。

    磁盘存量 zh 时整份写会被回填回 zh（save_public_config 保留模式），
    只有 override 声明才能把语言真正改成 en，再改回 zh 同理。

    隔离用 monkeypatch CONFIG_PATH 模块属性（test_public_config_model_refs
    同款）：setenv("VIBELUTION_CONFIG_PATH") 对 public_config 的无参读写
    无效——默认路径是 import 期常量，env 后设不生效，会把保存打到真实
    operator config。
    """

    from config import public_config as public_config_module

    config_path = tmp_path / "config.toml"
    config_path.write_text('[ui]\nlanguage = "zh"\n', encoding="utf-8")
    public_config_module._reset_public_config_cache()
    monkeypatch.setattr(public_config_module, "CONFIG_PATH", config_path)
    config_service._invalidate_config_result_cache()

    summary = config_service.update_language("en")

    assert summary["language"] == "en"
    assert public_config_module.load_public_config(config_path)["ui"]["language"] == "en"

    summary = config_service.update_language("zh")

    assert summary["language"] == "zh"
    assert public_config_module.load_public_config(config_path)["ui"]["language"] == "zh"


def test_catalog_sweep_write_invalidates_result_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_config_summary", counters)

    # 先填 summary 缓存，再用真实 catalog 写路径（sweep 落盘）触发失效。
    config_service.get_config_summary()
    assert counters == {"_build_config_summary": 1}

    state = empty_model_catalog_state()
    state["providers"]["relay_keep"] = {
        "providerFingerprint": "fp-keep",
        "status": "reachable",
        "catalogStale": False,
        "lastAttemptAt": "2026-07-11T00:00:00+00:00",
        "lastSuccessAt": "2026-07-11T00:00:00+00:00",
        "lastErrorType": "",
        "models": {},
    }
    state["providers"]["relay_dead"] = {
        "providerFingerprint": "fp-dead",
        "status": "reachable",
        "catalogStale": False,
        "lastAttemptAt": "2026-07-11T00:00:00+00:00",
        "lastSuccessAt": "2026-07-11T00:00:00+00:00",
        "lastErrorType": "",
        "models": {
            "observed-model": {
                "upstreamId": "observed-model",
                "availability": "observed",
                "label": "Observed",
            }
        },
    }
    save_model_catalog_state(state)
    saved_config = _v2_single_provider_config()
    pruned = config_service._sweep_absent_model_catalog_providers(saved_config)
    assert pruned == ["relay_dead"]
    assert set(load_model_catalog_state()["providers"]) == {"relay_keep"}

    # catalog state 落盘后 summary 缓存已失效，必须重算。
    config_service.get_config_summary()
    assert counters == {"_build_config_summary": 2}


def _seed_agent_store_binding(project_root, dialogue_model_id: str) -> None:
    """Create a minimal conversations.sqlite3 with one bound agent config."""
    db_path = conversation_store_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE agents (
              agent_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL,
              kind TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              current_config_revision_id TEXT,
              created_at_ms INTEGER NOT NULL,
              updated_at_ms INTEGER NOT NULL,
              archived_at_ms INTEGER
            );
            CREATE TABLE agent_config_revisions (
              revision_id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL,
              config_hash TEXT NOT NULL,
              config_json TEXT NOT NULL,
              source TEXT NOT NULL,
              created_at_ms INTEGER NOT NULL
            );
            """
        )
        now_ms = 1_700_000_000_000
        connection.execute(
            "INSERT INTO agents (agent_id, display_name, kind, status, created_at_ms, updated_at_ms)"
            " VALUES ('agent-live', 'Live Agent', 'chat', 'active', ?, ?)",
            (now_ms, now_ms),
        )
        connection.execute(
            "INSERT INTO agent_config_revisions"
            " (revision_id, agent_id, config_hash, config_json, source, created_at_ms)"
            " VALUES ('agent-live:r1', 'agent-live', 'hash', ?, 'test', ?)",
            (json.dumps({"dialogueModelId": dialogue_model_id}), now_ms),
        )
        connection.commit()
    finally:
        connection.close()


def test_catalog_sweep_skips_provider_with_live_dialogue_binding(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    # 活引用扫描只看本测试的临时 agent 存储，不读真实 workspace。
    monkeypatch.setattr(model_reference_service, "PROJECT_ROOT", tmp_path)
    scene_events: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    state = empty_model_catalog_state()
    for provider_id, fingerprint in (
        ("relay_keep", "fp-keep"),
        ("relay_live", "fp-live"),
        ("relay_dead", "fp-dead"),
    ):
        state["providers"][provider_id] = {
            "providerFingerprint": fingerprint,
            "status": "reachable",
            "catalogStale": False,
            "lastAttemptAt": "2026-07-11T00:00:00+00:00",
            "lastSuccessAt": "2026-07-11T00:00:00+00:00",
            "lastErrorType": "",
            "models": {},
        }
    save_model_catalog_state(state)
    _seed_agent_store_binding(tmp_path, "relay_live/bound-model")

    pruned = config_service._sweep_absent_model_catalog_providers(_v2_single_provider_config())

    # 仍被活会话对话绑定引用的 provider 目录保留，无引用的照常 prune。
    assert pruned == ["relay_dead"]
    assert set(load_model_catalog_state()["providers"]) == {"relay_keep", "relay_live"}
    assert [event[1] for event in scene_events] == ["config.model_catalog.prune_skipped_live_refs"]
    assert scene_events[0][2]["fields"] == {"providerId": "relay_live", "liveReferenceCount": 1}


def test_saved_model_verification_write_invalidates_result_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)

    config_service.get_config_workspace()
    assert counters == {"_build_workspace": 1}

    saved_config = _v2_single_provider_config()
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(saved_config))
    persisted = config_service._persist_saved_model_verification(
        saved_config,
        None,
        "relay_keep/base-model",
        {
            "checked_at": "2026-10-01T00:00:00+00:00",
            "status": "verified",
            "error_type": "",
            "http_status": 200,
            "message": "ok",
        },
    )
    assert persisted is True

    # catalog state 已被「测试调用」落盘，workspace 缓存必须重算。
    config_service.get_config_workspace()
    assert counters == {"_build_workspace": 2}


def test_config_result_cache_ttl_expiry_recomputes(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    monkeypatch.setattr(config_service, "_CONFIG_RESULT_CACHE_TTL_SECONDS", 0.0)
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)

    config_service.get_config_workspace()
    config_service.get_config_workspace()

    # TTL=0：条目存入即过期，第二次读取必须重算。
    assert counters == {"_build_workspace": 2}


def test_config_cache_signature_change_invalidates(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    catalog_path = tmp_path / "model-catalog-state.json"
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    _warm_config_init()
    save_model_catalog_state(empty_model_catalog_state())
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)

    first = config_service.get_config_workspace()
    assert counters == {"_build_workspace": 1}

    # 文件签名变化（外部手改 mtime）立即失效，不等 TTL。
    stat = config_path.stat()
    os.utime(config_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    config_service.get_config_workspace()
    assert counters == {"_build_workspace": 2}

    stat = catalog_path.stat()
    os.utime(catalog_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    third = config_service.get_config_workspace()
    assert counters == {"_build_workspace": 3}
    # 内容未变，重算结果与首次构建一致。
    assert third == first


# ---------------------------------------------------------------------------
# Per-key single-flight（冷启动并发首击只付一次全价）。
# ---------------------------------------------------------------------------


def _slow_counting_builder(monkeypatch, *, build_seconds: float):
    """Replace _build_workspace with a slow counting stand-in.

    Returns (build_calls, build_entered). build_entered is set when the first
    build starts so tests can pin a leader as in-flight before adding waiters.
    """

    real_build = config_service._build_workspace
    build_calls: list[int] = []
    build_entered = threading.Event()

    def slow_counting(*args, **kwargs):
        build_calls.append(1)
        build_entered.set()
        time.sleep(build_seconds)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(config_service, "_build_workspace", slow_counting)
    return build_calls, build_entered


def _run_concurrent_hits(worker_count: int, target=None):
    """Start worker_count threads hitting the same getter behind a barrier."""

    if target is None:
        target = config_service.get_config_workspace
    barrier = threading.Barrier(worker_count)
    results: list = []
    errors: list = []

    def hit():
        barrier.wait()
        try:
            results.append(target())
        except Exception as exc:  # noqa: BLE001 - the test asserts on outcomes
            errors.append(exc)

    threads = [threading.Thread(target=hit) for _ in range(worker_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results, errors


def test_config_workspace_concurrent_first_hits_compute_once(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    build_calls, _ = _slow_counting_builder(monkeypatch, build_seconds=0.15)

    results, errors = _run_concurrent_hits(6)

    assert errors == []
    assert len(results) == 6
    # 同 key 并发首击：底层构建只发生一次，等待者共享同一份结果。
    assert len(build_calls) == 1
    assert all(result == results[0] for result in results)
    assert all(result is not results[0] for result in results[1:])

    # 热态再读：走缓存，不再构建。
    config_service.get_config_workspace()
    assert len(build_calls) == 1


def test_config_summary_concurrent_first_hits_compute_once(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    real_build = config_service._build_config_summary
    build_calls: list[int] = []

    def slow_counting(*args, **kwargs):
        build_calls.append(1)
        time.sleep(0.15)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(config_service, "_build_config_summary", slow_counting)

    results, errors = _run_concurrent_hits(5, target=config_service.get_config_summary)

    assert errors == []
    assert len(results) == 5
    assert len(build_calls) == 1
    assert all(result == results[0] for result in results)


def test_config_single_flight_failure_is_not_shared(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    real_build = config_service._build_workspace
    build_calls: list[int] = []

    def flaky_build(*args, **kwargs):
        build_calls.append(1)
        if len(build_calls) == 1:
            raise RuntimeError("injected first-build failure")
        time.sleep(0.1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(config_service, "_build_workspace", flaky_build)

    results, errors = _run_concurrent_hits(4)

    # 成功共享、失败不共享：首击者拿到注入异常，等待者各自重算并成功。
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert len(results) == 3
    assert all(result == results[0] for result in results)
    assert len(build_calls) >= 2

    # 失败后缓存不落毒：成功者的构建已把缓存填好，顺序读取命中、不再构建。
    payload = config_service.get_config_workspace()
    assert len(build_calls) == 2
    assert payload == results[0]


def test_config_single_flight_waiter_timeout_computes_own(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    monkeypatch.setattr(
        config_service, "_CONFIG_RESULT_FLIGHT_WAIT_TIMEOUT_SECONDS", 0.05
    )
    build_calls, build_entered = _slow_counting_builder(
        monkeypatch, build_seconds=0.5
    )

    leader = threading.Thread(target=config_service.get_config_workspace)
    leader.start()
    assert build_entered.wait(timeout=5), "leader never entered the build"

    waiter_payload = config_service.get_config_workspace()
    leader.join(timeout=30)
    leader_payload = config_service.get_config_workspace()

    # 等待者超过兜底窗口后自行计算（不永等）：总构建 2 次（领导一次、
    # 超时等待者一次），而非等待者无限挂起或共享领导的单次构建。
    assert len(build_calls) == 2
    assert waiter_payload == leader_payload


def test_config_single_flight_rearms_after_invalidation(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    build_calls, _ = _slow_counting_builder(monkeypatch, build_seconds=0.15)

    results, errors = _run_concurrent_hits(4)
    assert errors == []
    assert len(build_calls) == 1

    # 失效（writer 无锁换出）后新一轮并发首击重新 single-flight。
    config_service._invalidate_config_result_cache()
    results2, errors2 = _run_concurrent_hits(4)
    assert errors2 == []
    assert len(build_calls) == 2
    assert all(result == results2[0] for result in results2)
    assert results2[0] == results[0]
