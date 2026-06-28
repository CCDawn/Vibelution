# -*- coding: utf-8 -*-
"""image2 generation tool bridge for session-scoped chat artifacts."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
from typing import Any

from core.chat.chat_task_types import trim_lines
from core.infrastructure.image_model_discovery import resolve_image_model


IMAGE2_TOOL_NAME = "image2_generate_tool"
DEFAULT_IMAGE2_MODEL = "gpt-image-1.5"
ALLOWED_IMAGE2_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
ALLOWED_IMAGE2_QUALITIES = {"auto", "low", "medium", "high"}
ALLOWED_IMAGE2_FORMATS = {"png"}
_SAFE_LOG_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


def image2_generate_tool(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "auto",
    output_format: str = "png",
    input_artifact_id: str = "",
) -> str:
    """
    Generate an image through the current Agent's configured provider and attach it to this session.

    Args:
        prompt: Natural-language image prompt.
        size: Image size. Allowed: 1024x1024, 1536x1024, 1024x1536.
        quality: Image quality. Allowed: auto, low, medium, high.
        output_format: Output format. First version supports png only.
        input_artifact_id: Optional session image artifact id to use as an edit/style reference.

    Returns:
        JSON result with artifact id, image URL, download URL, and status.
    """

    started = time.perf_counter()
    model = _resolve_image2_model()
    model_ref = ""
    try:
        from config.settings import get_config
        from core.web.services import session_service
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
        session_id = str(runtime.get("sessionId") or "").strip()
        agent = runtime.get("agent") if isinstance(runtime.get("agent"), dict) else {}
        agent_id = str(runtime.get("agentId") or (agent or {}).get("agentId") or "").strip()
        profile_id = "primary"

        normalized_prompt = trim_lines(str(prompt or ""), max_lines=80).strip()
        normalized_size = str(size or "1024x1024").strip() or "1024x1024"
        normalized_quality = str(quality or "auto").strip().lower() or "auto"
        normalized_format = str(output_format or "png").strip().lower().lstrip(".") or "png"
        normalized_input_artifact_id = str(input_artifact_id or "").strip()
        validation_error = _validate_request(
            normalized_prompt,
            normalized_size,
            normalized_quality,
            normalized_format,
            session_id=session_id,
        )
        if validation_error:
            result = _failed_result(
                validation_error,
                error_type="validation_error",
                session_id=session_id,
                agent_id=agent_id,
                profile_id=profile_id,
                model=model,
                model_ref=model_ref,
                size=normalized_size,
                quality=normalized_quality,
                output_format=normalized_format,
                prompt=normalized_prompt,
                duration_ms=_duration_ms(started),
            )
            if session_id:
                try:
                    _append_failure_message(
                        session_service,
                        session_id,
                        result,
                        prompt=normalized_prompt,
                    )
                except Exception as append_exc:
                    result["appendError"] = f"{type(append_exc).__name__}: {append_exc}"
                    result["appendFailure"] = True
            _record_image2_event(
                "image2.generate.failed",
                runtime=runtime,
                level="warning",
                outcome="failed",
                fields={
                    "errorType": "validation_error",
                    "size": normalized_size,
                    "quality": normalized_quality,
                    "outputFormat": normalized_format,
                    "durationMs": result["durationMs"],
                    "promptChars": len(normalized_prompt),
                },
            )
            return _json_result(result)

        config = get_config()
        image2_target = _resolve_image2_target(config, profile_id=profile_id)
        model = image2_target["model"]
        model_ref = image2_target["modelRef"]
        configured_model = image2_target.get("configuredModel", model)
        model_discovery = image2_target.get("modelDiscovery", {})
        input_image = (
            _load_session_input_image(session_service, session_id, normalized_input_artifact_id)
            if normalized_input_artifact_id
            else None
        )
        _record_image2_event(
            "image2.generate.started",
            runtime=runtime,
            outcome="running",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "profileId": profile_id,
                "model": model,
                "configuredModel": configured_model,
                "modelRef": model_ref,
                "modelDiscoveryStatus": str(model_discovery.get("status") or ""),
                "discoveredModelCount": len(model_discovery.get("models") or []),
                "size": normalized_size,
                "quality": normalized_quality,
                "outputFormat": normalized_format,
                "promptChars": len(normalized_prompt),
                "promptPreview": trim_lines(normalized_prompt, max_lines=2),
                "hasInputImage": input_image is not None,
                "inputArtifactId": normalized_input_artifact_id,
            },
            child_log_payload={
                "session_id": session_id,
                "agent_id": agent_id,
                "profile_id": profile_id,
                "model": model,
                "configured_model": configured_model,
                "model_ref": model_ref,
                "model_discovery": _image2_discovery_log_payload(model_discovery),
                "size": normalized_size,
                "quality": normalized_quality,
                "output_format": normalized_format,
                "prompt_preview": trim_lines(normalized_prompt, max_lines=4),
                "has_input_image": input_image is not None,
                "input_artifact_id": normalized_input_artifact_id,
            },
        )

        generated = _request_image2_generation(
            config=config,
            profile_id=profile_id,
            prompt=normalized_prompt,
            model=model,
            model_ref=model_ref,
            size=normalized_size,
            quality=normalized_quality,
            output_format=normalized_format,
            input_image=input_image,
        )
        artifact = session_service.store_session_image_artifact(
            session_id,
            generated["imageBytes"],
            output_format=normalized_format,
            source="image2_edit" if input_image is not None else "image2",
        )
        duration_ms = _duration_ms(started)
        metadata = {
            "kind": "image2_generation",
            "toolName": IMAGE2_TOOL_NAME,
            "status": "succeeded",
            "prompt": normalized_prompt,
            "inputArtifactId": normalized_input_artifact_id,
            "hasInputImage": input_image is not None,
            "model": model,
            "configuredModel": configured_model,
            "modelRef": model_ref,
            "modelDiscovery": _image2_discovery_log_payload(model_discovery),
            "size": normalized_size,
            "quality": normalized_quality,
            "outputFormat": normalized_format,
            "artifactId": artifact["artifactId"],
            "artifactPath": artifact["artifactPath"],
            "imageUrl": artifact["imageUrl"],
            "downloadUrl": artifact["downloadUrl"],
            "contentType": artifact["contentType"],
            "sizeBytes": artifact["sizeBytes"],
            "providerResponseId": str(generated.get("providerResponseId") or ""),
            "revisedPrompt": str(generated.get("revisedPrompt") or ""),
            "durationMs": duration_ms,
        }
        message = session_service.append_session_assistant_artifact_message(
            session_id,
            "已生成图片。",
            metadata=metadata,
        )
        result = {
            "ok": True,
            "status": "succeeded",
            "toolName": IMAGE2_TOOL_NAME,
            "sessionId": session_id,
            "agentId": agent_id,
            "profileId": profile_id,
            "model": model,
            "configuredModel": configured_model,
            "modelRef": model_ref,
            "modelDiscovery": _image2_discovery_log_payload(model_discovery),
            "size": normalized_size,
            "quality": normalized_quality,
            "outputFormat": normalized_format,
            "inputArtifactId": normalized_input_artifact_id,
            "hasInputImage": input_image is not None,
            "artifactId": artifact["artifactId"],
            "artifactPath": artifact["artifactPath"],
            "imageUrl": artifact["imageUrl"],
            "downloadUrl": artifact["downloadUrl"],
            "messageId": str(message.get("id") or ""),
            "providerResponseId": metadata["providerResponseId"],
            "durationMs": duration_ms,
        }
        _record_image2_event(
            "image2.generate.succeeded",
            runtime=runtime,
            outcome="succeeded",
            fields={
                "agentId": agent_id,
                "sessionId": session_id,
                "profileId": profile_id,
                "model": model,
                "configuredModel": configured_model,
                "modelRef": model_ref,
                "modelDiscoveryStatus": str(model_discovery.get("status") or ""),
                "discoveredModelCount": len(model_discovery.get("models") or []),
                "size": normalized_size,
                "quality": normalized_quality,
                "outputFormat": normalized_format,
                "artifactId": artifact["artifactId"],
                "artifactPath": artifact["artifactPath"],
                "sizeBytes": artifact["sizeBytes"],
                "durationMs": duration_ms,
                "promptChars": len(normalized_prompt),
                "hasInputImage": input_image is not None,
                "inputArtifactId": normalized_input_artifact_id,
            },
            child_log_payload={
                "session_id": session_id,
                "agent_id": agent_id,
                "profile_id": profile_id,
                "model": model,
                "configured_model": configured_model,
                "model_ref": model_ref,
                "model_discovery": _image2_discovery_log_payload(model_discovery),
                "artifact_id": artifact["artifactId"],
                "artifact_path": artifact["artifactPath"],
                "provider_response_id": metadata["providerResponseId"],
                "duration_ms": duration_ms,
                "prompt_preview": trim_lines(normalized_prompt, max_lines=4),
                "has_input_image": input_image is not None,
                "input_artifact_id": normalized_input_artifact_id,
            },
        )
        return _json_result(result)
    except Exception as exc:
        duration_ms = _duration_ms(started)
        error_type = type(exc).__name__
        message = trim_lines(str(exc), max_lines=2)
        runtime = _safe_current_runtime()
        session_id = str(runtime.get("sessionId") or "").strip()
        agent = runtime.get("agent") if isinstance(runtime.get("agent"), dict) else {}
        result = _failed_result(
            message or "图片生成失败。",
            error_type=error_type,
            session_id=session_id,
            agent_id=str(runtime.get("agentId") or (agent or {}).get("agentId") or "").strip(),
            profile_id="primary",
            model=model,
            model_ref=model_ref,
            size=str(size or "1024x1024"),
            quality=str(quality or "auto"),
            output_format=str(output_format or "png"),
            prompt=trim_lines(str(prompt or ""), max_lines=80).strip(),
            duration_ms=duration_ms,
        )
        if session_id:
            try:
                from core.web.services import session_service

                _append_failure_message(
                    session_service,
                    session_id,
                    result,
                    prompt=str(prompt or "").strip(),
                )
            except Exception as append_exc:
                result["appendError"] = f"{type(append_exc).__name__}: {append_exc}"
                result["appendFailure"] = True
        _record_image2_event(
            "image2.generate.failed",
            runtime=runtime,
            level="error",
            outcome="failed",
            fields={
                "errorType": error_type,
                "errorPreview": message,
                "durationMs": duration_ms,
                "promptChars": len(str(prompt or "")),
            },
            child_log_payload={
                "session_id": session_id,
                "error_type": error_type,
                "error_preview": message,
                "duration_ms": duration_ms,
                "prompt_preview": trim_lines(str(prompt or ""), max_lines=4),
            },
        )
        return _json_result(result)


def _validate_request(
    prompt: str,
    size: str,
    quality: str,
    output_format: str,
    *,
    session_id: str,
) -> str:
    if not session_id:
        return "当前工具需要在已绑定会话的 Agent 运行时中调用。"
    if not prompt:
        return "请提供图片生成提示词。"
    if size not in ALLOWED_IMAGE2_SIZES:
        return f"不支持的图片尺寸：{size}。"
    if quality not in ALLOWED_IMAGE2_QUALITIES:
        return f"不支持的图片质量：{quality}。"
    if output_format not in ALLOWED_IMAGE2_FORMATS:
        return f"不支持的图片格式：{output_format}。"
    return ""


def _resolve_image2_model() -> str:
    try:
        return str(os.environ.get("VIBELUTION_IMAGE2_MODEL") or DEFAULT_IMAGE2_MODEL).strip() or DEFAULT_IMAGE2_MODEL
    except Exception:
        return DEFAULT_IMAGE2_MODEL


def _resolve_image2_target(config: Any, *, profile_id: str) -> dict[str, Any]:
    model_ref = _configured_image2_model_ref(config)
    if model_ref:
        item = _model_library_item(config, model_ref)
        if item is None:
            raise RuntimeError(f"全局 image2 模型引用不存在：{model_ref}。请在模型库中添加该模型，或清空 tools.image2.default_model_ref。")
        model = str(item.get("model") or "").strip()
        if not model:
            raise RuntimeError(f"全局 image2 模型引用缺少模型名：{model_ref}。")
        return _with_resolved_image2_model(config, profile_id=profile_id, model_ref=model_ref, configured_model=model)

    return _with_resolved_image2_model(
        config,
        profile_id=profile_id,
        model_ref="",
        configured_model=_resolve_image2_model(),
    )


def _with_resolved_image2_model(config: Any, *, profile_id: str, model_ref: str, configured_model: str) -> dict[str, Any]:
    binding = _resolve_image2_request_binding(config, profile_id, model_ref)
    provider = binding["provider"]
    api_key = str(binding.get("apiKey") or "")
    base_url = _image2_provider_base_url(provider)
    headers = _image2_request_headers(provider, api_key=api_key, content_type="")
    resolved = resolve_image_model(
        configured_model=configured_model,
        base_url=base_url,
        api_key=api_key,
        headers=headers,
        timeout=min(10, max(3, int(binding.get("timeout") or 8))),
    )
    return {
        "model": str(resolved.get("model") or configured_model).strip() or configured_model,
        "configuredModel": str(resolved.get("configuredModel") or configured_model).strip() or configured_model,
        "modelRef": model_ref,
        "modelDiscovery": resolved.get("discovery") if isinstance(resolved.get("discovery"), dict) else {},
    }


def _configured_image2_model_ref(config: Any) -> str:
    try:
        image2_cfg = getattr(getattr(config, "tools", None), "image2", None)
        return str(getattr(image2_cfg, "default_model_ref", "") or "").strip()
    except Exception:
        return ""


def _model_library_item(config: Any, model_ref: str) -> dict[str, Any] | None:
    try:
        library = getattr(getattr(config, "llm", None), "model_library", {}) or {}
        item = library.get(model_ref) if isinstance(library, dict) else None
        return item if isinstance(item, dict) else None
    except Exception:
        return None


def _read_config_env_var(name: str) -> str:
    token = str(name or "").strip()
    if not token:
        return ""
    try:
        from config.models import _read_env_var

        return str(_read_env_var(token) or "")
    except Exception:
        return str(os.environ.get(token) or "")


def _resolve_image2_request_binding(config: Any, profile_id: str, model_ref: str) -> dict[str, Any]:
    if model_ref:
        item = _model_library_item(config, model_ref)
        if item is None:
            raise RuntimeError(f"全局 image2 模型引用不存在：{model_ref}。")
        provider_id = str(item.get("provider_id") or "").strip()
        if not provider_id:
            raise RuntimeError(f"全局 image2 模型引用缺少 provider：{model_ref}。")
        provider = config.llm.get_provider(provider_id)
        model_env = str(item.get("api_key_env") or "").strip()
        api_key = _read_config_env_var(model_env) if model_env else ""
        if not api_key:
            api_key = provider.resolve_api_key()
        try:
            timeout = int(item.get("timeout") or 0)
        except (TypeError, ValueError):
            timeout = 0
        if timeout <= 0:
            timeout = 60
        return {
            "provider": provider,
            "apiKey": api_key,
            "timeout": timeout,
        }

    profile = config.llm.get_profile(profile_id=profile_id)
    provider = config.llm.get_provider(profile.provider_id)
    return {
        "provider": provider,
        "apiKey": config.get_api_key_for_profile(profile_id=profile_id),
        "timeout": max(30, int(getattr(profile, "timeout", 60) or 60)),
    }


def _image2_provider_base_url(provider: Any) -> str:
    base_url = str(getattr(provider, "base_url", "") or "").strip()
    if not base_url and str(getattr(provider, "kind", "") or "").strip().lower() == "openai":
        return "https://api.openai.com/v1"
    return base_url


def _image2_request_headers(provider: Any, *, api_key: str, content_type: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    extra_headers = getattr(provider, "extra_headers", None)
    if isinstance(extra_headers, dict):
        headers.update({str(key): str(value) for key, value in extra_headers.items() if str(key).strip()})
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _load_session_input_image(session_service: Any, session_id: str, artifact_id: str) -> dict[str, Any]:
    attachment = session_service.resolve_session_image_attachment_data_url(session_id, artifact_id)
    data_url = str(attachment.get("dataUrl") or "").strip()
    prefix, _, encoded = data_url.partition(",")
    if not encoded or ";base64" not in prefix:
        raise RuntimeError("会话图片附件无法作为 image2 输入读取。")
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("会话图片附件包含无效的 base64 数据。") from exc
    if not image_bytes:
        raise RuntimeError("会话图片附件为空，无法作为 image2 输入。")
    return {
        "artifactId": str(attachment.get("artifactId") or artifact_id).strip(),
        "filename": str(attachment.get("filename") or artifact_id).strip() or "input.png",
        "contentType": str(attachment.get("contentType") or "image/png").strip() or "image/png",
        "imageBytes": image_bytes,
    }


def _request_image2_generation(
    *,
    config: Any,
    profile_id: str,
    prompt: str,
    model: str,
    size: str,
    quality: str,
    output_format: str,
    model_ref: str = "",
    input_image: dict[str, Any] | None = None,
) -> dict[str, Any]:
    binding = _resolve_image2_request_binding(config, profile_id, model_ref)
    provider = binding["provider"]
    api_key = str(binding.get("apiKey") or "")
    if getattr(provider, "requires_api_key", True) and not api_key:
        if model_ref:
            raise RuntimeError("全局 image2 模型配置没有可用 API Key。")
        raise RuntimeError("当前 Agent 的模型配置没有可用 API Key。")

    try:
        import requests
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("requests 未安装，无法调用 image2 服务。") from exc

    base_url = _image2_provider_base_url(provider)
    if not base_url:
        raise RuntimeError("当前 Agent 的模型配置没有 base_url，无法调用 image2 服务。")

    timeout = max(30, int(binding.get("timeout") or 60))
    if input_image:
        headers = _image2_request_headers(provider, api_key=api_key)
        fields = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": "1",
            "output_format": output_format,
        }
        filename = str(input_image.get("filename") or input_image.get("artifactId") or "input.png").strip() or "input.png"
        content_type = str(input_image.get("contentType") or "image/png").strip() or "image/png"
        files = {
            "image": (
                filename,
                bytes(input_image.get("imageBytes") or b""),
                content_type,
            )
        }
        response = requests.post(
            f"{base_url.rstrip('/')}/images/edits",
            headers=headers,
            data=fields,
            files=files,
            timeout=timeout,
        )
    else:
        headers = _image2_request_headers(provider, api_key=api_key, content_type="application/json")
        body = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": 1,
            "output_format": output_format,
        }
        response = requests.post(
            f"{base_url.rstrip('/')}/images/generations",
            headers=headers,
            json=body,
            timeout=timeout,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"image2 provider returned {response.status_code}: "
            f"{trim_lines(response.text, max_lines=2)[:500]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("image2 provider response was not JSON.") from exc
    return _extract_image2_payload(payload, requests_module=requests, timeout=timeout)


def _extract_image2_payload(payload: dict[str, Any], *, requests_module: Any, timeout: int) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        raise RuntimeError("image2 provider did not return image data.")
    first = data[0] if isinstance(data[0], dict) else {}
    b64_json = str(first.get("b64_json") or first.get("b64Json") or "").strip()
    if b64_json:
        try:
            image_bytes = base64.b64decode(b64_json, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("image2 provider returned invalid base64 image data.") from exc
    else:
        image_url = str(first.get("url") or "").strip()
        if not image_url:
            raise RuntimeError("image2 provider did not return b64_json or url.")
        image_response = requests_module.get(image_url, timeout=timeout)
        if image_response.status_code >= 400:
            raise RuntimeError(f"image2 image download failed: {image_response.status_code}")
        image_bytes = bytes(image_response.content or b"")
    if not image_bytes:
        raise RuntimeError("image2 provider returned an empty image.")
    return {
        "imageBytes": image_bytes,
        "providerResponseId": str(payload.get("id") or ""),
        "revisedPrompt": str(first.get("revised_prompt") or first.get("revisedPrompt") or ""),
    }


def _append_failure_message(
    session_service: Any,
    session_id: str,
    result: dict[str, Any],
    *,
    prompt: str,
) -> None:
    metadata = {
        "kind": "image2_generation",
        "toolName": IMAGE2_TOOL_NAME,
        "status": "failed",
        "prompt": trim_lines(prompt, max_lines=80).strip(),
        "model": str(result.get("model") or ""),
        "modelRef": str(result.get("modelRef") or ""),
        "size": str(result.get("size") or ""),
        "quality": str(result.get("quality") or ""),
        "outputFormat": str(result.get("outputFormat") or ""),
        "errorType": str(result.get("errorType") or ""),
        "errorMessage": str(result.get("message") or ""),
        "durationMs": int(result.get("durationMs") or 0),
    }
    session_service.append_session_assistant_artifact_message(
        session_id,
        f"图片生成失败：{result.get('message') or '请稍后重试。'}",
        metadata=metadata,
    )


def _failed_result(
    message: str,
    *,
    error_type: str,
    session_id: str,
    agent_id: str,
    profile_id: str,
    model: str,
    model_ref: str,
    size: str,
    quality: str,
    output_format: str,
    prompt: str,
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "toolName": IMAGE2_TOOL_NAME,
        "message": trim_lines(message, max_lines=2),
        "errorType": error_type,
        "sessionId": session_id,
        "agentId": agent_id,
        "profileId": profile_id,
        "model": model,
        "modelRef": model_ref,
        "size": size,
        "quality": quality,
        "outputFormat": output_format,
        "promptChars": len(prompt or ""),
        "durationMs": duration_ms,
    }


def _record_image2_event(
    event_code: str,
    *,
    runtime: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
    child_log_payload: dict[str, Any] | None = None,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        session_id = str((runtime or {}).get("sessionId") or "").strip()
        child_log_path = ""
        if child_log_payload is not None:
            child_log_path = f"artifacts/{_safe_log_token(session_id or 'session')}-image2.jsonl"
        record_runtime_scene_event(
            "image2",
            "generate",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields or {},
            child_log_path=child_log_path,
            child_log_payload=child_log_payload or None,
            lifecycle=True,
        )
    except Exception:
        return


def _image2_discovery_log_payload(discovery: Any) -> dict[str, Any]:
    payload = discovery if isinstance(discovery, dict) else {}
    return {
        "status": str(payload.get("status") or ""),
        "url": str(payload.get("url") or ""),
        "selected_model": str(payload.get("selectedModel") or ""),
        "model_count": len(payload.get("models") or []),
        "error": trim_lines(str(payload.get("error") or ""), max_lines=2)[:300],
    }


def _safe_log_token(value: str) -> str:
    token = _SAFE_LOG_TOKEN.sub("-", str(value or "session")).strip("._-")
    return token[:96] or "session"


def _safe_current_runtime() -> dict[str, Any]:
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
        return runtime if isinstance(runtime, dict) else {}
    except Exception:
        return {}


def _duration_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
