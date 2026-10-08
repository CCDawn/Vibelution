"""Preview, persistence and public projections for AI backtest runs."""

from __future__ import annotations

import base64
import csv
import io
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from core.web.services import agent_directory_service as directory
from core.web.services.financial_backtest import data, engine
from core.web.services.financial_backtest.contract import (
    DEFAULT_MAX_TOKENS,
    MAX_OUTPUT_TOKENS_PER_DECISION,
    MAX_RUNS_PER_AGENT,
    PREVIEW_TTL_SECONDS,
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    canonical_request_id,
    canonical_uuid,
    deterministic_run_id,
    normalize_preview_request,
    project_status,
    sha256_json,
)
from core.web.services.financial_backtest.decision import (
    build_decision_input,
    build_messages,
    reserve_decision_call,
    runtime_config_for_decision,
)
from core.web.services.financial_backtest.store import (
    FinancialBacktestStore,
    default_store,
)

_PROFILE_ID = "financial_ai_backtest"
_ALLOWED_ACTION_STATUSES = {"clear", "factor_check_passed"}
_TERMINAL_STATUSES = {"stopped", "paused_unknown", "completed", "failed", "blocked"}


def create_financial_backtest_preview(
    agent_id: str,
    payload: Mapping[str, Any],
    *,
    store: FinancialBacktestStore | None = None,
    data_loader: Callable[[Mapping[str, Any]], data.BacktestSnapshot] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    request = normalize_preview_request(payload)
    _agent, bound_model_id = _require_owner_and_model(agent_id, request.get("modelId"))
    request["modelId"] = bound_model_id
    model_fingerprint = _model_fingerprint(bound_model_id)
    snapshot = (data_loader or data.prepare_data)(request)
    if snapshot.actions_status not in _ALLOWED_ACTION_STATUSES:
        raise FinancialBacktestConflict("公司行动/复权完整性检查未通过，当前行情不能用于AI回测")

    params = {**request["params"], "strategy": request["strategy"], "maxTokens": request["maxTokens"]}
    schedule = engine.build_decision_schedule(snapshot, params)
    engine.validate_benchmark(snapshot, params)
    params_hash = sha256_json(
        {
            "symbol": request["symbol"],
            "startDate": request["startDate"],
            "endDate": request["endDate"],
            "strategy": request["strategy"],
            "params": request["params"],
            "maxTokens": request["maxTokens"],
            "modelId": bound_model_id,
        }
    )
    selected_store.save_snapshot(agent_id, snapshot.to_dict())
    now = _now(now_provider)
    expires_at = now + timedelta(seconds=PREVIEW_TTL_SECONDS)
    estimated_tokens, reserved_output_tokens, reservation_plan = _estimate_budget(snapshot, params, schedule)
    max_tokens = int(request["maxTokens"])
    can_start = estimated_tokens <= max_tokens
    block_reason = None if can_start else f"預估需要約{estimated_tokens:,} tokens，超出本次预算{max_tokens:,} tokens"
    public_params = _public_params(params)
    preview = {
        "agentId": str(agent_id),
        "previewId": str(uuid4()),
        "expiresAt": _iso(expires_at),
        "symbol": snapshot.symbol,
        "dateCoverage": snapshot.coverage.to_dict(),
        "decisionSchedule": list(schedule),
        "decisionCount": len(schedule),
        "maxDecisions": int(params["maxDecisions"]),
        "maxTokens": max_tokens,
        "estimatedTokens": estimated_tokens,
        "reservedOutputTokens": reserved_output_tokens,
        "modelId": bound_model_id,
        "modelConfigHash": model_fingerprint,
        "paramsHash": params_hash,
        "dataHash": snapshot.data_hash,
        "actionsStatus": snapshot.actions_status,
        "actionDates": list(snapshot.action_dates),
        "canStart": can_start,
        "blockReason": block_reason,
        "warnings": _preview_warnings(snapshot, estimated_tokens, max_tokens),
        "source": snapshot.source,
        "sourceUrl": snapshot.source_url,
        "fetchedAt": snapshot.fetched_at,
        "adjustment": "raw",
        "notice": "\n".join(snapshot.notice),
        "params": public_params,
        "_modelFingerprint": model_fingerprint,
        "_reservationPlan": reservation_plan,
        "createdAt": _iso(now),
    }
    selected_store.save_preview(agent_id, preview)
    return {key: value for key, value in preview.items() if key not in {"createdAt", "_reservationPlan", "_modelFingerprint"}}


def start_financial_backtest_run(
    agent_id: str,
    client_request_id: str,
    preview_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    _require_owner(agent_id)
    request_id = canonical_request_id(client_request_id)
    normalized_preview_id = canonical_uuid(preview_id, "预览标识")
    preview = selected_store.load_preview(agent_id, normalized_preview_id)
    now = _now(now_provider)
    run_id = deterministic_run_id(str(agent_id), request_id)
    request_hash = sha256_json({"paramsHash": preview["paramsHash"], "dataHash": preview["dataHash"], "modelFingerprint": preview.get("_modelFingerprint")})
    existing_run_id = deterministic_run_id(str(agent_id), request_id)
    try:
        existing = selected_store.load_run(agent_id, existing_run_id)
    except FinancialBacktestNotFound:
        existing = None
    if existing is not None:
        if (
            str(existing.get("clientRequestId") or "") != request_id
            or str(existing.get("requestHash") or "") != request_hash
        ):
            raise FinancialBacktestConflict("clientRequestId已用于不同的回测预览")
        return project_run(existing)
    if str(_require_owner_and_model(agent_id)[1]) != str(preview.get("modelId") or ""):
        raise FinancialBacktestConflict("炒股智能体的绑定模型已变化，请重新生成回测预览")
    if _model_fingerprint(str(preview.get("modelId") or "")) != str(preview.get("_modelFingerprint") or ""):
        raise FinancialBacktestConflict("回测模型路由已变化，请重新生成预览以冻结当前模型配置")
    expires_at = _parse_iso(str(preview.get("expiresAt") or ""))
    if expires_at <= now:
        raise FinancialBacktestConflict("回测预览已过期，请重新生成预览")
    if not bool(preview.get("canStart")):
        raise FinancialBacktestConflict(str(preview.get("blockReason") or "该回测预览不可启动"))
    if preview.get("actionsStatus") not in _ALLOWED_ACTION_STATUSES:
        raise FinancialBacktestConflict("公司行动/复权完整性检查未通过，不能启动回测")
    selected_store.load_snapshot(agent_id, str(preview.get("dataHash") or ""))
    timestamp = _iso(now)
    run = {
        "agentId": str(agent_id),
        "runId": run_id,
        "clientRequestId": request_id,
        "requestHash": request_hash,
        "symbol": str(preview["symbol"]),
        "status": "queued",
        "progress": 0.0,
        "currentDecisionDate": None,
        "decisionSchedule": list(preview["decisionSchedule"]),
        "decisionCount": int(preview["decisionCount"]),
        "completedDecisionCount": 0,
        "callsUsed": 0,
        "tokensUsed": 0,
        "estimatedTokens": int(preview["estimatedTokens"]),
        "tokensReserved": int(preview["estimatedTokens"]),
        "maxTokens": int(preview["maxTokens"]),
        "modelId": str(preview["modelId"]),
        "modelFingerprint": str(preview.get("_modelFingerprint") or ""),
        "paramsHash": str(preview["paramsHash"]),
        "dataHash": str(preview["dataHash"]),
        "params": dict(preview["params"]),
        "dateCoverage": dict(preview["dateCoverage"]),
        "actionsStatus": str(preview["actionsStatus"]),
        "actionDates": list(preview.get("actionDates") or []),
        "source": str(preview["source"]),
        "sourceUrl": str(preview["sourceUrl"]),
        "fetchedAt": str(preview["fetchedAt"]),
        "adjustment": "raw",
        "notice": str(preview["notice"]),
        "warnings": list(preview.get("warnings") or []),
        "decisions": [],
        "metrics": None,
        "equity": [],
        "trades": [],
        "orders": [],
        "startedAt": None,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "completedAt": None,
        "terminalReason": None,
        "errorCode": None,
        "uncertainDecisionDate": None,
        "decisionSubmission": None,
        "tokenAccounting": "reserved",
        "resumeUnknownDecisionDate": None,
        "reservationPlan": dict(preview.get("_reservationPlan") or {}),
        "budgetTokensCommitted": 0,
    }
    state, _created = selected_store.create_run_if_absent(
        agent_id, run, max_runs=MAX_RUNS_PER_AGENT
    )
    if _created:
        _sync_runtime_task(agent_id, state, "queued", rearm=True)
    return project_run(state)


def list_financial_backtest_runs(
    agent_id: str,
    *,
    limit: int = 30,
    cursor: str = "",
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    bounded_limit = max(1, min(100, int(limit)))
    rows = (store or default_store()).list_runs(agent_id)
    cursor_key = _decode_cursor(cursor)
    if cursor_key:
        rows = [row for row in rows if (str(row.get("createdAt") or ""), str(row.get("runId") or "")) < cursor_key]
    page = rows[:bounded_limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > bounded_limit and page else None
    return {
        "agentId": str(agent_id),
        "items": [project_summary(row) for row in page],
        "nextCursor": next_cursor,
        "limit": bounded_limit,
    }


def get_financial_backtest_run(
    agent_id: str,
    run_id: str,
    *,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    return project_run((store or default_store()).load_run(agent_id, run_id))


def request_financial_backtest_stop(
    agent_id: str,
    run_id: str,
    *,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    _require_owner(agent_id)
    def mutate(run: dict[str, Any]) -> None:
        status = project_status(run.get("status"))
        if status in _TERMINAL_STATUSES:
            return
        submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
        if status == "queued" and submission.get("status") != "submitting":
            run["status"] = "stopped"
            run["completedAt"] = _iso(_now())
            run["terminalReason"] = "用户停止了尚未开始的回测"
        else:
            run["status"] = "stop_requested"
            run["terminalReason"] = "用户请求在当前模型调用结束后停止"
        run["tokensReserved"] = _reserved_for_run(run)
    state, _ = selected_store.update_run(agent_id, run_id, mutate)
    _sync_runtime_task(agent_id, state, str(state.get("status") or ""))
    return project_run(state)


def resume_financial_backtest_run(
    agent_id: str,
    run_id: str,
    *,
    retry_unknown_decision_date: str | None = None,
    confirm_possible_duplicate_charge: bool = False,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    _agent, current_model_id = _require_owner_and_model(agent_id)
    def mutate(run: dict[str, Any]) -> None:
        status = project_status(run.get("status"))
        if status == "paused_unknown":
            expected = str(run.get("uncertainDecisionDate") or "")
            if not retry_unknown_decision_date or retry_unknown_decision_date != expected:
                raise FinancialBacktestConflict("请明确选择唯一处于结果未知的AI决策日期后再继续")
            if not confirm_possible_duplicate_charge:
                raise FinancialBacktestConflict("重试未知决策可能重复计费，请先确认后再继续")
            run["resumeUnknownDecisionDate"] = expected
        elif status == "stopped":
            if retry_unknown_decision_date or confirm_possible_duplicate_charge:
                raise FinancialBacktestConflict("已停止的回测没有未知模型调用，不需要重复计费确认")
            run["resumeUnknownDecisionDate"] = None
        else:
            raise FinancialBacktestConflict("当前回测状态不能恢复")
        if current_model_id != str(run.get("modelId") or ""):
            raise FinancialBacktestConflict("炒股智能体的绑定模型已变化，不能安全恢复该回测")
        run["status"] = "queued"
        run["terminalReason"] = None
        run["errorCode"] = None
        run["completedAt"] = None
        run["updatedAt"] = _iso(_now())
        run["tokensReserved"] = _reserved_for_run(run)
    state, _ = selected_store.update_run(agent_id, run_id, mutate)
    _sync_runtime_task(agent_id, state, str(state.get("status") or ""), rearm=True)
    return project_run(state)


def export_financial_backtest_run(
    agent_id: str,
    run_id: str,
    export_format: str,
    *,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    run = (store or default_store()).load_run(agent_id, run_id)
    normalized_format = str(export_format or "").strip().lower()
    if normalized_format not in {"json", "csv"}:
        raise FinancialBacktestConflict("导出格式仅支持json或csv")
    projected = project_run(run)
    if normalized_format == "json":
        content = json.dumps(projected, ensure_ascii=False, indent=2, allow_nan=False)
        media_type = "application/json"
        filename = f"backtest-{run['runId']}.json"
    else:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["runId", "symbol", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash"])
        writer.writerow([_csv_safe(projected.get(key)) for key in ("runId", "symbol", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash")])
        output.write("\n")
        writer.writerow(["date", "equity", "benchmarkEquity", "cash", "shares", "marketValue"])
        for row in projected["equity"]:
            writer.writerow([_csv_safe(row.get(key)) for key in ("date", "equity", "benchmarkEquity", "cash", "shares", "marketValue")])
        output.write("\n")
        writer.writerow(["account", "signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason"])
        for account, orders in (("strategy", projected["orders"]), ("benchmark", projected["benchmarkOrders"])):
            for row in orders:
                writer.writerow([account, *[_csv_safe(row.get(key)) for key in ("signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason")]])
        output.write("\n")
        writer.writerow(["date", "targetWeight", "reason", "confidence", "modelId", "decisionHash"])
        for row in projected["decisions"]:
            writer.writerow([_csv_safe(row.get(key)) for key in ("date", "targetWeight", "reason", "confidence", "modelId", "decisionHash")])
        output.write("\n")
        writer.writerow(["metric", "value"])
        for key, value in (projected["metrics"] or {}).items():
            writer.writerow([_csv_safe(key), _csv_safe(value)])
        content = output.getvalue()
        media_type = "text/csv"
        filename = f"backtest-{run['runId']}.csv"
    return {
        "agentId": str(agent_id),
        "runId": str(run["runId"]),
        "format": normalized_format,
        "fileName": filename,
        "mediaType": media_type,
        "encoding": "utf8",
        "content": content,
    }


def project_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    count = max(0, int(run.get("decisionCount") or 0))
    completed = max(0, min(count, int(run.get("completedDecisionCount") or 0)))
    return {
        "agentId": str(run.get("agentId") or ""),
        "runId": str(run.get("runId") or ""),
        "symbol": str(run.get("symbol") or ""),
        "status": project_status(run.get("status")),
        "createdAt": str(run.get("createdAt") or ""),
        "updatedAt": str(run.get("updatedAt") or ""),
        "startedAt": run.get("startedAt"),
        "completedAt": run.get("completedAt"),
        "decisionCount": count,
        "completedDecisionCount": completed,
        "progress": completed / count if count else 0.0,
        "modelId": str(run.get("modelId") or ""),
        "paramsHash": str(run.get("paramsHash") or ""),
        "dataHash": str(run.get("dataHash") or ""),
        "totalReturnPct": metrics.get("totalReturnPct"),
        "maxDrawdownPct": metrics.get("maxDrawdownPct"),
        "terminalReason": run.get("terminalReason"),
    }


def project_run(run: Mapping[str, Any]) -> dict[str, Any]:
    count = max(0, int(run.get("decisionCount") or 0))
    completed = max(0, min(count, int(run.get("completedDecisionCount") or 0)))
    decisions: list[dict[str, Any]] = []
    for item in run.get("decisions", []) if isinstance(run.get("decisions"), list) else []:
        if not isinstance(item, Mapping):
            continue
        decisions.append({key: item[key] for key in ("date", "targetWeight", "reason", "confidence", "modelId", "inputHash", "decisionHash", "attempts", "tokens") if key in item})
    return {
        "agentId": str(run.get("agentId") or ""),
        "runId": str(run.get("runId") or ""),
        "clientRequestId": str(run.get("clientRequestId") or ""),
        "symbol": str(run.get("symbol") or ""),
        "status": project_status(run.get("status")),
        "progress": completed / count if count else 0.0,
        "currentDecisionDate": run.get("currentDecisionDate"),
        "decisionCount": count,
        "completedDecisionCount": completed,
        "callsUsed": max(0, int(run.get("callsUsed") or 0)),
        "tokensUsed": max(0, int(run.get("tokensUsed") or 0)),
        "estimatedTokens": max(0, int(run.get("estimatedTokens") or 0)),
        "tokensReserved": max(0, int(run.get("tokensReserved") or 0)),
        "maxTokens": max(0, int(run.get("maxTokens") or DEFAULT_MAX_TOKENS)),
        "modelId": str(run.get("modelId") or ""),
        "modelConfigHash": str(run.get("modelFingerprint") or ""),
        "paramsHash": str(run.get("paramsHash") or ""),
        "dataHash": str(run.get("dataHash") or ""),
        "params": dict(run.get("params") or {}),
        "dateCoverage": dict(run.get("dateCoverage") or {}),
        "actionsStatus": str(run.get("actionsStatus") or "unavailable"),
        "actionDates": list(run.get("actionDates") or []),
        "source": str(run.get("source") or ""),
        "sourceUrl": str(run.get("sourceUrl") or ""),
        "fetchedAt": str(run.get("fetchedAt") or ""),
        "adjustment": str(run.get("adjustment") or "raw"),
        "notice": str(run.get("notice") or ""),
        "warnings": [str(item) for item in run.get("warnings", []) if str(item or "").strip()],
        "decisions": decisions,
        "metrics": dict(run["metrics"]) if isinstance(run.get("metrics"), Mapping) else None,
        "equity": list(run.get("equity") or []),
        "trades": list(run.get("trades") or []),
        "orders": list(run.get("orders") or []),
        "benchmarkOrders": list(run.get("benchmarkOrders") or []),
        "startedAt": run.get("startedAt"),
        "updatedAt": str(run.get("updatedAt") or ""),
        "completedAt": run.get("completedAt"),
        "terminalReason": run.get("terminalReason"),
        "errorCode": run.get("errorCode"),
        "uncertainDecisionDate": run.get("uncertainDecisionDate"),
        "tokenAccounting": str(run.get("tokenAccounting") or "reserved"),
    }


def _require_owner(agent_id: str) -> dict[str, Any]:
    normalized_id = str(agent_id or "").strip()
    agent = directory.get_agent(normalized_id)
    if not isinstance(agent, dict):
        raise FinancialBacktestNotFound("炒股智能体不存在")
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if (
        str(agent.get("status") or "") != "active"
        or metadata.get("financialAssistantProfile") != "financial_assistant_v1"
        or metadata.get("financialAssistantSetup") != "ready"
    ):
        raise FinancialBacktestNotFound("可用的炒股智能体不存在")
    return agent


def _require_owner_and_model(agent_id: str, requested_model_id: str | None = None) -> tuple[dict[str, Any], str]:
    agent = _require_owner(agent_id)
    model_id = str(directory.agent_dialogue_model_id(agent) or "").strip()
    if not model_id:
        raise FinancialBacktestConflict("请先为炒股智能体绑定对话模型")
    requested = str(requested_model_id or "").strip()
    if requested and requested != model_id:
        raise FinancialBacktestConflict("回测模型必须使用炒股智能体当前绑定的对话模型")
    return agent, model_id


def _validate_model_available(model_id: str) -> None:
    try:
        runtime_config_for_decision(model_id)
    except data.BacktestInputError as exc:
        raise FinancialBacktestConflict(str(exc)) from exc
    except Exception as exc:
        raise FinancialBacktestConflict("炒股智能体当前绑定的模型不可用，请先修复模型配置") from exc


def _model_fingerprint(model_id: str) -> str:
    try:
        runtime_config = runtime_config_for_decision(model_id)
        profile = runtime_config.llm.get_profile(_PROFILE_ID)
        provider = runtime_config.llm.get_provider(profile.provider_id)
        from urllib.parse import urlsplit

        parts = urlsplit(str(getattr(provider, "base_url", "") or ""))
        safe_endpoint = {
            "scheme": parts.scheme.lower(),
            "hostname": (parts.hostname or "").lower(),
            "port": parts.port,
            "path": parts.path.rstrip("/"),
        }
        from core.llm import get_llm_client

        client = get_llm_client(profile_id=_PROFILE_ID, config=runtime_config)
        route = client.protocol_route
        return sha256_json(
            {
                "modelId": model_id,
                "providerId": profile.provider_id,
                "model": profile.model,
                "endpoint": safe_endpoint,
                "protocol": str(getattr(getattr(route, "protocol", None), "value", getattr(route, "protocol", ""))),
                "wireProtocol": str(getattr(getattr(route, "wire_protocol", None), "value", getattr(route, "wire_protocol", ""))),
                "reasoningEffort": str(profile.reasoning_effort or ""),
                "thinkingType": str(profile.thinking_type or ""),
                "maxOutputTokens": int(profile.max_output_tokens),
                "temperature": float(profile.temperature),
                "reasoningEffortAdapter": str(profile.reasoning_effort_adapter or ""),
                "reasoningEffortValues": list(profile.reasoning_effort_values),
                "reasoningEffortMap": dict(profile.reasoning_effort_map),
                "defaultReasoningEffort": str(profile.default_reasoning_effort or ""),
                "contract": str(profile.contract),
                "transport": str(profile.transport),
                "compat": dict(profile.compat),
                "driver": str(getattr(provider, "driver", "") or ""),
                "providerKind": str(getattr(provider, "kind", "") or ""),
            }
        )
    except FinancialBacktestConflict:
        raise
    except data.BacktestInputError as exc:
        raise FinancialBacktestConflict(str(exc)) from exc
    except Exception as exc:
        raise FinancialBacktestConflict("炒股智能体当前绑定的模型不可用，请先修复模型配置") from exc


def _public_params(params: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "strategy",
        "initialCash",
        "maxPositionPct",
        "decisionInterval",
        "commissionBps",
        "minimumCommission",
        "slippageBps",
        "maxDecisions",
        "maxTokens",
    )
    return {key: params[key] for key in keys}


def _estimate_budget(snapshot: data.BacktestSnapshot, params: Mapping[str, Any], schedule: tuple[str, ...]) -> tuple[int, int, dict[str, int]]:
    cash = float(params["initialCash"])
    portfolio = {
        "date": snapshot.start_date,
        "cash": cash,
        "shares": 0,
        "sellableShares": 0,
        "marketValue": 0.0,
        "equity": cash,
        "positionWeightPct": 0.0,
    }
    reservation_plan: dict[str, int] = {}
    for decision_date in schedule:
        decision_input = build_decision_input(snapshot, params, as_of_date=decision_date, portfolio=portfolio)
        messages = build_messages(decision_input)
        # Runtime reserve_decision_call also includes wire-wrapper room. Add a
        # separate margin here for the seven changing numeric portfolio fields;
        # a filled account serializes more digits than the initial empty account.
        reservation_plan[decision_date] = reserve_decision_call(messages) + 1_024
    output = len(schedule) * MAX_OUTPUT_TOKENS_PER_DECISION
    return sum(reservation_plan.values()), output, reservation_plan


def _preview_warnings(snapshot: data.BacktestSnapshot, estimated_tokens: int, max_tokens: int) -> list[str]:
    warnings = [
        "AI决策仅接收截至对应收盘日的冻结行情、既往模拟持仓和用户策略；不读取普通会话、记忆或工具。",
        "历史行情和模型训练知识可能包含区间之后形成的信息，不能宣称完全消除前视偏差。",
        "仅模拟A股现金账户、整手、T+1与日线撮合；公司行动检查不是交易所公司行动清单认证。",
        "预算预检按提示词UTF-8字节数和输出上限做保守预留；有供应商用量时会另行显示实际用量。",
    ]
    if estimated_tokens > max_tokens:
        warnings.append("当前token预算不足以覆盖所有决策点，请提高预算、缩短区间或增大决策间隔。")
    return warnings


def _reserved_for_run(run: Mapping[str, Any]) -> int:
    schedule = [str(item) for item in run.get("decisionSchedule", [])]
    completed = {str(item.get("date") or "") for item in run.get("decisions", []) if isinstance(item, Mapping)}
    plan = run.get("reservationPlan") if isinstance(run.get("reservationPlan"), Mapping) else {}
    current = str(run.get("uncertainDecisionDate") or "")
    current_submission = run.get("decisionSubmission") if isinstance(run.get("decisionSubmission"), Mapping) else {}
    if not current:
        current = str(current_submission.get("date") or "") if str(current_submission.get("status") or "") in {"submitting", "unknown"} else ""
    return sum(max(0, int(plan.get(day) or MAX_OUTPUT_TOKENS_PER_DECISION)) for day in schedule if day not in completed and (not current or day != current)) + (max(0, int(plan.get(current) or MAX_OUTPUT_TOKENS_PER_DECISION)) if current else 0)


def _sync_runtime_task(agent_id: str, run: Mapping[str, Any], status: str, *, rearm: bool = False) -> None:
    """Mirror every active backtest into the lifecycle registry used by guards."""
    from core.web.services import runtime_task_registry

    run_id = str(run.get("runId") or "").strip()
    if not run_id:
        return
    task_id = f"financial-backtest-{run_id}"
    tasks = runtime_task_registry.default_store()
    current = tasks.load_state(task_id)
    state = str(status or "").strip().lower()
    terminal = state in {"stopped", "paused_unknown", "completed", "failed", "blocked"}
    registry_state = {
        "agentId": str(agent_id),
        "runId": run_id,
        "publicStatus": state,
        "decisionCount": int(run.get("decisionCount") or 0),
        "completedDecisionCount": int(run.get("completedDecisionCount") or 0),
        "uncertainDecisionDate": str(run.get("uncertainDecisionDate") or ""),
    }
    if current is None:
        snapshot = runtime_task_registry.new_snapshot(
            kind=runtime_task_registry.KIND_RESEARCH_TASK,
            task_id=task_id,
            status="queued" if state not in {"running", "stop_requested"} else "running",
            label="股票AI回测",
            backgrounding_disabled=True,
            branch_generation=0,
        )
        snapshot.update({"coordinationOwner": "financial_ai_backtest", "financialBacktest": registry_state})
        current, _created = tasks.register_task_if_absent(snapshot, branch_generation=0)
    if current.get("coordinationOwner") != "financial_ai_backtest" or (current.get("financialBacktest") or {}).get("agentId") != str(agent_id):
        raise FinancialBacktestConflict("回测运行标识已被其他任务占用")
    def refresh_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["financialBacktest"] = registry_state
        return snapshot
    tasks.update_task(task_id, refresh_projection)
    if state == "stop_requested":
        tasks.request_stop(task_id, "user")
    elif terminal:
        runtime_terminal = "blocked" if state == "paused_unknown" else state
        tasks.mark_task_terminal(task_id, status=runtime_terminal, stop_initiator="user" if state == "stopped" else None, reason=str(run.get("terminalReason") or state))
    else:
        def update(snapshot: dict[str, Any]) -> dict[str, Any]:
            snapshot["status"] = "running" if state == "running" else "queued"
            snapshot["financialBacktest"] = registry_state
            if rearm:
                snapshot["completedAt"] = ""
                snapshot["stopInitiator"] = None
                snapshot["stopRequestedAt"] = ""
                snapshot["terminalReason"] = ""
            return snapshot
        tasks.update_task(task_id, update)


def _encode_cursor(row: Mapping[str, Any]) -> str:
    raw = json.dumps([str(row.get("createdAt") or ""), str(row.get("runId") or "")], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> tuple[str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        decoded = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        value = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise FinancialBacktestConflict("回测分页游标无效") from exc
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(item, str) for item in value):
        raise FinancialBacktestConflict("回测分页游标无效")
    return value[0], value[1]


def _csv_safe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.lstrip()
    if value.startswith(("\t", "\r", "\n")) or candidate.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _now(provider: Callable[[], datetime] | None = None) -> datetime:
    value = provider() if provider else datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise FinancialBacktestConflict("回测预览有效期无效，请重新生成") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "create_financial_backtest_preview",
    "export_financial_backtest_run",
    "get_financial_backtest_run",
    "list_financial_backtest_runs",
    "project_run",
    "project_summary",
    "request_financial_backtest_stop",
    "resume_financial_backtest_run",
    "start_financial_backtest_run",
]
