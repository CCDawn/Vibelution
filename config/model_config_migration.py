"""Deterministic, fail-closed migration from the public LLM v1 schema to v2."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.llm_identity import make_model_key, make_model_ref, normalize_provider_endpoint
from config.llm_provider_registry import suggest_provider_id
from config.llm_security import validate_llm_public_config
from config.paths import resolve_config_backup_dir
from config.public_config import (
    PROFILE_OVERRIDE_FIELDS,
    _config_edit_lock,
    build_effective_config,
    load_public_config,
    public_config_hash,
)
from config.settings import reload_config
from config.toml_writer import dumps_public_config
from core.web.services.model_reference_service import (
    ModelReferenceRewritePlan,
    apply_model_reference_rewrite_plan,
    build_model_reference_rewrite_plan,
    scan_model_alias_usage,
    scan_model_references,
)


_PREVIEW_TTL_SECONDS = 15 * 60
_PREVIEW_LIMIT = 32
_PREVIEWS: dict[str, tuple[float, "ModelConfigMigrationPreview"]] = {}
_PROCESS_HMAC_KEY = os.urandom(32)
_ARTIFACT_SUFFIXES = (".gguf", ".safetensors", ".bin")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ModelConfigMigrationPreview:
    preview_id: str
    base_hash: str
    status: str
    providers: tuple[dict[str, Any], ...]
    model_ref_map: dict[str, str]
    reference_impact: dict[str, Any]
    conflicts: tuple[dict[str, Any], ...]
    proposed_public_config: dict[str, Any] = field(repr=False)


def normalize_legacy_service_root(base_url: str, *, adapter: str, wire_protocol: str) -> str:
    normalized = normalize_provider_endpoint(base_url)
    suffixes = {
        ("openai_compatible", "responses"): "/responses",
        ("openai_compatible", "chat_completions"): "/chat/completions",
        ("openai", "responses"): "/responses",
        ("openai", "chat_completions"): "/chat/completions",
        ("anthropic", "messages"): "/v1/messages",
    }
    suffix = suffixes.get((str(adapter).lower(), str(wire_protocol).lower()))
    if not suffix or not normalized.lower().endswith(suffix):
        return normalized
    return normalized[: -len(suffix)].rstrip("/")


def _legacy_credential_ref(model_id: str, entry: dict[str, Any], provider: dict[str, Any]) -> str:
    explicit = str(provider.get("credential_ref") or entry.get("credential_ref") or "").strip()
    if explicit:
        return canonicalize_credential_ref(explicit)
    env_name = str(provider.get("api_key_env") or entry.get("api_key_env") or "").strip()
    if env_name:
        return canonicalize_credential_ref(f"env:{env_name}")
    kind = str(provider.get("kind") or "").strip().lower()
    requires = kind not in {"local", "local_runtime", "ollama"} or bool(
        provider.get("requires_api_key", provider.get("requires_credential", False))
    )
    return "" if requires else "none"


def _adapter_and_driver(provider: dict[str, Any]) -> tuple[str, str]:
    kind = str(provider.get("kind") or "").strip().lower()
    compat = str(provider.get("compat_mode") or "").strip().lower()
    if "anthropic" in {kind, compat}:
        return "anthropic", "anthropic"
    if "gemini" in {kind, compat}:
        return "gemini", "gemini"
    if compat == "custom":
        return "custom", "openai"
    return "openai_compatible", "openai"


def _service_class(provider: dict[str, Any]) -> str:
    kind = str(provider.get("kind") or "").strip().lower()
    if kind == "relay":
        return "relay"
    if kind in {"ollama", "local", "local_runtime"}:
        return "local_runtime"
    if kind in {"openrouter", "aggregator"}:
        return "aggregator"
    return "official_api" if kind in {"openai", "anthropic", "gemini"} else "relay"


def _vendor(base_url: str, provider: dict[str, Any]) -> str:
    explicit = str(provider.get("vendor") or "").strip().lower()
    if explicit:
        return explicit
    host = urlsplit(base_url).hostname or "custom"
    token = host.split(".")[0].lower()
    return re.sub(r"[^a-z0-9_-]+", "_", token).strip("_") or "custom"


def _model_payload(entry: dict[str, Any], upstream_id: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    for source, target in (
        ("temperature", "temperature"),
        ("max_output_tokens", "max_output_tokens"),
        ("timeout", "timeout"),
        ("connect_timeout", "connect_timeout"),
        ("streaming", "streaming"),
        ("tool_calling_mode", "tool_calling_mode"),
    ):
        if source in entry:
            defaults[target] = copy.deepcopy(entry[source])
    payload: dict[str, Any] = {
        "upstream_id": upstream_id,
        "label": str(entry.get("label") or upstream_id),
        "enabled": True,
        "wire_protocol": str(entry.get("transport") or "chat_completions"),
        "interaction_contract": str(entry.get("contract") or "tool_chat"),
        "model_protocol": str(entry.get("protocol") or ""),
        "compatibility": copy.deepcopy(entry.get("compat") or {}),
        "defaults": defaults,
    }
    for field_name in ("prompt_cache", "thinking_type", "thinking_display", "reasoning_effort"):
        if field_name in entry:
            payload[field_name] = copy.deepcopy(entry[field_name])
    if "supports_image_input" in entry:
        payload["capabilities"] = {"image_input": bool(entry["supports_image_input"])}
    return payload


def _artifact_path_suspected(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.endswith(_ARTIFACT_SUFFIXES) or bool(_WINDOWS_ABSOLUTE_RE.match(value.strip()))


def _model_behavior(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"label", "enabled", "upstream_id"}}


def _purge_expired_previews(now: float) -> None:
    for preview_id, (expires_at, _) in list(_PREVIEWS.items()):
        if expires_at <= now:
            _PREVIEWS.pop(preview_id, None)
    while len(_PREVIEWS) >= _PREVIEW_LIMIT:
        oldest = min(_PREVIEWS, key=lambda key: _PREVIEWS[key][0])
        _PREVIEWS.pop(oldest, None)


def _reference_impact(mapping: dict[str, str], public_config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    items = [
        scan_model_references(model_id, public_config=public_config, project_root=project_root)
        for model_id in sorted(mapping)
    ]
    return {
        "models": items,
        "liveReferenceCount": sum(int(item["liveReferenceCount"]) for item in items),
        "historicalReferenceCount": sum(int(item["historicalReferenceCount"]) for item in items),
    }


def preview_v1_to_v2(public_config: dict[str, Any], *, project_root: Path | str) -> ModelConfigMigrationPreview:
    source = copy.deepcopy(public_config)
    llm = source.get("llm") if isinstance(source, dict) else None
    if not isinstance(llm, dict) or int(llm.get("schema_version") or 1) != 1:
        raise ValueError("migration preview requires llm schema v1")
    library = llm.get("model_library")
    if not isinstance(library, dict) or not library:
        raise ValueError("migration preview requires llm.model_library")

    conflicts: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any], dict[str, Any], str, str, str]]] = {}
    secret_fingerprints: dict[tuple[str, str], str] = {}
    for model_id, raw_entry in sorted(library.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_entry, dict):
            conflicts.append({"code": "invalid_model_entry", "modelId": str(model_id)})
            continue
        provider = raw_entry.get("provider") if isinstance(raw_entry.get("provider"), dict) else {}
        upstream_id = str(raw_entry.get("model") or "").strip()
        if _artifact_path_suspected(upstream_id):
            conflicts.append({"code": "artifact_path_suspected", "modelId": str(model_id)})
            continue
        adapter, driver = _adapter_and_driver(provider)
        wire_protocol = str(raw_entry.get("transport") or "chat_completions").strip().lower()
        base_url = normalize_legacy_service_root(
            str(provider.get("base_url") or ""), adapter=adapter, wire_protocol=wire_protocol
        )
        credential_ref = _legacy_credential_ref(str(model_id), raw_entry, provider)
        if not credential_ref:
            conflicts.append({"code": "credential_source_missing", "modelId": str(model_id)})
            credential_ref = "none"
        key = (base_url, canonicalize_credential_ref(credential_ref))
        grouped.setdefault(key, []).append((str(model_id), raw_entry, provider, upstream_id, adapter, driver))
        if key[1] != "none":
            resolution = resolve_credential_ref(key[1])
            if resolution.secret:
                secret_fingerprints[key] = hmac.new(
                    _PROCESS_HMAC_KEY, resolution.secret.encode("utf-8"), hashlib.sha256
                ).hexdigest()

    provider_dicts: list[dict[str, Any]] = []
    provider_registry: dict[str, Any] = {}
    model_ref_map: dict[str, str] = {}
    existing_ids: list[str] = []
    model_defaults_seen: dict[tuple[str, str], dict[str, Any]] = {}
    for (base_url, credential_ref), rows in sorted(grouped.items(), key=lambda item: item[0]):
        first_id, _, first_provider, _, adapter, driver = rows[0]
        service_class = _service_class(first_provider)
        vendor = _vendor(base_url, first_provider)
        protocol_values = sorted({str(row[1].get("transport") or "chat_completions") for row in rows})
        provider = {
            "label": str(first_provider.get("label") or vendor.replace("_", " ").title()),
            "service_class": service_class,
            "vendor": vendor,
            "driver": driver,
            "base_url": base_url,
            "auth_kind": "none" if credential_ref == "none" else "api_key",
            "credential_ref": credential_ref,
            "requires_credential": credential_ref != "none",
            "protocols": {"default": protocol_values[0], "allowed": protocol_values},
            "discovery": {"mode": "manual", "adapter": adapter, "cache_ttl_seconds": 0},
            "models": {},
        }
        provider_id = suggest_provider_id(provider, existing_ids)
        existing_ids.append(provider_id)
        for legacy_id, entry, _, upstream_id, _, _ in rows:
            model_key = make_model_key(upstream_id)
            model_payload = _model_payload(entry, upstream_id)
            seen_key = (provider_id, upstream_id)
            behavior = _model_behavior(model_payload)
            previous = model_defaults_seen.get(seen_key)
            if previous is not None and previous != behavior:
                differing = sorted(
                    key for key in set(previous) | set(behavior) if previous.get(key) != behavior.get(key)
                )
                conflicts.append(
                    {"code": "model_defaults_conflict", "modelId": legacy_id, "fields": differing}
                )
            else:
                model_defaults_seen[seen_key] = copy.deepcopy(behavior)
            provider["models"].setdefault(model_key, model_payload)
            model_ref_map[legacy_id] = make_model_ref(provider_id, model_key)
        provider_registry[provider_id] = provider
        provider_dicts.append(
            {
                "provider_id": provider_id,
                **copy.deepcopy(provider),
                "credential_state": resolve_credential_ref(credential_ref).state,
                "source_model_id": first_id,
            }
        )

    grouped_by_endpoint: dict[str, list[tuple[tuple[str, str], str]]] = {}
    for key, digest in secret_fingerprints.items():
        grouped_by_endpoint.setdefault(key[0], []).append((key, digest))
    for endpoint, values in grouped_by_endpoint.items():
        for index, (left, left_digest) in enumerate(values):
            for right, right_digest in values[index + 1 :]:
                if left_digest == right_digest and left[1] != right[1]:
                    conflicts.append(
                        {
                            "code": "same_secret_different_reference",
                            "severity": "suggestion",
                            "endpoint": endpoint,
                            "credentialReferences": [left[1], right[1]],
                        }
                    )

    proposed = copy.deepcopy(source)
    proposed_llm = proposed.setdefault("llm", {})
    proposed_llm.pop("model_library", None)
    proposed_llm["schema_version"] = 2
    proposed_llm["providers"] = provider_registry
    proposed_llm["model_aliases"] = dict(sorted(model_ref_map.items()))
    profiles = proposed_llm.get("profiles")
    if isinstance(profiles, dict):
        for profile in profiles.values():
            if not isinstance(profile, dict):
                continue
            old_ref = str(profile.get("model_ref") or "")
            if old_ref in model_ref_map:
                profile["model_ref"] = model_ref_map[old_ref]
            overrides = profile.get("overrides") if isinstance(profile.get("overrides"), dict) else {}
            for field_name in PROFILE_OVERRIDE_FIELDS:
                if field_name in {
                    "api_key_env",
                    "capability_status",
                    "capability_source",
                    "capability_checked_at",
                    "capability_error",
                }:
                    continue
                if field_name in profile:
                    overrides[field_name] = profile.pop(field_name)
            profile["overrides"] = overrides
    for section, field_name in (("tools", "default_model_ref"), ("git", "commit_message_model_ref")):
        if section == "tools":
            owner = proposed.get("tools", {}).get("image2", {}) if isinstance(proposed.get("tools"), dict) else {}
        else:
            owner = proposed.get("git", {})
        if isinstance(owner, dict):
            old_ref = str(owner.get(field_name) or "")
            if old_ref in model_ref_map:
                owner[field_name] = model_ref_map[old_ref]

    base_hash = public_config_hash(source)
    stable_payload = json.dumps(
        {"baseHash": base_hash, "providers": provider_dicts, "mapping": model_ref_map, "conflicts": conflicts},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    preview_id = "preview-" + hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:24]
    blocking = [item for item in conflicts if item.get("severity") != "suggestion"]
    preview = ModelConfigMigrationPreview(
        preview_id=preview_id,
        base_hash=base_hash,
        status="NEEDS_REVIEW" if blocking else "READY",
        providers=tuple(provider_dicts),
        model_ref_map=model_ref_map,
        reference_impact=_reference_impact(model_ref_map, source, Path(project_root)),
        conflicts=tuple(conflicts),
        proposed_public_config=proposed,
    )
    now = time.monotonic()
    _purge_expired_previews(now)
    _PREVIEWS[preview_id] = (now + _PREVIEW_TTL_SECONDS, preview)
    return preview


def _preview_for_apply(preview_id: str) -> ModelConfigMigrationPreview:
    now = time.monotonic()
    _purge_expired_previews(now)
    stored = _PREVIEWS.get(str(preview_id or "").strip())
    if stored is None:
        raise ValueError("unknown or expired migration preview")
    return stored[1]


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


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    _strict_atomic_write(
        path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _manifest_files(
    migration_id: str,
    config_path: Path,
    config_before: bytes,
    config_after: bytes,
    plan: ModelReferenceRewritePlan,
    backup_dir: Path,
) -> tuple[list[dict[str, Any]], list[tuple[Path, bytes, bytes]]]:
    payloads = [(config_path, config_before, config_after)] + [
        (item.path, item.before_bytes, item.after_bytes) for item in plan.file_rewrites
    ]
    records: list[dict[str, Any]] = []
    for index, (target, before, after) in enumerate(payloads):
        before_name = f"llm-config-migration-{migration_id}-{index:03d}.before.bin"
        after_name = f"llm-config-migration-{migration_id}-{index:03d}.after.bin"
        _strict_atomic_write(backup_dir / before_name, before)
        _strict_atomic_write(backup_dir / after_name, after)
        records.append(
            {
                "target": str(target.resolve()),
                "beforeBackup": before_name,
                "afterBackup": after_name,
                "beforeSha256": _sha256(before),
                "afterSha256": _sha256(after),
            }
        )
    return records, payloads


def apply_v1_to_v2(
    preview_id: str,
    *,
    expected_base_hash: str,
    config_path: Path | str,
    project_root: Path | str,
) -> dict[str, Any]:
    preview = _preview_for_apply(preview_id)
    resolved_config = Path(config_path).resolve()
    expected = str(expected_base_hash or "").strip()
    if not expected:
        raise ValueError("expected base hash is required")
    if preview.status != "READY":
        raise ValueError("migration preview has unresolved conflicts")
    migration_id = "migration-" + uuid.uuid4().hex
    backup_dir = resolve_config_backup_dir(resolved_config)
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = backup_dir / f"llm-config-migration-{migration_id}.json"
    manifest: dict[str, Any] | None = None
    phase = "preflight"
    with _config_edit_lock(resolved_config):
        current = load_public_config(resolved_config)
        current_hash = public_config_hash(current)
        if current_hash != preview.base_hash or current_hash != expected:
            raise ValueError("stale config hash")
        plan = build_model_reference_rewrite_plan(
            preview.model_ref_map,
            public_config=preview.proposed_public_config,
            project_root=project_root,
        )
        config_before = resolved_config.read_bytes()
        config_after = dumps_public_config(plan.public_config).encode("utf-8")
        records, payloads = _manifest_files(
            migration_id, resolved_config, config_before, config_after, plan, backup_dir
        )
        manifest = {
            "schemaVersion": 1,
            "migrationId": migration_id,
            "previewId": preview.preview_id,
            "status": "prepared",
            "baseHash": preview.base_hash,
            "appliedHash": public_config_hash(plan.public_config),
            "files": records,
            "phase": "prepared",
        }
        _write_manifest(manifest_path, manifest)
        written_payloads: list[tuple[Path, bytes, bytes]] = []
        try:
            phase = "write_config"
            _strict_atomic_write(resolved_config, config_after)
            written_payloads.append(payloads[0])
            phase = "write_references"
            apply_model_reference_rewrite_plan(plan)
            written_payloads.extend(payloads[1:])
            phase = "validate_config"
            persisted = load_public_config(resolved_config)
            build_effective_config(persisted)
            validate_llm_public_config(persisted)
            phase = "reload_config"
            reload_config(str(resolved_config))
            phase = "scan_alias_usage"
            alias_usage = scan_model_alias_usage(persisted, project_root=project_root)
            if not alias_usage["canRemoveAliases"]:
                raise ValueError("live model alias references remain after migration")
            manifest.update(status="applied", phase="applied")
            _write_manifest(manifest_path, manifest)
            _PREVIEWS.pop(preview.preview_id, None)
            return {
                "migrationId": migration_id,
                "status": "applied",
                "hash": public_config_hash(persisted),
                "modelAliasUsage": alias_usage,
                "updatedReferenceCount": sum(len(item.references) for item in plan.file_rewrites),
            }
        except Exception as exc:
            for target, before, _ in reversed(written_payloads):
                _strict_atomic_write(target, before)
            restored = load_public_config(resolved_config)
            build_effective_config(restored)
            manifest.update(
                status="rolled_back",
                phase=phase,
                errorType=type(exc).__name__,
            )
            _write_manifest(manifest_path, manifest)
            raise


def rollback_v1_to_v2(
    migration_id: str,
    *,
    config_path: Path | str,
    project_root: Path | str,
    expected_current_hash: str = "",
) -> dict[str, Any]:
    del project_root
    resolved_config = Path(config_path).resolve()
    backup_dir = resolve_config_backup_dir(resolved_config)
    manifest_path = backup_dir / f"llm-config-migration-{migration_id}.json"
    with _config_edit_lock(resolved_config):
        if not manifest_path.exists():
            raise ValueError("unknown migration id")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("migrationId") != migration_id or manifest.get("status") != "applied":
            raise ValueError("migration is not rollback eligible")
        current = load_public_config(resolved_config)
        current_hash = public_config_hash(current)
        required_hash = str(expected_current_hash or manifest.get("appliedHash") or "").strip()
        if not required_hash or current_hash != required_hash:
            raise ValueError("stale config hash")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("invalid migration manifest")
        targets: list[tuple[Path, bytes, bytes]] = []
        for record in files:
            if not isinstance(record, dict):
                raise ValueError("invalid migration manifest")
            target = Path(str(record.get("target") or ""))
            before = (backup_dir / str(record.get("beforeBackup") or "")).read_bytes()
            after = (backup_dir / str(record.get("afterBackup") or "")).read_bytes()
            if _sha256(before) != record.get("beforeSha256") or _sha256(after) != record.get("afterSha256"):
                raise ValueError("migration backup hash mismatch")
            if not target.exists() or _sha256(target.read_bytes()) != record.get("afterSha256"):
                raise ValueError("migration target hash drift")
            targets.append((target, before, after))
        written: list[tuple[Path, bytes]] = []
        try:
            for target, before, after in targets:
                _strict_atomic_write(target, before)
                written.append((target, after))
            restored = load_public_config(resolved_config)
            build_effective_config(restored)
            reload_config(str(resolved_config))
        except Exception:
            for target, after in reversed(written):
                _strict_atomic_write(target, after)
            raise
        manifest.update(status="rolled_back", phase="manual_rollback")
        _write_manifest(manifest_path, manifest)
    return {
        "migrationId": migration_id,
        "status": "rolled_back",
        "hash": public_config_hash(restored),
    }


__all__ = [
    "ModelConfigMigrationPreview",
    "apply_v1_to_v2",
    "normalize_legacy_service_root",
    "preview_v1_to_v2",
    "rollback_v1_to_v2",
]
