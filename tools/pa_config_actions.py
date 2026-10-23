"""Closed assistant config actions; secrets and full workspaces stay server-side.

The caller owns canonical PA identity and native approval. Sensitive actions
also require ``governed=True`` here; no model argument can supply that flag.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import re
import tomllib
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.json_schema import SkipJsonSchema


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Catalog(Arguments):
    query: str = Field(default="", max_length=120)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=20, ge=1, le=30)


class ModelUpdate(Arguments):
    model_id: str = Field(min_length=3, max_length=162)
    updates: dict[str, Any]


class ModelRemove(Arguments):
    model_id: str = Field(min_length=3, max_length=162)


class ModelDefault(Arguments):
    model_id: str = Field(max_length=162, description="已有模型引用；git/image2目标可传空字符串清除默认并恢复自动，profile目标必须非空。")
    target: Literal["profile", "image2", "git"] = "profile"
    profile_id: str = Field(default="primary", min_length=1, max_length=64)


class ProviderAdd(Arguments):
    provider_id: str = Field(min_length=1, max_length=64)
    source_provider_id: str = Field(default="", max_length=64)
    base_url: str = Field(default="", max_length=512)
    label: str = Field(default="", max_length=120)
    service_class: Literal["official_api", "aggregator", "relay", "self_hosted", "local_runtime"] = Field(
        default="self_hosted", description="localhost/loopback及私网本地服务使用local_runtime；self_hosted用于远程服务。省略时仅对已提供的loopback地址自动选择local_runtime；显式值不会改写。")
    driver: Literal["openai", "anthropic", "gemini"] = "openai"
    wire_protocol: Literal["responses", "chat_completions", "anthropic_messages", "gemini_generate_content"] = "chat_completions"


class ProviderUpdate(Arguments):
    provider_id: str = Field(min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=512)
    source_provider_id: str = Field(default="", max_length=64)
    clear_credential: bool = False


class ProviderRemove(Arguments):
    provider_id: str = Field(min_length=1, max_length=64)


class ProviderTest(ProviderRemove):
    model_id: str = Field(min_length=3, max_length=162)


class ProviderModels(Catalog):
    provider_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class ModelEdits(Arguments):
    # Omission leaves a field unchanged. Only context_window explicitly accepts
    # null, which removes that persisted override and restores native fallback.
    label: str | SkipJsonSchema[None] = Field(default=None, max_length=120)
    upstream_id: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=200)
    enabled: bool | SkipJsonSchema[None] = None
    context_window: int | None = Field(default=None, gt=0, description="正整数覆盖上下文窗口；null删除覆盖并恢复原生回退；省略则不改。")
    temperature: float | SkipJsonSchema[None] = Field(default=None, ge=0, le=2)
    max_output_tokens: int | SkipJsonSchema[None] = Field(default=None, gt=0)
    timeout: int | SkipJsonSchema[None] = Field(default=None, gt=0)
    streaming: bool | SkipJsonSchema[None] = None
    default_reasoning_effort: str | SkipJsonSchema[None] = Field(default=None, max_length=24)


_CONTRACTS = {
    "provider_catalog": (Catalog, False, "分页查看已有连接标识、origin、状态和模型；不返回完整URL、凭据或环境变量名。"),
    "provider_add": (ProviderAdd, True, "添加连接。可沿用已有连接的凭据，但仅限同一发送 origin；无来源时建立无凭据连接。重复连接返回 existing。"),
    "provider_update": (ProviderUpdate, True, "修改连接名称、启用状态或地址。跨 origin 必须清除凭据或选择新 origin 的已有连接。"),
    "provider_remove": (ProviderRemove, True, "移除无模型、无活动引用的连接；需原生审批。"),
    "provider_test": (ProviderTest, True, "用该连接的已固定模型执行原生连接测试；返回有限状态，不返回响应正文。"),
    "provider_discover": (ProviderModels, True, "通过已配置连接的原生发现器查询上游模型，并保存派生目录；不接收地址或凭据。"),
    "provider_models": (ProviderModels, False, "只读查询该连接的已缓存上游模型标识；不会发起网络请求，stale=true 时应先重新发现。"),
    "model_update": (ModelUpdate, False, "修改已固定模型的人工可编辑字段；不接收协议、能力或凭据字段。"),
    "model_details": (ModelRemove, False, "读取已固定模型的9个可编辑字段值与显式配置字段名；null表示未显式覆盖，不返回协议、路由或凭据。"),
    "model_defaults": (Arguments, False, "读取可选profile档位及当前profile/git/image2模型引用；git/image2空值表示自动选择。"),
    "model_remove": (ModelRemove, True, "移除无活动引用的固定模型；需原生审批。"),
    "model_default": (ModelDefault, True, "设置已有profile、image2或git默认模型；git/image2可用空model_id清除恢复自动，profile不可为空。不改变助理当前会话模型。"),
}


def contracts() -> dict[str, dict[str, Any]]:
    """Action descriptors for the parent's closed dispatch/catalog."""
    result = {}
    for name, (schema, governed, description) in _CONTRACTS.items():
        item = {"action": name, "description": description, "governed": governed,
                "parameters": schema.model_json_schema()}
        if name == "model_update":
            item["updatesSchema"] = ModelEdits.model_json_schema()
            for field in item["updatesSchema"]["properties"].values():
                # Optional patch fields have no applied default on omission.
                field.pop("default", None)
        result[name] = item
    return result


def describe(action: str) -> dict:
    return contracts().get(action, {"ok": False, "error": "unknown_action"})


def catalog() -> dict:
    return {"actions": [{"action": key, "governed": value[1], "description": value[2]}
                        for key, value in _CONTRACTS.items()]}


def _failure(code: str, *, status: str = "blocked") -> dict:
    # Never expose native exception messages, validation input, paths or config.
    return {"ok": False, "status": status, "error": code,
            "message": "配置操作未完成；请按错误状态核验，不要自动重复写入。"}


def _path() -> Path:
    from config.paths import resolve_config_path
    return resolve_config_path()


def _read(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _at(config: dict, path: tuple[str, ...], default=None):
    node = config
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _providers(config: dict) -> dict:
    if _at(config, ("llm", "schema_version")) != 2:
        raise ValueError("schema")
    result = _at(config, ("llm", "providers"))
    if not isinstance(result, dict):
        raise ValueError("providers")
    return result


def _provider(config: dict, provider_id: str) -> dict:
    from config.llm_identity import validate_provider_id
    validate_provider_id(provider_id)
    result = _providers(config).get(provider_id)
    if not isinstance(result, dict):
        raise ValueError("provider")
    return result


def _model(config: dict, model_id: str) -> tuple[str, str, dict]:
    from config.llm_identity import split_model_ref
    provider_id, key = split_model_ref(model_id)
    entry = _provider(config, provider_id).get("models", {}).get(key)
    if not isinstance(entry, dict):
        raise ValueError("model")
    return provider_id, key, entry


def _origin(base_url: str) -> tuple[str, str, int]:
    from config.llm_identity import normalize_provider_endpoint
    parsed = urlsplit(normalize_provider_endpoint(base_url))
    return parsed.scheme, parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)


def _is_loopback(base_url: str) -> bool:
    _, host, _ = _origin(base_url)
    if host.rstrip(".") == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _provider_target_failure(provider: dict) -> dict | None:
    from config.llm_security import is_llm_local_network_base_url, validate_llm_provider_target
    try:
        validate_llm_provider_target(provider, context="personal_assistant.provider")
    except ValueError:
        if provider.get("service_class") != "local_runtime" and is_llm_local_network_base_url(provider.get("base_url", "")):
            return {**_failure("local_endpoint_requires_local_runtime"),
                    "field": "service_class", "suggestedValue": "local_runtime", "retryRequiresApproval": True}
        raise
    return None


def _reuse_auth(provider: dict, source: dict) -> None:
    if _origin(provider["base_url"]) != _origin(source["base_url"]):
        raise PermissionError("credential_origin")
    for field, default in (("auth_kind", "api_key"), ("credential_ref", "none"), ("requires_credential", True)):
        provider[field] = copy.deepcopy(source.get(field, default))


def _discovery_settings(provider: dict, source: dict | None = None) -> dict:
    # These are the real adapter IDs registered by provider_discovery.adapters;
    # they choose distinct OpenAI / Anthropic / Gemini endpoints and auth.
    from core.llm.provider_discovery.adapters import get_provider_discovery_adapter
    adapters = {"openai": "openai_compatible", "anthropic": "anthropic", "gemini": "gemini"}
    settings = {"adapter": adapters[provider["driver"]], "mode": "auto", "cache_ttl_seconds": 300}
    if source is None or source.get("driver", "openai") != provider["driver"]:
        return settings
    original = source.get("discovery", {})
    if not isinstance(original, dict):
        return settings
    adapter = original.get("adapter", settings["adapter"])
    if isinstance(adapter, str):
        get_provider_discovery_adapter(adapter)
        settings["adapter"] = adapter
    if original.get("mode") in {"auto", "manual"}:
        settings["mode"] = original["mode"]
    ttl = original.get("cache_ttl_seconds")
    if type(ttl) is int and 0 <= ttl <= 86400:
        settings["cache_ttl_seconds"] = ttl
    for key in ("include", "exclude"):
        value = original.get(key)
        if isinstance(value, list) and len(value) <= 50 and all(isinstance(item, str) and len(item) <= 200 for item in value):
            settings[key] = copy.deepcopy(value)
    override = original.get("models_url_override")
    if isinstance(override, str) and override and len(override) <= 512:
        if _origin(override) == _origin(provider["base_url"]):
            settings["models_url_override"] = override
    return settings


def _duplicate(config: dict, provider: dict, *, exclude: str = "") -> str:
    from config.llm_identity import provider_identity_fingerprint
    def fingerprint(item):
        return provider_identity_fingerprint(item["base_url"], item.get("credential_ref", "none"),
                                             auth_kind=item.get("auth_kind", "api_key"))
    target = fingerprint(provider)
    return next((key for key, item in _providers(config).items()
                 if key != exclude and isinstance(item, dict) and fingerprint(item) == target), "")


def _assert_model_unused(config: dict, model_id: str) -> None:
    from core.web.services.model_reference_service import assert_model_delete_safe
    assert_model_delete_safe(model_id, public_config=config)


def _assert_provider_unused(provider_id: str) -> None:
    from core.web.services.model_reference_service import scan_provider_live_references
    if scan_provider_live_references(provider_id).get("liveReferenceCount"):
        raise PermissionError("live_references")


def _catalog_participant(config_path: Path, provider_id: str):
    """Remove only the deleted provider's derived catalog row, with compensation.

    Refuse derived-file drift instead of overwriting another discovery's data.
    No sweep of unrelated stale providers is performed.
    """
    from config.paths import resolve_model_catalog_state_path
    from config.operator_config_transaction import TransactionParticipant, _strict_atomic_write
    target = resolve_model_catalog_state_path(config_path)
    before = target.read_bytes() if target.exists() else None
    if before is None:
        return []
    payload = json.loads(before)
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        raise ValueError("catalog")
    if provider_id not in payload["providers"]:
        return []
    del payload["providers"][provider_id]
    after = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    applied = False
    def apply():
        nonlocal applied
        if target.read_bytes() != before:
            raise ValueError("catalog drift")
        _strict_atomic_write(target, after)
        applied = True
    def verify():
        if target.read_bytes() != after:
            raise ValueError("catalog verification")
    def rollback():
        if not applied:
            return
        if target.read_bytes() != after:
            raise ValueError("catalog rollback drift")
        _strict_atomic_write(target, before)
    return [TransactionParticipant("pa_removed_provider_catalog", apply, verify, rollback)]


def _commit(path: Path, before: dict, candidate: dict, tables: list[tuple[str, ...]], *, removed_provider: str = "") -> dict:
    from config.operator_config_transaction import (
        append_toml_table, remove_toml_table_tree,
        apply_operator_config_transaction, prepare_operator_config_transaction,
    )
    from config.public_config import public_config_hash
    def mutate(text):
        for table in tables:
            if _at(before, table) is not None:
                text = remove_toml_table_tree(text, table)
            values = _at(candidate, table)
            if values is not None:
                text = append_toml_table(text, table, values)
        if tomllib.loads(text) != candidate:
            raise ValueError("unexpected config mutation")
        return text
    prepared = prepare_operator_config_transaction(operation_kind="pa_config_action",
        expected_base_hash=public_config_hash(before), mutate_text=mutate, config_path=path)
    participants = _catalog_participant(path, removed_provider) if removed_provider else []
    result = apply_operator_config_transaction(prepared, participants=participants)
    if _read(path) != candidate:
        return _failure("verification_failed", status="unknown")
    return {"ok": True, "status": "applied", "verified": True,
            "updatedPaths": [".".join(table) for table in tables], "resultHash": result["hash"]}


def _provider_catalog(config: dict, args: Catalog) -> dict:
    rows = []
    for provider_id, item in _providers(config).items():
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or provider_id)[:120]
        if args.query and args.query.casefold() not in f"{provider_id} {label}".casefold():
            continue
        models = item.get("models", {})
        scheme, host, port = _origin(str(item.get("base_url") or ""))
        display_host = f"[{host}]" if ":" in host else host
        origin = f"{scheme}://{display_host}" + (f":{port}" if port != (443 if scheme == "https" else 80) else "")
        rows.append({"providerId": provider_id, "label": label,
                     "origin": origin,
                     "enabled": item.get("enabled", True) is True,
                     "credentialMode": "none" if item.get("credential_ref", "none") == "none" else "existing",
                     "modelCount": len(models) if isinstance(models, dict) else 0,
                     "modelIds": [f"{provider_id}/{key}" for key in list(models)[:10]] if isinstance(models, dict) else []})
    return {"ok": True, "providers": rows[args.offset:args.offset + args.limit], "total": len(rows),
            "offset": args.offset, "limit": args.limit, "truncated": args.offset + args.limit < len(rows)}


def _model_details(config: dict, model_id: str) -> dict:
    _, _, entry = _model(config, model_id)
    fields = {}
    configured = []
    for name in ModelEdits.model_fields:
        source = entry if name in {"label", "upstream_id", "enabled", "context_window"} else entry.get("defaults", {})
        if not isinstance(source, dict) or name not in source:
            fields[name] = None
            continue
        # Validate one public scalar before projecting it; a corrupt stored
        # object never becomes a serialized config or arbitrary nested payload.
        try:
            value = ModelEdits.model_validate({name: source[name]}).model_dump(exclude_unset=True)[name]
        except ValidationError:
            fields[name] = None
            continue
        fields[name] = value
        configured.append(name)
    return {"ok": True, "modelId": model_id, "values": fields, "configuredFields": configured}


def _model_defaults(config: dict) -> dict:
    profiles = _at(config, ("llm", "profiles"), {})
    if not isinstance(profiles, dict):
        raise ValueError("profiles")
    def text(value, limit=200):
        return value[:limit] if isinstance(value, str) else ""
    rows = [{"profileId": text(key, 64), "label": text(profile.get("label") or key, 120),
             "modelId": text(profile.get("model_ref"))}
            for key, profile in profiles.items() if isinstance(key, str) and isinstance(profile, dict)]
    return {"ok": True, "profiles": rows[:100], "totalProfiles": len(rows), "truncated": len(rows) > 100,
            "gitModelId": text(_at(config, ("git", "commit_message_model_ref"), "")),
            "imageModelId": text(_at(config, ("tools", "image2", "default_model_ref"), ""))}


def _model_page(provider_id: str, upstream_ids, args: ProviderModels) -> dict:
    # Provider-controlled metadata is untrusted. Only bounded upstream IDs are
    # useful for model_add; do not project arbitrary labels, errors or payloads.
    identifiers = sorted({value for value in upstream_ids if isinstance(value, str)
                          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+~-]{0,199}", value)
                          and "env:" not in value.lower()})
    matches = [value for value in identifiers if not args.query or args.query.casefold() in value.casefold()]
    return {"ok": True, "providerId": provider_id,
            "models": [{"upstreamId": value} for value in matches[args.offset:args.offset + args.limit]],
            "total": len(matches), "offset": args.offset, "limit": args.limit,
            "truncated": args.offset + args.limit < len(matches)}


def _provider_models(config: dict, path: Path, args: ProviderModels, *, discover: bool) -> dict:
    provider = _provider(config, args.provider_id)
    from config.llm_identity import provider_discovery_fingerprint
    from config.model_catalog import load_model_catalog_state
    from config.paths import resolve_model_catalog_state_path
    if discover:
        if _at(provider, ("discovery", "adapter"), "manual") == "manual":
            return {**_failure("not_discovered", status="manual"),
                    "providerId": args.provider_id, "models": [], "stale": True}
        # A configured discovery override must not redirect this connection's
        # credential to another origin through this assistant adapter.
        override = _at(provider, ("discovery", "models_url_override"), "")
        if override and provider.get("credential_ref", "none") != "none" and _origin(override) != _origin(provider["base_url"]):
            return _failure("credential_origin_blocked")
        if provider.get("enabled", True) is not True:
            return _failure("provider_disabled")
        from core.llm.provider_discovery.service import discover_provider_models
        discovered = discover_provider_models(config, args.provider_id,
                                              catalog_path=resolve_model_catalog_state_path(path))
        if discovered.adapter_id == "manual" or not discovered.models:
            return {**_failure("not_discovered", status="not_discovered"),
                    "providerId": args.provider_id, "models": [], "stale": True}
        page = _model_page(args.provider_id, [model.upstream_id for model in discovered.models], args)
        # Discovery validates credential taint before writing derived metadata.
        # This receipt reports discovery, not a verified dialogue invocation.
        return {**page, "status": "discovered", "stale": False}
    state = load_model_catalog_state(resolve_model_catalog_state_path(path))
    cached = state.get("providers", {}).get(args.provider_id, {})
    models = cached.get("models", {}) if isinstance(cached, dict) else {}
    ids = [model.get("upstreamId") for model in models.values() if isinstance(model, dict)] if isinstance(models, dict) else []
    page = _model_page(args.provider_id, ids, args)
    stale = not isinstance(cached, dict) or cached.get("providerFingerprint") != provider_discovery_fingerprint(provider) or cached.get("catalogStale") is True
    return {**page, "status": "cached", "stale": stale}


def execute(action: str, parameters: dict, runtime: dict, governed: bool = False) -> dict:
    """Run only closed semantic actions; identity/approval are supplied by wrapper."""
    contract = _CONTRACTS.get(action)
    if contract is None:
        return _failure("unknown_action")
    if contract[1] and governed is not True:
        return _failure("native_approval_required")
    try:
        if not isinstance(parameters, dict) or len(json.dumps(parameters, allow_nan=False)) > 16000:
            return _failure("invalid_input")
        args = contract[0].model_validate(json.loads(json.dumps(parameters)))
        path = _path()
        before = _read(path)
        _providers(before)
        if action == "provider_catalog":
            return _provider_catalog(before, args)
        if action in {"provider_models", "provider_discover"}:
            return _provider_models(before, path, args, discover=action == "provider_discover")
        if action == "model_details":
            return _model_details(before, args.model_id)
        if action == "model_defaults":
            return _model_defaults(before)
        candidate = copy.deepcopy(before)
        removed_provider = ""
        if action == "model_update":
            provider_id, key, entry = _model(before, args.model_id)
            edits = ModelEdits.model_validate(args.updates).model_dump(exclude_unset=True)
            if not edits:
                return _failure("empty_update")
            updated = copy.deepcopy(entry)
            for field, value in edits.items():
                if value is None and field != "context_window":
                    return _failure("invalid_input")
                target = updated if field in {"label", "upstream_id", "enabled", "context_window"} else updated.setdefault("defaults", {})
                if value is None:
                    target.pop(field, None)
                else:
                    target[field] = value
            _provider(candidate, provider_id)["models"][key] = updated
            tables = [("llm", "providers", provider_id, "models", key)]
        elif action == "model_remove":
            from config.llm_provider_registry import unpin_llm_model
            provider_id, key, _ = _model(before, args.model_id)
            _assert_model_unused(before, args.model_id)
            candidate = unpin_llm_model(before, args.model_id)
            tables = [("llm", "providers", provider_id, "models", key)]
        elif action == "model_default":
            selected_id = args.model_id.strip()
            if not selected_id and args.target == "profile":
                return _failure("profile_model_required")
            if selected_id:
                provider_id, _, model = _model(before, selected_id)
                if model.get("enabled", True) is not True or _provider(before, provider_id).get("enabled", True) is not True:
                    return _failure("model_unavailable")
            if args.target == "profile":
                table = ("llm", "profiles", args.profile_id)
                profile = _at(candidate, table)
                if not isinstance(profile, dict):
                    return _failure("unknown_profile")
                profile["model_ref"] = selected_id
            elif args.target == "image2":
                from core.infrastructure.image_model_discovery import is_probable_image_model
                if selected_id and not is_probable_image_model(str(model.get("upstream_id") or "")):
                    return _failure("image_model_required")
                table = ("tools", "image2")
                candidate.setdefault("tools", {}).setdefault("image2", {})["default_model_ref"] = selected_id
            else:
                table = ("git",)
                candidate.setdefault("git", {})["commit_message_model_ref"] = selected_id
            tables = [table]
        elif action == "provider_add":
            from config.llm_provider_registry import add_llm_provider
            provider = {"label": args.label or args.provider_id, "base_url": args.base_url,
                        "service_class": args.service_class, "driver": args.driver,
                        "auth_kind": "none", "credential_ref": "none", "requires_credential": False,
                        "protocols": {"default": args.wire_protocol, "allowed": [args.wire_protocol]}, "models": {}}
            source = None
            if args.source_provider_id:
                source = _provider(before, args.source_provider_id)
                provider["base_url"] = args.base_url or source["base_url"]
                _reuse_auth(provider, source)
                if "service_class" not in args.model_fields_set:
                    provider["service_class"] = source.get("service_class", args.service_class)
                if "driver" not in args.model_fields_set:
                    provider["driver"] = source.get("driver", "openai")
                if "wire_protocol" not in args.model_fields_set:
                    protocols = source.get("protocols", {})
                    if isinstance(protocols, dict):
                        provider["protocols"] = {key: copy.deepcopy(value) for key, value in protocols.items()
                                                 if key in {"default", "allowed", "routes"}}
            provider["discovery"] = _discovery_settings(provider, source)
            _origin(provider["base_url"])
            if "service_class" not in args.model_fields_set and _is_loopback(provider["base_url"]):
                provider["service_class"] = "local_runtime"
            target_failure = _provider_target_failure(provider)
            if target_failure:
                return target_failure
            duplicate = _duplicate(before, provider)
            if duplicate:
                return {"ok": True, "status": "existing", "verified": True, "providerId": duplicate}
            candidate = add_llm_provider(before, args.provider_id, provider)
            tables = [("llm", "providers", args.provider_id)]
        elif action == "provider_update":
            from config.llm_provider_registry import update_llm_provider
            old = _provider(before, args.provider_id)
            provider = copy.deepcopy(old)
            for field in ("label", "enabled", "base_url"):
                if field in args.model_fields_set:
                    if getattr(args, field) is None:
                        return _failure("invalid_input")
                    provider[field] = getattr(args, field)
            crossed = _origin(provider["base_url"]) != _origin(old["base_url"])
            if args.clear_credential:
                provider.update(auth_kind="none", credential_ref="none", requires_credential=False)
                if crossed:
                    provider.pop("extra_headers", None)
            if args.source_provider_id:
                if args.clear_credential:
                    return _failure("ambiguous_credential_source")
                _reuse_auth(provider, _provider(before, args.source_provider_id))
            elif crossed and provider.get("credential_ref", "none") != "none":
                return _failure("credential_origin_blocked")
            if crossed:
                # Existing discovery overrides/headers may carry connection data.
                # A new origin never silently inherits them.
                if provider.get("extra_headers") or _at(provider, ("discovery", "models_url_override"), ""):
                    return _failure("route_metadata_blocked")
            target_failure = _provider_target_failure(provider)
            if target_failure:
                return target_failure
            duplicate = _duplicate(before, provider, exclude=args.provider_id)
            if duplicate:
                return _failure("duplicate_provider") | {"existingProviderId": duplicate}
            candidate = update_llm_provider(before, args.provider_id, provider)
            tables = [("llm", "providers", args.provider_id)]
        elif action == "provider_remove":
            from config.llm_provider_registry import delete_llm_provider
            provider = _provider(before, args.provider_id)
            if provider.get("models"):
                return _failure("provider_has_models")
            _assert_provider_unused(args.provider_id)
            candidate = delete_llm_provider(before, args.provider_id)
            removed_provider = args.provider_id
            tables = [("llm", "providers", args.provider_id)]
        elif action == "provider_test":
            provider_id, _, _ = _model(before, args.model_id)
            if provider_id != args.provider_id:
                return _failure("provider_model_mismatch")
            from core.web.services.config_service import run_draft_llm_test
            result = run_draft_llm_test(before, model_id=args.model_id, capability="text")
            passed = result.get("ok") is True
            return {"ok": passed, "status": "tested" if passed else "failed",
                    "providerId": args.provider_id, "modelId": args.model_id,
                    "connectionVerified": passed}
        return _commit(path, before, candidate, tables, removed_provider=removed_provider)
    except ValidationError:
        return _failure("invalid_input")
    except PermissionError:
        return _failure("credential_or_reference_blocked")
    except Exception as exc:
        from core.web.services.model_reference_service import ModelReferenceConflictError
        if isinstance(exc, ModelReferenceConflictError):
            return _failure("live_model_references")
        if isinstance(exc, ValueError):
            message = str(exc)
            if "stale config hash" in message or "changed after transaction preparation" in message:
                return _failure("config_conflict")
            return _failure("invalid_config")
        return _failure("config_operation_failed", status="unknown")
