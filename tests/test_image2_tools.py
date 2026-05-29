import json

from fastapi.testclient import TestClient

from core.ui.chat_state import build_chat_state, load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service, session_service
from tools import image2_tools
from tools.Key_Tools import create_llm_facing_tools


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _seed_session(root, session_id="session-image"):
    save_chat_state(
        root,
        build_chat_state(
            [{"role": "user", "content": "生成一张雨夜工作室图片", "timestamp": "2026-05-27T00:00:00"}],
            conversation_id=session_id,
            title="Image session",
        ),
    )


def _bind_agent(root, session_id="session-image"):
    agent_directory_service.PROJECT_ROOT = root
    return agent_directory_service.create_agent_instance(
        display_name="Image Agent",
        profile_id="primary",
        direct_session_id=session_id,
    )


def test_image2_tool_generates_session_artifact_message(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_session(tmp_path)
    agent = _bind_agent(tmp_path)
    captured = {}

    def fake_request_image2_generation(**kwargs):
        captured.update(kwargs)
        return {
            "imageBytes": PNG_BYTES,
            "providerResponseId": "img-response-1",
            "revisedPrompt": "rainy studio",
        }

    monkeypatch.setattr(image2_tools, "_request_image2_generation", fake_request_image2_generation)

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-image", turn_id="turn-image"):
        result = json.loads(
            image2_tools.image2_generate_tool(
                prompt="一间雨夜里的工作室",
                size="1024x1024",
                quality="auto",
            )
        )

    assert result["ok"] is True
    assert result["artifactId"].endswith(".png")
    assert result["imageUrl"] == f"/api/sessions/session-image/artifacts/{result['artifactId']}"
    assert captured["prompt"] == "一间雨夜里的工作室"
    artifact_path = tmp_path / "workspace" / "sessions" / "session-image" / "artifacts" / "images" / result["artifactId"]
    assert artifact_path.read_bytes() == PNG_BYTES

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["role"] == "assistant"
    assert message["metadata"]["kind"] == "image2_generation"
    assert message["metadata"]["status"] == "succeeded"
    assert message["metadata"]["downloadUrl"].endswith("?download=1")

    response = client.get(f"/api/sessions/session-image/artifacts/{result['artifactId']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == PNG_BYTES


def test_image2_tool_passes_session_input_artifact_to_request(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_session(tmp_path)
    agent = _bind_agent(tmp_path)
    source = session_service.store_session_image_artifact(
        "session-image",
        PNG_BYTES,
        output_format="png",
        source="user_upload",
    )
    captured = {}

    def fake_request_image2_generation(**kwargs):
        captured.update(kwargs)
        return {
            "imageBytes": PNG_BYTES,
            "providerResponseId": "img-edit-1",
            "revisedPrompt": "cartoon avatar",
        }

    monkeypatch.setattr(image2_tools, "_request_image2_generation", fake_request_image2_generation)

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-image", turn_id="turn-image"):
        result = json.loads(
            image2_tools.image2_generate_tool(
                prompt="把这张图改成 2D 卡通头像",
                input_artifact_id=source["artifactId"],
            )
        )

    assert result["ok"] is True
    assert result["inputArtifactId"] == source["artifactId"]
    assert captured["input_image"]["artifactId"] == source["artifactId"]
    assert captured["input_image"]["contentType"] == "image/png"
    assert captured["input_image"]["imageBytes"] == PNG_BYTES

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["metadata"]["hasInputImage"] is True
    assert message["metadata"]["inputArtifactId"] == source["artifactId"]


def test_request_image2_generation_uses_edits_endpoint_for_input_image(monkeypatch):
    from config import AppConfig

    captured = {}
    config = AppConfig.model_validate(
        {
            "llm": {
                "providers": {
                    "provider-image": {
                        "kind": "relay",
                        "api_key_env": "IMAGE_KEY",
                        "base_url": "https://image.example",
                        "compat_mode": "openai",
                        "requires_api_key": True,
                        "context_window": 128000,
                    }
                },
                "profiles": {
                    "primary": {
                        "provider_id": "provider-image",
                        "model": "chat-model",
                        "timeout": 60,
                    }
                },
                "model_library": {
                    "image2": {
                        "provider_id": "provider-image",
                        "model": "gpt-image-2",
                        "api_key_env": "IMAGE_KEY",
                        "timeout": 120,
                    }
                },
            }
        }
    )

    def fake_post(url, headers, data=None, files=None, json=None, timeout=None):
        captured.update({"url": url, "headers": headers, "data": data, "files": files, "json": json, "timeout": timeout})

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                import base64

                return {"id": "img-edit-2", "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]}

        return Response()

    monkeypatch.setattr(image2_tools, "_read_config_env_var", lambda name: "image-secret")
    monkeypatch.setitem(__import__("sys").modules, "requests", type("Requests", (), {"post": staticmethod(fake_post)}))

    result = image2_tools._request_image2_generation(
        config=config,
        profile_id="primary",
        prompt="换成水彩风",
        model="gpt-image-2",
        model_ref="image2",
        size="1024x1024",
        quality="auto",
        output_format="png",
        input_image={
            "artifactId": "source.png",
            "filename": "source.png",
            "contentType": "image/png",
            "imageBytes": PNG_BYTES,
        },
    )

    assert result["imageBytes"] == PNG_BYTES
    assert captured["url"] == "https://image.example/images/edits"
    assert captured["data"]["prompt"] == "换成水彩风"
    assert captured["files"]["image"][0] == "source.png"
    assert captured["files"]["image"][1] == PNG_BYTES
    assert captured["headers"]["Authorization"] == "Bearer image-secret"
    assert captured["json"] is None


def test_image2_tool_uses_global_default_model_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("GLOBAL_IMAGE2_KEY", "image-secret")
    _seed_session(tmp_path)
    agent = _bind_agent(tmp_path)
    captured = {}

    def fake_get_config(**kwargs):
        from config import AppConfig

        return AppConfig.model_validate(
            {
                "llm": {
                    "providers": {
                        "provider-image-model": {
                            "kind": "openai",
                            "api_key_env": "GLOBAL_IMAGE2_KEY",
                            "base_url": "https://image.example/v1",
                            "compat_mode": "openai",
                            "requires_api_key": True,
                            "context_window": 128000,
                        },
                        "provider-chat-model": {
                            "kind": "openai",
                            "api_key_env": "CHAT_KEY",
                            "base_url": "https://chat.example/v1",
                            "compat_mode": "openai",
                            "requires_api_key": True,
                            "context_window": 128000,
                        },
                    },
                    "profiles": {
                        "primary": {
                            "provider_id": "provider-chat-model",
                            "model": "chat-model",
                            "timeout": 60,
                        }
                    },
                    "model_library": {
                        "global_image_model": {
                            "provider_id": "provider-image-model",
                            "model": "configured-image-model",
                            "label": "Configured Image",
                            "api_key_env": "GLOBAL_IMAGE2_KEY",
                            "timeout": 181,
                        }
                    },
                },
                "tools": {"image2": {"default_model_ref": "global_image_model"}},
            }
        )

    def fake_get(url, headers, timeout):
        captured["discovery"] = {"url": url, "headers": headers, "timeout": timeout}

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {
                    "data": [
                        {"id": "chat-model"},
                        {"id": "gpt-image-1"},
                        {"id": "gpt-image-1.5"},
                        {"id": "gpt-image-2"},
                    ]
                }

        return Response()

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                import base64

                return {"id": "img-global-1", "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]}

        return Response()

    monkeypatch.setattr("config.settings.get_config", fake_get_config)
    monkeypatch.setattr(image2_tools, "_record_image2_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(image2_tools, "_safe_current_runtime", lambda: {})
    monkeypatch.setattr(image2_tools, "_read_config_env_var", lambda name: "image-secret" if name == "GLOBAL_IMAGE2_KEY" else "")
    monkeypatch.setitem(
        __import__("sys").modules,
        "requests",
        type("Requests", (), {"get": staticmethod(fake_get), "post": staticmethod(fake_post)}),
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-image", turn_id="turn-image"):
        result = json.loads(image2_tools.image2_generate_tool(prompt="一张透明玻璃小屋"))

    assert result["ok"] is True
    assert result["model"] == "configured-image-model"
    assert result["modelRef"] == "global_image_model"
    assert captured["url"] == "https://image.example/v1/images/generations"
    assert captured["json"]["model"] == "configured-image-model"
    assert captured["headers"]["Authorization"] == "Bearer image-secret"
    assert captured["timeout"] == 181

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["metadata"]["model"] == "configured-image-model"
    assert message["metadata"]["modelRef"] == "global_image_model"


def test_image2_tool_uses_relay_image2_root_base_url(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_session(tmp_path)
    agent = _bind_agent(tmp_path)
    captured = {}

    def fake_get_config(**kwargs):
        from config import AppConfig

        return AppConfig.model_validate(
            {
                "llm": {
                    "providers": {
                        "provider-relay-image2": {
                            "kind": "relay",
                            "api_key_env": "OPENAI_API_KEY",
                            "base_url": "https://ai-pixel.online",
                            "compat_mode": "openai",
                            "requires_api_key": True,
                            "context_window": 128000,
                        }
                    },
                    "profiles": {
                        "primary": {
                            "provider_id": "provider-relay-image2",
                            "model": "chat-model",
                            "timeout": 60,
                        }
                    },
                    "model_library": {
                        "relay_image2": {
                            "provider_id": "provider-relay-image2",
                            "model": "image2",
                            "label": "Image2 via relay",
                            "api_key_env": "VIBELUTION_LLM_RELAY_IMAGE2_API_KEY",
                            "timeout": 180,
                        }
                    },
                },
                "tools": {"image2": {"default_model_ref": "relay_image2"}},
            }
        )

    def fake_get(url, headers, timeout):
        captured["discovery"] = {"url": url, "headers": headers, "timeout": timeout}

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {
                    "data": [
                        {"id": "chat-model"},
                        {"id": "gpt-image-1"},
                        {"id": "gpt-image-1.5"},
                        {"id": "gpt-image-2"},
                    ]
                }

        return Response()

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})

        class Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                import base64

                return {"id": "img-relay-1", "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]}

        return Response()

    monkeypatch.setattr("config.settings.get_config", fake_get_config)
    monkeypatch.setattr(image2_tools, "_record_image2_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(image2_tools, "_safe_current_runtime", lambda: {})
    monkeypatch.setattr(
        image2_tools,
        "_read_config_env_var",
        lambda name: "image-secret" if name == "VIBELUTION_LLM_RELAY_IMAGE2_API_KEY" else "",
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "requests",
        type("Requests", (), {"get": staticmethod(fake_get), "post": staticmethod(fake_post)}),
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-image", turn_id="turn-image"):
        result = json.loads(image2_tools.image2_generate_tool(prompt="一张赛博风格城市海报"))

    assert result["ok"] is True
    assert result["model"] == "gpt-image-1.5", result.get("modelDiscovery")
    assert result["configuredModel"] == "image2"
    assert result["modelRef"] == "relay_image2"
    assert result["modelDiscovery"]["status"] == "succeeded"
    assert result["modelDiscovery"]["model_count"] == 3
    assert captured["discovery"]["url"] == "https://ai-pixel.online/v1/models"
    assert captured["url"] == "https://ai-pixel.online/images/generations"
    assert "/v1/" not in captured["url"]
    assert captured["json"]["model"] == "gpt-image-1.5"
    assert captured["headers"]["Authorization"] == "Bearer image-secret"
    assert captured["timeout"] == 180


def test_image2_target_falls_back_to_env_model_when_global_ref_empty(monkeypatch):
    from config import AppConfig

    monkeypatch.setenv("VIBELUTION_IMAGE2_MODEL", "env-image-model")
    config = AppConfig.model_validate({"tools": {"image2": {"default_model_ref": ""}}})

    target = image2_tools._resolve_image2_target(config, profile_id="primary")

    assert target["model"] == "env-image-model"
    assert target["configuredModel"] == "env-image-model"
    assert target["modelRef"] == ""
    assert target["modelDiscovery"]["status"] == "skipped"


def test_image2_tool_appends_failure_message_for_invalid_args(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_session(tmp_path)
    agent = _bind_agent(tmp_path)

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-image", turn_id="turn-image"):
        result = json.loads(image2_tools.image2_generate_tool(prompt="画图", size="2048x2048"))

    assert result["ok"] is False
    assert result["errorType"] == "validation_error"
    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["role"] == "assistant"
    assert "图片生成失败" in message["content"]
    assert message["metadata"]["kind"] == "image2_generation"
    assert message["metadata"]["status"] == "failed"
    assert message["metadata"]["errorType"] == "validation_error"


def test_image2_tool_is_llm_visible():
    names = {tool.name for tool in create_llm_facing_tools()}

    assert "image2_generate_tool" in names
