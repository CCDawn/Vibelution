"""Closed personal-assistant preferences and existing-provider model additions.

Identity and tool authorization belong to the canonical PA wrapper. These
ordinary functions accept no config paths, provider edits, secrets or TOML.
"""

from __future__ import annotations

import copy
import re
import tomllib
from itertools import islice
from pathlib import Path
from typing import Any

from tools import pa_managed_writes as managed

_READABILITY = ["soft", "standard", "strong"]
_THEME_IMAGE = "workbench_theme.background_image_path"
_THEME_READABILITY = "workbench_theme.background_readability"
_MODEL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.~-]{0,95}$")
_PREFERENCE_KEYS = {
    "user_profile": {"display_name", "bio", "preferences", "avatar_preset"},
    "ui": {"language", "max_log_entries", "refresh_rate", "show_ascii_art", "show_welcome"},
}


def _failure(error: str, *, conflict: bool = False) -> dict:
    # Exceptions from config validation may contain config values or paths.
    return {
        "ok": False, "status": "blocked" if conflict else "error", "error": error,
        "message": {
            "invalid_input": "参数不在允许范围内，本次未写入。",
            "config_conflict": "配置已发生变化，本次未写入；请重新读取后再试。",
            "model_conflict": "模型键已指向其他上游模型，本次未覆盖。",
            "verification_failed": "未能核验配置写回结果，请先重新读取，勿自动重试。",
        }.get(error, "配置操作未完成，请检查配置状态；勿自动重试。"),
    }


def _config_path() -> Path:
    from config.paths import resolve_config_path

    return resolve_config_path()


def _read_config(path: Path) -> dict:
    # Read the authoritative operator document without workspace defaults,
    # discovery, migration, environment access, or derived-catalog writes.
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _at(config: dict, path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _avatar_options() -> list[str]:
    from config.editor_schema_data import USER_AVATAR_PRESET_OPTIONS

    return list(USER_AVATAR_PRESET_OPTIONS)


def _wallpaper(value: Any, config_path: Path) -> str:
    from core.web.services import theme_background_service as backgrounds

    if not isinstance(value, str) or len(value) > 240:
        raise ValueError("invalid wallpaper")
    value = value.strip().replace("\\", "/")
    if not value:
        return ""
    filename = backgrounds.theme_background_filename(value)
    if not filename:
        raise ValueError("invalid wallpaper")
    resolved = backgrounds.resolve_theme_background_file(filename).resolve(strict=True)
    operator_root = config_path.resolve().parent
    resource_root = (operator_root / backgrounds.THEME_BACKGROUND_DIR_NAME).resolve()
    bundle_root = backgrounds.BUNDLED_THEME_BACKGROUND_DIR.resolve()
    operator_resource = resource_root.parent == operator_root and resolved.parent == resource_root
    bundle_resource = filename in backgrounds.DEFAULT_THEME_BACKGROUND_FILENAMES and resolved.parent == bundle_root
    if not (operator_resource or bundle_resource) or not resolved.is_file():
        raise ValueError("wallpaper outside resource roots")
    return f"{backgrounds.THEME_BACKGROUND_DIR_NAME}/{filename}"


def _validate_updates(updates: Any, path: Path) -> list[tuple[tuple[str, ...], str, Any]]:
    if not isinstance(updates, list) or not 1 <= len(updates) <= managed._MAX_UPDATES:
        raise ValueError("invalid updates")
    normalized = []
    seen: set[tuple[str, ...]] = set()
    for item in updates:
        if not isinstance(item, dict) or set(item) != {"section", "key", "value"}:
            raise ValueError("invalid update shape")
        section, key, value = item["section"], item["key"], item["value"]
        if not isinstance(section, str) or not isinstance(key, str):
            raise ValueError("invalid key type")
        if section == "ui" and key in {_THEME_IMAGE, _THEME_READABILITY}:
            if key == _THEME_IMAGE:
                value = _wallpaper(value, path)
            elif not isinstance(value, str) or value not in _READABILITY:
                raise ValueError("invalid readability")
            table, leaf = ("ui", "workbench_theme"), key.split(".")[-1]
        else:
            if key not in _PREFERENCE_KEYS.get(section, set()):
                raise ValueError("not a preference")
            if section == "user_profile" and key in {"display_name", "bio"} and isinstance(value, str) and not value.strip():
                # Both native settings default to empty. Clearing a temporary
                # value must be as usable as setting it; keep avatar enum and
                # nonempty text validation in the existing validator below.
                table, leaf, value = (section,), key, ""
            else:
                # Keep the previously reviewed preference types and ranges.
                table, leaf, value = managed._validate_one_update(section, key, value)
            if table == ("user_profile",) and leaf == "avatar_preset" and value not in _avatar_options():
                raise ValueError("unknown avatar preset")
            if leaf == "preferences" and any(not isinstance(v, str) for v in item["value"]):
                raise ValueError("invalid preference type")
        target = (*table, leaf)
        if target in seen:
            raise ValueError("duplicate update target")
        seen.add(target)
        normalized.append((table, leaf, value))
    return normalized


def _transaction(path: Path, before: dict, mutate_text, operation: str) -> None:
    from config.operator_config_transaction import (
        apply_operator_config_transaction, prepare_operator_config_transaction,
    )
    from config.public_config import public_config_hash

    prepared = prepare_operator_config_transaction(
        operation_kind=operation,
        expected_base_hash=public_config_hash(before),
        mutate_text=mutate_text,
        config_path=path,
    )
    apply_operator_config_transaction(prepared)


def _transaction_failure(exc: Exception) -> dict:
    if isinstance(exc, ValueError) and any(marker in str(exc) for marker in (
        "stale config hash", "changed after transaction preparation",
    )):
        return _failure("config_conflict", conflict=True)
    return _failure("config_operation_failed")


def settings_update(updates: list) -> dict:
    """Atomically update only public profile/UI preferences; verify disk values."""
    try:
        path = _config_path()
        normalized = _validate_updates(updates, path)
    except (ValueError, OSError, TypeError):
        return _failure("invalid_input")
    except Exception:
        return _failure("config_operation_failed")
    try:
        before = _read_config(path)
        expected = copy.deepcopy(before)
        for table, key, value in normalized:
            node = expected
            for part in table:
                node = node.setdefault(part, {})
            node[key] = value

        def mutate(text: str) -> str:
            for table, key, value in normalized:
                text = managed._upsert_toml_key(text, table, key, managed._format_value(value))
            # A source-preserving patch must change precisely the intended data.
            # This also fails closed on multiline/quoted/inline table layouts
            # the existing PA scalar patcher cannot safely represent.
            if tomllib.loads(text) != expected:
                raise ValueError("preference patch changed unexpected data")
            return text

        _transaction(path, before, mutate, "pa_settings_update")
        persisted = _read_config(path)
        if any(_at(persisted, (*table, key)) != value for table, key, value in normalized):
            return _failure("verification_failed")
        return {
            "ok": True, "status": "applied", "verified": True,
            "updatedPaths": [".".join((*table, key)) for table, key, _ in normalized],
        }
    except Exception as exc:
        return _transaction_failure(exc)


def settings_catalog() -> dict:
    """Project public preference values/options, never provider/config payloads."""
    try:
        from core.web.services import theme_background_service as backgrounds

        path = _config_path()
        config = _read_config(path)
        specs = [
            ("user_profile", "display_name", "", {"maxLength": 120, "allowEmpty": True}),
            ("user_profile", "bio", "", {"maxLength": 2000, "allowEmpty": True}),
            ("user_profile", "preferences", [], {"maxItems": 50, "maxItemLength": 200}),
            ("user_profile", "avatar_preset", "default", {"options": _avatar_options()}),
            ("ui", "language", "zh", {"options": sorted(managed._UI_LANGUAGE_VALUES)}),
            ("ui", "max_log_entries", 100, {"min": 1, "max": 10000}),
            ("ui", "refresh_rate", 4, {"min": 1, "max": 120}),
            ("ui", "show_ascii_art", True, {}),
            ("ui", "show_welcome", True, {}),
            ("ui", _THEME_IMAGE, "", {}),
            ("ui", _THEME_READABILITY, "standard", {"options": _READABILITY}),
        ]
        settings = []
        for section, key, default, metadata in specs:
            value = _at(config, (section, *key.split(".")), default)
            # Existing config is not trusted to contain a bounded/type-safe value.
            try:
                if type(value) is not type(default) or value != default:
                    value = _validate_updates([{"section": section, "key": key, "value": value}], path)[0][2]
            except (ValueError, OSError, TypeError):
                value = None
            settings.append({"path": f"{section}.{key}", "section": section, "key": key, "value": value, **metadata})
        options = []
        candidates = [item["value"] for item in backgrounds.list_default_theme_background_options("zh")]
        resource_root = path.parent / backgrounds.THEME_BACKGROUND_DIR_NAME
        if resource_root.is_dir() and resource_root.resolve().parent == path.parent.resolve():
            candidates.extend(f"{backgrounds.THEME_BACKGROUND_DIR_NAME}/{item.name}" for item in islice(resource_root.iterdir(), 100))
        for candidate in dict.fromkeys(candidates):
            try:
                options.append(_wallpaper(candidate, path))
            except (ValueError, OSError):
                continue
            if len(options) >= 50:
                break
        return {"ok": True, "settings": settings, "wallpaperOptions": options}
    except Exception:
        return _failure("config_operation_failed")


def model_add(provider_id: str, upstream_id: str, model_key: str = "", label: str = "") -> dict:
    """Pin one model on an existing schema-v2 provider, without altering its route."""
    try:
        from config.llm_identity import make_model_key, validate_provider_id
        from config.llm_provider_registry import pin_llm_model
        from config.operator_config_transaction import append_toml_table

        if not all(isinstance(value, str) for value in (provider_id, upstream_id, model_key, label)):
            raise ValueError("invalid type")
        provider_id = validate_provider_id(provider_id)
        upstream_id, model_key, label = upstream_id.strip(), model_key.strip(), label.strip()
        if not upstream_id or len(upstream_id) > 256 or any(c.isspace() or ord(c) < 32 for c in upstream_id) or "://" in upstream_id:
            raise ValueError("invalid upstream")
        model_key = model_key or make_model_key(upstream_id)
        if not _MODEL_KEY.fullmatch(model_key) or len(label) > 120 or any(ord(c) < 32 for c in label):
            raise ValueError("invalid model key or label")
        path = _config_path()
        before = _read_config(path)
        if _at(before, ("llm", "schema_version")) != 2:
            raise ValueError("schema v2 required")
        provider = _at(before, ("llm", "providers", provider_id))
        if not isinstance(provider, dict):
            raise ValueError("unknown provider")
        models = provider.get("models", {})
        if not isinstance(models, dict):
            raise ValueError("invalid models")
        receipt = {"ok": True, "verified": True, "providerId": provider_id, "modelKey": model_key,
                   "modelRef": f"{provider_id}/{model_key}", "upstreamId": upstream_id}
        if model_key in models:
            if not isinstance(models[model_key], dict) or models[model_key].get("upstream_id") != upstream_id:
                return _failure("model_conflict", conflict=True)
            return {**receipt, "status": "existing"}
        expected = pin_llm_model(before, provider_id, upstream_id=upstream_id, model_key=model_key, label=label)
        table = ("llm", "providers", provider_id, "models", model_key)
        model = _at(expected, table)
    except (ValueError, OSError, TypeError):
        return _failure("invalid_input")
    except Exception:
        return _failure("config_operation_failed")
    try:
        def mutate(text: str) -> str:
            candidate = append_toml_table(text, table, model)
            if tomllib.loads(candidate) != expected:
                raise ValueError("model patch changed unexpected data")
            return candidate

        _transaction(path, before, mutate, "pa_model_add")
        if _at(_read_config(path), table) != model:
            return _failure("verification_failed")
        return {**receipt, "status": "added"}
    except Exception as exc:
        return _transaction_failure(exc)
