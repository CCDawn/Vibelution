import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_chat_state
from core.web.services import session_service
from core.web.services.session import title_generation
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _seed_conversation(tmp_path, session_id="session-a", **overrides):
    row = {
        "conversation_id": session_id,
        "title": "默认对话",
        "session_kind": "main",
        "last_turn_status": "ready",
    }
    row.update(overrides)
    save_chat_state(tmp_path, {"version": 1, "conversations": [row]})


def _patch_session_writes(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_is_session_workspace_intentionally_deleted",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(session_service, "_conversation_is_read_only", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "_invalidate_session_list_cache", lambda: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *_args, **_kwargs: {"accepted": True})
    monkeypatch.setattr(
        "core.web.services.session.directory_bridge.touch_directory_session_safe",
        lambda *_args, **_kwargs: None,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("修复登录 bug。", "修复登录 bug"),
        ('"Session title: Fix login flow"', "Fix login flow"),
        ("标题：优化数据库查询", "优化数据库查询"),
        ("<thinking>hmm</thinking>Clean Title", "Clean Title"),
        ("First line\nSecond line", "First line"),
        ("修复 bug (v2)", "修复 bug (v2)"),
        ("「深色模式」", "深色模式"),
        ("  ", ""),
        ("", ""),
        ("a" * 80, "a" * title_generation.SESSION_TITLE_MAX_CHARS),
    ],
)
def test_clean_generated_session_title(raw, expected):
    assert title_generation.clean_generated_session_title(raw) == expected


def test_apply_generated_session_title_replaces_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_conversation(tmp_path)
    _patch_session_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "修复登录 bug") is True
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "修复登录 bug"


def test_apply_generated_session_title_keeps_manual_rename(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_conversation(tmp_path, title="手动命名")
    _patch_session_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "自动标题") is False
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "手动命名"


def test_apply_generated_session_title_skips_child_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_conversation(tmp_path, title="新会话", session_kind="child")
    _patch_session_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "自动标题") is False
    assert load_session_chat_state(tmp_path, "session-a")["title"] == "新会话"


def test_apply_generated_session_title_skips_identical_title(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_conversation(tmp_path)
    _patch_session_writes(monkeypatch)

    assert session_service.apply_generated_session_title("session-a", "默认对话") is False


def test_generate_session_title_now_applies_candidate(monkeypatch):
    monkeypatch.setattr(title_generation, "_resolve_title_model_id", lambda _session_id: "model-a")
    monkeypatch.setattr(
        title_generation,
        "_generate_title_candidate",
        lambda session_id, message, model_id: "Alpha",
    )
    applied: dict[str, str] = {}
    monkeypatch.setattr(
        session_service,
        "apply_generated_session_title",
        lambda session_id, title, **kwargs: applied.update(sessionId=session_id, title=title, **kwargs) or True,
    )

    assert title_generation.generate_session_title_now("session-a", "  hi  ") == "Alpha"
    assert applied == {"sessionId": "session-a", "title": "Alpha", "source": "auto"}


def test_generate_session_title_now_skips_without_model(monkeypatch):
    monkeypatch.setattr(title_generation, "_resolve_title_model_id", lambda _session_id: "")
    called: list[str] = []
    monkeypatch.setattr(
        title_generation,
        "_generate_title_candidate",
        lambda session_id, message, model_id: called.append(message) or "Alpha",
    )

    assert title_generation.generate_session_title_now("session-a", "hi") == ""
    assert called == []


def test_generate_session_title_now_returns_empty_when_cas_rejects(monkeypatch):
    monkeypatch.setattr(title_generation, "_resolve_title_model_id", lambda _session_id: "model-a")
    monkeypatch.setattr(title_generation, "_generate_title_candidate", lambda session_id, message, model_id: "Alpha")
    monkeypatch.setattr(session_service, "apply_generated_session_title", lambda *_args, **_kwargs: False)

    assert title_generation.generate_session_title_now("session-a", "hi") == ""


def test_run_title_generation_survives_failure(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(title_generation, "generate_session_title_now", _boom)

    title_generation._run_title_generation("session-a", "hi")


def test_maybe_schedule_session_title_generation_skips_ineligible():
    assert (
        title_generation.maybe_schedule_session_title_generation(
            "session-a",
            message="hi",
            message_source="raw",
            had_previous_user_message=True,
        )
        is False
    )
    assert (
        title_generation.maybe_schedule_session_title_generation(
            "session-a",
            message="hi",
            message_source="supervised_evolution",
        )
        is False
    )
    assert (
        title_generation.maybe_schedule_session_title_generation(
            "session-a",
            message="   ",
            message_source="raw",
        )
        is False
    )


def test_maybe_schedule_session_title_generation_spawns_daemon_thread(monkeypatch):
    created: list[dict] = []

    class _FakeThread:
        def __init__(self, *, target=None, args=(), name="", daemon=False):
            created.append({"target": target, "args": args, "name": name, "daemon": daemon})

        def start(self):
            created[-1]["started"] = True

    monkeypatch.setattr(title_generation.threading, "Thread", _FakeThread)

    assert (
        title_generation.maybe_schedule_session_title_generation(
            "session-a",
            message="hi",
            message_source="raw",
        )
        is True
    )
    assert len(created) == 1
    assert created[0]["target"] is title_generation._run_title_generation
    assert created[0]["args"] == ("session-a", "hi")
    assert created[0]["daemon"] is True
    assert created[0]["started"] is True


def test_submit_first_raw_message_schedules_title_generation(tmp_path, monkeypatch):
    session_id = "session-title-hook"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    scheduled: list[dict] = []
    monkeypatch.setattr(
        title_generation,
        "maybe_schedule_session_title_generation",
        lambda session, **kwargs: scheduled.append({"session": session, **kwargs}),
    )

    try:
        first = session_service.submit_session_message_lightweight(
            session_id,
            "first user message",
            client_submission_id="submission-title-hook-1",
            mental_model_enabled=False,
        )
        _reset_seeded_session_runtime(session_id)
        second = session_service.submit_session_message_lightweight(
            session_id,
            "second user message",
            client_submission_id="submission-title-hook-2",
            mental_model_enabled=False,
        )

        assert first["accepted"] is True
        assert second["accepted"] is True
        assert scheduled == [
            {
                "session": session_id,
                "message": "first user message",
                "message_source": "raw",
                "had_previous_user_message": False,
            },
            {
                "session": session_id,
                "message": "second user message",
                "message_source": "raw",
                "had_previous_user_message": True,
            },
        ]
    finally:
        _reset_seeded_session_runtime(session_id)


def _v2_llm_payload():
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "openai_main": {
                    "label": "OpenAI Main",
                    "driver": "openai",
                    "vendor": "openai",
                    "service_class": "official_api",
                    "base_url": "https://api.example.test/v1",
                    "auth_kind": "none",
                    "credential_ref": "none",
                    "requires_credential": False,
                    "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                    "models": {
                        "gpt-5.6-luna": {
                            "upstream_id": "gpt-5.6-luna",
                            "label": "Luna",
                            "enabled": True,
                        },
                    },
                },
            },
            "profiles": {"default": {"model_ref": "openai_main/gpt-5.6-luna"}},
        }
    }


class _StubService:
    def __init__(self, config):
        self._config = config

    def get_config(self):
        return self._config


def _v2_effective_config(*, alias: str = ""):
    from config.public_config import build_effective_config

    payload = _v2_llm_payload()
    if alias:
        payload["llm"]["model_aliases"] = {alias: "openai_main/gpt-5.6-luna"}
    return build_effective_config(payload)


def test_title_runtime_config_binds_schema_v2_model():
    config = _v2_effective_config()

    bound = title_generation._title_runtime_config(_StubService(config), "openai_main/gpt-5.6-luna")

    profile = bound.llm.profiles[title_generation.SESSION_TITLE_PROFILE_ID]
    assert profile.model_ref == "openai_main/gpt-5.6-luna"
    assert profile.provider_id == "openai_main"
    assert profile.model == "gpt-5.6-luna"
    assert title_generation.SESSION_TITLE_PROFILE_ID not in config.llm.profiles


def test_title_runtime_config_resolves_model_alias():
    config = _v2_effective_config(alias="fast-luna")

    bound = title_generation._title_runtime_config(_StubService(config), "fast-luna")

    assert (
        bound.llm.profiles[title_generation.SESSION_TITLE_PROFILE_ID].model_ref
        == "openai_main/gpt-5.6-luna"
    )


def test_title_runtime_config_rejects_unknown_model():
    from core.llm.agent_runtime import AgentLlmResolutionError

    config = _v2_effective_config()

    with pytest.raises(AgentLlmResolutionError):
        title_generation._title_runtime_config(_StubService(config), "openai_main/missing")


def test_generate_title_candidate_uses_bound_runtime_profile(monkeypatch):
    sentinel_config = object()
    captured: dict = {}

    def _bind(_service_obj, model_id):
        captured["model"] = model_id
        return sentinel_config

    monkeypatch.setattr(title_generation, "_title_runtime_config", _bind)
    monkeypatch.setattr(
        title_generation,
        "get_llm_client",
        lambda *, profile_id=None, config=None: captured.update(profile_id=profile_id, config=config) or object(),
    )
    monkeypatch.setattr(
        title_generation,
        "invoke_llm",
        lambda client, messages, context=None, metadata=None: type("R", (), {"content": "标题：修复登录 bug"})(),
    )

    assert title_generation._generate_title_candidate("session-a", "hi", "model-a") == "修复登录 bug"
    assert captured["model"] == "model-a"
    assert captured["profile_id"] == title_generation.SESSION_TITLE_PROFILE_ID
    assert captured["config"] is sentinel_config


def test_run_title_generation_records_failure_event(monkeypatch):
    events: list[dict] = []

    def _boom(*_args, **_kwargs):
        raise ValueError("unknown session title model: model-x")

    monkeypatch.setattr(title_generation, "generate_session_title_now", _boom)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        )
        or {"accepted": True},
    )

    title_generation._run_title_generation("session-a", "hi")

    assert len(events) == 1
    assert events[0]["component"] == "conversation"
    assert events[0]["eventCode"] == "conversation.title.generation_failed"
    assert events[0]["level"] == "warning"
    assert events[0]["fields"]["sessionId"] == "session-a"
    assert events[0]["fields"]["errorType"] == "ValueError"
