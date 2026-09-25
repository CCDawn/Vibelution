"""Model-input image variant layer for session image attachments.

Covers the LLM input normalization at resolve_session_image_attachment_data_url:
longest-edge downscale to <= 2000px, base64 <= 5MiB budget ladder, deterministic
sibling cache reuse, and fail-open pass-through for undecodable bytes.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import pytest
from PIL import Image

from core.web.services.session import image_model_variant
from tests.test_agent_config_workspace_service import (
    _fake_config_workspace,
    _use_tmp_project_root,
    config_service,
    session_service,
)


def _make_png(width: int, height: int, *, noise: bool = False) -> bytes:
    buffer = io.BytesIO()
    if noise:
        Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
            buffer, format="PNG"
        )
    else:
        Image.new("RGB", (width, height), (120, 80, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _store_image_attachment(
    tmp_path,
    monkeypatch,
    payload: bytes,
    *,
    filename: str,
) -> tuple[str, dict]:
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    session = session_service.create_chat_session(title="图片降采样测试")
    attachment = session_service.store_session_user_image_attachment(
        session["id"],
        payload,
        filename=filename,
        content_type="image/png",
    )
    return str(session["id"]), attachment


def _resolve(session_id: str, artifact_id: str) -> dict:
    return session_service.resolve_session_image_attachment_data_url(session_id, artifact_id)


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    prefix, _, encoded = data_url.partition(",")
    content_type = prefix.removeprefix("data:").split(";", 1)[0]
    return content_type, base64.b64decode(encoded, validate=True)


def test_large_image_is_downscaled_and_cached_for_model_input(tmp_path, monkeypatch):
    original_png = _make_png(3000, 2000)
    session_id, attachment = _store_image_attachment(
        tmp_path, monkeypatch, original_png, filename="big.png"
    )
    artifact_path = Path(attachment["path"])
    cache_path = image_model_variant.model_variant_cache_path(artifact_path)
    assert image_model_variant.MODEL_VARIANT_STRATEGY in cache_path.name

    resolved = _resolve(session_id, attachment["artifactId"])

    content_type, payload = _decode_data_url(resolved["dataUrl"])
    assert content_type == image_model_variant.MODEL_VARIANT_CONTENT_TYPE
    with Image.open(io.BytesIO(payload)) as variant_image:
        assert max(variant_image.size) <= image_model_variant.MODEL_VARIANT_MAX_EDGE
    # Original artifact stays untouched for UI preview.
    assert artifact_path.read_bytes() == original_png
    with Image.open(io.BytesIO(artifact_path.read_bytes())) as original_image:
        assert original_image.size == (3000, 2000)
    # Sibling cache written next to the artifact.
    assert cache_path.is_file()
    assert cache_path.read_bytes() == payload

    # A second resolve must reuse the cache without re-rendering.
    mtime_ns = cache_path.stat().st_mtime_ns

    def unexpected_render(_payload: bytes):
        raise AssertionError("model variant must be served from the sibling cache")

    monkeypatch.setattr(image_model_variant, "_render_model_variant", unexpected_render)
    replayed = _resolve(session_id, attachment["artifactId"])
    assert replayed["dataUrl"] == resolved["dataUrl"]
    assert cache_path.stat().st_mtime_ns == mtime_ns


def test_small_image_passes_through_without_variant_cache(tmp_path, monkeypatch):
    original_png = _make_png(400, 300)
    session_id, attachment = _store_image_attachment(
        tmp_path, monkeypatch, original_png, filename="small.png"
    )
    artifact_path = Path(attachment["path"])

    resolved = _resolve(session_id, attachment["artifactId"])

    content_type, payload = _decode_data_url(resolved["dataUrl"])
    assert content_type == "image/png"
    assert payload == original_png
    assert not image_model_variant.model_variant_cache_path(artifact_path).exists()


def test_oversized_base64_budget_reencodes_within_budget(tmp_path, monkeypatch):
    noisy_png = _make_png(1500, 1500, noise=True)
    assert len(noisy_png) <= session_service._SESSION_USER_IMAGE_MAX_BYTES
    session_id, attachment = _store_image_attachment(
        tmp_path, monkeypatch, noisy_png, filename="noisy.png"
    )
    artifact_path = Path(attachment["path"])

    resolved = _resolve(session_id, attachment["artifactId"])

    content_type, payload = _decode_data_url(resolved["dataUrl"])
    assert content_type == image_model_variant.MODEL_VARIANT_CONTENT_TYPE
    assert len(resolved["dataUrl"]) <= image_model_variant.MODEL_VARIANT_MAX_BASE64_BYTES + 64
    with Image.open(io.BytesIO(payload)) as variant_image:
        assert max(variant_image.size) <= image_model_variant.MODEL_VARIANT_MAX_EDGE
    assert artifact_path.read_bytes() == noisy_png
    assert image_model_variant.model_variant_cache_path(artifact_path).is_file()


def test_corrupt_image_bytes_fail_open_to_original_payload(tmp_path, monkeypatch):
    corrupted = b"\x89PNG\r\n\x1a\n" + b"corrupted-not-a-real-image"
    session_id, attachment = _store_image_attachment(
        tmp_path, monkeypatch, corrupted, filename="broken.png"
    )
    artifact_path = Path(attachment["path"])

    resolved = _resolve(session_id, attachment["artifactId"])

    content_type, payload = _decode_data_url(resolved["dataUrl"])
    assert content_type == "image/png"
    assert payload == corrupted
    assert not image_model_variant.model_variant_cache_path(artifact_path).exists()
