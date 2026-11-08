"""Credential apply recovery uses only in-memory config and synthetic secrets."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import llm_credentials, models, public_config
from core.web.services import config_service


@pytest.fixture
def isolated_apply(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    stored = {
        "llm": {
            "schema_version": 2,
            "providers": {
                "synthetic": {
                    "service_class": "relay",
                    "vendor": "multi_model",
                    "driver": "openai",
                    "base_url": "https://synthetic.example/v1",
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_SYNTHETIC_WRITE_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "responses", "allowed": ["responses"]},
                    "models": {"model": {"upstream_id": "synthetic-model", "enabled": True}},
                }
            },
            "profiles": {"primary": {"model_ref": "synthetic/model"}},
            "model_aliases": {},
        },
        "git": {"commit_message_model_ref": "synthetic/model"},
        "ui": {"language": "en"},
    }
    credential_store = {"VIBELUTION_LLM_SYNTHETIC_WRITE_API_KEY": "old-synthetic-key"}
    scene_events = []
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_service, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_service, "MODEL_REFERENCE_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_service, "_PENDING_API_KEY_SECRETS", {})
    monkeypatch.setattr(config_service, "_PENDING_CLEAR_ENVS", set())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(stored))

    def save_config(value):
        stored.clear()
        stored.update(copy.deepcopy(value))

    def unexpected_credential_write(*_args):
        pytest.fail("credential storage must be replaced by the test")

    monkeypatch.setattr(config_service, "save_public_config", save_config)
    monkeypatch.setattr(config_service, "reload_config", lambda *_args: None)
    monkeypatch.setattr(config_service, "_read_raw_public_config", lambda: "")
    monkeypatch.setattr(config_service, "materialize_observed_binding_pins", lambda value: value)
    monkeypatch.setattr(config_service, "_sweep_absent_model_catalog_providers", lambda _value: [])
    monkeypatch.setattr(config_service, "_set_user_env_var", unexpected_credential_write)
    monkeypatch.setattr(config_service, "_delete_user_env_var", unexpected_credential_write)
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, code, **kwargs: scene_events.append((phase, code, kwargs)),
    )
    # Block ambient key reads as well as writes. The credential resolver binds
    # its reader as a default argument, so patch that binding explicitly.
    for module in (models, public_config, config_service, llm_credentials):
        monkeypatch.setattr(module, "_read_env_var", credential_store.get)
    monkeypatch.setattr(
        llm_credentials.resolve_credential_ref,
        "__kwdefaults__",
        {"env_reader": credential_store.get, "resolve_secret": False},
    )

    from core.web.routes.config import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, stored=stored, credential_store=credential_store, scene_events=scene_events
        )


@pytest.mark.parametrize("language", ["en", "zh"])
def test_partial_apply_returns_only_failed_credentials_for_retry(monkeypatch, isolated_apply, language):
    state = isolated_apply
    state.stored["ui"]["language"] = language
    failed_write = "VIBELUTION_LLM_SYNTHETIC_WRITE_API_KEY"
    healthy_write = "VIBELUTION_LLM_SYNTHETIC_HEALTHY_API_KEY"
    failed_clear = "VIBELUTION_LLM_SYNTHETIC_CLEAR_API_KEY"
    healthy_clear = "VIBELUTION_LLM_SYNTHETIC_CLEAR_HEALTHY_API_KEY"
    foreign_write = "VIBELUTION_LLM_SYNTHETIC_OTHER_DRAFT_API_KEY"
    foreign_clear = "VIBELUTION_LLM_SYNTHETIC_OTHER_CLEAR_API_KEY"
    state.credential_store.update({failed_write: "old-synthetic-key", failed_clear: "old-clear-key"})
    state.credential_store[healthy_clear] = "old-healthy-clear-key"
    state.credential_store[foreign_clear] = "other-draft-clear-key"
    writes, deletes = [], []
    fail_once = {failed_write, failed_clear}

    def write_credential(name, value):
        writes.append(name)
        if name in fail_once:
            fail_once.remove(name)
            raise PermissionError(f"synthetic-new-key must not reach diagnostics: {value}")
        state.credential_store[name] = value

    def delete_credential(name):
        deletes.append(name)
        if name in fail_once:
            fail_once.remove(name)
            raise PermissionError("old-clear-key must not reach diagnostics")
        state.credential_store.pop(name, None)

    monkeypatch.setattr(config_service, "_set_user_env_var", write_credential)
    monkeypatch.setattr(config_service, "_delete_user_env_var", delete_credential)
    meta = config_service._with_pending_api_key({}, failed_write, "synthetic-new-key")
    meta = config_service._with_pending_api_key(meta, healthy_write, "synthetic-healthy-key")
    meta = config_service._with_cleared_api_key(meta, failed_clear)
    meta = config_service._with_cleared_api_key(meta, healthy_clear)
    original_meta = copy.deepcopy(meta)
    foreign_meta = config_service._with_pending_api_key({}, foreign_write, "synthetic-other-key")
    foreign_meta = config_service._with_cleared_api_key(foreign_meta, foreign_clear)
    submitted = copy.deepcopy(state.stored)
    submitted["ui"]["credential_apply_probe"] = "persisted"

    response = state.client.put(
        "/api/config/apply", json={"publicConfig": submitted, "draftMeta": meta}
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draftMeta"] == {
        "pending_api_keys": {failed_write: meta["pending_api_keys"][failed_write]},
        "pending_cleared_api_keys": [failed_clear],
    }
    assert payload["envWriteFailureCount"] == 2
    assert payload["envWriteFailures"] == [
        {"env": failed_clear, "operation": "delete", "errorType": "PermissionError"},
        {"env": failed_write, "operation": "write", "errorType": "PermissionError"},
    ]
    assert state.stored["ui"]["credential_apply_probe"] == "persisted"
    assert payload["baseHash"] == payload["hash"]
    assert state.credential_store[failed_write] == "old-synthetic-key"
    assert state.credential_store[failed_clear] == "old-clear-key"
    assert state.credential_store[healthy_write] == "synthetic-healthy-key"
    assert healthy_clear not in state.credential_store
    assert config_service._resolve_pending_api_key(healthy_write, meta["pending_api_keys"][healthy_write]) is None
    assert healthy_clear not in config_service._PENDING_CLEAR_ENVS
    assert failed_clear in config_service._PENDING_CLEAR_ENVS
    assert meta == original_meta
    if language == "en":
        assert "retry" in payload["message"].lower()
    else:
        assert "重试" in payload["message"]
    applied = [event[2] for event in state.scene_events if event[1] == "config.workspace.applied"][-1]
    assert applied["outcome"] == "partial"
    assert applied["fields"]["clearedApiKeyEnvs"] == [healthy_clear]
    assert applied["fields"]["clearedApiKeyEnvCount"] == 1

    # An unrelated apply must not pull failed or foreign drafts from globals.
    response = state.client.put("/api/config/apply", json={"publicConfig": payload["publicConfig"]})
    assert response.status_code == 200, response.text
    assert response.json()["draftMeta"] == config_service._empty_draft_meta()
    assert writes == [failed_write, healthy_write]
    assert deletes == [failed_clear, healthy_clear]

    retry = state.client.put(
        "/api/config/apply",
        json={
            "publicConfig": payload["publicConfig"],
            "baseHash": payload["baseHash"],
            "draftMeta": payload["draftMeta"],
        },
    )
    assert retry.status_code == 200, retry.text
    recovered = retry.json()
    assert recovered["draftMeta"] == config_service._empty_draft_meta()
    assert recovered["envWriteFailureCount"] == 0
    assert recovered["envWriteFailures"] == []
    applied = [event[2] for event in state.scene_events if event[1] == "config.workspace.applied"][-1]
    assert applied["outcome"] == "succeeded"
    assert writes == [failed_write, healthy_write, failed_write]
    assert deletes == [failed_clear, healthy_clear, failed_clear]
    assert state.credential_store[failed_write] == "synthetic-new-key"
    assert failed_clear not in state.credential_store
    assert config_service._resolve_pending_api_key(failed_write, meta["pending_api_keys"][failed_write]) is None
    assert config_service._normalize_draft_meta(foreign_meta) == foreign_meta
    assert state.credential_store[foreign_clear] == "other-draft-clear-key"
    assert foreign_write not in state.credential_store
    assert "synthetic-new-key" not in json.dumps([payload, recovered, state.scene_events, state.stored])
    for secret in ("old-clear-key", "old-synthetic-key", "synthetic-healthy-key", "synthetic-other-key"):
        assert secret not in json.dumps([payload, recovered, state.scene_events])


def test_apply_does_not_return_forged_or_mismatched_pending_tokens(isolated_apply):
    env_name = "VIBELUTION_LLM_SYNTHETIC_VALID_API_KEY"
    other_env = "VIBELUTION_LLM_SYNTHETIC_MISMATCH_API_KEY"
    valid_meta = config_service._with_pending_api_key({}, env_name, "synthetic-unsubmitted-key")
    response = isolated_apply.client.put(
        "/api/config/apply",
        json={
            "publicConfig": isolated_apply.stored,
            "draftMeta": {"pending_api_keys": {
                env_name: "synthetic-forged-value",
                other_env: valid_meta["pending_api_keys"][env_name],
            }},
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draftMeta"] == config_service._empty_draft_meta()
    assert payload["envWriteFailureCount"] == 0
    assert config_service._normalize_draft_meta(valid_meta) == valid_meta
    assert "synthetic-unsubmitted-key" not in response.text
    assert "synthetic-forged-value" not in response.text


@pytest.mark.parametrize("fail_write", [False, True])
def test_apply_write_intent_takes_precedence_over_same_env_clear(monkeypatch, isolated_apply, fail_write):
    state = isolated_apply
    env_name = "VIBELUTION_LLM_SYNTHETIC_CONFLICT_API_KEY"
    state.credential_store[env_name] = "synthetic-old-key"
    writes, deletes = [], []
    meta = config_service._with_pending_api_key({}, env_name, "synthetic-replacement-key")
    # Normal draft helpers keep these disjoint. A submitted payload can still
    # contradict itself; its final write must never leave a destructive retry.
    meta["pending_cleared_api_keys"] = [env_name]
    foreign_clear_meta = config_service._with_cleared_api_key({}, env_name)

    def write_credential(name, value):
        writes.append(name)
        if fail_write:
            raise PermissionError("synthetic write denied")
        state.credential_store[name] = value

    def delete_credential(name):
        deletes.append(name)
        state.credential_store.pop(name, None)

    monkeypatch.setattr(config_service, "_set_user_env_var", write_credential)
    monkeypatch.setattr(config_service, "_delete_user_env_var", delete_credential)
    response = state.client.put(
        "/api/config/apply", json={"publicConfig": state.stored, "draftMeta": meta}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert writes == [env_name]
    assert deletes == []
    assert payload["draftMeta"]["pending_cleared_api_keys"] == []
    assert env_name in config_service._PENDING_CLEAR_ENVS
    assert config_service._normalize_draft_meta(foreign_clear_meta) == foreign_clear_meta
    if fail_write:
        assert state.credential_store[env_name] == "synthetic-old-key"
        assert payload["draftMeta"]["pending_api_keys"] == meta["pending_api_keys"]
        assert payload["envWriteFailureCount"] == 1
        assert config_service._resolve_pending_api_key(env_name, meta["pending_api_keys"][env_name]) is not None
    else:
        assert state.credential_store[env_name] == "synthetic-replacement-key"
        assert payload["draftMeta"] == config_service._empty_draft_meta()
        assert payload["envWriteFailureCount"] == 0
        assert config_service._resolve_pending_api_key(env_name, meta["pending_api_keys"][env_name]) is None
