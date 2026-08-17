"""Deterministic, fail-closed migration from the public LLM v1 schema to v2."""

from __future__ import annotations

import copy
import hashlib
import hmac
import ipaddress
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

from config.effective_llm_graph import EffectiveLLMGraphBuilder, LLMGraphError
from config.llm_canonical_schema import (
    CanonicalLLMConfigError,
    validate_canonical_llm_payload,
)
from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.llm_identity import (
    make_model_key,
    make_model_ref,
    normalize_provider_endpoint,
)
from config.llm_provider_registry import suggest_provider_id
from config.llm_security import validate_llm_public_config
from config.paths import resolve_config_backup_dir
from config.public_config import (
    PROFILE_OVERRIDE_FIELDS,
    _config_edit_lock,
    _load_raw_public_config,
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
_INTERACTION_CONTRACT_VALUES = frozenset(
    {"basic_chat", "tool_chat", "reasoning_chat", "responses_agent"}
)


@dataclass(frozen=True)
class ModelConfigMigrationPreview:
    preview_id: str
    base_hash: str
    status: str
    providers: tuple[dict[str, Any], ...] = field(repr=False)
    model_ref_map: dict[str, str] = field(repr=False)
    reference_impact: dict[str, Any]
    conflicts: tuple[dict[str, Any], ...]
    proposed_public_config: dict[str, Any] = field(repr=False)
    migration_summary: dict[str, Any]
    rollback_plan_id: str


@dataclass(frozen=True)
class ArtifactResolution:
    model_id: str
    decision: str
    upstream_id: str = ""


class ModelConfigMigrationRollbackError(RuntimeError):
    """Raised when disk rollback succeeds but restored runtime reload fails."""


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


def _service_class(provider: dict[str, Any], base_url: str = "") -> str:
    kind = str(provider.get("kind") or "").strip().lower()
    if kind in {"ollama", "local", "local_runtime"}:
        return "local_runtime"
    host = (urlsplit(base_url).hostname or "").lower()
    if host == "localhost":
        return "local_runtime"
    try:
        if ipaddress.ip_address(host).is_loopback:
            return "local_runtime"
    except ValueError:
        pass
    if kind == "relay":
        return "relay"
    if kind in {"openrouter", "aggregator"}:
        return "aggregator"
    return "official_api" if kind in {"openai", "anthropic", "gemini"} else "relay"


_KIND_VENDORS = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google",
    "google": "google",
    "deepseek": "deepseek",
    "aliyun": "aliyun",
    "groq": "groq",
    "minimax": "minimax",
    "xiaomi": "xiaomi",
    "zhipu": "zhipu",
    "siliconflow": "siliconflow",
    "local": "local",
    "ollama": "ollama",
    "llamacpp": "llamacpp",
    "local_runtime": "local",
    "opencode": "opencode",
}
_GENERIC_HOST_TOKENS = {"api", "www", "open", "app", "cloud"}


def _vendor(base_url: str, provider: dict[str, Any]) -> str:
    explicit = str(provider.get("vendor") or "").strip().lower()
    if explicit:
        return explicit
    kind = str(provider.get("kind") or "").strip().lower()
    mapped = _KIND_VENDORS.get(kind)
    if mapped:
        return mapped
    if kind in {"openai_compatible", "openai-compatible"}:
        return "custom"
    host = urlsplit(base_url).hostname or "custom"
    parts = [part.lower() for part in host.split(".") if part]
    token = parts[0] if parts else "custom"
    if token in _GENERIC_HOST_TOKENS and len(parts) > 1:
        token = parts[1]
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
    legacy_protocol = str(entry.get("protocol") or "").strip().lower()
    interaction_contracts = {"basic_chat", "tool_chat", "reasoning_chat", "responses_agent"}
    interaction_contract = (
        legacy_protocol
        if legacy_protocol in interaction_contracts
        else str(entry.get("contract") or "tool_chat")
    )
    model_protocol = "" if legacy_protocol in interaction_contracts else legacy_protocol
    payload: dict[str, Any] = {
        "upstream_id": upstream_id,
        "label": str(entry.get("label") or upstream_id),
        "enabled": True,
        "wire_protocol": str(entry.get("transport") or "chat_completions"),
        "interaction_contract": interaction_contract,
        "model_protocol": model_protocol,
        "compatibility": copy.deepcopy(entry.get("compat") or {}),
        "defaults": defaults,
    }
    for field_name in (
        "prompt_cache",
        "thinking_type",
        "thinking_display",
        "reasoning_effort",
        "reasoning_state_field",
        "discovery_enabled",
        "strict_compatibility",
        "retry_policy",
    ):
        if field_name in entry:
            payload[field_name] = copy.deepcopy(entry[field_name])
    if "supports_image_input" in entry:
        payload["capabilities"] = {"image_input": bool(entry["supports_image_input"])}
    return payload


def _artifact_path_suspected(value: str) -> bool:
    candidate = value.strip()
    lowered = candidate.lower()
    return (
        lowered.endswith(_ARTIFACT_SUFFIXES)
        or lowered.startswith("file:")
        or bool(_WINDOWS_ABSOLUTE_RE.match(candidate))
        or candidate.startswith("\\\\")
        or candidate.startswith("/")
        or candidate.startswith(("~/", "~\\"))
        or candidate.startswith(("./", "../", ".\\", "..\\"))
    )


def _parse_artifact_resolutions(
    payload: list[dict[str, Any]] | None,
    *,
    model_ids: set[str],
) -> dict[str, ArtifactResolution]:
    if payload is None:
        return {}
    if not isinstance(payload, list):
        raise ValueError("artifact resolutions must be an array")
    parsed: dict[str, ArtifactResolution] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("artifact resolution entries must be objects")
        model_id = item.get("modelId")
        decision = item.get("decision")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("artifact resolution requires modelId")
        if model_id not in model_ids:
            raise ValueError("unknown artifact resolution modelId")
        if model_id in parsed:
            raise ValueError("duplicate artifact resolution modelId")
        if decision == "preserve_upstream_id":
            if set(item) != {"modelId", "decision"}:
                raise ValueError("invalid artifact resolution fields")
            parsed[model_id] = ArtifactResolution(model_id=model_id, decision=decision)
            continue
        if decision == "split_deployment_artifact":
            if set(item) != {"modelId", "decision", "upstreamId"}:
                raise ValueError("invalid artifact resolution fields")
            upstream_id = item.get("upstreamId")
            if not isinstance(upstream_id, str) or not upstream_id.strip():
                raise ValueError("split_deployment_artifact requires upstreamId")
            if _artifact_path_suspected(upstream_id):
                raise ValueError("split_deployment_artifact upstreamId must not be an artifact path")
            parsed[model_id] = ArtifactResolution(
                model_id=model_id,
                decision=decision,
                upstream_id=upstream_id.strip(),
            )
            continue
        if decision not in {"preserve_upstream_id", "split_deployment_artifact"}:
            raise ValueError("unknown artifact resolution decision")
    return parsed


def _model_behavior(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in {"label", "enabled", "upstream_id"}}


def _stable_diff_fields(left: Any, right: Any, *, prefix: str = "") -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        fields: list[str] = []
        for key in sorted(set(left) | set(right), key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(_stable_diff_fields(left.get(key), right.get(key), prefix=path))
        return fields
    return [prefix] if left != right and prefix else []


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


def preview_v1_to_v2(
    public_config: dict[str, Any],
    *,
    project_root: Path | str,
    artifact_resolutions: list[dict[str, Any]] | None = None,
) -> ModelConfigMigrationPreview:
    from config.public_config import _ensure_model_library_prompt_cache_defaults

    source = _ensure_model_library_prompt_cache_defaults(copy.deepcopy(public_config))
    llm = source.get("llm") if isinstance(source, dict) else None
    if not isinstance(llm, dict) or int(llm.get("schema_version") or 1) != 1:
        raise ValueError("migration preview requires llm schema v1")
    llm["schema_version"] = 1
    library = llm.get("model_library")
    if not isinstance(library, dict) or not library:
        raise ValueError("migration preview requires llm.model_library")

    resolutions = _parse_artifact_resolutions(
        artifact_resolutions,
        model_ids={str(model_id) for model_id in library},
    )

    conflicts: list[dict[str, Any]] = []
    typo_fields = {"protcols", "wire_protcol", "overides", "service_clas"}
    for model_id, raw_entry in library.items():
        if not isinstance(raw_entry, dict):
            continue
        for field_name in sorted(set(raw_entry).intersection(typo_fields)):
            conflicts.append(
                {
                    "code": "unknown_legacy_field",
                    "path": f"llm.model_library.{model_id}.{field_name}",
                }
            )
        raw_provider = raw_entry.get("provider")
        if isinstance(raw_provider, dict):
            for field_name in sorted(set(raw_provider).intersection(typo_fields)):
                conflicts.append(
                    {
                        "code": "unknown_legacy_field",
                        "path": f"llm.model_library.{model_id}.provider.{field_name}",
                    }
                )
    grouped: dict[
        tuple[str, str],
        list[tuple[str, dict[str, Any], dict[str, Any], str, str, str, str]],
    ] = {}
    consumed_resolution_ids: set[str] = set()
    secret_fingerprints: dict[tuple[str, str], str] = {}
    for model_id, raw_entry in sorted(library.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_entry, dict):
            conflicts.append({"code": "invalid_model_entry", "modelId": str(model_id)})
            continue
        provider = raw_entry.get("provider") if isinstance(raw_entry.get("provider"), dict) else {}
        legacy_upstream_id = str(raw_entry.get("model") or "")
        upstream_id = legacy_upstream_id.strip()
        artifact_path = ""
        if _artifact_path_suspected(legacy_upstream_id):
            resolution = resolutions.get(str(model_id))
            if resolution is None:
                conflicts.append({"code": "artifact_path_suspected", "modelId": str(model_id)})
                continue
            consumed_resolution_ids.add(str(model_id))
            artifact_path = legacy_upstream_id
            if resolution.decision == "preserve_upstream_id":
                provider_kind = str(provider.get("kind") or "").strip().lower()
                if provider_kind not in {"local", "local_runtime", "ollama"}:
                    raise ValueError("preserve_upstream_id requires a local provider")
                upstream_id = legacy_upstream_id
            else:
                upstream_id = resolution.upstream_id
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
        grouped.setdefault(key, []).append(
            (str(model_id), raw_entry, provider, upstream_id, adapter, driver, artifact_path)
        )
        if key[1] != "none":
            resolution = resolve_credential_ref(key[1])
            if resolution.secret:
                secret_fingerprints[key] = hmac.new(
                    _PROCESS_HMAC_KEY, resolution.secret.encode("utf-8"), hashlib.sha256
                ).hexdigest()

    if set(resolutions) != consumed_resolution_ids:
        raise ValueError("artifact resolution does not target an artifact path")

    provider_dicts: list[dict[str, Any]] = []
    provider_registry: dict[str, Any] = {}
    model_ref_map: dict[str, str] = {}
    group_provider_ids: dict[tuple[str, str], str] = {}
    existing_ids: list[str] = []
    model_defaults_seen: dict[tuple[str, str], dict[str, Any]] = {}
    for (base_url, credential_ref), rows in sorted(grouped.items(), key=lambda item: item[0]):
        first_id, _, first_provider, _, adapter, driver, _ = rows[0]
        service_class = _service_class(first_provider, base_url)
        vendor = _vendor(base_url, first_provider)
        classifications = [
            {
                "service_class": _service_class(row_provider, base_url),
                "vendor": _vendor(base_url, row_provider),
                "adapter": row_adapter,
                "driver": row_driver,
            }
            for _, _, row_provider, _, row_adapter, row_driver, _ in rows
        ]
        classification_fields = sorted(
            field_name
            for field_name in ("service_class", "vendor", "adapter", "driver")
            if len({classification[field_name] for classification in classifications}) > 1
        )
        if classification_fields:
            conflicts.append(
                {
                    "code": "provider_classification_conflict",
                    "modelIds": sorted(row[0] for row in rows),
                    "fields": classification_fields,
                }
            )
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
        artifact_rows = [row for row in rows if row[6]]
        artifact_paths = {row[6] for row in artifact_rows}
        if len(artifact_paths) > 1:
            conflicts.append(
                {
                    "code": "provider_artifact_path_conflict",
                    "modelIds": sorted(row[0] for row in artifact_rows),
                }
            )
        elif artifact_paths:
            provider["deployment"] = {
                "runtime_framework": "",
                "artifact_path": next(iter(artifact_paths)),
            }
        provider_id = suggest_provider_id(provider, existing_ids)
        existing_ids.append(provider_id)
        group_provider_ids[(base_url, credential_ref)] = provider_id
        for legacy_id, entry, _, upstream_id, _, _, artifact_path in rows:
            model_key = make_model_key(upstream_id)
            model_entry = entry
            legacy_label = str(entry.get("label") or "").strip()
            if artifact_path and upstream_id != artifact_path and _artifact_path_suspected(legacy_label):
                model_entry = copy.deepcopy(entry)
                model_entry["label"] = upstream_id
            model_payload = _model_payload(model_entry, upstream_id)
            seen_key = (provider_id, upstream_id)
            behavior = _model_behavior(model_payload)
            previous = model_defaults_seen.get(seen_key)
            if previous is not None and previous != behavior:
                differing = _stable_diff_fields(previous, behavior)
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
                            "proposedProviderId": group_provider_ids[left],
                        }
                    )

    proposed = copy.deepcopy(source)
    proposed_llm = proposed.setdefault("llm", {})
    proposed_llm.pop("model_library", None)
    proposed_llm["schema_version"] = 2
    proposed_llm["providers"] = provider_registry
    proposed_llm["model_aliases"] = dict(
        sorted((old, new) for old, new in model_ref_map.items() if old != new)
    )
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
                    profile.pop(field_name, None)
                    continue
                if field_name in profile:
                    overrides[field_name] = profile.pop(field_name)
            for stale_key in (
                "api_key",
                "api_key_env",
                "credential_ref",
                "provider",
                "model",
                "provider_id",
            ):
                profile.pop(stale_key, None)
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
        {
            "baseHash": base_hash,
            "providers": provider_dicts,
            "mapping": model_ref_map,
            "conflicts": conflicts,
            "artifactResolutions": [
                {
                    "modelId": resolution.model_id,
                    "decision": resolution.decision,
                    "upstreamId": resolution.upstream_id,
                }
                for resolution in sorted(resolutions.values(), key=lambda item: item.model_id)
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    preview_id = "preview-" + hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:24]
    blocking = [item for item in conflicts if item.get("severity") != "suggestion"]
    before_summary = {
        "providers": len(library),
        "models": len(library),
        "profiles": len(llm.get("profiles") or {}) if isinstance(llm.get("profiles"), dict) else 0,
    }
    after_summary = {
        "providers": len(provider_registry),
        "models": sum(len(provider.get("models") or {}) for provider in provider_registry.values()),
        "profiles": len(proposed_llm.get("profiles") or {}) if isinstance(proposed_llm.get("profiles"), dict) else 0,
    }
    rollback_plan_id = "rollback-plan-" + hashlib.sha256(
        f"{preview_id}\0{base_hash}".encode("utf-8")
    ).hexdigest()[:24]
    preview = ModelConfigMigrationPreview(
        preview_id=preview_id,
        base_hash=base_hash,
        status="NEEDS_REVIEW" if blocking else "READY",
        providers=tuple(provider_dicts),
        model_ref_map=model_ref_map,
        reference_impact=_reference_impact(model_ref_map, source, Path(project_root)),
        conflicts=tuple(conflicts),
        proposed_public_config=proposed,
        migration_summary={
            "before": before_summary,
            "after": after_summary,
            "blockingIssueCount": len(blocking),
        },
        rollback_plan_id=rollback_plan_id,
    )
    now = time.monotonic()
    _purge_expired_previews(now)
    _PREVIEWS[preview_id] = (now + _PREVIEW_TTL_SECONDS, preview)
    return preview


def preview_v2_canonical_repair(
    public_config: dict[str, Any],
    *,
    project_root: Path | str,
    model_ref_map: dict[str, str],
) -> ModelConfigMigrationPreview:
    """Preview a strict, transactional repair of an existing schema v2 config.

    The caller supplies explicit legacy-id to canonical-model-ref mappings so an
    ambiguous provider choice is never inferred from a model name alone.
    """

    source = copy.deepcopy(public_config)
    llm = source.get("llm") if isinstance(source, dict) else None
    if not isinstance(llm, dict) or int(llm.get("schema_version") or 1) != 2:
        raise ValueError("canonical repair preview requires llm schema v2")

    proposed = copy.deepcopy(source)
    proposed_llm = proposed["llm"]
    conflicts: list[dict[str, Any]] = []
    protocol_field_repairs = 0
    providers = proposed_llm.get("providers")
    if not isinstance(providers, dict):
        conflicts.append({"code": "provider_registry_missing", "path": "llm.providers"})
        providers = {}

    canonical_refs: set[str] = set()
    for provider_id, provider in sorted(providers.items(), key=lambda item: str(item[0])):
        if not isinstance(provider, dict):
            continue
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_key, model in sorted(models.items(), key=lambda item: str(item[0])):
            canonical_ref = make_model_ref(str(provider_id), str(model_key))
            canonical_refs.add(canonical_ref)
            if not isinstance(model, dict):
                continue
            model_protocol = str(model.get("model_protocol") or "").strip()
            if model_protocol not in _INTERACTION_CONTRACT_VALUES:
                continue
            path = f"llm.providers.{provider_id}.models.{model_key}"
            interaction_contract = str(model.get("interaction_contract") or "").strip()
            if interaction_contract and interaction_contract != model_protocol:
                conflicts.append(
                    {
                        "code": "interaction_contract_conflict",
                        "path": path,
                        "modelProtocol": model_protocol,
                        "interactionContract": interaction_contract,
                    }
                )
                continue
            model["interaction_contract"] = model_protocol
            model["model_protocol"] = ""
            protocol_field_repairs += 1

    normalized_mapping: dict[str, str] = {}
    for legacy_id, target_ref in sorted(model_ref_map.items(), key=lambda item: str(item[0])):
        legacy = str(legacy_id or "").strip()
        target = str(target_ref or "").strip()
        if not legacy or not target:
            conflicts.append({"code": "invalid_model_ref_mapping", "modelId": legacy})
            continue
        if target not in canonical_refs:
            conflicts.append(
                {
                    "code": "model_ref_target_not_found",
                    "modelId": legacy,
                    "targetModelRef": target,
                }
            )
            continue
        normalized_mapping[legacy] = target

    blocking = [item for item in conflicts if item.get("severity") != "suggestion"]
    if not blocking:
        try:
            canonical = validate_canonical_llm_payload(proposed_llm)
            EffectiveLLMGraphBuilder().build(canonical)
            build_effective_config(proposed)
            validate_llm_public_config(proposed)
        except CanonicalLLMConfigError as exc:
            conflicts.extend(
                {
                    "code": issue.code,
                    "path": f"llm.{issue.path}" if issue.path else "llm",
                    "message": issue.message,
                }
                for issue in exc.issues
            )
        except LLMGraphError as exc:
            conflicts.extend(
                {
                    "code": issue.code,
                    "subjectRef": issue.subject_ref,
                    "message": issue.message,
                }
                for issue in exc.issues
            )
        except ValueError as exc:
            conflicts.append(
                {
                    "code": "canonical_validation_failed",
                    "errorType": type(exc).__name__,
                }
            )

    reference_impact = _reference_impact(normalized_mapping, source, Path(project_root))
    blocking = [item for item in conflicts if item.get("severity") != "suggestion"]
    base_hash = public_config_hash(source)
    stable_payload = json.dumps(
        {
            "baseHash": base_hash,
            "mapping": normalized_mapping,
            "protocolFieldRepairs": protocol_field_repairs,
            "conflicts": conflicts,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    preview_id = "preview-v2-repair-" + hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:24]
    rollback_plan_id = "rollback-plan-" + hashlib.sha256(
        f"{preview_id}\0{base_hash}".encode("utf-8")
    ).hexdigest()[:24]
    preview = ModelConfigMigrationPreview(
        preview_id=preview_id,
        base_hash=base_hash,
        status="NEEDS_REVIEW" if blocking else "READY",
        providers=tuple(
            {
                "provider_id": str(provider_id),
                "model_count": len(provider.get("models") or {}) if isinstance(provider, dict) else 0,
            }
            for provider_id, provider in sorted(providers.items(), key=lambda item: str(item[0]))
        ),
        model_ref_map=normalized_mapping,
        reference_impact=reference_impact,
        conflicts=tuple(conflicts),
        proposed_public_config=proposed,
        migration_summary={
            "protocolFieldRepairCount": protocol_field_repairs,
            "referenceRewriteCount": reference_impact["liveReferenceCount"],
            "blockingIssueCount": len(blocking),
        },
        rollback_plan_id=rollback_plan_id,
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
        current = _load_raw_public_config(resolved_config)
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
            restored = _load_raw_public_config(resolved_config)
            rollback_reload_error: Exception | None = None
            restored_llm = restored.get("llm") if isinstance(restored, dict) else None
            restored_schema = (
                int(restored_llm.get("schema_version") or 2) if isinstance(restored_llm, dict) else 2
            )
            try:
                if restored_schema == 2:
                    build_effective_config(restored)
                    reload_config(str(resolved_config))
                else:
                    import config.settings as config_settings

                    config_settings._settings = None
                    config_settings._config_path = None
            except Exception as rollback_exc:
                rollback_reload_error = rollback_exc
            manifest.update(
                status="rolled_back",
                phase=phase,
                errorType=type(exc).__name__,
            )
            if rollback_reload_error is not None:
                manifest["rollbackErrorType"] = type(rollback_reload_error).__name__
            _write_manifest(manifest_path, manifest)
            if rollback_reload_error is not None:
                raise ModelConfigMigrationRollbackError(
                    "migration failed and restored config reload failed"
                ) from None
            raise


def apply_v2_canonical_repair(
    preview_id: str,
    *,
    expected_base_hash: str,
    config_path: Path | str,
    project_root: Path | str,
) -> dict[str, Any]:
    """Apply a READY schema v2 repair using the shared transactional writer."""

    return apply_v1_to_v2(
        preview_id,
        expected_base_hash=expected_base_hash,
        config_path=config_path,
        project_root=project_root,
    )


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
            restored = _load_raw_public_config(resolved_config)
            restored_llm = restored.get("llm") if isinstance(restored, dict) else None
            restored_schema = (
                int(restored_llm.get("schema_version") or 2) if isinstance(restored_llm, dict) else 2
            )
            if restored_schema == 2:
                build_effective_config(restored)
                reload_config(str(resolved_config))
            else:
                import config.settings as config_settings

                config_settings._settings = None
                config_settings._config_path = None
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


def rollback_v2_canonical_repair(
    migration_id: str,
    *,
    config_path: Path | str,
    project_root: Path | str,
    expected_current_hash: str = "",
) -> dict[str, Any]:
    """Roll back a schema v2 repair from its verified whole-file backups."""

    return rollback_v1_to_v2(
        migration_id,
        config_path=config_path,
        project_root=project_root,
        expected_current_hash=expected_current_hash,
    )


__all__ = [
    "ArtifactResolution",
    "ModelConfigMigrationPreview",
    "ModelConfigMigrationRollbackError",
    "apply_v1_to_v2",
    "apply_v2_canonical_repair",
    "normalize_legacy_service_root",
    "preview_v1_to_v2",
    "preview_v2_canonical_repair",
    "rollback_v1_to_v2",
    "rollback_v2_canonical_repair",
]
