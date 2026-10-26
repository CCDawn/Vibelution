"""Read-only configuration/catalog snapshots and opt-in discovery injection."""
from __future__ import annotations

import copy
import json
import tomllib
from types import SimpleNamespace

import pytest

from tests.test_external_management_session_parameters import PUBLIC_CONFIG


def test_peek_does_not_construct_or_load_settings(monkeypatch):
    from config import settings
    def forbidden(*_a, **_k):
        pytest.fail("peek initialized configuration")
    monkeypatch.setattr(settings, "get_settings", forbidden)
    monkeypatch.setattr(settings.ConfigLoader, "load", forbidden)
    monkeypatch.setattr(settings, "_settings", None)
    assert settings.peek_loaded_config_snapshot() is None
    monkeypatch.setattr(settings, "_settings", settings.Settings())
    assert settings.peek_loaded_config_snapshot() is None


@pytest.mark.parametrize("replacement", ["settings", "config"])
def test_peek_rejects_rebound_source_and_returns_private_copy(monkeypatch, replacement):
    from config import settings
    original = SimpleNamespace(_config={"nested": [1]})
    monkeypatch.setattr(settings, "_settings", original)
    result = settings.peek_loaded_config_snapshot()
    result["nested"].append(2)
    assert original._config == {"nested": [1]}
    deepcopy = copy.deepcopy
    def race(value):
        if replacement == "settings":
            monkeypatch.setattr(settings, "_settings", SimpleNamespace(_config=value))
        else:
            original._config = {"replacement": True}
        return deepcopy(value)
    monkeypatch.setattr(settings.copy, "deepcopy", race)
    assert settings.peek_loaded_config_snapshot() is None


def test_catalog_snapshot_missing_is_explicit_and_never_creates(tmp_path):
    from config import model_catalog
    path = tmp_path / "absent" / "catalog.json"
    with pytest.raises(ValueError, match="EXISTING_MODEL_CATALOG_UNAVAILABLE"):
        model_catalog.read_existing_model_catalog_snapshot(path)
    state, source = model_catalog.read_existing_model_catalog_snapshot(path, allow_missing=True)
    assert state == model_catalog.empty_model_catalog_state() and source == "absent"
    assert not path.parent.exists()


@pytest.mark.parametrize("payload", ["{broken", "[]", '{"schemaVersion":2,"providers":{},"metadata":NaN}',
    '{"schemaVersion":2,"schemaVersion":2,"providers":{},"metadata":{}}',
    '{"schemaVersion":2,"providers":[],"metadata":{}}',
    '{"schemaVersion":2,"providers":{"fixture":{"models":[]}},"metadata":{}}',
    '{"schemaVersion":2,"providers":{"fixture":{"models":{"model":{"reasoningContract":[]}}}},"metadata":{}}'])
def test_catalog_snapshot_rejects_corruption_instead_of_empty_fallback(tmp_path, payload):
    from config import model_catalog
    path = tmp_path / "catalog.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="EXISTING_MODEL_CATALOG_UNAVAILABLE"):
        model_catalog.read_existing_model_catalog_snapshot(path, allow_missing=True)


def test_catalog_snapshot_rejects_changed_handle(tmp_path, monkeypatch):
    from config import model_catalog
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(model_catalog.empty_model_catalog_state()), encoding="utf-8")
    real_fstat = model_catalog.os.fstat
    count = 0
    def fstat(fd):
        nonlocal count
        result = real_fstat(fd)
        count += 1
        if count == 2:
            values = {name: getattr(result, name) for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
            values["st_mtime_ns"] += 1
            return SimpleNamespace(**values)
        return result
    monkeypatch.setattr(model_catalog.os, "fstat", fstat)
    with pytest.raises(ValueError, match="EXISTING_MODEL_CATALOG_UNAVAILABLE"):
        model_catalog.read_existing_model_catalog_snapshot(path)


def test_catalog_snapshot_bounds_input_before_opening(tmp_path, monkeypatch):
    from config import model_catalog
    path = tmp_path / "catalog.json"
    path.write_text("{}", encoding="utf-8")
    real_stat, real_open = type(path).stat, type(path).open
    def stat(target, *args, **kwargs):
        if target == path:
            return SimpleNamespace(st_size=16 * 1024 * 1024 + 1)
        return real_stat(target, *args, **kwargs)
    def open_file(target, *args, **kwargs):
        if target == path:
            pytest.fail("oversized catalog was opened")
        return real_open(target, *args, **kwargs)
    monkeypatch.setattr(type(path), "stat", stat)
    monkeypatch.setattr(type(path), "open", open_file)
    with pytest.raises(ValueError, match="EXISTING_MODEL_CATALOG_UNAVAILABLE"):
        model_catalog.read_existing_model_catalog_snapshot(path)


def test_explicit_catalog_snapshot_freezes_both_runtime_discoveries(monkeypatch):
    from config import public_config
    from core.llm import discovery
    from core.llm.agent_runtime import resolve_agent_llm
    config = public_config.build_effective_config(tomllib.loads(PUBLIC_CONFIG))
    agent = {"agentId": "a", "llmBindings": {"dialogue": {"modelId": "fixture/model"}},
        "metadata": {"llmModelParameters": {"fixture/model": {"contextWindow": 32000}}}}
    def forbidden():
        pytest.fail("explicit catalog snapshot fell through to global loader")
    monkeypatch.setattr(discovery, "load_model_catalog_state", forbidden)
    snapshot = {"providers": {"fixture": {"models": {"model": {"contextWindow": 900000}}}}}
    before = copy.deepcopy((config.model_dump(), agent, snapshot))
    resolved = resolve_agent_llm(agent, config=config, catalog_snapshot=snapshot)
    assert resolved.resolved_spec.context_window == 32000
    assert (config.model_dump(), agent, snapshot) == before


def test_omitted_snapshot_preserves_old_discovery_call_signatures(monkeypatch):
    from config import public_config
    from core.llm import agent_runtime, discovery
    config = public_config.build_effective_config(tomllib.loads(PUBLIC_CONFIG))
    spec = discovery.discover_model(config, "primary", catalog_snapshot={})
    calls = []
    # Existing narrow mocks/callers need no new keyword when the option is omitted.
    def old_discover(cfg, profile_id):
        calls.append(profile_id)
        return copy.deepcopy(spec)
    monkeypatch.setattr(agent_runtime, "discover_model", old_discover)
    agent = {"llmBindings": {"dialogue": {"modelId": "fixture/model"}}}
    agent_runtime.resolve_agent_llm(agent, config=config)
    assert calls == ["primary"]
    def old_details(provider_id, model_ref):
        assert (provider_id, model_ref) == ("fixture", "fixture/model")
        return {}, {}
    monkeypatch.setattr(discovery, "_catalog_model_details", old_details)
    assert discovery.discover_model(config, "primary").provider_details["model_ref"] == "fixture/model"
