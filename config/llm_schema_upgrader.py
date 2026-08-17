"""One-shot, fail-closed upgrade of persisted LLM config to canonical schema v2.

Runtime loaders consume only schema v2. Identifiable v1 / role_bindings files are
upgraded atomically; unsafe inputs raise without replacing the original bytes.
This module never logs secret values.
"""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from config.toml_writer import dumps_public_config

_PROFILE_LIBRARY_FIELDS = (
    "transport",
    "contract",
    "timeout",
    "connect_timeout",
    "temperature",
    "max_output_tokens",
    "label",
)


class LLMSchemaUpgradeError(ValueError):
    """Persisted LLM config cannot be safely upgraded to the canonical schema."""

    def __init__(self, reason: str, *, detail: str = "") -> None:
        self.reason = str(reason or "unsafe_llm_schema").strip() or "unsafe_llm_schema"
        self.detail = str(detail or "").strip()
        message = self.reason if not self.detail else f"{self.reason}: {self.detail}"
        super().__init__(message)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def convert_legacy_llm_config(
    public_config: dict[str, Any],
    *,
    project_root: Path | str | None = None,
    allow_missing_credentials: bool = False,
) -> dict[str, Any]:
    proposed, _action = _proposed_canonical_config(
        public_config,
        project_root=project_root,
        allow_missing_credentials=allow_missing_credentials,
    )
    return proposed


def llm_config_needs_upgrade(public_config: dict[str, Any] | None) -> bool:
    if not isinstance(public_config, dict):
        return False
    llm = public_config.get("llm")
    if not isinstance(llm, dict):
        return False
    if "role_bindings" in llm:
        return True
    return _llm_schema_version(llm) == 1


def build_effective_config(public_config: dict[str, Any]) -> Any:
    """Patch point for tests; lazily imports the runtime builder to avoid cycles."""

    from config.public_config import build_effective_config as _impl

    return _impl(public_config)


def upgrade_persisted_llm_schema_if_needed(
    config_path: Path | str,
    *,
    project_root: Path | str | None = None,
) -> dict[str, str]:
    """Upgrade a persisted public config file to canonical LLM schema v2.

    Returns a small status dict. Does not rewrite an already-canonical file.
    On any failure the original file bytes are left in place or restored.
    """

    path = Path(config_path)
    if not path.is_file():
        return {"status": "missing", "reason": "config_file_missing"}
    if "tests" in path.parts and "fixtures" in path.parts:
        return {"status": "skipped", "reason": "test_fixture_not_mutated"}

    original = path.read_bytes()
    try:
        parsed = tomllib.loads(original.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LLMSchemaUpgradeError("corrupt_toml") from exc

    if not isinstance(parsed, dict):
        raise LLMSchemaUpgradeError("corrupt_toml")

    llm = parsed.get("llm")
    if llm is None:
        return {"status": "already_canonical", "reason": "no_llm_section", "sha256": _sha256(original)}
    if not isinstance(llm, dict):
        raise LLMSchemaUpgradeError("invalid_llm_section")

    try:
        proposed, action = _proposed_canonical_config(parsed, project_root=project_root)
    except LLMSchemaUpgradeError:
        if path.read_bytes() != original:
            _strict_atomic_write(path, original)
        raise
    if action == "already_canonical":
        return {"status": "already_canonical", "reason": "schema_v2", "sha256": _sha256(original)}

    from config.llm_security import validate_llm_public_config
    from config.public_config import _config_edit_lock

    build_effective_config(proposed)
    payload = dumps_public_config(proposed).encode("utf-8")
    with _config_edit_lock(path):
        current = path.read_bytes()
        if current != original:
            raise LLMSchemaUpgradeError("stale_config_bytes")
        try:
            _strict_atomic_write(path, payload)
            persisted = tomllib.loads(path.read_text(encoding="utf-8"))
            _assert_canonical_llm(persisted.get("llm"))
            build_effective_config(persisted)
            validate_llm_public_config(persisted)
        except Exception as exc:
            _strict_atomic_write(path, original)
            if isinstance(exc, LLMSchemaUpgradeError):
                raise
            raise LLMSchemaUpgradeError("write_failed_restored", detail=type(exc).__name__) from exc
    return {
        "status": "upgraded",
        "reason": action,
        "sha256": _sha256(path.read_bytes()),
        "beforeSha256": _sha256(original),
    }


def _proposed_canonical_config(
    public_config: dict[str, Any],
    *,
    project_root: Path | str | None = None,
    allow_missing_credentials: bool = False,
) -> tuple[dict[str, Any], str]:
    if not isinstance(public_config, dict):
        raise LLMSchemaUpgradeError("invalid_public_config")
    working = copy.deepcopy(public_config)
    llm = working.get("llm")
    if not isinstance(llm, dict):
        raise LLMSchemaUpgradeError("invalid_llm_section")
    had_role_bindings = "role_bindings" in llm
    schema_version = _llm_schema_version(llm)
    if schema_version == 2 and not had_role_bindings:
        return working, "already_canonical"

    _fold_role_bindings(llm)
    schema_version = _llm_schema_version(llm)

    if schema_version == 2:
        _assert_canonical_llm(llm)
        return working, "role_bindings_folded" if had_role_bindings else "already_canonical"

    if schema_version != 1:
        raise LLMSchemaUpgradeError("unsupported_schema_version")

    from config.model_config_migration import preview_v1_to_v2
    from config.public_config import (
        _ensure_model_library_prompt_cache_defaults,
        _repair_legacy_model_library_shape,
    )

    repaired = _ensure_model_library_prompt_cache_defaults(
        _repair_legacy_model_library_shape(working)
    )
    repaired_llm = repaired.get("llm")
    if not isinstance(repaired_llm, dict):
        raise LLMSchemaUpgradeError("invalid_llm_section")
    _synthesize_v1_model_library(repaired_llm)
    repaired = _ensure_model_library_prompt_cache_defaults(repaired)
    repaired_llm = repaired.get("llm")
    if not isinstance(repaired_llm, dict):
        raise LLMSchemaUpgradeError("invalid_llm_section")
    library = repaired_llm.get("model_library")
    if not isinstance(library, dict) or not library:
        raise LLMSchemaUpgradeError("v1_model_library_missing")
    repaired_llm["schema_version"] = 1
    if allow_missing_credentials:
        _fill_missing_v1_credentials(repaired_llm)
    preview = preview_v1_to_v2(repaired, project_root=Path(project_root or "."))
    if preview.status != "READY":
        codes = sorted(
            {
                str(item.get("code") or "unresolved_conflict")
                for item in preview.conflicts
                if item.get("severity") != "suggestion"
            }
        )
        raise LLMSchemaUpgradeError(
            "unresolved_conflicts",
            detail=",".join(codes) or "NEEDS_REVIEW",
        )
    proposed = copy.deepcopy(preview.proposed_public_config)
    proposed_llm = proposed.get("llm")
    if not isinstance(proposed_llm, dict):
        raise LLMSchemaUpgradeError("unsafe_upgrade")
    _fold_role_bindings(proposed_llm)
    _assert_canonical_llm(proposed_llm)
    return proposed, "v1_to_v2"


def _llm_schema_version(llm: dict[str, Any]) -> int:
    raw = llm.get("schema_version")
    if raw is None:
        if _looks_like_v1(llm):
            return 1
        return 2
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise LLMSchemaUpgradeError("unsupported_schema_version") from exc


def _looks_like_v1(llm: dict[str, Any]) -> bool:
    library = llm.get("model_library")
    if isinstance(library, dict):
        for item in library.values():
            if isinstance(item, dict) and isinstance(item.get("provider"), dict):
                return True
    providers = llm.get("providers")
    if isinstance(providers, dict):
        for item in providers.values():
            if isinstance(item, dict) and "kind" in item and "models" not in item:
                return True
    return False


def _fold_role_bindings(llm: dict[str, Any]) -> None:
    if "role_bindings" not in llm:
        return
    bindings = llm.pop("role_bindings")
    if bindings is None:
        return
    if not isinstance(bindings, dict):
        raise LLMSchemaUpgradeError("role_bindings_invalid")
    profiles = llm.get("profiles")
    if not isinstance(profiles, dict):
        raise LLMSchemaUpgradeError("role_bindings_profiles_missing")
    for role, source_profile_id in bindings.items():
        role_id = str(role or "").strip()
        source_id = str(source_profile_id or "").strip()
        if not role_id or not source_id:
            raise LLMSchemaUpgradeError("role_bindings_empty_id")
        source_profile = profiles.get(source_id)
        if not isinstance(source_profile, dict):
            raise LLMSchemaUpgradeError("role_bindings_source_missing")
        if role_id == source_id and role_id in profiles:
            continue
        migrated = copy.deepcopy(source_profile)
        migrated["profile_id"] = role_id
        profiles[role_id] = migrated


def _synthesize_v1_model_library(llm: dict[str, Any]) -> None:
    library = llm.get("model_library")
    if not isinstance(library, dict):
        library = {}
        llm["model_library"] = library
    providers = llm.get("providers") if isinstance(llm.get("providers"), dict) else {}

    for item in library.values():
        if not isinstance(item, dict) or isinstance(item.get("provider"), dict):
            continue
        provider_id = str(item.get("provider_id") or "").strip()
        provider_payload = providers.get(provider_id)
        if provider_id and isinstance(provider_payload, dict):
            item["provider"] = copy.deepcopy(provider_payload)

    profiles = llm.get("profiles") if isinstance(llm.get("profiles"), dict) else {}
    for profile_id, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        model_ref = str(profile.get("model_ref") or "").strip()
        if model_ref and isinstance(library.get(model_ref), dict):
            item = library[model_ref]
            if not isinstance(item.get("provider"), dict):
                provider_id = str(item.get("provider_id") or profile.get("provider_id") or "").strip()
                provider_payload = providers.get(provider_id)
                if provider_id and isinstance(provider_payload, dict):
                    item["provider"] = copy.deepcopy(provider_payload)
            continue
        provider_payload = profile.get("provider") if isinstance(profile.get("provider"), dict) else None
        provider_id = str(profile.get("provider_id") or "").strip()
        if provider_payload is None and provider_id:
            raw_provider = providers.get(provider_id)
            if isinstance(raw_provider, dict):
                provider_payload = copy.deepcopy(raw_provider)
        model = str(profile.get("model") or "").strip()
        if not isinstance(provider_payload, dict) or not model:
            continue
        new_id = model_ref or str(profile_id)
        entry: dict[str, Any] = {
            "model": model,
            "label": str(profile.get("label") or model),
            "provider": copy.deepcopy(provider_payload),
        }
        for field_name in _PROFILE_LIBRARY_FIELDS:
            if field_name in profile and field_name not in {"label"}:
                entry[field_name] = copy.deepcopy(profile[field_name])
        library[new_id] = entry
        profile["model_ref"] = new_id


def _fill_missing_v1_credentials(llm: dict[str, Any]) -> None:
    library = llm.get("model_library")
    if not isinstance(library, dict):
        return
    for item in library.values():
        if not isinstance(item, dict):
            continue
        provider = item.get("provider") if isinstance(item.get("provider"), dict) else {}
        has_ref = bool(str(item.get("credential_ref") or provider.get("credential_ref") or "").strip())
        has_env = bool(str(item.get("api_key_env") or provider.get("api_key_env") or "").strip())
        has_key = bool(str(item.get("api_key") or provider.get("api_key") or "").strip())
        if has_ref or has_env or has_key:
            continue
        provider = dict(provider)
        provider["credential_ref"] = "none"
        provider["requires_api_key"] = False
        item["provider"] = provider


def _assert_canonical_llm(llm: Any) -> None:
    if not isinstance(llm, dict):
        raise LLMSchemaUpgradeError("invalid_llm_section")
    if "role_bindings" in llm:
        raise LLMSchemaUpgradeError("role_bindings_not_canonical")
    try:
        schema_version = int(llm.get("schema_version") or 2)
    except (TypeError, ValueError) as exc:
        raise LLMSchemaUpgradeError("unsupported_schema_version") from exc
    if schema_version != 2:
        raise LLMSchemaUpgradeError("runtime_requires_schema_v2")
    providers = llm.get("providers")
    profiles = llm.get("profiles")
    if not isinstance(providers, dict) or not providers:
        raise LLMSchemaUpgradeError("canonical_providers_missing")
    if not isinstance(profiles, dict) or not profiles:
        raise LLMSchemaUpgradeError("canonical_profiles_missing")
