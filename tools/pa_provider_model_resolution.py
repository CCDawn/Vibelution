"""Resolve and pin models on an existing provider through native config owners.

The enclosing assistant tool owns strict argument validation and native approval.
This module accepts no credentials, creates no provider, and persists no drafts.
"""
from __future__ import annotations

import json
import re

from tools import pa_config_actions as config_actions
from tools import pa_settings_actions as settings_actions


def _failure(provider_id: str, code: str, *, configured: bool = True,
             next_action: str = "review_existing_provider", required_fields: tuple = ()) -> dict:
    return {"ok": False, "status": "blocked", "error": code,
            "providerId": provider_id, "configured": configured,
            "connectionVerified": False, "ready": False,
            "nextAction": next_action, "requiredFields": list(required_fields),
            "message": "现有连接已保留；请核对连接设置后继续。" if configured else "参数或现有连接尚未确认，请核对后继续。"}


def _discovery_failure(provider_id: str, exc: Exception) -> dict:
    from core.web.services.provider_config_service import _provider_discovery_failure_details
    if type(exc) is ValueError and str(exc) == "model discovery returned no usable models":
        return {**_failure(provider_id, "not_discovered", next_action="provide_upstream_id",
                           required_fields=("upstream_id",)), "retryable": False,
                "message": "连接已保留，但模型列表为空或没有可用条目；仅补充准确的上游模型ID即可继续测试。"}
    code, retryable = _provider_discovery_failure_details(exc)
    if code in {"credential_rejected", "credential_missing"}:
        result = _failure(provider_id, code, next_action="review_provider_credentials")
        result["message"] = "连接已保留；请在现有连接的凭据设置中核对或补充凭据，再验证。无需重新建连接或填写模型ID。"
    elif code in {"protocol_mismatch", "invalid_response"}:
        result = _failure(provider_id, code, next_action="provide_upstream_id", required_fields=("upstream_id",))
        result["message"] = "连接已保留，但模型列表不可用；可核对地址和协议，或仅补充准确的上游模型ID再测试。"
    elif retryable:
        result = _failure(provider_id, code, next_action="retry_existing_connection")
        result["message"] = "模型列表暂时无法读取；连接和模型查询已保留，稍后重试现有连接，无需补模型ID或重新配置。"
    else:
        result = _failure(provider_id, code)
    return {**result, "retryable": retryable}


def _tokens(value: str) -> tuple[str, ...]:
    # Keep complete numeric components: 5.5 and 5.50 must stay different.
    return tuple(re.findall(r"[^\W\d_]+|\d+", value.casefold()))


def _matches(query: str, upstream_id: str) -> bool:
    wanted, candidate = _tokens(query), _tokens(upstream_id)
    if not wanted:
        return False
    # Joining adjacent alphabetic pieces supports ClaudeOpus / claude-opus,
    # while numeric components remain delimited, never prefix-matched.
    def compact(parts):
        return "".join(f"\0{part}\0" if part.isdecimal() else part for part in parts)
    if compact(wanted) == compact(candidate):
        return True
    return any(candidate[index:index + len(wanted)] == wanted
               for index in range(len(candidate) - len(wanted) + 1))


def _candidates(provider_id: str, identifiers: list[str], query: str, offset: int, limit: int) -> dict:
    exact = [item for item in identifiers if item == query] if query else []
    matches = exact or [item for item in identifiers if not query or _matches(query, item)]
    if len(matches) == 1:
        return {"selected": matches[0]}
    options = matches if matches else identifiers
    result = {**_failure(provider_id, "ambiguous_model" if matches else "model_not_found",
                       next_action="select_upstream_id", required_fields=("upstream_id",)),
            "status": "needs_selection", "candidates": [],
            "total": len(options), "offset": offset, "limit": limit,
            "nextOffset": None,
            "message": "找到多个模型；请从候选中选择准确的上游模型ID。" if matches
                       else "未找到确定匹配；可从候选中选择或补充准确的上游模型ID。"}
    # Manage-tool packaging has a 4000-character default including its facts
    # header. Leave room for that wrapper; limit is a maximum, not a row promise.
    for item in options[offset:offset + limit]:
        result["candidates"].append({"upstreamId": item})
        end = offset + len(result["candidates"])
        result["nextOffset"] = end if end < len(options) else None
        if len(json.dumps(result, ensure_ascii=False)) > 2800 and len(result["candidates"]) > 1:
            result["candidates"].pop()
            end -= 1
            result["nextOffset"] = end if end < len(options) else None
            break
    return result


def _discovered_ids(config: dict, path, provider_id: str) -> list[str] | dict:
    """Discover once, then validate the authoritative derived snapshot in full."""
    from config.llm_identity import provider_discovery_fingerprint
    from config.model_catalog import read_existing_model_catalog_snapshot
    from config.paths import resolve_model_catalog_state_path

    args = config_actions.ProviderModels(provider_id=provider_id, limit=30)
    discovered = config_actions._provider_models(config, path, args, discover=True)
    if discovered.get("ok") is not True or discovered.get("stale") is not False:
        code = discovered.get("error")
        safe_codes = {"provider_disabled", "credential_origin_blocked", "not_discovered"}
        if code == "not_discovered":
            return {**_failure(provider_id, code, next_action="provide_upstream_id", required_fields=("upstream_id",)),
                    "message": "现有连接不提供可用模型列表；仅补充准确的上游模型ID即可继续测试。"}
        return _failure(provider_id, code if code in safe_codes else "discovery_unavailable")

    # Read config again: a discovery receipt for the old endpoint cannot bless
    # a connection edited during discovery.
    current = config_actions._read(path)
    provider = config_actions._provider(current, provider_id)
    if provider != config_actions._provider(config, provider_id):
        return _failure(provider_id, "config_conflict")
    cached = config_actions._provider_models(current, path, args, discover=False)
    if cached.get("ok") is not True or cached.get("stale") is not False:
        return _failure(provider_id, "catalog_stale", next_action="rediscover_models")
    state, _ = read_existing_model_catalog_snapshot(resolve_model_catalog_state_path(path))
    row = state.get("providers", {}).get(provider_id, {})
    if (row.get("providerFingerprint") != provider_discovery_fingerprint(provider)
        or row.get("catalogStale") is not False or row.get("status") != "reachable"):
        return _failure(provider_id, "catalog_stale", next_action="rediscover_models")
    # Native cached pages also contain pinned models missing from the current
    # response. Exclude those before using the native safe identifier projection.
    raw = [item.get("upstreamId") for item in row.get("models", {}).values()
           if isinstance(item, dict) and item.get("availability") in {"observed", "pinned"}]
    # Project bounded chunks through the native ID filter, then deduplicate in
    # memory. Public paging remains independent of the full-directory scan.
    identifiers = set()
    for offset in range(0, len(raw), args.limit):
        page = config_actions._model_page(provider_id, raw[offset:offset + args.limit], args)
        identifiers.update(item["upstreamId"] for item in page["models"])
    ids = sorted(identifiers)
    if not ids:
        return _failure(provider_id, "not_discovered", next_action="provide_upstream_id",
                        required_fields=("upstream_id",))
    return ids


def _pin_and_verify(provider_id: str, upstream_id: str, runtime: dict, *, verify: bool,
                    expected_provider: dict, path) -> dict:
    from core.infrastructure.model_reference_fence import model_reference_fence
    # Native operator transactions use this same reentrant Fence -> Config
    # order. Hold it through the native time-bounded probe because provider_test
    # rereads operator config before sending; compliant route writers must not
    # replace the approved target in that window. No store is queued here.
    with model_reference_fence(path):
        return _pin_and_verify_fenced(provider_id, upstream_id, runtime, verify=verify,
                                      expected_provider=expected_provider, path=path)


def _pin_and_verify_fenced(provider_id: str, upstream_id: str, runtime: dict, *, verify: bool,
                          expected_provider: dict, path) -> dict:
    from config.llm_provider_registry import pin_llm_model
    current = config_actions._read(path)
    provider = config_actions._provider(current, provider_id)
    if provider != expected_provider:
        return _failure(provider_id, "config_conflict")
    # Preserve an existing custom key for the exact upstream instead of adding
    # another pin for the same model. The native owner validates this key.
    models = provider.get("models", {})
    existing = sorted(key for key, item in models.items()
                      if isinstance(item, dict) and item.get("upstream_id") == upstream_id)
    # Compute the exact allowed delta with the native pure owner. This also
    # covers protocol/defaults on the new pin, not only its upstream ID.
    expected_after = current if existing else pin_llm_model(current, provider_id, upstream_id=upstream_id)
    expected_after_provider = config_actions._provider(expected_after, provider_id)
    saved = settings_actions.model_add(provider_id, upstream_id, model_key=existing[0] if existing else "")
    if saved.get("ok") is not True:
        code = saved.get("error")
        safe_codes = {"invalid_input", "config_conflict", "model_conflict", "verification_failed"}
        return _failure(provider_id, code if code in safe_codes else "model_save_failed")
    model_ref = saved["modelRef"]
    receipt = {"ok": True, "status": "configured_unverified", "providerId": provider_id,
               "upstreamId": upstream_id, "modelRef": model_ref, "configured": True,
               "connectionVerified": False, "ready": False, "requiredFields": [],
               "nextAction": "verify_connection"}
    def identity_matches(config):
        latest = config_actions._provider(config, provider_id)
        model_key = model_ref.split("/", 1)[1]
        return (latest == expected_after_provider
                and latest.get("models", {}).get(model_key, {}).get("upstream_id") == upstream_id)

    conflict = {**receipt, "ok": False, "status": "blocked", "error": "config_conflict",
                "nextAction": "review_existing_provider",
                "message": "模型引用已保留，但连接或模型在保存/测试期间发生变化；请核对现有配置后重新验证。"}
    # An existing disabled pin must never become ready merely because a probe
    # succeeds. Do not enable it or alter any route as part of recovery.
    try:
        latest = config_actions._read(path)
        if not identity_matches(latest):
            return conflict
        latest_provider, _, model = config_actions._model(latest, model_ref)
        if (latest_provider != provider_id or model.get("enabled", True) is not True
            or config_actions._provider(latest, provider_id).get("enabled", True) is not True):
            return {**receipt, "ok": False, "status": "blocked", "error": "model_unavailable",
                    "nextAction": "review_existing_provider"}
    except Exception:
        return {**receipt, "ok": False, "error": "verification_failed",
                "nextAction": "review_existing_provider"}
    if not verify:
        return receipt
    try:
        tested = config_actions.execute("provider_test", {"provider_id": provider_id, "model_id": model_ref},
                                        runtime, governed=True)
    except Exception:
        tested = {}
    try:
        if not identity_matches(config_actions._read(path)):
            return conflict
    except Exception:
        return {**receipt, "ok": False, "error": "verification_failed",
                "nextAction": "review_existing_provider"}
    if tested.get("ok") is True and tested.get("connectionVerified") is True:
        return {**receipt, "status": "ready", "connectionVerified": True, "ready": True,
                "nextAction": "none"}
    return {**receipt, "ok": False, "status": "connection_failed", "error": "connection_test_failed",
            "nextAction": "review_existing_provider"}


def resolve_model(parameters: dict, runtime: dict) -> dict:
    """Resolve, pin and optionally test a model; caller supplies approval."""
    from config.llm_identity import validate_provider_id

    provider_id = ""
    configured = False
    try:
        if (not isinstance(parameters, dict)
            or set(parameters) - {"provider_id", "model_query", "upstream_id", "offset", "limit", "verify"}):
            return _failure("", "invalid_input", configured=False)
        provider_id = validate_provider_id(parameters.get("provider_id"))
        query, manual = parameters.get("model_query", ""), parameters.get("upstream_id", "")
        offset, limit, verify = parameters.get("offset", 0), parameters.get("limit", 20), parameters.get("verify", True)
        if (not isinstance(query, str) or len(query) > 120 or not isinstance(manual, str)
            or type(offset) is not int or not 0 <= offset <= 10000
            or type(limit) is not int or not 1 <= limit <= 30 or type(verify) is not bool):
            return _failure(provider_id, "invalid_input", configured=False)
        # Reuse the native restricted public-ID projection for hand-entered IDs.
        if manual and not config_actions._model_page(provider_id, [manual],
                config_actions.ProviderModels(provider_id=provider_id))["models"]:
            return _failure(provider_id, "invalid_input", configured=False)
        path = config_actions._path()
        config = config_actions._read(path)
        provider = config_actions._provider(config, provider_id)
        configured = True
        if provider.get("enabled", True) is not True:
            return _failure(provider_id, "provider_disabled")
        target_failure = config_actions._provider_target_failure(provider)
        if target_failure:
            return _failure(provider_id, target_failure["error"])
        selected = manual
        if not selected:
            try:
                identifiers = _discovered_ids(config, path, provider_id)
            except Exception as exc:
                return _discovery_failure(provider_id, exc)
            if isinstance(identifiers, dict):
                return identifiers
            selection = _candidates(provider_id, identifiers, query.strip(), offset, limit)
            if "selected" not in selection:
                return selection
            selected = selection["selected"]
        return _pin_and_verify(provider_id, selected, runtime, verify=verify,
                               expected_provider=provider, path=path)
    except Exception:
        # Never reflect native exceptions, provider URLs or credential material.
        return _failure(provider_id, "config_operation_failed", configured=configured)
