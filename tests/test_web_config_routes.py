import base64
import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from config import models as config_models
from config import public_config as public_config_module
from config.models import LLMProfile, ProviderConfig
from config.public_config import LLM_MODEL_PRESETS, UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from config.runtime_capabilities import MODEL_CAPABILITY_CACHE_ENV
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    config_service,
    log_service,
    runtime_scene_service,
    runtime_service,
    self_evolution_control_service,
    self_evolution_service,
    session_service,
    supervised_control_service,
    workbench_contract_service,
)
import core.web.services.avatar_image_service as avatar_image_service
import core.web.services.theme_background_service as theme_background_service
from tests.helpers.web_chat_state import _seed_chat_state
from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()


def _ensure_preset_model(public_config: dict, preset_id: str) -> dict:
    preset = LLM_MODEL_PRESETS[preset_id]
    model_entry = copy.deepcopy(preset["model"])
    model_entry["provider"] = copy.deepcopy(preset["provider"])
    model_entry.setdefault("label", str(preset.get("label") or model_entry.get("model") or preset_id))
    model_entry.setdefault("api_key_env", f"VIBELUTION_LLM_MODEL_{preset_id.upper()}_API_KEY")
    public_config.setdefault("llm", {}).setdefault("model_library", {})[preset_id] = model_entry
    return model_entry


def test_config_summary_exposes_language():
    response = client.get("/api/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] in {"zh", "en"}


def test_config_summary_exposes_model_labels(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {})["model_library"] = {
        "gpt_5_5_gpt_5_5": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "gpt-5.5",
            "label": "gpt-5.5-share",
        },
        "raw_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "raw-model",
        },
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["modelLabels"]["gpt_5_5_gpt_5_5"] == "gpt-5.5-share"
    assert payload["modelLabels"]["raw_model"] == "raw-model"


def test_config_summary_exposes_model_image_input_support(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {})["providers"] = {
        "xiaomi_provider": {"kind": "xiaomi", "api": "openai", "base_url": "https://example.test/v1"},
    }
    public_config.setdefault("llm", {})["model_library"] = {
        "vision_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "vision-model",
            "supports_image_input": True,
        },
        "text_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "text-model",
            "capability_status": "unsupported",
        },
        "mimo_model": {
            "provider": {"kind": "xiaomi", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "mimo-v2.5",
        },
        "provider_ref_mimo_model": {
            "provider_id": "xiaomi_provider",
            "model": "mimo-v2.5",
        },
        "blocked_vision_hint_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "gpt-5.5-vision-like",
            "capability_status": "unsupported",
        },
        "unknown_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "unknown-model",
        },
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["modelImageInputSupport"]["vision_model"] is True
    assert payload["modelImageInputSupport"]["text_model"] is False
    assert payload["modelImageInputSupport"]["mimo_model"] is True
    assert payload["modelImageInputSupport"]["provider_ref_mimo_model"] is True
    assert payload["modelImageInputSupport"]["blocked_vision_hint_model"] is False
    assert payload["modelImageInputSupport"]["unknown_model"] is None


def test_config_workspace_exposes_unified_config_payload(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "en"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["publicConfig"]["ui"]["language"] == "en"
    assert "rawToml" in payload
    assert "diagnosis" in payload
    preset_options = {item["preset_id"]: item for item in payload["modelPresetOptions"]}
    relay_preset = preset_options["relay_openai_gpt_5_5"]
    assert relay_preset["category"] == "relay"
    assert relay_preset["provider"]["kind"] == "relay"
    assert relay_preset["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert relay_preset["model"]["transport"] == "responses"
    assert relay_preset["model"]["contract"] == "tool_chat"
    image2_preset = preset_options["relay_image2"]
    assert image2_preset["category"] == "relay"
    assert image2_preset["provider"]["kind"] == "relay"
    assert image2_preset["provider"]["base_url"] == "https://ai-pixel.online"
    assert not image2_preset["provider"]["base_url"].endswith("/v1")
    assert image2_preset["model"]["model"] == "image2"
    assert image2_preset["model"]["streaming"] is False
    assert image2_preset["model"]["tool_calling_mode"] == "disabled"
    assert preset_options["custom_openai_compatible_relay"]["category"] == "openai_compatible"
    assert preset_options["custom_openai_compatible_relay"]["provider"]["kind"] == "openai_compatible"
    assert preset_options["custom_relay_responses"]["category"] == "relay"
    assert preset_options["custom_relay_responses"]["model"]["transport"] == "responses"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["category"] == "official"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["kind"] == "xiaomi"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["base_url"] == (
        "https://token-plan-cn.xiaomimimo.com/v1"
    )
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["model"] == "mimo-v2.5-pro"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["supports_image_input"] is False
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["capability_status"] == "unsupported"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["category"] == "official"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["provider"]["kind"] == "xiaomi"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["provider"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["model"]["model"] == "mimo-v2.5"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["model"]["supports_image_input"] is True
    assert preset_options["deepseek_v4_pro"]["model"]["supports_image_input"] is False
    assert preset_options["deepseek_v4_pro"]["model"]["capability_status"] == "unsupported"
    assert preset_options["deepseek_v4_flash"]["model"]["supports_image_input"] is False
    assert preset_options["deepseek_v4_flash"]["model"]["capability_status"] == "unsupported"
    provider_options = {item["provider_preset_id"]: item for item in payload["providerPresetOptions"]}
    assert provider_options["openai_main"]["vendor_label"] == "OpenAI"
    assert provider_options["openai_main"]["label"] == "OpenAI 官方 API"
    assert provider_options["openai_main"]["provider"]["kind"] == "openai"
    assert provider_options["xiaomi_mimo_token_plan_cn"]["vendor_label"] == "小米 MiMo"
    assert provider_options["xiaomi_mimo_token_plan_cn"]["label"] == "MiMo Token Plan CN"
    assert provider_options["xiaomi_mimo_api_cn"]["label"] == "MiMo 官方 API CN"
    assert provider_options["relay_openai"]["vendor_label"] == "中转站 / Relay"
    assert len([item for item in payload["providerPresetOptions"] if item["provider_preset_id"] == "openai_main"]) == 1
    assert "modelOptions" in payload
    assert "profileCards" not in payload
    assert "profileCount" not in payload


def test_config_workspace_exposes_editor_schema_without_launcher_owned_startup_settings(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    editor_sections = {section["id"]: section for section in payload["editorSections"]}
    editor_meta = payload["editorMeta"]

    assert "runtime" not in editor_sections
    assert "workbench" not in editor_sections
    assert "tools" not in editor_sections
    assert "context-compression" in editor_sections
    assert "analysis" in editor_sections
    assert "prompt" not in editor_sections
    assert "llm-profiles" not in editor_sections
    assert "agent" not in editor_sections
    assert "evolution" not in editor_sections
    assert "memory" not in editor_sections
    assert "strategy" not in editor_sections
    sections_by_id = {section["id"]: section for section in payload["sections"]}
    assert "runtime" not in sections_by_id
    assert "workbench" not in sections_by_id
    assert "profiles" not in sections_by_id
    assert sections_by_id["models"]["title"] == "模型库"
    assert "模型资产" in sections_by_id["models"]["summary"]
    assert sections_by_id["draft"]["title"] == "高级配置检查"
    assert "JSON" not in sections_by_id["draft"]["title"]
    assert "JSON" not in sections_by_id["draft"]["summary"]
    assert "草稿" not in sections_by_id["draft"]["summary"]
    assert editor_sections["context-compression"]["title"] == "上下文压缩"
    assert "git" not in editor_sections
    assert editor_sections["git-commit-model"]["path"] == "git.commit_message_model_ref"
    assert editor_sections["git-commit-model"]["title"] == "Git 提交模型"
    assert editor_sections["git-commit-model"]["fieldCount"] == 1
    assert editor_sections["git-commit-prompt"]["path"] == "git.commit_message_prompt"
    assert editor_sections["git-commit-prompt"]["title"] == "Git 提交提示词"
    assert editor_sections["git-commit-prompt"]["fieldCount"] == 1
    assert "user-profile" in editor_sections
    assert editor_sections["user-profile"]["path"] == "user_profile"
    assert editor_sections["user-profile"]["title"] == "用户信息"
    assert payload["publicConfig"]["runtime"] == public_config["runtime"]
    assert payload["publicConfig"]["workbench"] == public_config["workbench"]
    assert "runtime.profile" not in editor_meta
    assert "runtime.preflight_doctor" not in editor_meta
    assert "runtime.require_venv" not in editor_meta
    assert "workbench.backend_port" not in editor_meta
    assert "workbench.frontend_port" not in editor_meta
    assert "workbench.window_mode" not in editor_meta
    assert editor_meta["user_profile.display_name"]["kind"] == "text"
    assert editor_meta["user_profile.display_name"]["label"] == "用户显示名"
    assert editor_meta["user_profile.bio"]["kind"] == "multiline"
    assert editor_meta["user_profile.preferences"]["kind"] == "string_list"
    assert editor_meta["user_profile.avatar_preset"]["kind"] == "select"
    assert editor_meta["user_profile.avatar_preset"]["options"]
    assert editor_meta["user_profile.avatar_image_path"]["kind"] == "image"
    assert "本地图片" in editor_meta["user_profile.avatar_image_path"]["hint"]
    assert editor_meta["ui.workbench_theme.background_image_path"]["kind"] == "background_image"
    assert "项目外配置资源目录" in editor_meta["ui.workbench_theme.background_image_path"]["hint"]
    background_options = editor_meta["ui.workbench_theme.background_image_path"]["options"]
    assert background_options[0]["value"] == theme_background_service.DEFAULT_THEME_BACKGROUND_PATH
    assert background_options[0]["label"] == "石墨命令中心"
    assert {option["value"] for option in background_options} >= {
        "theme_backgrounds/default-graphite-command-center.png",
        "theme_backgrounds/default-midnight-glass.png",
        "theme_backgrounds/default-sunrise-research.png",
        "theme_backgrounds/default-glass-observatory.png",
        "theme_backgrounds/default-promptsref-candid-lifestyle.png",
        "theme_backgrounds/default-promptsref-mirror-cosplay.png",
        "theme_backgrounds/default-promptsref-sunlit-street.png",
        "theme_backgrounds/default-promptsref-negative-film-street.png",
        "theme_backgrounds/default-promptsref-tokyo-shadow-snap.png",
        "theme_backgrounds/default-wallpaper-football-editorial.png",
        "theme_backgrounds/default-wallpaper-storm-manga-warrior.png",
        "theme_backgrounds/default-wallpaper-neon-hunter-stage.png",
        "theme_backgrounds/default-wallpaper-golden-stadium.png",
        "theme_backgrounds/default-wallpaper-neon-casino-lounge.png",
    }
    assert editor_meta["ui.workbench_theme.background_readability"]["kind"] == "select"
    assert [option["value"] for option in editor_meta["ui.workbench_theme.background_readability"]["options"]] == [
        "soft",
        "standard",
        "strong",
    ]
    assert "可读" in editor_meta["ui.workbench_theme.background_readability"]["hint"]
    assert editor_meta["network.proxy_enabled"]["kind"] == "boolean"
    assert editor_meta["network.proxy_enabled"]["label"] == "启用代理"
    assert editor_meta["network.proxy_url"]["kind"] == "url"
    assert editor_meta["network.proxy_url"]["label"] == "代理地址"
    assert "科研调研" in editor_meta["network.proxy_enabled"]["hint"]
    assert editor_meta["log.level"]["kind"] == "select"
    assert [option["value"] for option in editor_meta["log.level"]["options"]] == [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    assert editor_meta["log.format"]["kind"] == "text"
    assert editor_meta["log.date_format"]["kind"] == "text"
    assert editor_meta["log.file_path"]["kind"] == "path"
    assert editor_meta["log.third_party.urllib3"]["kind"] == "select"
    assert [option["value"] for option in editor_meta["log.third_party.urllib3"]["options"]] == [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    assert "tools.file.editable_extensions" not in editor_meta
    assert "tools.image2.default_model_ref" not in editor_meta
    assert "prompt.sections" not in editor_meta
    assert "llm.profiles.primary.model_ref" not in editor_meta
    assert "llm.profiles.primary.provider.kind" not in editor_meta
    assert "llm.profiles.primary.provider.base_url" not in editor_meta
    assert "commit_message_profile" not in payload["publicConfig"]["git"]
    assert "commit_message_model_ref" in payload["publicConfig"]["git"]
    assert "{diff}" in payload["publicConfig"]["git"]["commit_message_prompt"]
    assert editor_meta["git.commit_message_model_ref"]["kind"] == "select"
    assert editor_meta["git.commit_message_model_ref"]["label"] == "Git 提交使用的模型"
    assert "profile" not in editor_meta["git.commit_message_model_ref"]["hint"].lower()
    assert editor_meta["git.commit_message_prompt"]["kind"] == "multiline"
    assert "系统提示词模板" in editor_meta["git.commit_message_prompt"]["hint"]
    assert sections_by_id["health-diagnostics"]["title"] == "健康诊断"
    assert any(section["id"] == "overview" for section in payload["sections"])
    assert any(section["id"] == "shell" for section in payload["sections"])


def test_config_public_summary_exposes_theme_background_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {}).setdefault("workbench_theme", {})[
        "background_image_path"
    ] = "theme_backgrounds/custom-background.png"
    public_config["ui"]["workbench_theme"]["background_readability"] = "strong"
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["themeBackgroundImagePath"] == "theme_backgrounds/custom-background.png"
    assert payload["themeBackgroundImageUrl"] == "/api/config/theme-background-image/custom-background.png"
    assert payload["themeBackgroundReadability"] == "strong"


def test_config_public_summary_defaults_to_bundled_theme_background(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {}).setdefault("workbench_theme", {}).pop("background_image_path", None)
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["themeBackgroundImagePath"] == theme_background_service.DEFAULT_THEME_BACKGROUND_PATH
    assert payload["themeBackgroundImageUrl"] == "/api/config/theme-background-image/default-graphite-command-center.png"


def test_config_avatar_image_upload_stores_safe_project_file(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "my avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(png_payload).decode("ascii"),
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["path"].startswith("workspace/user_avatars/avatar-")
    assert payload["path"].endswith(".png")
    assert payload["url"].startswith("/api/config/avatar-image/avatar-")
    saved_files = list((tmp_path / "user_avatars").glob("*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == png_payload

    image_response = client.get(payload["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.content == png_payload


def test_config_avatar_image_upload_rejects_disguised_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "not-image.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"not a png").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_config_avatar_image_upload_rejects_oversized_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    monkeypatch.setattr(avatar_image_service, "MAX_USER_AVATAR_IMAGE_BYTES", 8)

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\nextra").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_config_theme_background_image_upload_stores_external_config_resource(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_background_service, "CONFIG_PATH", tmp_path / "config.toml")
    png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    response = client.post(
        "/api/config/theme-background-image",
        json={
            "filename": "my background.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(png_payload).decode("ascii"),
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["path"].startswith("theme_backgrounds/background-")
    assert payload["path"].endswith(".png")
    assert payload["url"].startswith("/api/config/theme-background-image/background-")
    saved_files = list((tmp_path / "theme_backgrounds").glob("*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == png_payload

    image_response = client.get(payload["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.content == png_payload


def test_config_theme_background_image_upload_rejects_disguised_image(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_background_service, "CONFIG_PATH", tmp_path / "config.toml")

    response = client.post(
        "/api/config/theme-background-image",
        json={
            "filename": "not-image.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"not a png").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "theme_backgrounds").exists()


def test_config_theme_background_image_route_serves_bundled_default(monkeypatch, tmp_path):
    monkeypatch.setattr(theme_background_service, "CONFIG_PATH", tmp_path / "config.toml")

    response = client.get(
        f"/api/config/theme-background-image/{theme_background_service.DEFAULT_THEME_BACKGROUND_FILENAME}"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == (
        theme_background_service.BUNDLED_THEME_BACKGROUND_DIR
        / theme_background_service.DEFAULT_THEME_BACKGROUND_FILENAME
    ).read_bytes()


def test_health_diagnostics_endpoint_returns_log_helpers(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"type":"external_request"}\n', encoding="utf-8")

    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-health", status="failed")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/diagnostics/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    session_helpers = {item["id"]: item for item in payload["sessionHelpers"]}
    assert session_helpers["chat_sessions"]["sessionCount"] == 1
    assert session_helpers["chat_sessions"]["activeSessionId"] == "session-live"
    assert session_helpers["chat_sessions"]["route"] == "/chat?session=session-live"
    assert session_helpers["chat_sessions"]["protected"] is True
    helpers = {item["id"]: item for item in payload["logHelpers"]}
    assert set(helpers) == {"runtime_scenes", "runtime_logs", "workspace_logs", "conversation_logs"}
    assert helpers["runtime_scenes"]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["resetItemId"] == "stopped_runtime_scenes"
    assert helpers["runtime_scenes"]["protected"] is True
    assert helpers["runtime_logs"]["route"] == "/logs?root=runtime_logs"
    assert helpers["conversation_logs"]["resetItemId"] == "conversation_logs"
    assert helpers["workspace_logs"]["status"] == "warning"
    assert payload["findings"][0]["id"] == "runtime_scene_failed"
    assert payload["findings"][0]["severity"] == "blocked"
    assert payload["findings"][0]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["primaryFindingId"] == "runtime_scene_failed"
    assert any(item["source"] == "reset" and item["protected"] is True for item in payload["findings"])
    assert payload["quickActions"][0]["findingId"] == "runtime_scene_failed"
    assert any(item["resetItemId"] == "stopped_runtime_scenes" for item in payload["quickActions"])


def test_config_workspace_surfaces_llm_security_diagnostics_without_blocking_read(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"]["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockingCount"] >= 1
    assert any("LLM security guard" in item for item in payload["diagnosis"]["blocking_issues"])


def test_config_workspace_draft_delete_model_rejects_primary_profile_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert response.status_code == 422
    assert "primary" in response.json()["detail"]
    assert scene_events[-1][1] == "config.llm_model.delete_rejected"
    assert scene_events[-1][2]["fields"]["reason"] == "primary_profile_ref"


def test_config_workspace_draft_delete_model_rejects_git_commit_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("git", {})["commit_message_model_ref"] = "relay_openai_gpt_5_5"
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert response.status_code == 422
    assert "Git commit" in response.json()["detail"]
    assert scene_events[-1][1] == "config.llm_model.delete_rejected"
    assert scene_events[-1][2]["fields"]["reason"] == "git_commit_model_ref"


def test_config_workspace_apply_allows_deleted_non_primary_profile_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    public_config["llm"]["profiles"]["mental_model"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }

    saved_configs = []
    scene_events = []
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda payload: saved_configs.append(copy.deepcopy(payload)))
    monkeypatch.setattr(config_service, "reload_config", lambda path: config_service.build_effective_config(saved_configs[-1]))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    delete_response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert delete_response.status_code == 200, delete_response.json()
    draft_payload = delete_response.json()
    assert draft_payload["publicConfig"]["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF

    apply_response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert apply_response.status_code == 200, apply_response.json()
    assert saved_configs
    assert "relay_openai_gpt_5_5" not in saved_configs[-1]["llm"]["model_library"]
    assert any(event_code == "config.llm_profiles.optional_missing_allowed" for _, event_code, _ in scene_events)


def test_config_open_environment_opens_system_ui_without_returning_keys(monkeypatch):
    launched_commands = []
    focused_windows = []

    def fake_run(command, **kwargs):
        launched_commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)
    monkeypatch.setattr(config_service, "_focus_environment_variables_window", lambda: focused_windows.append("focused") or True)
    monkeypatch.setenv("VIBELUTION_SECRET_TEST_KEY", "should-not-leak")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["opened"] is True
    assert payload["method"] == "interactive-scheduled-task"
    assert payload["focused"] is True
    assert payload["cleanup_ok"] is True
    assert payload["cleanup_error"] is None
    assert launched_commands
    assert focused_windows == ["focused"]
    assert [command[0][1] for command in launched_commands] == ["/Delete", "/Create", "/Run", "/Delete"]
    create_command = launched_commands[1][0]
    assert "/IT" in create_command
    assert "rundll32.exe sysdm.cpl,EditEnvironmentVariables" in create_command
    assert "should-not-leak" not in response.text
    assert "VIBELUTION_SECRET_TEST_KEY" not in response.text


def test_config_open_environment_reports_cleanup_failure(monkeypatch):
    launched_commands = []

    def fake_run(command, **kwargs):
        launched_commands.append(command)
        if command[1] == "/Delete" and len(launched_commands) == 4:
            return SimpleNamespace(returncode=1, stdout="", stderr="delete denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)
    monkeypatch.setattr(config_service, "_focus_environment_variables_window", lambda: True)

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["opened"] is True
    assert payload["cleanup_ok"] is False
    assert payload["cleanup_error"] == "delete denied"


def test_config_open_environment_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(config_service.os, "name", "posix")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "Windows" in response.json()["detail"]


def test_config_open_environment_reports_launch_failure(monkeypatch):
    def fake_run(command, **kwargs):
        if command[1] == "/Create":
            return SimpleNamespace(returncode=1, stdout="", stderr="blocked")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "无法打开系统环境变量窗口" in response.json()["detail"]


def test_config_open_environment_focuses_detected_window(monkeypatch):
    focused_handles = []

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service, "_find_environment_variables_window", lambda: 12345)
    monkeypatch.setattr(config_service, "_focus_window", lambda hwnd: focused_handles.append(hwnd) or True)

    assert config_service._focus_environment_variables_window(timeout_seconds=0.01) is True
    assert focused_handles == [12345]


def test_config_open_environment_promotes_window_when_foreground_is_blocked(monkeypatch):
    calls = []

    class FakeUser32:
        def GetForegroundWindow(self):
            return 0

        def GetWindowThreadProcessId(self, hwnd, process_id):
            return 222 if hwnd == 12345 else 0

        def AttachThreadInput(self, current_thread, target_thread, attach):
            calls.append(("AttachThreadInput", current_thread, target_thread, attach))
            return True

        def ShowWindow(self, hwnd, mode):
            calls.append(("ShowWindow", hwnd, mode))
            return True

        def BringWindowToTop(self, hwnd):
            calls.append(("BringWindowToTop", hwnd))
            return True

        def SetActiveWindow(self, hwnd):
            calls.append(("SetActiveWindow", hwnd))
            return hwnd

        def SetFocus(self, hwnd):
            calls.append(("SetFocus", hwnd))
            return hwnd

        def SetForegroundWindow(self, hwnd):
            calls.append(("SetForegroundWindow", hwnd))
            return False

        def SwitchToThisWindow(self, hwnd, alt_tab):
            calls.append(("SwitchToThisWindow", hwnd, alt_tab))
            return None

        def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
            calls.append(("SetWindowPos", hwnd, insert_after, flags))
            return True

    class FakeKernel32:
        def GetCurrentThreadId(self):
            return 111

    monkeypatch.setattr(
        config_service.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32(), kernel32=FakeKernel32()),
        raising=False,
    )

    assert config_service._focus_window(12345) is False
    assert ("AttachThreadInput", 111, 222, True) in calls
    assert ("AttachThreadInput", 111, 222, False) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_TOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_NOTOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls


def test_config_workspace_test_llm_uses_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv(deepseek_env, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key == "draft-secret"
        return {"ok": True, "message": "ok", "runtime_route": f"{profile.transport}:{profile.model}"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": deepseek_env,
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    pending_token = draft_payload["draftMeta"]["pending_api_keys"][deepseek_env]
    assert pending_token != "draft-secret"
    assert pending_token.startswith("pending-secret:")

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["api_key_source"] == f"pending-env:{deepseek_env}"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is True
    assert payload["transport"] == "chat_completions"
    assert payload["contract"] == "reasoning_chat"


def test_config_workspace_test_llm_can_target_model_library_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv(deepseek_env, "model-secret")
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    calls = []

    def fake_runtime_probe(provider, profile, api_key=None):
        calls.append((provider.kind, profile.profile_id, profile.model, api_key))
        return {"ok": True, "message": "ok", "runtime_route": f"{profile.transport}:{profile.model}"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "modelId": "deepseek_v4_pro",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["provider_kind"] == "deepseek"
    assert payload["api_key_source"] == f"model-env:{deepseek_env}"
    assert calls == [("deepseek", "__capability_probe_deepseek_v4_pro", "deepseek-v4-pro", "model-secret")]


def test_config_workspace_test_llm_ignores_forged_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    config_service._PENDING_API_KEY_SECRETS.clear()
    config_service._PENDING_CLEAR_ENVS.clear()
    llm_config = public_config.get("llm", {})
    for provider in (llm_config.get("providers") or {}).values():
        if isinstance(provider, dict):
            provider["api_key"] = ""
    for model in (llm_config.get("model_library") or {}).values():
        if not isinstance(model, dict):
            continue
        model["api_key"] = ""
        provider = model.get("provider")
        if isinstance(provider, dict):
            provider["api_key"] = ""
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv(deepseek_env, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config_service, "_read_env_var", lambda _name: "")
    monkeypatch.setattr(public_config_module, "_read_env_var", lambda _name: "")
    monkeypatch.setattr(config_models, "_read_env_var", lambda _name: "")

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key is None
        return {"ok": False, "message": "missing"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["api_key_source"] == "missing"


def test_config_workspace_test_llm_reports_local_draft_route_clearly(monkeypatch):
    saved_config = copy.deepcopy(load_public_config())
    draft_config = copy.deepcopy(saved_config)
    draft_config.setdefault("runtime", {})["profile"] = "safe_local"
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(saved_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://localhost:11434/v1"
        return {"ok": False, "message": "<urlopen error [WinError 10061] connection refused>"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://localhost:11434/v1"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is False
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_llm_http_fallback_uses_anthropic_messages(monkeypatch):
    provider = ProviderConfig(
        provider_id="anthropic_test",
        kind="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://www.atpify.cn",
        compat_mode="native",
        requires_api_key=True,
        context_window=200000,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="anthropic_test",
        model="claude-opus-4-7",
        temperature=0.7,
        max_output_tokens=4096,
        timeout=60,
        connect_timeout=10,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(public_config_module.urllib.request, "build_opener", lambda *_args, **_kwargs: FakeOpener())

    result = public_config_module._probe_llm_http(provider, profile, "anthropic-secret")

    assert result["ok"] is True
    assert captured["url"] == "https://www.atpify.cn/v1/messages"
    assert captured["payload"]["model"] == "claude-opus-4-7"
    assert "temperature" not in captured["payload"]
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["headers"]["X-api-key"] == "anthropic-secret"


def test_config_workspace_llm_http_fallback_uses_primary_openai_chat_completion(monkeypatch):
    provider = ProviderConfig(
        provider_id="primary",
        kind="xiaomi",
        api_key_env="XIAOMI_API_KEY",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        compat_mode="openai",
        requires_api_key=True,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="primary",
        model="mimo-v2.5",
        transport="chat_completions",
        contract="tool_chat",
        temperature=0.7,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(public_config_module.urllib.request, "build_opener", lambda *_args, **_kwargs: FakeOpener())

    result = public_config_module._probe_llm_http(provider, profile, "token-plan-secret")

    assert result["ok"] is True
    assert captured["url"] == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured["payload"]["model"] == "mimo-v2.5"
    assert captured["payload"]["temperature"] == profile.temperature
    assert captured["headers"]["Authorization"] == "Bearer token-plan-secret"


def test_config_workspace_test_llm_rejects_metadata_service_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "http://169.254.169.254/v1",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


def test_config_workspace_test_llm_rejects_file_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "http(s)" in response.json()["detail"]


def test_config_workspace_test_llm_allows_localhost_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {}).setdefault("model_library", {})["local_loopback_model"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Loopback Model",
    }
    public_config.setdefault("llm", {}).setdefault("profiles", {}).setdefault("primary", {})["model_ref"] = "local_loopback_model"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind in {"local", "llamacpp"}
        assert provider.base_url.startswith("http://")
        assert api_key is None
        return {"ok": True, "message": "local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] in {"local", "llamacpp"}


def test_config_workspace_test_llm_allows_private_lan_local_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {}).setdefault("model_library", {})["lan_local_model"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://192.168.20.46:8081/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "qwen-local",
        "label": "LAN Local Model",
    }
    public_config.setdefault("llm", {}).setdefault("profiles", {}).setdefault("primary", {})["model_ref"] = "lan_local_model"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://192.168.20.46:8081/v1"
        assert api_key is None
        return {"ok": True, "message": "lan-local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://192.168.20.46:8081/v1"
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_test_llm_extends_private_lan_local_probe_timeout():
    provider = ProviderConfig(
        provider_id="local_model_server_b",
        kind="local",
        api_key_env="VIBELUTION_LLM_MODEL_LOCAL_MODEL_SERVER_B_API_KEY",
        base_url="http://192.168.20.63:8000/v1",
        compat_mode="openai",
        requires_api_key=True,
        context_window=128000,
    )
    profile = LLMProfile(
        profile_id="__capability_probe_local_model_server_b",
        provider_id="local_model_server_b",
        model="Qwen3-32B-AWQ",
        temperature=0.3,
        max_output_tokens=4096,
        timeout=120,
        connect_timeout=20,
    )

    assert config_service._llm_test_probe_timeout_seconds(provider, profile) == 30


def test_config_workspace_test_llm_keeps_remote_probe_timeout_short():
    provider = ProviderConfig(
        provider_id="deepseek",
        kind="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        compat_mode="native",
        requires_api_key=True,
        context_window=65536,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        temperature=0.3,
        max_output_tokens=4096,
        timeout=120,
        connect_timeout=20,
    )

    assert config_service._llm_test_probe_timeout_seconds(provider, profile) == 10


def test_config_image_input_probe_status_avoids_generic_vision_overmatch():
    assert config_service._image_input_probe_status("vision") == (None, "unknown")
    assert config_service._image_input_probe_status("vision is not supported by this route") == (False, "unsupported")
    assert config_service._image_input_probe_status("model does not support vision") == (False, "unsupported")


def test_config_workspace_test_llm_image_input_reports_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Image Probe",
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_image_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        config_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("connection refused")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability"] == "image_input"
    assert payload["capability_status"] == "unknown"
    assert payload["supports_image_input"] is None
    assert payload["api_key_source"] == "not-required"
    assert payload["requires_api_key"] is False
    assert recorded_scene_events
    fields = recorded_scene_events[-1][1]["fields"]
    assert fields["capability"] == "image_input"
    assert fields["supportsImageInput"] is None
    assert "base64" not in str(fields).lower()


def test_config_workspace_test_llm_image_input_maps_provider_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Image Probe",
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_image_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("OpenAIException - No endpoints found that support image input")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability_status"] == "unsupported"
    assert payload["supports_image_input"] is False
    assert payload["message"] == "image input is not supported by this model route"


def test_config_workspace_batch_image_capability_persists_model_only(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_vision_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-vision",
        "label": "Local Vision",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
        "supports_image_input": False,
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_vision_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            config = kwargs["config"]
            profile_id = kwargs["profile_id"]
            profile = config.llm.get_profile(profile_id=profile_id)
            assert config.llm.get_provider(profile.provider_id).provider_id
            assert profile.supports_image_input is True
            model_entry = config.llm.get_model_library_entry_for_profile(profile)[1]
            assert model_entry["model"] == "local-vision"
            assert model_entry["supports_image_input"] is True

        def invoke(self, messages, tools=None, metadata=None):
            assert metadata["probeCapability"] == "image_input"
            assert metadata["llmInvocationSurface"] == "config_image_input_probe"
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            return {"ok": True}

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/draft/check-model-capabilities",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelIds": ["local_vision_probe"],
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    model = payload["publicConfig"]["llm"]["model_library"]["local_vision_probe"]
    profile = payload["publicConfig"]["llm"]["profiles"]["primary"]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "runtime_probe"
    assert "capability_checked_at" in model
    assert "capability_error" not in model
    assert "supports_image_input" not in profile
    assert "capability_status" not in profile
    assert "capability_source" not in profile
    assert "capability_checked_at" not in profile
    assert payload["capabilityResults"][0]["supportsImageInput"] is True


def test_config_workspace_batch_image_capability_records_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_text_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-text",
        "label": "Local Text",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
    }
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            raise RuntimeError("No endpoints found that support image input")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/draft/check-model-capabilities",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelIds": ["local_text_probe"],
        },
    )

    assert response.status_code == 200, response.json()
    model = response.json()["publicConfig"]["llm"]["model_library"]["local_text_probe"]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "runtime_probe"
    assert model["capability_error"] == "image input is not supported by this model route"


def test_config_workspace_draft_model_ignores_submitted_api_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "PATH",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["deepseek_v4_pro"]
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY"
    assert "PATH" not in payload["draftMeta"]["pending_api_keys"]
    assert "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY" in payload["draftMeta"]["pending_api_keys"]


def test_config_workspace_draft_model_persists_manual_image_input_support(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_manual_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-vision",
        "label": "Local Vision",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "supports_image_input": False,
    }
    target = public_config["llm"]["model_library"]["local_manual_image_probe"]

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "local_manual_image_probe",
            "provider": target["provider"],
            "model": "local-vision",
            "label": "Local Vision",
            "details": {
                **target,
                "supports_image_input": True,
                "capability_status": "supported",
                "capability_source": "manual",
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model = response.json()["publicConfig"]["llm"]["model_library"]["local_manual_image_probe"]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "manual"
def test_config_workspace_draft_model_allows_custom_public_relay_host(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    provider = copy.deepcopy(target["provider"])
    provider["base_url"] = "https://relay.example.com/v1"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
            "provider": provider,
            "model": "gpt-5.5",
            "label": "GPT-5.5 via relay",
            "details": target,
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["relay_openai_gpt_5_5"]
    assert updated["provider"]["base_url"] == "https://relay.example.com/v1"


def test_config_workspace_draft_model_allows_custom_openai_compatible_relay(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["provider"]["kind"] == "openai_compatible"
    assert updated["provider"]["base_url"] == "https://relay.example.com/v1"
    assert updated["prompt_cache"] == {"mode": "automatic"}
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY" in payload["draftMeta"]["pending_api_keys"]


def test_config_workspace_draft_update_model_preserves_prompt_cache_when_details_omit_it(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "prompt_cache": {"mode": "unsupported"},
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
            "provider": public_config["llm"]["model_library"]["custom_relay"]["provider"],
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    updated = response.json()["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["prompt_cache"] == {"mode": "unsupported"}


def test_config_workspace_draft_model_allows_custom_relay_responses(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_relay_responses",
            "modelId": "custom_relay_responses_model",
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://ai-pixel.online",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "model": "gpt-5.5",
            "label": "Custom Relay Responses",
            "details": {
                "transport": "responses",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay_responses_model"]
    assert updated["provider"]["kind"] == "relay"
    assert updated["provider"]["base_url"] == "https://ai-pixel.online"
    assert updated["transport"] == "responses"
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY"


def test_config_workspace_draft_model_rejects_unknown_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "generated_from_profile",
            "provider": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]["provider"],
            "model": "gpt-5.5",
            "label": "Generated from profile",
            "details": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"],
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "unknown LLM model" in response.json()["detail"]


def test_config_workspace_draft_update_model_migrates_to_unique_model_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setenv("VIBELUTION_LLM_CUSTOM_RELAY_API_KEY", "legacy-secret")
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", raising=False)

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
            "provider": public_config["llm"]["model_library"]["custom_relay"]["provider"],
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {},
            "apiKeyEnv": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY" in payload["draftMeta"]["pending_api_keys"]
    assert payload["draftMeta"]["pending_cleared_api_keys"] == ["VIBELUTION_LLM_CUSTOM_RELAY_API_KEY"]


def test_config_workspace_draft_model_auto_generates_custom_relay_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "gpt-5.5",
            "label": "GPT-5.5",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model_library = response.json()["publicConfig"]["llm"]["model_library"]
    assert "gpt_5_5" in model_library
    assert "custom_openai_compatible_relay" not in model_library
    assert model_library["gpt_5_5"]["api_key_env"] == "VIBELUTION_LLM_MODEL_GPT_5_5_API_KEY"


def test_config_workspace_draft_model_rejects_custom_relay_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_draft_model_rejects_custom_responses_relay_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_relay_responses",
            "modelId": "custom_relay_responses_model",
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "model": "gpt-5.5",
            "label": "Custom Relay Responses",
            "details": {
                "transport": "responses",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"]


def test_config_workspace_draft_model_allows_private_lan_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "local_openai_compatible",
            "modelId": "lan_local_model",
            "provider": {
                "kind": "local",
                "api_key_env": "",
                "base_url": "http://192.168.20.46:8081/v1",
                "compat_mode": "openai",
                "requires_api_key": False,
                "context_window": 65536,
            },
            "model": "qwen-local",
            "label": "LAN Local Model",
            "details": {
                "transport": "chat_completions",
                "contract": "basic_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model_library = response.json()["publicConfig"]["llm"]["model_library"]
    assert model_library["lan_local_model"]["provider"]["kind"] == "local"
    assert model_library["lan_local_model"]["provider"]["base_url"] == "http://192.168.20.46:8081/v1"
    assert model_library["lan_local_model"]["provider"]["requires_api_key"] is False


def test_config_workspace_draft_model_rejects_private_lan_remote_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "lan_remote_model",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://192.168.20.46:8081/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "qwen-local",
            "label": "LAN Remote Model",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_LAN_REMOTE_MODEL_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "https" in response.json()["detail"] or "non-public" in response.json()["detail"]


def test_config_workspace_draft_model_rejects_link_local_metadata_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "local_openai_compatible",
            "modelId": "metadata_local_model",
            "provider": {
                "kind": "local",
                "api_key_env": "",
                "base_url": "http://169.254.169.254/v1",
                "compat_mode": "openai",
                "requires_api_key": False,
                "context_window": 65536,
            },
            "model": "metadata-model",
            "label": "Metadata Local Model",
            "details": {
                "transport": "chat_completions",
                "contract": "basic_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "private LAN" in response.json()["detail"]


def _mock_model_discovery_public_dns(monkeypatch):
    monkeypatch.setattr(
        "config.llm_security.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )


def test_config_workspace_discovers_custom_openai_compatible_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [
            {"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000},
            {"id": "gpt-5.5-mini", "label": "GPT-5.5 Mini", "context_window": 128000},
        ]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["models"][0]["id"] == "gpt-5.5"
    assert payload["models"][0]["contextWindow"] == 1000000
    assert payload["models"][1]["id"] == "gpt-5.5-mini"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_discovers_custom_public_relay_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [{"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["providerKind"] == "relay"
    assert response.json()["baseUrl"] == "https://relay.example.com/v1"
    assert response.json()["models"][0]["id"] == "gpt-5.5"
    assert seen == {
        "api_base": "https://relay.example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_discovers_custom_public_relay_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [{"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["providerKind"] == "relay"
    assert response.json()["baseUrl"] == "https://relay.example.com/v1"
    assert response.json()["models"][0]["id"] == "gpt-5.5"
    assert seen == {
        "api_base": "https://relay.example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_model_discovery_uses_configured_environment_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", "env-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "relay-model", "label": "Relay Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["apiKeySource"] == "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "env-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_prefers_model_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", "model-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "relay-model", "label": "Relay Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "modelId": "custom_relay",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["apiKeySource"] == "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "model-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_uses_submitted_model_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY", "new-model-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "new-model", "label": "New Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "modelId": "new_relay",
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert seen == {
        "api_key": "new-model-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_url_candidates_do_not_duplicate_v1():
    assert config_service._model_discovery_urls("https://ai-pixel.online") == [
        "https://ai-pixel.online/models",
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1") == [
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1/models") == [
        "https://ai-pixel.online/v1/models",
    ]


def test_config_workspace_model_discovery_uses_fast_fail_timeout(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["timeout"] = timeout
        return [{"id": "fast-model", "label": "Fast Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert seen["timeout"] == config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS


def test_config_workspace_model_discovery_caches_recent_failures(monkeypatch):
    calls = []
    events = []

    config_service._MODEL_DISCOVERY_NEGATIVE_CACHE.clear()
    monkeypatch.setattr(config_service, "_model_discovery_urls", lambda api_base: ["https://example.com/models"])
    monkeypatch.setattr(config_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))

    def fake_discover_model_url(url, *, headers, timeout):
        calls.append((url, timeout))
        return url, 404, 12, [], httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", url),
            response=httpx.Response(404, request=httpx.Request("GET", url)),
        )

    monkeypatch.setattr(config_service, "_discover_model_url", fake_discover_model_url)

    with pytest.raises(ValueError) as first_error:
        config_service._discover_openai_compatible_model_list(
            "https://example.com",
            api_key="secret",
            timeout=10,
            api_key_source="手动输入",
        )
    with pytest.raises(ValueError) as second_error:
        config_service._discover_openai_compatible_model_list(
            "https://example.com",
            api_key="secret",
            timeout=10,
            api_key_source="手动输入",
        )

    assert len(calls) == 1
    assert calls[0][1] == config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS
    assert str(first_error.value) == str(second_error.value)
    assert any(args[2] == "config.model_discovery.cached_failure" for args, _ in events)


def test_config_workspace_model_discovery_rejects_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_apply_rejects_stale_base_hash(monkeypatch):
    original = copy.deepcopy(load_public_config())
    stale_hash = public_config_hash(original)
    external = copy.deepcopy(original)
    external.setdefault("ui", {})["language"] = "en"
    public_config = external

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": original,
            "draftMeta": {},
            "baseHash": stale_hash,
        },
    )

    assert response.status_code == 409
    assert "重新加载" in response.json()["detail"]


def test_config_workspace_apply_persists_changes_and_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    writes = []
    deletes = []
    reloads = []
    scene_events = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))
    monkeypatch.setattr(
        config_service,
        "reload_config",
        lambda config_path=None: reloads.append((config_path, copy.deepcopy(public_config)))
        or config_service.build_effective_config(public_config),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *args, **kwargs: scene_events.append((args, kwargs)))

    payload = copy.deepcopy(public_config)
    payload.setdefault("ui", {})["language"] = "en"

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": payload["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": payload["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    persisted = response.json()
    assert public_config["ui"]["language"] == "en"
    assert writes == [("VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY", "draft-secret")]
    assert deletes == []
    assert persisted["baseHash"] == persisted["hash"]
    assert len(reloads) == 1
    assert reloads[0][0] == str(config_service.CONFIG_PATH)
    assert reloads[0][1]["ui"]["language"] == "en"
    applied_event = scene_events[-1][1]["fields"]
    assert applied_event["runtimeConfigReloaded"] is True
    assert applied_event["primaryProviderKind"]
    assert applied_event["primaryTransport"]
    assert applied_event["primaryModel"] == config_service.build_effective_config(public_config).llm.get_profile(role="primary").model


def test_config_workspace_apply_deletes_removed_model_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }
    writes = []
    deletes = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))
    monkeypatch.setattr(
        config_service,
        "reload_config",
        lambda config_path=None: config_service.build_effective_config(public_config),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *args, **kwargs: None)

    draft_response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
        },
    )
    assert draft_response.status_code == 200, draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_response.json()["publicConfig"],
            "draftMeta": draft_response.json()["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200, response.json()
    assert writes == []
    assert deletes == ["VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"]
    assert "custom_relay" not in public_config["llm"]["model_library"]


def test_config_workspace_apply_rejects_missing_git_commit_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    public_config["llm"]["model_library"]["git_commit_model"] = copy.deepcopy(
        public_config["llm"]["model_library"]["deepseek_v4_pro"]
    )
    public_config.setdefault("git", {})["commit_message_model_ref"] = "git_commit_model"
    payload = copy.deepcopy(public_config)
    payload["llm"]["model_library"].pop("git_commit_model", None)
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: pytest.fail("invalid config should not be saved"))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 422
    assert "unknown Git commit message model" in response.json()["detail"]
    assert scene_events[-1][1] == "config.git_commit_model_ref.rejected"


def test_config_workspace_apply_rejects_invalid_git_commit_prompt(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    payload = copy.deepcopy(public_config)
    payload.setdefault("git", {})["commit_message_prompt"] = "Summary only: {summary}"
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: pytest.fail("invalid config should not be saved"))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 422
    assert "{files}" in response.json()["detail"]
    assert "{diff}" in response.json()["detail"]
    assert scene_events[-1][1] == "config.git_commit_prompt.rejected"


def test_config_workspace_apply_ignores_forged_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: None)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    assert writes == []


def test_config_and_evolution_share_intake_mode(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("evolution", {})["intake_mode"] = "auto"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(workbench_contract_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_chat_disable_redirects_home_contract_to_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    agent_cfg = public_config.setdefault("agent", {})
    modes_cfg = agent_cfg.setdefault("modes", {})
    modes_cfg["chat_enabled"] = False
    modes_cfg["self_evolution_enabled"] = True
    modes_cfg["supervised_evolution_enabled"] = True
    modes_cfg["default_shell_mode"] = "chat"
    public_config.setdefault("evolution", {})["enabled"] = True

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    runtime_response = client.get("/api/runtime/summary")

    assert config_response.status_code == 200
    assert runtime_response.status_code == 200

    config_payload = config_response.json()
    runtime_payload = runtime_response.json()

    assert config_payload["defaultRoute"] == "/self-evolution"
    assert runtime_payload["defaultRoute"] == "/self-evolution"
    assert config_payload["defaultMode"] == "self_evolution"
    assert runtime_payload["mode"] == "self_evolution"
    assert config_payload["domainAvailability"]["chat"] is False
    assert config_payload["domainAvailability"]["evolution"] is True
    assert runtime_payload["domainAvailability"]["chat"] is False
    assert runtime_payload["domainAvailability"]["evolution"] is True


def test_updating_intake_mode_refreshes_config_and_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(workbench_contract_service, "load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/intake-mode", json={"intakeMode": "auto"})
    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert update_response.json()["intakeMode"] == "auto"
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_updating_language_refreshes_config_summary(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "zh"

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr("core.web.services.i18n.load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/language", json={"language": "en"})
    config_response = client.get("/api/config/public")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert update_response.json()["language"] == "en"
    assert config_response.json()["language"] == "en"
