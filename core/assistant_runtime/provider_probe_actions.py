"""Approved diagnostics for the operator's saved model connections."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import tomllib
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import Field, ValidationError

from config.llm_identity import make_model_ref, normalize_provider_endpoint, split_model_ref
from tools.pa_config_actions import Arguments


_MAX_TARGETS = 16
_PLAN_TTL_SECONDS = 360
_RESULT_TTL_SECONDS = 600
_PROBE_TIMEOUT_SECONDS = 12
_MAX_PLANS = 32
_LOCK = threading.Lock()


class ProbePlanArguments(Arguments):
    query: str = Field(default="", max_length=120, description="已有厂商名或连接 ID。空字符串覆盖全部已启用连接。")
    failed_only: bool = Field(default=False, description="只重测本会话最近一批失败或暂未确认的连接。")


class ProbeBatchArguments(Arguments):
    plan_id: str = Field(pattern=r"^[0-9a-f]{32}$", description="当前轮provider_test_batch_plan返回的plan_id。")


@dataclass(frozen=True)
class ProbePlan:
    identity: tuple[str, str, str]
    config_digest: str
    expires: float
    targets: list[dict]
    skipped: list[dict]


@dataclass(frozen=True)
class ProbeReport:
    config_digest: str
    checked_at: str
    expires: float
    rows: list[dict]


_PLANS: dict[str, ProbePlan] = {}
_REPORTS: dict[tuple[str, str], ProbeReport] = {}
_CONTRACTS = {
    "provider_test_batch_plan": (ProbePlanArguments, False, "准备本机已配置连接的文本实测清单。空参数测全部启用连接；指定厂商传query；只重测失败传failed_only。零网络请求，approvalArguments原样交给provider_test_batch。"),
    "provider_test_batch": (ProbeBatchArguments, True, "一次原生审批实测整批已保存连接，每条最多一次文本调用。只接受本轮清单，完成后用同一条回复逐项说明通过的模型、失败原因和未测项。"),
    "provider_test_batch_status": (Arguments, False, "读取本会话最近一批连接实测结果与是否过期，零网络请求。"),
}


def contracts() -> dict:
    return {name: {"action": name, "description": help_text, "governed": governed,
                   "parameters": schema.model_json_schema()}
            for name, (schema, governed, help_text) in _CONTRACTS.items()}


def _identity(runtime: dict) -> tuple[str, str, str]:
    agent, session, turn = (str(runtime.get(key) or "").strip() for key in ("agentId", "sessionId", "turnId"))
    if not agent or not session or not turn:
        raise ValueError("Provider diagnostics require a native assistant turn")
    return agent, session, turn


def _snapshot() -> tuple[dict, str]:
    from config.paths import resolve_config_path

    raw = resolve_config_path().read_bytes()
    return tomllib.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def _safe_text(value: str, max_chars: int) -> bool:
    return 0 < len(value) <= max_chars and not any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value
    )


def _select_targets(config: dict, agent_id: str, query: str, provider_ids: set[str] | None) -> tuple[list[dict], list[dict]]:
    from core.web.services.agent_directory_service import get_agent
    from core.web.services.agent_model_candidate_service import project_slot_compatibility

    llm = config["llm"]
    bindings = (get_agent(agent_id) or {}).get("llmBindings") or {}
    current = str((bindings.get("dialogue") or {}).get("modelId") or "")
    preferred = [current, *(profile.get("model_ref") for profile in llm.get("profiles", {}).values())]
    targets, skipped = [], []
    for provider_id, provider in sorted(llm.get("providers", {}).items()):
        label = str(provider.get("label") or provider_id)
        if provider_ids is not None and provider_id not in provider_ids:
            continue
        if query and query not in f"{provider_id} {label} {provider.get('vendor', '')}".casefold():
            continue
        if provider.get("enabled", True) is False:
            if query or provider_ids is not None:
                skipped.append({"providerId": provider_id, "status": "not_tested", "reason": "disabled", "message": "连接已禁用。"})
            continue
        models = {
            make_model_ref(provider_id, key): model
            for key, model in provider.get("models", {}).items()
            if model.get("enabled", True) is not False and project_slot_compatibility(
                str(model.get("upstream_id") or key), model, {},
            )["dialogue"]["allowed"]
        }
        model_id = next((ref for ref in preferred if ref in models), next(iter(models), ""))
        if not model_id:
            skipped.append({"providerId": provider_id, "status": "not_tested", "reason": "no_text_model", "message": "没有已启用的文本模型。"})
            continue
        endpoint = urlsplit(normalize_provider_endpoint(provider["base_url"]))
        origin = f"{endpoint.scheme}://{endpoint.netloc}"
        protocol = str(models[model_id].get("wire_protocol") or provider["protocols"]["default"])
        target = {"providerId": provider_id, "modelId": model_id, "origin": origin, "protocol": protocol}
        if not _safe_text(origin, 180) or not _safe_text(model_id, 161) or not _safe_text(protocol, 64):
            skipped.append({"providerId": provider_id, "status": "not_tested", "reason": "invalid_config", "message": _REASONS["invalid_config"]})
            continue
        targets.append(target)
    return targets, skipped


def _failure(reason: str, message: str) -> dict:
    return {"ok": False, "status": "blocked", "reason": reason, "message": message}


def _prepare(args: ProbePlanArguments, identity: tuple[str, str, str], config: dict, digest: str) -> dict:
    failed_ids = None
    if args.failed_only:
        with _LOCK:
            report = _REPORTS.get(identity[:2])
        if report is None:
            return _failure("no_previous_batch", "当前会话没有上次的检测结果。")
        failed_ids = {row["providerId"] for row in report.rows if row["status"] != "verified"}
    targets, skipped = _select_targets(config, identity[0], args.query.strip().casefold(), failed_ids)
    if len(targets) > _MAX_TARGETS or len(skipped) > _MAX_TARGETS:
        return _failure("too_many_targets", f"一次最多检查 {_MAX_TARGETS} 条连接，请缩小厂商范围。")
    if not targets:
        return {"ok": True, "status": "no_targets", "maxCalls": 0, "results": skipped}
    plan_id = secrets.token_hex(16)
    now = time.monotonic()
    with _LOCK:
        for key in [key for key, plan in _PLANS.items() if plan.expires < now]:
            del _PLANS[key]
        if len(_PLANS) >= _MAX_PLANS:
            del _PLANS[next(iter(_PLANS))]
        _PLANS[plan_id] = ProbePlan(identity, digest, now + _PLAN_TTL_SECONDS, targets, skipped)
    return {"ok": True, "status": "ready", "maxCalls": len(targets), "targets": targets,
            "results": skipped, "approvalArguments": {"plan_id": plan_id}}


def approval_targets(parameters: dict) -> tuple[str, list[dict]]:
    """The operator sees the actual server-owned plan bound to this turn."""
    from core.web.services.agent_directory_service import current_agent_runtime

    plan_id = ProbeBatchArguments.model_validate(parameters).plan_id
    identity = _identity(current_agent_runtime())
    with _LOCK:
        plan = _PLANS.get(plan_id)
        if not plan or plan.identity != identity or plan.expires < time.monotonic():
            raise ValueError("Provider diagnostics plan expired or belongs to another turn")
        return plan_id, plan.targets


_REASONS = {
    "missing_credential": "缺少密钥或尚未连接 ChatGPT。",
    "auth_failed": "上游拒绝了身份验证，请检查密钥或重新登录。",
    "permission_denied": "上游拒绝访问此模型或当前账号无权限。",
    "quota_exhausted": "调用额度不足或计费受限。",
    "rate_limited": "上游限制了请求频率或用量。",
    "not_found": "上游没有找到此模型或请求接口。",
    "timeout": "等待上游响应超时。",
    "network": "连接上游失败，请检查网络或线路。",
    "upstream_unavailable": "上游线路暂时不可用。",
    "service_unavailable": "上游服务暂时不可用。",
    "bad_request": "上游拒绝了请求参数或模型协议。",
    "provider_protocol_error": "模型接口返回了错误或无法解析的响应。",
    "incomplete_response": "接口没有返回完整的文本回答。",
    "capability_error": "模型或接口不支持本次文本探测。",
    "configuration_error": "本地模型连接或协议配置无法发起调用。",
    "invalid_config": "无法从已保存配置解析这条模型线路。",
    "busy": "探测槽仍在处理其他请求，本次未能发出调用。",
    "cancelled": "本次检测已停止。",
    "failed": "模型调用失败，上游未提供可识别的原因。",
}


def _probe(config: dict, target: dict, cancel_checker: Callable[[], str] | None) -> dict:
    from core.web.services import config_service

    started = time.monotonic()
    model_id = target["modelId"]
    if callable(cancel_checker) and cancel_checker():
        reason = "cancelled"
    else:
        try:
            prepared = config_service._v2_model_ref_test_target(config, model_id, saved_credential_only=True)
            profile = prepared["profile"]
            provider_id, model_key = split_model_ref(model_id)
            provider = prepared["provider"]
            model = config["llm"]["providers"][provider_id]["models"][model_key]
            if (provider.provider_id != provider_id or profile.model_ref != model_id
                    or profile.model != str(model["upstream_id"]).strip()):
                raise ValueError("Effective route differs from the approved model")
            profile = profile.model_copy(update={"timeout": min(profile.timeout, _PROBE_TIMEOUT_SECONDS),
                                                 "connect_timeout": min(profile.connect_timeout, _PROBE_TIMEOUT_SECONDS)})
            result = config_service._run_bounded_llm_runtime_probe(
                provider, profile, prepared["api_key"], cancel_checker=cancel_checker,
            )
        except (KeyError, TypeError, ValueError):
            reason = "invalid_config"
        except Exception:  # Keep other routes running; never expose exception text to the model.
            reason = "failed"
        else:
            verification = config_service._model_verification_summary(result)
            reason = verification["error_type"] if not result.get("ok") else (
                "" if result.get("completed_text") is True else "incomplete_response"
            )
            if verification["http_status"] is not None:
                target = {**target, "httpStatus": verification["http_status"]}
    if not reason:
        status = "verified"
    elif reason in {"missing_credential", "busy", "cancelled", "invalid_config"}:
        status = "not_tested"
    elif reason in {"timeout", "network"}:
        status = "unconfirmed"
    else:
        status = "failed"
    return {**target, "status": status, "reason": reason, "message": _REASONS.get(reason, ""),
            "elapsedMs": round((time.monotonic() - started) * 1000)}


def execute(action: str, parameters: dict, runtime: dict, *, governed: bool, cancel_checker=None) -> dict:
    schema, requires_approval, _ = _CONTRACTS[action]
    if requires_approval and not governed:
        return _failure("native_approval_required", "批量调用需要一次原生审批。")
    try:
        args = schema.model_validate(parameters)
        identity = _identity(runtime)
        config, digest = _snapshot()
        if action == "provider_test_batch_plan":
            return _prepare(args, identity, config, digest)
    except (OSError, KeyError, TypeError, ValueError, ValidationError):
        return _failure("config_unavailable", "无法读取本机保存的模型连接，或提供的检查参数无效。")

    if action == "provider_test_batch_status":
        with _LOCK:
            report = _REPORTS.get(identity[:2])
        if not report:
            return {"ok": True, "status": "no_previous_batch", "results": []}
        stale = report.config_digest != digest or report.expires < time.monotonic()
        return {"ok": True, "status": "completed", "stale": stale,
                "checkedAt": report.checked_at, "results": report.rows}

    with _LOCK:
        plan = _PLANS.get(args.plan_id)
        if not plan or plan.identity != identity or plan.expires < time.monotonic():
            return _failure("plan_unavailable", "清单已过期、已执行或不属于当前轮。")
        del _PLANS[args.plan_id]
    if plan.config_digest != digest:
        return _failure("configuration_changed", "审批期间连接配置有变动，请重新生成清单。")
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="provider-diagnostics") as pool:
        probed = list(pool.map(lambda target: _probe(config, target, cancel_checker), plan.targets))
    rows = probed + plan.skipped
    checked_at = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        if len(_REPORTS) >= _MAX_PLANS and identity[:2] not in _REPORTS:
            del _REPORTS[next(iter(_REPORTS))]
        _REPORTS[identity[:2]] = ProbeReport(digest, checked_at, time.monotonic() + _RESULT_TTL_SECONDS, rows)
    from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

    record_runtime_scene_event_quietly(
        "config", "llm_test", "config.provider_batch_test.completed",
        message="Assistant provider diagnostics completed.", outcome="completed",
        fields={"sessionId": identity[1], "turnId": identity[2], "planned": len(plan.targets),
                "results": [{key: row[key] for key in ("providerId", "status", "reason")} for row in rows]},
        lifecycle=True,
    )
    return {"ok": True, "status": "completed", "checkedAt": checked_at, "results": rows}
