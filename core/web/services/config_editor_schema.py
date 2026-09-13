"""Shared config editor schema helpers for the web workbench."""

from __future__ import annotations

import copy
from typing import Any

from config.editor_schema_data import (
    AVATAR_PRESET_OPTIONS,
    BADGE_LABELS,
    FIELD_HINTS,
    FIELD_LABELS,
    FIELD_SUFFIX_LABELS,
    LOG_LEVEL_OPTIONS,
    RUNTIME_PROFILE_OPTIONS,
    SECTION_LABELS,
    SEGMENTATION_STRATEGY_OPTIONS,
    USER_AVATAR_PRESET_OPTIONS,
    WORKBENCH_BACKGROUND_READABILITY_OPTIONS,
    WORKBENCH_WINDOW_MODE_OPTIONS,
)
from config.public_config import list_llm_model_options

from .theme_background_service import list_default_theme_background_options

EDITOR_SECTION_SPECS = [
    ("avatar", "avatar"),
    ("user-profile", "user_profile"),
    ("context-compression", "context_compression"),
    ("security", "security"),
    ("log", "log"),
    ("network", "network"),
    ("analysis", "analysis"),
    ("git-commit-model", "git.commit_message_model_ref"),
    ("git-commit-prompt", "git.commit_message_prompt"),
    ("ui", "ui"),
    ("parser", "parser"),
    ("debug", "debug"),
    ("pet", "pet"),
]

LAUNCHER_OWNED_FIELD_PATHS = {
    "ui.language",
}


def _humanize_token(token: str) -> str:
    cleaned = str(token or "").strip()
    if not cleaned:
        return ""
    return " ".join(part.upper() if part.isupper() else part.capitalize() for part in cleaned.split("_") if part)


def localize_label(path: str, fallback: str, lang: str) -> str:
    exact = FIELD_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    parts = [part for part in str(path or "").split(".") if part]
    suffix_map = FIELD_SUFFIX_LABELS.get(lang, {})
    for token_count in (2, 1):
        if len(parts) >= token_count:
            suffix = ".".join(parts[-token_count:])
            mapped = suffix_map.get(suffix)
            if mapped:
                return mapped
    token = str(fallback or "").strip() or str(path or "").split(".")[-1]
    parts = [part for part in token.split("_") if part]
    if not parts:
        return token
    return " ".join(_humanize_token(part) for part in parts)


def localize_section_label(path: str, fallback: str, lang: str) -> str:
    exact = SECTION_LABELS.get(lang, {}).get(path)
    if exact:
        return exact
    return localize_label(path, fallback, lang)


def field_hint(path: str, lang: str) -> str:
    return FIELD_HINTS.get(lang, {}).get(path, "")


def localize_badge(label: str, lang: str) -> str:
    return BADGE_LABELS.get(lang, {}).get(label, label)


def _is_secret_path(path: str) -> bool:
    return str(path or "").split(".")[-1] == "api_key"


def _field_options(path: str, lang: str) -> list[dict[str, str]]:
    if path == "ui.language":
        return [
            {"value": "zh", "label": "中文" if lang == "zh" else "Chinese"},
            {"value": "en", "label": "English"},
        ]
    if path == "runtime.profile":
        return [{"value": value, "label": value} for value in RUNTIME_PROFILE_OPTIONS]
    if path == "workbench.window_mode":
        labels = {
            "zh": {
                "windowed": "窗口化",
                "fullscreen": "沉浸全屏",
            },
            "en": {
                "windowed": "Windowed",
                "fullscreen": "Immersive fullscreen",
            },
        }
        return [{"value": value, "label": labels.get(lang, labels["en"]).get(value, value)} for value in WORKBENCH_WINDOW_MODE_OPTIONS]
    if path == "avatar.preset":
        return [{"value": value, "label": value} for value in AVATAR_PRESET_OPTIONS]
    if path == "user_profile.avatar_preset":
        return [{"value": value, "label": value} for value in USER_AVATAR_PRESET_OPTIONS]
    if path == "ui.workbench_theme.background_readability":
        labels = {
            "zh": {
                "soft": "柔和",
                "standard": "标准",
                "strong": "增强",
            },
            "en": {
                "soft": "Soft",
                "standard": "Standard",
                "strong": "Strong",
            },
        }
        return [
            {"value": value, "label": labels.get(lang, labels["en"]).get(value, value)}
            for value in WORKBENCH_BACKGROUND_READABILITY_OPTIONS
        ]
    if path == "ui.workbench_theme.background_image_path":
        return list_default_theme_background_options(lang)
    if path == "evolution.chat_dataset.segmentation_strategy":
        return [{"value": value, "label": value} for value in SEGMENTATION_STRATEGY_OPTIONS]
    if path == "log.level" or path.startswith("log.third_party."):
        return [{"value": value, "label": value} for value in LOG_LEVEL_OPTIONS]
    return []


def _field_options_for_config(path: str, public_config: dict[str, Any], lang: str) -> list[dict[str, str]]:
    if path == "git.commit_message_model_ref":
        return [
            {
                "value": str(option.get("model_id") or ""),
                "label": str(option.get("label") or option.get("model") or option.get("model_id") or ""),
            }
            for option in list_llm_model_options(public_config)
            if str(option.get("model_id") or "").strip()
        ]
    return _field_options(path, lang)


def _field_kind(path: str, value: Any, options: list[dict[str, str]] | None = None) -> tuple[str, str]:
    if path == "user_profile.avatar_image_path":
        return "image", "Image"
    if path == "ui.workbench_theme.background_image_path":
        return "background_image", "Image"
    if path in {"user_profile.bio", "git.commit_message_prompt"}:
        return "multiline", "Multiline"
    if isinstance(value, bool):
        return "boolean", "Toggle"
    if options:
        return "select", "Option"
    if isinstance(value, int) and not isinstance(value, bool):
        if any(token in path for token in ("timeout", "interval", "runtime")):
            return "number", "Seconds"
        if any(token in path for token in ("tokens", "token", "context_window")):
            return "number", "Token"
        return "number", "Number"
    if isinstance(value, float):
        return "number", "Number"
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "string_list", "List"
    if isinstance(value, list):
        return "json", "JSON"
    if _is_secret_path(path):
        return "secret", "Secret"
    normalized_path = str(path or "").replace("-", "_").lower()
    path_tokens = set(normalized_path.replace(".", "_").split("_"))
    if "url" in path_tokens or normalized_path.endswith((".api_base", ".base_url")):
        return "url", "URL"
    if path_tokens.intersection({"path", "workspace", "directory", "directories", "file"}):
        return "path", "Path"
    return "text", "Text"


def _lookup_path_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in [token for token in str(path or "").split(".") if token]:
        if isinstance(current, dict):
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
            continue
        raise KeyError(path)
    return current


def _without_launcher_owned_fields(value: Any, path: str) -> Any:
    if path in LAUNCHER_OWNED_FIELD_PATHS:
        return None
    if isinstance(value, dict):
        filtered: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if child_path in LAUNCHER_OWNED_FIELD_PATHS:
                continue
            filtered_child = _without_launcher_owned_fields(child, child_path)
            if filtered_child is not None:
                filtered[key] = filtered_child
        return filtered
    if isinstance(value, list):
        return [
            filtered_child
            for index, child in enumerate(value)
            for filtered_child in [_without_launcher_owned_fields(child, f"{path}.{index}")]
            if filtered_child is not None
        ]
    return value


def _count_leaf_fields(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_count_leaf_fields(item) for item in value.values())
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return sum(_count_leaf_fields(item) for item in value)
    return 1


def _walk_editor_meta(value: Any, path: str, lang: str, into: dict[str, dict[str, Any]], public_config: dict[str, Any]) -> None:
    label = localize_section_label(path, path.split(".")[-1] if path else "", lang)
    hint = field_hint(path, lang)
    if isinstance(value, dict):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object",
            "badge": localize_badge("Group", lang),
            "options": [],
        }
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            _walk_editor_meta(child, child_path, lang, into, public_config)
        return
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        into[path] = {
            "path": path,
            "label": label,
            "hint": hint,
            "kind": "object_list",
            "badge": localize_badge("List", lang),
            "options": [],
        }
        for index, child in enumerate(value):
            child_path = f"{path}.{index}"
            _walk_editor_meta(child, child_path, lang, into, public_config)
        return
    options = _field_options_for_config(path, public_config, lang)
    kind, badge = _field_kind(path, value, options)
    into[path] = {
        "path": path,
        "label": localize_label(path, path.split(".")[-1] if path else "", lang),
        "hint": hint,
        "kind": kind,
        "badge": localize_badge(badge, lang),
        "options": options,
    }


def build_editor_meta(public_config: dict[str, Any], lang: str) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {}
    for _, path in EDITOR_SECTION_SPECS:
        try:
            section_value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        filtered = _without_launcher_owned_fields(copy.deepcopy(section_value), path)
        if filtered in ({}, [], None):
            continue
        _walk_editor_meta(filtered, path, lang, meta, public_config)
    return meta


def build_editor_sections(public_config: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section_id, path in EDITOR_SECTION_SPECS:
        try:
            value = _lookup_path_value(public_config, path)
        except KeyError:
            continue
        filtered = _without_launcher_owned_fields(copy.deepcopy(value), path)
        if filtered in ({}, [], None):
            continue
        title = localize_section_label(path, path.split(".")[-1], lang)
        sections.append(
            {
                "id": section_id,
                "path": path,
                "title": title,
                "summary": field_hint(path, lang)
                or (
                    "结构化编辑并确认这个配置分区，再统一应用。"
                    if lang == "zh"
                    else "Edit and confirm this config block before the global apply step."
                ),
                "fieldCount": _count_leaf_fields(filtered),
            }
        )
    return sections
