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
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    _warm_config_init()
    counters: dict = {}
    _count_builder(monkeypatch, "_build_workspace", counters)
    _count_builder(monkeypatch, "_build_config_summary", counters)

    config_service.get_config_workspace()
    config_service.get_config_summary()
    assert counters == {"_build_workspace": 1, "_build_config_summary": 1}

    summary = config_service.update_language("en")
    assert summary["language"] == "en"
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
