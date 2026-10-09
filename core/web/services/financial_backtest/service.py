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
from core.web.services.financial_backtest import (
    basket_data,
    data,
    engine,
    portfolio_engine,
    robustness,
)
from core.web.services.financial_backtest.contract import (
    DEFAULT_MAX_TOKENS,
    MAX_OUTPUT_TOKENS_PER_DECISION,
    MAX_RESULT_CHARS,
    MAX_RUNS_PER_AGENT,
    PREVIEW_TTL_SECONDS,
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    FinancialBacktestStoreError,
    canonical_request_id,
    canonical_uuid,
    deterministic_run_id,
    normalize_preview_request,
    project_status,
    sha256_json,
)
from core.web.services.financial_backtest.decision import (
    build_basket_decision_input,
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
    data_loader: Callable[[Mapping[str, Any]], data.BacktestSnapshot | basket_data.BasketSnapshot] | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    request = normalize_preview_request(payload)
    _agent, bound_model_id = _require_owner_and_model(agent_id, request.get("modelId"))
    return _create_preview(
        agent_id,
        request,
        selected_store,
        model_id=bound_model_id,
        data_loader=data_loader,
        now_provider=now_provider,
    )


def create_financial_backtest_fork_preview(
    agent_id: str,
    source_run_id: str,
    payload: Mapping[str, Any],
    *,
    store: FinancialBacktestStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Create a new preview using only the source run's owner-frozen snapshot."""
    selected_store = store or default_store()
    _require_owner(agent_id)
    source_run = selected_store.load_run(agent_id, source_run_id)
    snapshot = _load_run_snapshot(agent_id, source_run, selected_store)
    overrides = dict(payload or {})
    parameter_override_keys = {
        "maxPositionPct",
        "decisionInterval",
        "commissionBps",
        "minimumCommission",
        "slippageBps",
        "maxParticipationPct",
    }
    allowed_override_keys = {"strategy", "modelId", "maxTokens", *parameter_override_keys}
    if set(overrides) - allowed_override_keys:
        raise FinancialBacktestConflict("派生预览包含不支持的覆盖字段")
    selected_parameter_overrides = {
        key: overrides[key]
        for key in parameter_override_keys
        if key in overrides
    }
    if any(value is None for value in selected_parameter_overrides.values()):
        raise FinancialBacktestConflict("回测参数覆盖值不能为空")
    if len(selected_parameter_overrides) > 1:
        raise FinancialBacktestConflict("单次派生预览最多更改一项回测参数")

    source_params = dict(source_run.get("params") or {})
    source_model_id = str(source_run.get("modelId") or "").strip()
    if not source_model_id:
        raise FinancialBacktestConflict("来源回测缺少冻结模型，无法派生预览")
    request_payload: dict[str, Any] = {
        "symbol": snapshot.symbol if isinstance(snapshot, data.BacktestSnapshot) else None,
        "symbols": list(snapshot.symbols) if isinstance(snapshot, basket_data.BasketSnapshot) else None,
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "outOfSampleStartDate": source_run.get("outOfSampleStartDate") or source_params.get("outOfSampleStartDate"),
        "strategy": (
            source_params.get("strategy")
            if overrides.get("strategy") is None
            else overrides["strategy"]
        ),
        "initialCash": source_params.get("initialCash", 100_000),
        "maxPositionPct": source_params.get("maxPositionPct", 100),
        "maxParticipationPct": source_params.get("maxParticipationPct", 1),
        "decisionInterval": source_params.get("decisionInterval", 5),
        "commissionBps": source_params.get("commissionBps", 3),
        "minimumCommission": source_params.get("minimumCommission", 5),
        "slippageBps": source_params.get("slippageBps", 5),
        "maxDecisions": source_params.get("maxDecisions", 500),
        "maxTokens": (
            source_run.get("maxTokens", source_params.get("maxTokens", DEFAULT_MAX_TOKENS))
            if overrides.get("maxTokens") is None
            else overrides["maxTokens"]
        ),
        "modelId": source_model_id if overrides.get("modelId") is None else overrides["modelId"],
        "researchInput": source_run.get("researchInput", "price_only"),
    }
    request_payload.update(selected_parameter_overrides)
    request = normalize_preview_request(request_payload)
    # A fork preserves the source execution contract, including old uncapped runs.
    if (
        "maxParticipationPct" not in source_params
        and "maxParticipationPct" not in selected_parameter_overrides
    ):
        request["params"].pop("maxParticipationPct", None)
    model_id = str(request.get("modelId") or "").strip()
    if not model_id:
        raise FinancialBacktestConflict("派生预览必须选择对话模型")
    candidate_source = _validate_candidate_model(model_id)
    # _load_run_snapshot above revalidated this source schedule against its original persisted params.
    source_schedule = tuple(str(item) for item in source_run.get("decisionSchedule", []))
    expected_schedule = _build_schedule(snapshot, request)
    research_input = source_run.get("researchInput", "price_only")
    source_interval = int(source_params.get("decisionInterval", 5))
    requested_interval = int(request["params"].get("decisionInterval", 5))
    if research_input == "announcements" and requested_interval != source_interval:
        raise FinancialBacktestConflict(
            "公告研究快照绑定源回测决策日程；更改决策频率不能重新联网补取公告"
        )
    if research_input == "announcements" and source_schedule != expected_schedule:
        raise FinancialBacktestConflict("来源回测决策计划与冻结行情或参数不匹配，无法安全派生")
    preview = _create_preview(
        agent_id,
        request,
        selected_store,
        model_id=model_id,
        snapshot=snapshot,
        schedule=expected_schedule,
        now_provider=now_provider,
        source_run_id=str(source_run.get("runId") or source_run_id),
        model_candidate_source=candidate_source,
        frozen_research=_load_research_snapshot(agent_id, source_run, selected_store),
    )
    from core.web.services.financial_backtest.runtime import _record_event

    _record_event(
        agent_id,
        str(source_run.get("runId") or source_run_id),
        "financial_backtest.preview.forked",
        "previewed",
        "",
    )
    return preview


def _create_preview(
    agent_id: str,
    request: Mapping[str, Any],
    selected_store: FinancialBacktestStore,
    *,
    model_id: str,
    data_loader: Callable[[Mapping[str, Any]], data.BacktestSnapshot | basket_data.BasketSnapshot] | None = None,
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot | None = None,
    schedule: tuple[str, ...] | None = None,
    now_provider: Callable[[], datetime] | None = None,
    source_run_id: str | None = None,
    model_candidate_source: str | None = None,
    frozen_research: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    model_fingerprint = _model_fingerprint(model_id)
    if request["mode"] == "basket":
        if snapshot is None:
            loader = data_loader or (
                lambda value: basket_data.prepare_basket_data(
                    value["symbols"], value["startDate"], value["endDate"],
                    data_source=value.get("dataSource", "tencent"),
                )
            )
            snapshot = loader(request)
        asset_snapshots = [snapshot.assets[symbol] for symbol in snapshot.symbols]
        if any(asset.actions_status not in _ALLOWED_ACTION_STATUSES for asset in asset_snapshots):
            raise FinancialBacktestConflict("组合中有股票未通过公司行动/复权完整性检查，当前行情不能用于AI回测")
        if schedule is None:
            schedule = portfolio_engine.build_decision_schedule(snapshot, {**request["params"], "maxDecisions": request["params"]["maxDecisions"]})
        symbols = list(snapshot.symbols)
        selected_symbol = None
        action_dates = sorted({day for asset in asset_snapshots for day in asset.action_dates})
        actions_status = "factor_check_passed" if any(asset.actions_status == "factor_check_passed" for asset in asset_snapshots) else "clear"
        date_coverage = snapshot.assets[snapshot.symbols[0]].coverage.to_dict()
        asset_coverage = {symbol: snapshot.assets[symbol].coverage.to_dict() for symbol in snapshot.symbols}
        asset_data_hashes = {symbol: snapshot.assets[symbol].data_hash for symbol in snapshot.symbols}
        asset_sources = {symbol: {"source": snapshot.assets[symbol].source, "sourceUrl": snapshot.assets[symbol].source_url, "fetchedAt": snapshot.assets[symbol].fetched_at} for symbol in snapshot.symbols}
        snapshot_payload = {"dataHash": snapshot.data_hash, "basketSnapshot": snapshot.to_dict()}
        source_url = ""
        fetched_at = max(asset.fetched_at for asset in asset_snapshots)
    else:
        if snapshot is None:
            snapshot = (data_loader or data.prepare_data)(request)
        if snapshot.actions_status not in _ALLOWED_ACTION_STATUSES:
            raise FinancialBacktestConflict("公司行动/复权完整性检查未通过，当前行情不能用于AI回测")
        if schedule is None:
            schedule = engine.build_decision_schedule(snapshot, request["params"])
            engine.validate_benchmark(snapshot, request["params"])
        symbols = [snapshot.symbol]
        selected_symbol = snapshot.symbol
        action_dates = list(snapshot.action_dates)
        actions_status = snapshot.actions_status
        date_coverage = snapshot.coverage.to_dict()
        asset_coverage = {snapshot.symbol: snapshot.coverage.to_dict()}
        asset_data_hashes = {snapshot.symbol: snapshot.data_hash}
        asset_sources = {snapshot.symbol: {"source": snapshot.source, "sourceUrl": snapshot.source_url, "fetchedAt": snapshot.fetched_at}}
        snapshot_payload = snapshot.to_dict()
        source_url = snapshot.source_url
        fetched_at = snapshot.fetched_at

    research_mode = request.get("researchInput", "price_only")
    research_hash = None
    research_coverage = None
    if research_mode == "announcements":
        from .research_snapshot import (
            freeze_announcement_research_snapshot,
            research_coverage_summary,
            validate_research_snapshot,
        )
        frozen_research = validate_research_snapshot(
            frozen_research, symbols=symbols, decision_dates=schedule,
        ) if frozen_research is not None else freeze_announcement_research_snapshot(symbols, schedule)
        research_hash = frozen_research["researchHash"]
        research_coverage = research_coverage_summary(frozen_research)
        selected_store.save_research_snapshot(agent_id, frozen_research)
    elif frozen_research is not None:
        raise FinancialBacktestConflict("纯行情回测不能混入历史公告快照")

    params = {**request["params"], "strategy": request["strategy"], "maxTokens": request["maxTokens"]}
    out_of_sample_start_date = _out_of_sample_start_date(
        snapshot, request.get("outOfSampleStartDate")
    )
    params["outOfSampleStartDate"] = out_of_sample_start_date
    params_hash = sha256_json(
        {
            "symbol": selected_symbol,
            "symbols": symbols,
            "startDate": request["startDate"],
            "endDate": request["endDate"],
            "outOfSampleStartDate": out_of_sample_start_date,
            "strategy": request["strategy"],
            "params": request["params"],
            "maxTokens": request["maxTokens"],
            "modelId": model_id,
            "researchInput": research_mode,
            "researchHash": research_hash,
        }
    )
    selected_store.save_snapshot(agent_id, snapshot_payload)
    now = _now(now_provider)
    expires_at = now + timedelta(seconds=PREVIEW_TTL_SECONDS)
    estimated_tokens, reserved_output_tokens, reservation_plan = _estimate_budget(
        snapshot, params, schedule, research_snapshot=frozen_research,
    )
    max_tokens = int(request["maxTokens"])
    can_start = estimated_tokens <= max_tokens
    block_reason = None if can_start else f"預估需要約{estimated_tokens:,} tokens，超出本次预算{max_tokens:,} tokens"
    public_params = _public_params(params)
    preview = {
        "agentId": str(agent_id),
        "previewId": str(uuid4()),
        "expiresAt": _iso(expires_at),
        "symbol": selected_symbol,
        "symbols": symbols,
        "dateCoverage": date_coverage,
        "assetCoverage": asset_coverage,
        "assetDataHashes": asset_data_hashes,
        "assetSources": asset_sources,
        "outOfSampleStartDate": out_of_sample_start_date,
        "decisionSchedule": list(schedule),
        "decisionCount": len(schedule),
        "maxDecisions": int(params["maxDecisions"]),
        "maxTokens": max_tokens,
        "estimatedTokens": estimated_tokens,
        "reservedOutputTokens": reserved_output_tokens,
        "modelId": model_id,
        "modelConfigHash": model_fingerprint,
        "paramsHash": params_hash,
        "dataHash": snapshot.data_hash,
        "researchInput": research_mode,
        "researchHash": research_hash,
        "researchCoverage": research_coverage,
        "actionsStatus": actions_status,
        "actionDates": action_dates,
        "canStart": can_start,
        "blockReason": block_reason,
        "warnings": _preview_warnings(snapshot, estimated_tokens, max_tokens),
        "source": snapshot.source,
        "sourceUrl": source_url,
        "fetchedAt": fetched_at,
        "adjustment": "raw",
        "notice": "\n".join(snapshot.notice) + ("\n" + research_coverage["notice"] if research_coverage else ""),
        "params": public_params,
        "_modelFingerprint": model_fingerprint,
        "_modelCandidateSource": model_candidate_source,
        "_reservationPlan": reservation_plan,
        "createdAt": _iso(now),
    }
    preview["comparisonProvenance"] = _build_comparison_provenance(
        preview,
        source_run_id=source_run_id,
    )
    if research_coverage:
        preview["warnings"][0] = "AI决策使用冻结行情、既往模拟账户、策略及决策日前公告标题；不读取普通会话、记忆或实时工具。"
        preview["warnings"].extend(research_coverage["warnings"])
    selected_store.save_preview(agent_id, preview)
    return {key: value for key, value in preview.items() if key not in {"createdAt", "_reservationPlan", "_modelFingerprint", "_modelCandidateSource", "mode"}}


def _build_schedule(
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    request: Mapping[str, Any],
) -> tuple[str, ...]:
    if isinstance(snapshot, basket_data.BasketSnapshot):
        return portfolio_engine.build_decision_schedule(
            snapshot,
            {**dict(request["params"]), "maxDecisions": request["params"]["maxDecisions"]},
        )
    schedule = engine.build_decision_schedule(snapshot, request["params"])
    engine.validate_benchmark(snapshot, request["params"])
    return schedule


def _build_comparison_provenance(
    record: Mapping[str, Any],
    *,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    from core.web.services.financial_backtest.comparisons import (
        build_comparison_provenance,
    )

    provenance_record = {
        "params": dict(record.get("params") or {}),
        "symbol": record.get("symbol"),
        "symbols": list(record.get("symbols") or []),
        "dataHash": str(record.get("dataHash") or ""),
        "researchInput": record.get("researchInput", "price_only"),
        "researchHash": record.get("researchHash"),
        "decisionSchedule": list(record.get("decisionSchedule") or []),
        "dateCoverage": dict(record.get("dateCoverage") or {}),
        "outOfSampleStartDate": record.get("outOfSampleStartDate"),
        "adjustment": str(record.get("adjustment") or "raw"),
        "maxTokens": int(record.get("maxTokens") or 0),
    }
    if source_run_id:
        provenance_record["sourceRunId"] = source_run_id
    return build_comparison_provenance(provenance_record)


def _load_research_snapshot(
    agent_id: str, record: Mapping[str, Any], selected_store: FinancialBacktestStore,
) -> dict[str, Any] | None:
    mode = record.get("researchInput", "price_only")
    if mode == "price_only":
        if record.get("researchHash"):
            raise FinancialBacktestStoreError("纯行情回测包含不匹配的公告摘要")
        return None
    if mode != "announcements" or not record.get("researchHash"):
        raise FinancialBacktestStoreError("回测研究输入或公告快照引用无效")
    from .research_snapshot import validate_research_snapshot
    return validate_research_snapshot(
        selected_store.load_research_snapshot(agent_id, str(record["researchHash"])),
        expected_hash=str(record["researchHash"]), symbols=_run_symbols(record),
        decision_dates=record.get("decisionSchedule", []),
    )


def _load_run_snapshot(
    agent_id: str,
    run: Mapping[str, Any],
    selected_store: FinancialBacktestStore,
) -> data.BacktestSnapshot | basket_data.BasketSnapshot:
    _load_research_snapshot(agent_id, run, selected_store)
    data_hash = str(run.get("dataHash") or "")
    payload = selected_store.load_snapshot(agent_id, data_hash)
    from core.web.services.financial_backtest.runtime import _restore_snapshot

    snapshot = _restore_snapshot(payload)
    if snapshot.data_hash != data_hash:
        raise FinancialBacktestStoreError("回测运行记录与冻结行情摘要不匹配")
    run_symbols = _run_symbols(run)
    if isinstance(snapshot, basket_data.BasketSnapshot):
        expected_symbols = list(snapshot.symbols)
        if not _is_basket_run(run) or run_symbols != expected_symbols:
            raise FinancialBacktestStoreError("组合回测运行记录与冻结行情标的列表不匹配")
    elif _is_basket_run(run) or run_symbols != [snapshot.symbol]:
        raise FinancialBacktestStoreError("单股回测运行记录与冻结行情标的不匹配")
    expected_coverage = (
        snapshot.assets[snapshot.symbols[0]].coverage.to_dict()
        if isinstance(snapshot, basket_data.BasketSnapshot)
        else snapshot.coverage.to_dict()
    )
    if isinstance(snapshot, basket_data.BasketSnapshot):
        expected_asset_coverage = {
            symbol: snapshot.assets[symbol].coverage.to_dict()
            for symbol in snapshot.symbols
        }
        expected_asset_hashes = {
            symbol: snapshot.assets[symbol].data_hash
            for symbol in snapshot.symbols
        }
        expected_action_dates = sorted(
            {day for asset in snapshot.assets.values() for day in asset.action_dates}
        )
        expected_actions_status = (
            "factor_check_passed"
            if any(
                asset.actions_status == "factor_check_passed"
                for asset in snapshot.assets.values()
            )
            else "clear"
        )
    else:
        expected_asset_coverage = {snapshot.symbol: snapshot.coverage.to_dict()}
        expected_asset_hashes = {snapshot.symbol: snapshot.data_hash}
        expected_action_dates = list(snapshot.action_dates)
        expected_actions_status = snapshot.actions_status
    coverage = run.get("dateCoverage") if isinstance(run.get("dateCoverage"), Mapping) else {}
    if dict(coverage) != expected_coverage:
        raise FinancialBacktestStoreError("回测运行记录与冻结行情日期范围不匹配")
    asset_coverage = run.get("assetCoverage") if isinstance(run.get("assetCoverage"), Mapping) else {}
    asset_hashes = run.get("assetDataHashes") if isinstance(run.get("assetDataHashes"), Mapping) else {}
    if dict(asset_coverage) != expected_asset_coverage or dict(asset_hashes) != expected_asset_hashes:
        raise FinancialBacktestStoreError("回测运行记录与冻结行情资产覆盖或摘要不匹配")
    if (
        list(run.get("actionDates") or []) != expected_action_dates
        or str(run.get("actionsStatus") or "") != expected_actions_status
        or str(run.get("adjustment") or "") != "raw"
    ):
        raise FinancialBacktestStoreError("回测运行记录与冻结行情复权或公司行动证据不匹配")
    params = run.get("params") if isinstance(run.get("params"), Mapping) else {}
    stored_schedule = tuple(str(item) for item in run.get("decisionSchedule", []))
    try:
        expected_schedule = _build_schedule(snapshot, {"params": params})
    except Exception as exc:
        raise FinancialBacktestStoreError("回测运行参数无法由冻结行情复核") from exc
    if stored_schedule != expected_schedule or int(run.get("decisionCount") or 0) != len(expected_schedule):
        raise FinancialBacktestStoreError("回测决策计划与冻结行情或运行参数不匹配")
    out_of_sample = run.get("outOfSampleStartDate") or params.get("outOfSampleStartDate")
    try:
        verified_oos = _out_of_sample_start_date(snapshot, out_of_sample)
    except Exception as exc:
        raise FinancialBacktestStoreError("回测样本外边界无法由冻结行情复核") from exc
    if verified_oos != out_of_sample:
        raise FinancialBacktestStoreError("回测样本外边界与冻结行情不匹配")
    return snapshot


def _validate_candidate_model(model_id: str) -> str:
    from core.web.services.agent_model_candidate_service import (
        list_agent_model_candidates,
    )

    try:
        candidate_payload = list_agent_model_candidates()
    except Exception as exc:
        raise FinancialBacktestConflict("当前无法校验派生回测的模型候选资格") from exc
    candidates = candidate_payload.get("candidates") if isinstance(candidate_payload, Mapping) else None
    candidate = next(
        (
            item
            for item in candidates or []
            if isinstance(item, Mapping)
            and str(item.get("modelId") or item.get("modelRef") or "").strip() == model_id
        ),
        None,
    )
    compatibility = candidate.get("slotCompatibility") if isinstance(candidate, Mapping) else None
    dialogue = compatibility.get("dialogue") if isinstance(compatibility, Mapping) else None
    if (
        not isinstance(candidate, Mapping)
        or candidate.get("runtimeSelectable") is not True
        or not isinstance(dialogue, Mapping)
        or dialogue.get("allowed") is not True
    ):
        raise FinancialBacktestConflict("所选模型当前不可作为对话模型运行派生回测")
    return sha256_json(
        {
            "operatorConfigHash": str(candidate_payload.get("operatorConfigHash") or ""),
            "modelId": model_id,
            "source": str(candidate.get("source") or ""),
            "providerId": str(candidate.get("providerId") or ""),
            "model": str(candidate.get("model") or ""),
            "runtimeSelectable": True,
            "dialogueAllowed": True,
        }
    )


def _source_run_id(run_or_preview: Mapping[str, Any]) -> str:
    provenance = run_or_preview.get("comparisonProvenance")
    return str(provenance.get("sourceRunId") or "").strip() if isinstance(provenance, Mapping) else ""


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
    request_inputs = {
        "paramsHash": preview["paramsHash"],
        "dataHash": preview["dataHash"],
        "modelFingerprint": preview.get("_modelFingerprint"),
    }
    # Old previews retain their original idempotency identity after upgrades.
    if "comparisonProvenance" in preview or "_modelCandidateSource" in preview:
        request_inputs.update(
            comparisonProvenance=preview.get("comparisonProvenance"),
            modelCandidateSource=preview.get("_modelCandidateSource"),
        )
    request_hash = sha256_json(request_inputs)
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
    model_id = str(preview.get("modelId") or "")
    source_run_id = _source_run_id(preview)
    if source_run_id:
        candidate_source = _validate_candidate_model(model_id)
        if candidate_source != str(preview.get("_modelCandidateSource") or ""):
            raise FinancialBacktestConflict("派生回测模型候选来源已变化，请重新生成预览")
    elif str(_require_owner_and_model(agent_id)[1]) != model_id:
        raise FinancialBacktestConflict("炒股智能体的绑定模型已变化，请重新生成回测预览")
    if _model_fingerprint(model_id) != str(preview.get("_modelFingerprint") or ""):
        raise FinancialBacktestConflict("回测模型路由已变化，请重新生成预览以冻结当前模型配置")
    expires_at = _parse_iso(str(preview.get("expiresAt") or ""))
    if expires_at <= now:
        raise FinancialBacktestConflict("回测预览已过期，请重新生成预览")
    if not bool(preview.get("canStart")):
        raise FinancialBacktestConflict(str(preview.get("blockReason") or "该回测预览不可启动"))
    if preview.get("actionsStatus") not in _ALLOWED_ACTION_STATUSES:
        raise FinancialBacktestConflict("公司行动/复权完整性检查未通过，不能启动回测")
    selected_store.load_snapshot(agent_id, str(preview.get("dataHash") or ""))
    _load_research_snapshot(agent_id, preview, selected_store)
    timestamp = _iso(now)
    run = {
        "agentId": str(agent_id),
        "runId": run_id,
        "clientRequestId": request_id,
        "requestHash": request_hash,
        "mode": "basket" if preview.get("symbol") is None else "single",
        "symbol": preview.get("symbol"),
        "symbols": list(preview.get("symbols") or ([preview["symbol"]] if preview.get("symbol") else [])),
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
        "comparisonProvenance": dict(preview.get("comparisonProvenance") or {}),
        "sourceRunId": _source_run_id(preview) or None,
        "paramsHash": str(preview["paramsHash"]),
        "dataHash": str(preview["dataHash"]),
        "researchInput": preview.get("researchInput", "price_only"),
        "researchHash": preview.get("researchHash"),
        "researchCoverage": preview.get("researchCoverage"),
        "params": dict(preview["params"]),
        "dateCoverage": dict(preview["dateCoverage"]),
        "assetCoverage": dict(preview.get("assetCoverage") or {}),
        "assetDataHashes": dict(preview.get("assetDataHashes") or {}),
        "assetSources": dict(preview.get("assetSources") or {}),
        "outOfSampleStartDate": preview.get("outOfSampleStartDate"),
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
        "evaluation": None,
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


def compare_financial_backtest_runs(
    agent_id: str,
    run_ids: list[str],
    axis: str,
    *,
    parameter_key: str | None = None,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    selected_store = store or default_store()
    normalized_ids = [canonical_uuid(value, "回测标识") for value in run_ids]
    records: list[dict[str, Any]] = []
    for run_id in normalized_ids:
        run = selected_store.load_run(agent_id, run_id)
        _load_run_snapshot(agent_id, run, selected_store)
        compare_record = dict(run)
        compare_record["sourceRunId"] = _source_run_id(run) or None
        records.append(compare_record)
    from core.web.services.financial_backtest.comparisons import compare_runs

    return compare_runs(records, axis, parameter_key=parameter_key)


def get_financial_backtest_run(
    agent_id: str,
    run_id: str,
    *,
    store: FinancialBacktestStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    selected_store = store or default_store()
    run = selected_store.load_run(agent_id, run_id)
    projected = project_run(run)
    projected["advancedEvaluation"] = _project_advanced_evaluation(
        agent_id, run, selected_store
    )
    return projected


def _project_advanced_evaluation(
    agent_id: str,
    run: Mapping[str, Any],
    selected_store: FinancialBacktestStore,
) -> dict[str, Any] | None:
    """Calculate detail-only projections from this store's frozen evidence."""
    if project_status(run.get("status")) != "completed":
        return None

    params = run.get("params") if isinstance(run.get("params"), Mapping) else {}
    boundary = run.get("outOfSampleStartDate") or params.get("outOfSampleStartDate")
    try:
        snapshot = _load_run_snapshot(agent_id, run, selected_store)
        schedule = [str(item) for item in run.get("decisionSchedule", [])]
        decisions = run.get("decisions")
        if not isinstance(decisions, list) or [
            str(item.get("date") or "")
            for item in decisions
            if isinstance(item, Mapping)
        ] != schedule or len(decisions) != len(schedule):
            raise data.BacktestInputError("已保存决策与冻结决策计划不一致")

        equity = run.get("equity")
        coverage = run.get("dateCoverage")
        if (
            not isinstance(equity, list)
            or not equity
            or not isinstance(coverage, Mapping)
            or coverage.get("complete") is not True
            or coverage.get("tradingDays") != len(equity)
            or not isinstance(equity[0], Mapping)
            or not isinstance(equity[-1], Mapping)
            or coverage.get("actualStartDate") != equity[0].get("date")
            or coverage.get("actualEndDate") != equity[-1].get("date")
        ):
            raise data.BacktestInputError("已保存净值与完整行情覆盖不一致")

        from core.web.services.financial_backtest import advanced_evaluation

        result = advanced_evaluation.evaluate_advanced_evaluation(
            snapshot,
            params,
            decisions,
            equity,
            out_of_sample_start_date=str(boundary) if boundary else None,
        )
        return {"status": "available", **result}
    except FinancialBacktestNotFound:
        return _unavailable_advanced_evaluation(
            boundary, "没有可校验的冻结行情快照；旧版或缺少快照的回测不生成高级评估。"
        )
    except (
        FinancialBacktestConflict,
        FinancialBacktestStoreError,
        data.BacktestDataError,
    ) as exc:
        return _unavailable_advanced_evaluation(
            boundary, f"冻结回测证据无法通过校验，高级评估不可用：{exc}"
        )


def _unavailable_advanced_evaluation(
    boundary: Any, reason: str
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "basis": "frozen_decisions",
        "status": "unavailable",
        "outOfSampleStartDate": str(boundary) if boundary else None,
        "costStress": {
            "status": "unavailable",
            "scenarios": [],
            "error": reason,
            "notice": "无法确认冻结行情与决策来源，不会补造压力测试结果。",
        },
        "returnUncertainty": {
            "status": "unavailable",
            "method": "newey_west_hac",
            "metric": "annualized_log_excess_return_pct",
            "confidenceLevel": 0.95,
            "observations": 0,
            "lag": None,
            "pointEstimatePct": None,
            "lowerPct": None,
            "upperPct": None,
            "error": reason,
            "notice": "只有通过校验且预先冻结的样本外收益序列才计算统计区间。",
        },
        "error": reason,
        "notice": "原始回测结果仍可读取；高级评估不会替缺失或无效的冻结证据补造数据。",
    }


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
    _require_owner(agent_id)
    initial_run = selected_store.load_run(agent_id, run_id)
    model_id = str(initial_run.get("modelId") or "")
    if _source_run_id(initial_run):
        _validate_candidate_model(model_id)
        if _model_fingerprint(model_id) != str(initial_run.get("modelFingerprint") or ""):
            raise FinancialBacktestConflict("派生回测的冻结模型路由已变化，不能安全恢复")
        current_model_id = model_id
    else:
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
    selected_store = store or default_store()
    run = selected_store.load_run(agent_id, run_id)
    normalized_format = str(export_format or "").strip().lower()
    if normalized_format not in {"json", "csv"}:
        raise FinancialBacktestConflict("导出格式仅支持json或csv")
    projected = project_run(run)
    projected["advancedEvaluation"] = _project_advanced_evaluation(
        agent_id, run, selected_store
    )
    schema_version = 2 if _is_basket_run(run) else 1
    frozen_research = _load_research_snapshot(agent_id, run, selected_store)
    if frozen_research is not None:
        schema_version = 3
    if normalized_format == "json":
        export_payload = {"schemaVersion": schema_version, **projected}
        if frozen_research is not None:
            export_payload["researchSnapshot"] = frozen_research
        if _is_basket_run(run):
            snapshot_payload = selected_store.load_snapshot(agent_id, str(run.get("dataHash") or ""))
            basket_snapshot = snapshot_payload.get("basketSnapshot")
            if not isinstance(basket_snapshot, Mapping):
                raise FinancialBacktestStoreError("组合回测冻结快照格式无效，无法导出")
            try:
                restored_snapshot = basket_data.restore_basket_snapshot(basket_snapshot)
            except data.BacktestDataError as exc:
                raise FinancialBacktestStoreError("组合回测冻结快照校验失败，无法导出") from exc
            run_symbols = run.get("symbols")
            if (
                restored_snapshot.data_hash != str(run.get("dataHash") or "")
                or not isinstance(run_symbols, (list, tuple))
                or tuple(str(symbol) for symbol in run_symbols) != restored_snapshot.symbols
            ):
                raise FinancialBacktestStoreError("组合回测冻结快照与运行记录不匹配，无法导出")
            export_payload["snapshot"] = restored_snapshot.to_dict()
        content = json.dumps(export_payload, ensure_ascii=False, indent=2, allow_nan=False)
        if len(content) > MAX_RESULT_CHARS:
            raise FinancialBacktestConflict("回测JSON导出超过安全大小限制，未生成截断文件")
        media_type = "application/json"
        filename = f"backtest-{run['runId']}.json"
    else:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        if _is_basket_run(run):
            writer.writerow(["runId", "symbol", "symbols", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash"])
            writer.writerow([_csv_safe(projected.get("runId")), "", _csv_safe(",".join(projected.get("symbols") or [])), *[_csv_safe(projected.get(key)) for key in ("status", "modelId", "modelConfigHash", "paramsHash", "dataHash")]])
        else:
            writer.writerow(["runId", "symbol", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash"])
            writer.writerow([_csv_safe(projected.get(key)) for key in ("runId", "symbol", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash")])
        output.write("\n")
        if _is_basket_run(run):
            writer.writerow(["date", "equity", "benchmarkEquity", "cash", "marketValue", "positions", "marketValues", "benchmarkPositions"])
            for row in projected["equity"]:
                writer.writerow([
                    _csv_safe(
                        json.dumps(row.get(key) or {}, ensure_ascii=False, sort_keys=True)
                    )
                    if key in {"positions", "marketValues", "benchmarkPositions"}
                    else _csv_safe(row.get(key))
                    for key in (
                        "date",
                        "equity",
                        "benchmarkEquity",
                        "cash",
                        "marketValue",
                        "positions",
                        "marketValues",
                        "benchmarkPositions",
                    )
                ])
        else:
            writer.writerow(["date", "equity", "benchmarkEquity", "cash", "shares", "marketValue"])
            for row in projected["equity"]:
                writer.writerow([_csv_safe(row.get(key)) for key in ("date", "equity", "benchmarkEquity", "cash", "shares", "marketValue")])
        output.write("\n")
        writer.writerow(["account", "symbol", "signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason"] if _is_basket_run(run) else ["account", "signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason"])
        for account, orders in (("strategy", projected["orders"]), ("benchmark", projected["benchmarkOrders"])):
            for row in orders:
                keys = ("symbol", "signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason") if _is_basket_run(run) else ("signalDate", "date", "side", "status", "requestedShares", "filledShares", "price", "fee", "notional", "reason")
                writer.writerow([account, *[_csv_safe(row.get(key)) for key in keys]])
        output.write("\n")
        writer.writerow(["date", "targetWeight", "targetWeights", "reason", "confidence", "modelId", "decisionHash"] if _is_basket_run(run) else ["date", "targetWeight", "reason", "confidence", "modelId", "decisionHash"])
        for row in projected["decisions"]:
            if _is_basket_run(run):
                writer.writerow([_csv_safe(row.get("date")), "", _csv_safe(json.dumps(row.get("targetWeights") or {}, ensure_ascii=False, sort_keys=True)), *[_csv_safe(row.get(key)) for key in ("reason", "confidence", "modelId", "decisionHash")]])
            else:
                writer.writerow([_csv_safe(row.get(key)) for key in ("date", "targetWeight", "reason", "confidence", "modelId", "decisionHash")])
        output.write("\n")
        writer.writerow(["metric", "value"])
        for key, value in (projected["metrics"] or {}).items():
            writer.writerow([_csv_safe(key), _csv_safe(value)])
        if isinstance(projected.get("evaluation"), Mapping):
            output.write("\n")
            writer.writerow(["window", "field", "value"])
            for window in ("inSample", "outOfSample"):
                values = projected["evaluation"].get(window)
                if not isinstance(values, Mapping):
                    continue
                for key, value in values.items():
                    if key == "metrics" and isinstance(value, Mapping):
                        for metric, metric_value in value.items():
                            writer.writerow([window, metric, _csv_safe(metric_value)])
                    else:
                        writer.writerow([window, key, _csv_safe(value)])
        segmented = projected.get("robustness")
        if isinstance(segmented, Mapping):
            writer.writerow([])
            writer.writerow(["periodEvaluation", "field", "value"])
            for key, value in segmented.items():
                if key not in {"annualWindows", "fixedWindows"}:
                    writer.writerow(["summary", key, _csv_safe(value)])
            for grouping in ("annualWindows", "fixedWindows"):
                for window in segmented.get(grouping, []):
                    label = f"{grouping}:{window['startDate']}"
                    for key, value in window.items():
                        if key == "metrics":
                            for metric, metric_value in value.items():
                                writer.writerow([label, metric, _csv_safe(metric_value)])
                        else:
                            writer.writerow([label, key, _csv_safe(value)])
        advanced = projected.get("advancedEvaluation")
        if isinstance(advanced, Mapping):
            writer.writerow([])
            writer.writerow(["advancedEvaluation", "field", "value"])
            for key in ("status", "basis", "outOfSampleStartDate", "error", "notice"):
                if key in advanced:
                    writer.writerow(["summary", key, _csv_safe(advanced.get(key))])
            cost_stress = advanced.get("costStress")
            if isinstance(cost_stress, Mapping):
                for key in ("status", "error", "notice"):
                    if key in cost_stress:
                        writer.writerow(["costStress", key, _csv_safe(cost_stress.get(key))])
                for scenario in cost_stress.get("scenarios", []):
                    if not isinstance(scenario, Mapping):
                        continue
                    label = f"costStress:{scenario.get('id') or 'unknown'}"
                    for key, value in scenario.items():
                        if key == "metrics" or key == "outOfSampleMetrics":
                            if isinstance(value, Mapping):
                                for metric, metric_value in value.items():
                                    writer.writerow([label, f"{key}.{metric}", _csv_safe(metric_value)])
                        else:
                            writer.writerow([label, key, _csv_safe(value)])
            uncertainty = advanced.get("returnUncertainty")
            if isinstance(uncertainty, Mapping):
                for key, value in uncertainty.items():
                    writer.writerow(["returnUncertainty", key, _csv_safe(value)])
        if frozen_research is not None:
            writer.writerow([])
            writer.writerow(["researchInput", "researchHash", "status", "groups", "items"])
            coverage = projected.get("researchCoverage") or {}
            writer.writerow(["announcements", _csv_safe(run.get("researchHash")), _csv_safe(coverage.get("status")), coverage.get("groupCount"), coverage.get("itemCount")])
            writer.writerow(["researchNotice", _csv_safe(coverage.get("notice"))])
        content = output.getvalue()
        media_type = "text/csv"
        filename = f"backtest-{run['runId']}.csv"
    return {
        "agentId": str(agent_id),
        "runId": str(run["runId"]),
        "format": normalized_format,
        "schemaVersion": schema_version,
        "fileName": filename,
        "mediaType": media_type,
        "encoding": "utf8",
        "content": content,
    }


def _is_basket_run(run: Mapping[str, Any]) -> bool:
    return str(run.get("mode") or "") == "basket" or run.get("symbol") is None


def _run_symbols(run: Mapping[str, Any]) -> list[str]:
    values = run.get("symbols")
    if isinstance(values, list):
        return [str(item) for item in values if str(item or "").strip()]
    symbol = str(run.get("symbol") or "").strip()
    return [symbol] if symbol else []


def project_summary(run: Mapping[str, Any]) -> dict[str, Any]:
    metrics = run.get("metrics") if isinstance(run.get("metrics"), Mapping) else {}
    count = max(0, int(run.get("decisionCount") or 0))
    completed = max(0, min(count, int(run.get("completedDecisionCount") or 0)))
    return {
        "agentId": str(run.get("agentId") or ""),
        "runId": str(run.get("runId") or ""),
        "symbol": None if _is_basket_run(run) else str(run.get("symbol") or ""),
        "symbols": _run_symbols(run),
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
        "comparisonProvenance": dict(run["comparisonProvenance"]) if isinstance(run.get("comparisonProvenance"), Mapping) else None,
        "totalReturnPct": metrics.get("totalReturnPct"),
        "maxDrawdownPct": metrics.get("maxDrawdownPct"),
        "benchmarkStatus": run.get("benchmarkStatus"),
        "unfilledBenchmarkSymbols": list(run.get("unfilledBenchmarkSymbols") or []),
        "terminalReason": run.get("terminalReason"),
        "outOfSampleStartDate": run.get("outOfSampleStartDate") or (run.get("params") or {}).get("outOfSampleStartDate"),
        "evaluation": dict(run["evaluation"]) if isinstance(run.get("evaluation"), Mapping) else None,
    }


def project_run(run: Mapping[str, Any]) -> dict[str, Any]:
    count = max(0, int(run.get("decisionCount") or 0))
    completed = max(0, min(count, int(run.get("completedDecisionCount") or 0)))
    decisions: list[dict[str, Any]] = []
    for item in run.get("decisions", []) if isinstance(run.get("decisions"), list) else []:
        if not isinstance(item, Mapping):
            continue
        decisions.append({key: item[key] for key in ("date", "targetWeight", "targetWeights", "reason", "confidence", "modelId", "inputHash", "decisionHash", "attempts", "tokens") if key in item})
    return {
        "agentId": str(run.get("agentId") or ""),
        "runId": str(run.get("runId") or ""),
        "clientRequestId": str(run.get("clientRequestId") or ""),
        "symbol": None if _is_basket_run(run) else str(run.get("symbol") or ""),
        "symbols": _run_symbols(run),
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
        "researchInput": run.get("researchInput", "price_only"),
        "researchHash": run.get("researchHash"),
        "researchCoverage": run.get("researchCoverage"),
        "params": dict(run.get("params") or {}),
        "dateCoverage": dict(run.get("dateCoverage") or {}),
        "assetCoverage": dict(run.get("assetCoverage") or {}),
        "assetDataHashes": dict(run.get("assetDataHashes") or {}),
        "assetSources": dict(run.get("assetSources") or {}),
        "outOfSampleStartDate": run.get("outOfSampleStartDate") or (run.get("params") or {}).get("outOfSampleStartDate"),
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
        "evaluation": dict(run["evaluation"]) if isinstance(run.get("evaluation"), Mapping) else None,
        "robustness": _project_robustness(run),
        "comparisonProvenance": dict(run["comparisonProvenance"]) if isinstance(run.get("comparisonProvenance"), Mapping) else None,
        "equity": list(run.get("equity") or []),
        "trades": list(run.get("trades") or []),
        "orders": list(run.get("orders") or []),
        "benchmarkOrders": list(run.get("benchmarkOrders") or []),
        "benchmarkStatus": run.get("benchmarkStatus"),
        "unfilledBenchmarkSymbols": list(run.get("unfilledBenchmarkSymbols") or []),
        "startedAt": run.get("startedAt"),
        "updatedAt": str(run.get("updatedAt") or ""),
        "completedAt": run.get("completedAt"),
        "terminalReason": run.get("terminalReason"),
        "errorCode": run.get("errorCode"),
        "uncertainDecisionDate": run.get("uncertainDecisionDate"),
        "tokenAccounting": str(run.get("tokenAccounting") or "reserved"),
    }


def _project_robustness(run: Mapping[str, Any]) -> dict[str, Any] | None:
    """Describe completed frozen results without rewriting or certifying old runs."""
    if run.get("status") != "completed":
        return None
    params = run.get("params") if isinstance(run.get("params"), Mapping) else {}
    boundary = params.get("outOfSampleStartDate") or run.get("outOfSampleStartDate")
    try:
        rows = run.get("equity") or []
        coverage = run.get("dateCoverage") if isinstance(run.get("dateCoverage"), Mapping) else {}
        if (
            not isinstance(rows, (list, tuple))
            or coverage.get("complete") is not True
            or not rows
            or not isinstance(rows[0], Mapping)
            or not isinstance(rows[-1], Mapping)
            or coverage.get("tradingDays") != len(rows)
            or coverage.get("actualStartDate") != rows[0].get("date")
            or coverage.get("actualEndDate") != rows[-1].get("date")
        ):
            raise data.BacktestInputError("已保存净值与完整行情覆盖不一致，无法评估分段表现")
        if run.get("outOfSampleStartDate") and params.get("outOfSampleStartDate") and run["outOfSampleStartDate"] != params["outOfSampleStartDate"]:
            raise data.BacktestInputError("已保存的样本外边界不一致")
        return robustness.evaluate_robustness(
            rows, run.get("orders") or [], initial_cash=params.get("initialCash"),
            out_of_sample_start_date=boundary,
        )
    except data.BacktestInputError as exc:
        return {
            "schemaVersion": 1, "status": "unavailable",
            "scope": "out_of_sample" if boundary else "full_period",
            "windowSize": 63, "minCompleteWindows": 4,
            "completeWindowCount": 0, "partialWindowCount": 0,
            "outperformingWindowRatePct": None,
            "evaluatedStartDate": None, "evaluatedEndDate": None, "tradingDays": 0,
            "annualWindows": [], "fixedWindows": [], "error": str(exc),
            "notice": "原始回测仍可读取；缺失或无效的评估依据不会被补造成完整结果。",
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
        "outOfSampleStartDate",
    )
    result = {key: params[key] for key in keys}
    if "maxParticipationPct" in params:
        result["maxParticipationPct"] = params["maxParticipationPct"]
    return result


def _estimate_budget(
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    params: Mapping[str, Any],
    schedule: tuple[str, ...],
    *, research_snapshot: Mapping[str, Any] | None = None,
) -> tuple[int, int, dict[str, int]]:
    cash = float(params["initialCash"])
    reservation_plan: dict[str, int] = {}
    for decision_date in schedule:
        if isinstance(snapshot, basket_data.BasketSnapshot):
            positions = []
            for symbol in snapshot.symbols:
                candle = next(item for item in snapshot.assets[symbol].candles if item.date == decision_date)
                positions.append({
                    "symbol": symbol,
                    "shares": 0,
                    "sellableShares": 0,
                    "marketValue": 0.0,
                    "weightPct": 0.0,
                    "close": candle.close,
                })
            portfolio = {
                "date": decision_date,
                "cash": cash,
                "equity": cash,
                "marketValue": 0.0,
                "positionWeightPct": 0.0,
                "positions": positions,
                "latestOrders": [],
            }
            decision_input = build_basket_decision_input(
                snapshot, params, as_of_date=decision_date, portfolio=portfolio
            )
        else:
            portfolio = {
                "date": decision_date,
                "cash": cash,
                "shares": 0,
                "sellableShares": 0,
                "marketValue": 0.0,
                "equity": cash,
                "positionWeightPct": 0.0,
            }
            decision_input = build_decision_input(
                snapshot, params, as_of_date=decision_date, portfolio=portfolio
            )
        if research_snapshot is not None:
            from .research_snapshot import decision_research_material
            material = decision_research_material(
                research_snapshot,
                symbols=list(snapshot.symbols) if isinstance(snapshot, basket_data.BasketSnapshot) else [snapshot.symbol],
                decision_date=decision_date,
            )
            if isinstance(snapshot, basket_data.BasketSnapshot):
                decision_input = build_basket_decision_input(snapshot, params, as_of_date=decision_date, portfolio=portfolio, research_material=material)
            else:
                decision_input = build_decision_input(snapshot, params, as_of_date=decision_date, portfolio=portfolio, research_material=material)
        messages = build_messages(decision_input)
        # Runtime reserve_decision_call also includes wire-wrapper room. Add a
        # separate account margin: filled positions and the five recent orders
        # grow the prompt after earlier decisions. Basket inputs reserve per
        # symbol so a ten-asset account is not estimated from its first asset.
        account_margin = 1_024 + (512 * len(snapshot.symbols)) if isinstance(snapshot, basket_data.BasketSnapshot) else 1_024
        reservation_plan[decision_date] = reserve_decision_call(messages) + account_margin
    output = len(schedule) * MAX_OUTPUT_TOKENS_PER_DECISION
    return sum(reservation_plan.values()), output, reservation_plan


def _out_of_sample_start_date(
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    requested_date: str | None = None,
) -> str:
    dates = (
        list(snapshot.session_dates)
        if isinstance(snapshot, basket_data.BasketSnapshot)
        else [candle.date for candle in snapshot.candles]
    )
    if len(dates) < 2:
        raise data.BacktestInputError("样本外评估至少需要两个完整交易日")
    if requested_date is not None:
        if requested_date not in dates or dates.index(requested_date) == 0:
            raise data.BacktestInputError("outOfSampleStartDate必须是区间内交易日，且前面至少保留一个交易日")
        return requested_date
    boundary = min(len(dates) - 1, max(1, int(len(dates) * 0.8)))
    return dates[boundary]


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
    if not current:
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
    "compare_financial_backtest_runs",
    "create_financial_backtest_fork_preview",
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
