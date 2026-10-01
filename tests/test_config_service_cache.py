"""Result-level cache behavior for the config workspace/summary getters.

get_config_workspace / get_config_summary cache their payloads keyed by the
config.toml + model-catalog-state.json on-disk signature with a TTL. These
tests pin: in-TTL hits, deep-copy isolation, explicit invalidation on every
config_service write path, TTL expiry, and signature-change invalidation.
"""

import copy
import os

import pytest

from config.model_catalog import (
    empty_model_catalog_state,
    load_model_catalog_state,
    save_model_catalog_state,
)
from core.web.services import config_service

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
