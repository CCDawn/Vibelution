"""Read-only, evidence-bound comparison manifests for completed backtest runs."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, Literal, NotRequired, TypedDict

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest.contract import sha256_json

COMPARISON_CONTRACT_VERSION = "finance-ai-backtest-v1"
COMPARISON_NOTICE = (
    "本清单仅比较同一冻结数据、共同参数与回测契约下的历史结果；"
    "样本外结果是回顾性检验，不代表未来收益。"
)

ComparisonAxis = Literal["strategy", "model", "parameter"]
ParameterKey = Literal[
    "maxPositionPct",
    "decisionInterval",
    "commissionBps",
    "minimumCommission",
    "slippageBps",
    "maxParticipationPct",
]
ComparisonStatus = Literal["comparable", "incomplete", "incompatible"]

_PARAMETER_KEYS = frozenset(
    {
        "maxPositionPct",
        "decisionInterval",
        "commissionBps",
        "minimumCommission",
        "slippageBps",
        "maxParticipationPct",
    }
)


class ComparisonProvenance(TypedDict):
    contractVersion: str
    commonParamsHash: str
    strategyHash: str
    sourceRunId: NotRequired[str]


class ComparisonReason(TypedDict):
    code: str
    runIds: list[str]
    message: str


class ComparisonRow(TypedDict):
    runId: str
    status: str
    modelId: str | None
    modelConfigHash: str | None
    strategy: str | None
    strategyHash: str | None
    callsUsed: int | None
    tokensUsed: int | None
    maxTokens: int | None
    metrics: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    parameterValue: NotRequired[float | None]


class ComparisonResult(TypedDict):
    comparisonId: str
    axis: str
    status: ComparisonStatus
    reasons: list[ComparisonReason]
    dataHash: str | None
    commonParamsHash: str | None
    outOfSampleStartDate: str | None
    rows: list[ComparisonRow]
    notice: str
    parameterKey: NotRequired[str]


_COVERAGE_FIELDS = (
    "actualStartDate",
    "actualEndDate",
    "availableStartDate",
    "availableEndDate",
    "tradingDays",
    "warmupBars",
    "tradingCalendarStatus",
    "calendarSymbol",
    "complete",
)
_COST_PARAMETER_KEYS = ("commissionBps", "minimumCommission", "slippageBps")
_INTEGER_PARAMETER_KEYS = ("decisionInterval", "maxDecisions")
_NUMERIC_PARAMETER_KEYS = (
    "initialCash",
    "maxPositionPct",
    *_COST_PARAMETER_KEYS,
)


def build_comparison_provenance(record: Mapping[str, Any]) -> ComparisonProvenance:
    """Build versioned fingerprints from frozen data and execution inputs.

    Strategy text and model identity intentionally have separate comparison
    axes, so neither enters ``commonParamsHash``.  Optional source-run metadata
    is preserved for audit display but is excluded from both hashes.
    """
    if not isinstance(record, Mapping):
        raise TypeError("回测记录必须是对象")
    common_inputs = _common_inputs(record)
    strategy = _normalized_strategy(record)
    result: ComparisonProvenance = {
        "contractVersion": COMPARISON_CONTRACT_VERSION,
        "commonParamsHash": sha256_json(common_inputs),
        "strategyHash": sha256_json(
            {"contractVersion": COMPARISON_CONTRACT_VERSION, "strategy": strategy}
        ),
    }
    source_run_id = _source_run_id(record)
    if source_run_id:
        result["sourceRunId"] = source_run_id
    return result


def compare_runs(
    records: Sequence[Mapping[str, Any]],
    axis: ComparisonAxis,
    parameter_key: str | None = None,
) -> ComparisonResult:
    """Return an in-memory comparison manifest; never ranks or writes runs."""
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        selected: list[Any] = []
    else:
        selected = list(records)

    run_ids = [_run_id(record, index) for index, record in enumerate(selected)]
    selected_parameter_key = (
        parameter_key
        if axis == "parameter" and parameter_key in _PARAMETER_KEYS
        else None
    )
    rows = [
        _comparison_row(record, run_id, parameter_key=selected_parameter_key)
        for record, run_id in zip(selected, run_ids)
    ]
    reasons: list[ComparisonReason] = []
    reason_indexes: dict[str, int] = {}
    reason_codes: set[str] = set()

    def add_reason(code: str, affected: Sequence[str], message: str) -> None:
        reason_codes.add(code)
        unique_ids = list(dict.fromkeys(item for item in affected if item))
        existing = reason_indexes.get(code)
        if existing is None:
            reason_indexes[code] = len(reasons)
            reasons.append({"code": code, "runIds": unique_ids, "message": message})
            return
        current = reasons[existing]
        current["runIds"] = list(dict.fromkeys([*current["runIds"], *unique_ids]))

    if len(selected) < 2 or len(selected) > 4:
        add_reason(
            "run_count_out_of_range",
            run_ids,
            "一次比较需要选择2到4条不同的回测记录。",
        )
    if axis not in {"strategy", "model", "parameter"}:
        add_reason("invalid_axis", run_ids, "比较维度无效，只支持策略、模型或单参数。")
    if axis == "parameter" and selected_parameter_key is None:
        add_reason("invalid_parameter_key", run_ids, "参数比较必须指定支持的单一回测参数。")
    elif axis != "parameter" and parameter_key is not None:
        add_reason("invalid_parameter_key", run_ids, "策略或模型比较不能携带参数键。")
    nonempty_ids = [item for item in run_ids if item]
    if len(nonempty_ids) != len(set(nonempty_ids)):
        duplicated = {item for item in nonempty_ids if nonempty_ids.count(item) > 1}
        add_reason("duplicate_run_ids", sorted(duplicated), "比较清单不能重复引用同一条回测记录。")

    provenance_rows: list[ComparisonProvenance | None] = []
    common_inputs_rows: list[dict[str, Any] | None] = []
    records_as_mappings: list[Mapping[str, Any] | None] = []
    for record, run_id in zip(selected, run_ids):
        if not isinstance(record, Mapping):
            add_reason("invalid_run_record", [run_id], "回测记录格式无效，无法验证比较依据。")
            provenance_rows.append(None)
            common_inputs_rows.append(None)
            records_as_mappings.append(None)
            continue

        records_as_mappings.append(record)
        stored = record.get("comparisonProvenance")
        if not isinstance(stored, Mapping):
            add_reason(
                "provenance_missing",
                [run_id],
                "该回测缺少冻结的比较依据；旧回测不会按当前算法追溯认证。",
            )
        elif stored.get("contractVersion") != COMPARISON_CONTRACT_VERSION:
            add_reason(
                "unsupported_contract_version",
                [run_id],
                "回测执行或决策契约版本不同，不能按当前口径比较。",
            )

        try:
            common_inputs = _common_inputs(record)
            expected = build_comparison_provenance(record)
        except (TypeError, ValueError, InvalidOperation, OverflowError):
            add_reason(
                "invalid_comparison_inputs",
                [run_id],
                "回测缺少有效的冻结数据、日期、策略或执行参数，无法验证可比性。",
            )
            provenance_rows.append(None)
            common_inputs_rows.append(None)
            continue

        common_inputs_rows.append(common_inputs)
        provenance_rows.append(expected)
        if (
            isinstance(stored, Mapping)
            and stored.get("contractVersion") == COMPARISON_CONTRACT_VERSION
            and any(
                stored.get(key) != expected.get(key)
                for key in ("contractVersion", "commonParamsHash", "strategyHash", "sourceRunId")
            )
        ):
            add_reason(
                "provenance_mismatch",
                [run_id],
                "保存的比较指纹与回测冻结数据、策略或共同参数不一致。",
            )

    _compare_shared_evidence(
        records_as_mappings,
        run_ids,
        common_inputs_rows,
        provenance_rows,
        reason_codes,
        add_reason,
        parameter_key=selected_parameter_key,
    )
    if axis == "strategy":
        _compare_model_identity(records_as_mappings, run_ids, add_reason)
    elif axis == "model":
        _compare_model_identity(records_as_mappings, run_ids, add_reason, require_equal=False)
        _compare_strategy_identity(run_ids, provenance_rows, add_reason)
    elif axis == "parameter":
        _compare_model_identity(records_as_mappings, run_ids, add_reason)
        _compare_strategy_identity(run_ids, provenance_rows, add_reason)

    incomplete_ids: list[str] = []
    evaluation_incomplete_ids: list[str] = []
    for record, run_id in zip(records_as_mappings, run_ids):
        if record is None:
            continue
        if str(record.get("status") or "").strip().lower() != "completed":
            incomplete_ids.append(run_id)
        if not _has_completed_evaluation(record):
            evaluation_incomplete_ids.append(run_id)
    if incomplete_ids:
        add_reason(
            "run_incomplete",
            incomplete_ids,
            "所有回测都完成后，才会生成比较结论；当前清单只提供进度信息。",
        )
    if evaluation_incomplete_ids:
        add_reason(
            "evaluation_incomplete",
            evaluation_incomplete_ids,
            "回测尚未生成完整的样本内与样本外指标。",
        )

    blocking_reasons = [
        reason
        for reason in reasons
        if reason["code"] not in {"run_incomplete", "evaluation_incomplete"}
    ]
    status: ComparisonStatus = (
        "incompatible"
        if blocking_reasons
        else ("incomplete" if reasons else "comparable")
    )

    data_hash = _same_value(
        [record.get("dataHash") if record is not None else None for record in records_as_mappings]
    )
    common_hash_values = [
        provenance.get("commonParamsHash") if provenance is not None else None
        for provenance in provenance_rows
    ]
    common_hash = _same_value(common_hash_values)
    # Do not project a freshly computed value as a certified manifest hash if
    # a run lacks a valid stored provenance record or its hashes drifted.
    provenance_verified = all(
        isinstance(record, Mapping)
        and isinstance(record.get("comparisonProvenance"), Mapping)
        and record["comparisonProvenance"].get("contractVersion") == COMPARISON_CONTRACT_VERSION
        and provenance is not None
        and all(
            record["comparisonProvenance"].get(key) == provenance.get(key)
            for key in ("contractVersion", "commonParamsHash", "strategyHash", "sourceRunId")
        )
        for record, provenance in zip(records_as_mappings, provenance_rows)
    )
    if not provenance_verified:
        common_hash = None
    elif selected_parameter_key is not None:
        shared_hashes = [
            _parameter_shared_hash(inputs, selected_parameter_key)
            if inputs is not None
            else None
            for inputs in common_inputs_rows
        ]
        common_hash = _same_value(shared_hashes)
    oos_start = _same_value(
        [
            inputs.get("outOfSampleStartDate") if inputs is not None else None
            for inputs in common_inputs_rows
        ]
    )

    evidence = [
        {
            "runId": run_id,
            "dataHash": record.get("dataHash") if record is not None else None,
            "comparisonProvenance": record.get("comparisonProvenance") if record is not None else None,
            "row": row,
        }
        for run_id, row, record in zip(run_ids, rows, records_as_mappings)
    ]
    comparison_id = "comparison-" + sha256_json(
        {
            "axis": str(axis),
            "parameterKey": selected_parameter_key,
            "orderedRunIds": run_ids,
            "evidence": evidence,
        }
    )
    result: ComparisonResult = {
        "comparisonId": comparison_id,
        "axis": str(axis),
        "status": status,
        "reasons": reasons,
        "dataHash": data_hash,
        "commonParamsHash": common_hash,
        "outOfSampleStartDate": oos_start,
        "rows": rows,
        "notice": (
            "参数对照仅展示每条独立完成回测的样本外指标，不排序或选胜者；LLM调用随机性仍存在，事后选择参数会产生试参偏差，结果不等于预先注册实验。"
            if axis == "parameter"
            else COMPARISON_NOTICE
        ),
    }
    if selected_parameter_key is not None:
        result["parameterKey"] = selected_parameter_key
    return result


def _common_inputs(record: Mapping[str, Any]) -> dict[str, Any]:
    params = record.get("params")
    if not isinstance(params, Mapping):
        raise TypeError("params")

    data_hash = record.get("dataHash")
    if not isinstance(data_hash, str) or not data_hash.strip():
        raise ValueError("dataHash")

    symbols = _canonical_symbols(record)
    schedule = _canonical_schedule(record.get("decisionSchedule"))
    date_coverage = _canonical_coverage(record.get("dateCoverage"), symbols)
    _validate_schedule_coverage(schedule, date_coverage)
    out_of_sample = _canonical_optional_date(
        record.get("outOfSampleStartDate"), "outOfSampleStartDate"
    )
    params_oos = _canonical_optional_date(
        params.get("outOfSampleStartDate"), "params.outOfSampleStartDate"
    )
    if out_of_sample is not None and params_oos is not None and out_of_sample != params_oos:
        raise ValueError("outOfSampleStartDate mismatch")
    if out_of_sample is None:
        out_of_sample = params_oos
    if out_of_sample is not None and not _date_within_coverage(out_of_sample, date_coverage):
        raise ValueError("outOfSampleStartDate outside coverage")

    parameters: dict[str, Any] = {}
    for key in _NUMERIC_PARAMETER_KEYS:
        parameters[key] = _canonical_decimal(params.get(key), f"params.{key}")
    for key in _INTEGER_PARAMETER_KEYS:
        parameters[key] = _canonical_integer(params.get(key), f"params.{key}")
    # Optional extension: omitting it preserves fingerprints of legacy uncapped runs.
    if params.get("maxParticipationPct") is not None:
        participation = _canonical_decimal(params["maxParticipationPct"], "params.maxParticipationPct")
        if not Decimal("0.1") <= Decimal(participation) <= Decimal(100):
            raise ValueError("maxParticipationPct outside range")
        parameters["maxParticipationPct"] = participation
        parameters["participationRule"] = "daily_volume_board_lots_v1"
    if "quantityRuleVersion" in params:
        quantity_rule = params["quantityRuleVersion"]
        if quantity_rule not in ("ashare_quantity_v2", "legacy_100_v1"):
            raise ValueError("quantityRuleVersion unsupported")
        parameters["quantityRuleVersion"] = quantity_rule
    if "corporateActionPolicy" in params:
        action_policy = params["corporateActionPolicy"]
        if action_policy not in ("block", "verified_cash_dividends"):
            raise ValueError("corporateActionPolicy unsupported")
        parameters["corporateActionPolicy"] = action_policy
    max_tokens = _canonical_integer(record.get("maxTokens"), "maxTokens")
    params_max_tokens = params.get("maxTokens")
    if params_max_tokens is not None and max_tokens != _canonical_integer(params_max_tokens, "params.maxTokens"):
        raise ValueError("maxTokens mismatch")

    adjustment = record.get("adjustment")
    if not isinstance(adjustment, str) or not adjustment.strip():
        raise ValueError("adjustment")

    common_parameters = {
        **parameters,
        "maxTokens": max_tokens,
    }
    research_mode = record.get("researchInput", "price_only")
    if research_mode in {"announcements", "financial_reports"}:
        research_hash = record.get("researchHash")
        if not isinstance(research_hash, str) or len(research_hash) != 64 or any(c not in "0123456789abcdef" for c in research_hash):
            raise ValueError("researchHash")
        common_parameters["researchInput"] = research_mode
        common_parameters["researchHash"] = research_hash
        common_parameters["researchContract"] = (
            "prior_day_financial_pdf_excerpts_v1"
            if research_mode == "financial_reports" else "prior_day_announcement_metadata_v1"
        )
    elif research_mode != "price_only" or record.get("researchHash"):
        raise ValueError("researchInput mismatch")
    return {
        "contractVersion": COMPARISON_CONTRACT_VERSION,
        "dataHash": data_hash.strip(),
        "symbols": symbols,
        "dateCoverage": date_coverage,
        "decisionSchedule": schedule,
        "outOfSampleStartDate": out_of_sample,
        "adjustment": adjustment.strip().lower(),
        "params": common_parameters,
    }


def _normalized_strategy(record: Mapping[str, Any]) -> str:
    params = record.get("params")
    params = params if isinstance(params, Mapping) else {}
    raw = record.get("strategy", params.get("strategy"))
    if not isinstance(raw, str):
        raise TypeError("strategy")
    normalized = unicodedata.normalize("NFC", raw.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not normalized:
        raise ValueError("strategy")
    return normalized


def _canonical_symbols(record: Mapping[str, Any]) -> list[str]:
    raw_symbols = record.get("symbols")
    raw_symbol = record.get("symbol")
    if raw_symbols is None:
        raw_symbols = [raw_symbol] if raw_symbol is not None else []
    if not isinstance(raw_symbols, Sequence) or isinstance(raw_symbols, (str, bytes)):
        raise TypeError("symbols")
    if not raw_symbols:
        raise ValueError("symbols")
    normalized: list[str] = []
    for raw in raw_symbols:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("symbol")
        try:
            normalized.append(market.normalize_a_share_symbol(raw))
        except (TypeError, ValueError, market.MarketDataError) as exc:
            raise ValueError("symbol") from exc
    canonical = sorted(normalized)
    if len(canonical) != len(set(canonical)):
        raise ValueError("duplicate symbol")
    if raw_symbol is not None:
        try:
            normalized_symbol = market.normalize_a_share_symbol(str(raw_symbol))
        except (TypeError, ValueError, market.MarketDataError) as exc:
            raise ValueError("symbol") from exc
        if normalized_symbol not in canonical or len(canonical) != 1:
            raise ValueError("symbol/symbols mismatch")
    return canonical


def _canonical_coverage(raw: Any, symbols: Sequence[str]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("dateCoverage")
    if "actualStartDate" in raw or "actualEndDate" in raw:
        return {"shared": _coverage_fields(raw)}

    result: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            raise TypeError("dateCoverage")
        try:
            symbol = market.normalize_a_share_symbol(key)
        except (TypeError, ValueError, market.MarketDataError) as exc:
            raise ValueError("dateCoverage symbol") from exc
        result[symbol] = _coverage_fields(value)
    if not result or any(symbol not in result for symbol in symbols):
        raise ValueError("dateCoverage constituents")
    return {symbol: result[symbol] for symbol in sorted(result)}


def _coverage_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    required = ("actualStartDate", "actualEndDate", "tradingDays")
    if any(key not in raw for key in required):
        raise ValueError("actual date coverage")
    fields: dict[str, Any] = {}
    for key in _COVERAGE_FIELDS:
        if key not in raw:
            continue
        value = raw[key]
        if key in {"actualStartDate", "actualEndDate", "availableStartDate", "availableEndDate"}:
            fields[key] = _canonical_optional_date(value, key)
        elif key in {"tradingDays", "warmupBars"}:
            fields[key] = _canonical_integer(value, key)
        elif key == "complete":
            if not isinstance(value, bool):
                raise ValueError("dateCoverage.complete")
            fields[key] = value
        elif value is None:
            fields[key] = None
        elif isinstance(value, str):
            fields[key] = value.strip()
        else:
            raise ValueError(f"dateCoverage.{key}")
    if fields["tradingDays"] <= 0 or fields["actualEndDate"] < fields["actualStartDate"]:
        raise ValueError("actual date coverage")
    if fields.get("complete") is False:
        raise ValueError("incomplete date coverage")
    return fields


def _validate_schedule_coverage(
    schedule: Sequence[str], date_coverage: Mapping[str, Any]
) -> None:
    coverages = (
        [date_coverage["shared"]]
        if "shared" in date_coverage
        else list(date_coverage.values())
    )
    for coverage in coverages:
        if (
            schedule[0] < coverage["actualStartDate"]
            or schedule[-1] > coverage["actualEndDate"]
            or len(schedule) > coverage["tradingDays"]
        ):
            raise ValueError("decisionSchedule outside date coverage")


def _date_within_coverage(value: str, date_coverage: Mapping[str, Any]) -> bool:
    coverages = (
        [date_coverage["shared"]]
        if "shared" in date_coverage
        else list(date_coverage.values())
    )
    return all(
        coverage["actualStartDate"] <= value <= coverage["actualEndDate"]
        for coverage in coverages
    )


def _canonical_schedule(raw: Any) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise ValueError("decisionSchedule")
    result = [_canonical_date(item, "decisionSchedule") for item in raw]
    if any(current <= previous for previous, current in pairwise(result)):
        raise ValueError("decisionSchedule ordering")
    return result


def _canonical_optional_date(raw: Any, label: str) -> str | None:
    if raw is None:
        return None
    return _canonical_date(raw, label)


def _canonical_date(raw: Any, label: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(label)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(label) from exc
    if parsed.isoformat() != raw:
        raise ValueError(label)
    return raw


def _canonical_integer(raw: Any, label: str) -> int:
    if isinstance(raw, bool):
        raise TypeError(label)
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label) from exc
    if value != raw or value < 0:
        raise ValueError(label)
    return value


def _canonical_decimal(raw: Any, label: str) -> str:
    if isinstance(raw, bool):
        raise TypeError(label)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(label) from exc
    if not value.is_finite() or value < 0:
        raise ValueError(label)
    normalized = value.normalize()
    return format(normalized, "f")


def _source_run_id(record: Mapping[str, Any]) -> str | None:
    raw = record.get("sourceRunId")
    if raw is None:
        raw = record.get("comparisonSourceRunId")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _run_id(record: Any, index: int) -> str:
    if not isinstance(record, Mapping):
        return ""
    value = record.get("runId")
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.strip()


def _comparison_row(
    record: Any, run_id: str, *, parameter_key: str | None = None
) -> ComparisonRow:
    if not isinstance(record, Mapping):
        return {
            "runId": run_id,
            "status": "invalid",
            "modelId": None,
            "modelConfigHash": None,
            "strategy": None,
            "strategyHash": None,
            "callsUsed": None,
            "tokensUsed": None,
            "maxTokens": None,
            "metrics": None,
            "evaluation": None,
        }
    params = record.get("params")
    params = params if isinstance(params, Mapping) else {}
    model_id = _optional_string(record.get("modelId"))
    config_hash = _model_config_hash(record)
    strategy = record.get("strategy", params.get("strategy"))
    try:
        strategy_hash = build_comparison_provenance(record).get("strategyHash")
    except (TypeError, ValueError, InvalidOperation, OverflowError):
        strategy_hash = None
    row: ComparisonRow = {
        "runId": run_id,
        "status": str(record.get("status") or "unknown").strip().lower(),
        "modelId": model_id,
        "modelConfigHash": config_hash,
        "strategy": strategy if isinstance(strategy, str) else None,
        "strategyHash": strategy_hash,
        "callsUsed": _optional_nonnegative_int(record.get("callsUsed")),
        "tokensUsed": _optional_nonnegative_int(record.get("tokensUsed")),
        "maxTokens": _optional_nonnegative_int(
            record.get("maxTokens", params.get("maxTokens"))
        ),
        "metrics": dict(record["metrics"]) if isinstance(record.get("metrics"), Mapping) else None,
        "evaluation": dict(record["evaluation"]) if isinstance(record.get("evaluation"), Mapping) else None,
    }
    if parameter_key in _PARAMETER_KEYS:
        raw_parameter_value = params.get(parameter_key)
        if raw_parameter_value is None:
            row["parameterValue"] = None
        else:
            try:
                row["parameterValue"] = float(raw_parameter_value)
            except (TypeError, ValueError, OverflowError):
                row["parameterValue"] = None
    return row


def _compare_shared_evidence(
    records: Sequence[Mapping[str, Any] | None],
    run_ids: Sequence[str],
    common_inputs: Sequence[dict[str, Any] | None],
    provenance_rows: Sequence[ComparisonProvenance | None],
    reason_codes: set[str],
    add_reason: Any,
    *,
    parameter_key: str | None = None,
) -> None:
    usable = [
        (record, run_id, inputs, provenance)
        for record, run_id, inputs, provenance in zip(records, run_ids, common_inputs, provenance_rows)
        if record is not None and inputs is not None and provenance is not None
    ]
    if len(usable) < 2:
        return
    base_record, base_id, base_inputs, base_provenance = usable[0]

    mismatched = [run_id for record, run_id, *_ in usable if record.get("dataHash") != base_record.get("dataHash")]
    if mismatched:
        add_reason("data_hash_mismatch", [base_id, *mismatched], "冻结行情数据不同，不能在同一清单中比较。")

    mismatched = [
        run_id
        for _record, run_id, inputs, _provenance in usable
        if inputs.get("outOfSampleStartDate") != base_inputs.get("outOfSampleStartDate")
    ]
    if mismatched:
        add_reason("out_of_sample_boundary_mismatch", [base_id, *mismatched], "样本外起点不同，不能比较样本外表现。")

    _compare_component(usable, base_inputs, "symbols", "symbols_mismatch", "组合股票范围不同，不能直接比较。", add_reason, base_id)
    _compare_component(usable, base_inputs, "dateCoverage", "date_coverage_mismatch", "实际行情覆盖区间或交易日历不同，不能直接比较。", add_reason, base_id)
    schedule_changed_by_parameter = parameter_key == "decisionInterval"
    schedule_mismatched = any(
        inputs.get("decisionSchedule") != base_inputs.get("decisionSchedule")
        for _record, _run_id, inputs, _provenance in usable
    )
    has_announcement_input = any(
        inputs["params"].get("researchInput", "price_only") != "price_only"
        for _record, _run_id, inputs, _provenance in usable
    )
    if not schedule_changed_by_parameter:
        _compare_component(usable, base_inputs, "decisionSchedule", "decision_schedule_mismatch", "模型决策交易日程不同，不能直接比较。", add_reason, base_id)
    elif schedule_mismatched and has_announcement_input:
        add_reason(
            "research_schedule_mismatch",
            [
                base_id,
                *[
                    run_id
                    for _record, run_id, inputs, _provenance in usable
                    if inputs.get("decisionSchedule") != base_inputs.get("decisionSchedule")
                ],
            ],
            "公告研究快照绑定原决策日程；频率变化造成日程不匹配，不能重新联网补取公告。",
        )
    _compare_component(usable, base_inputs, "adjustment", "adjustment_mismatch", "行情复权口径不同，不能直接比较。", add_reason, base_id)

    base_params = base_inputs["params"]
    param_codes = (
        ("initialCash", "initial_cash_mismatch", "初始现金不同，不能直接比较。"),
        ("maxPositionPct", "position_limit_mismatch", "仓位上限不同，不能直接比较。"),
        (
            "maxParticipationPct",
            "participation_limit_mismatch",
            "成交量参与率上限不同，不能直接比较。",
        ),
        (
            "quantityRuleVersion",
            "quantity_rule_mismatch",
            "板块股数撮合规则不同，不能直接比较。",
        ),
        (
            "corporateActionPolicy",
            "corporate_action_policy_mismatch",
            "公司行动记账规则不同，不能直接比较。",
        ),
        (
            "commissionBps",
            "cost_model_mismatch",
            "佣金、最低费用或滑点参数不同，不能直接比较。",
        ),
        (
            "minimumCommission",
            "cost_model_mismatch",
            "佣金、最低费用或滑点参数不同，不能直接比较。",
        ),
        (
            "slippageBps",
            "cost_model_mismatch",
            "佣金、最低费用或滑点参数不同，不能直接比较。",
        ),
        (
            "decisionInterval",
            "decision_schedule_mismatch",
            "决策频率或最大决策数不同，不能直接比较。",
        ),
        (
            "maxDecisions",
            "decision_schedule_mismatch",
            "决策频率或最大决策数不同，不能直接比较。",
        ),
        ("maxTokens", "token_budget_mismatch", "模型 token 预算不同，不能直接比较。"),
    )
    for key, code, message in param_codes:
        if key == parameter_key:
            continue
        affected = [
            run_id
            for _record, run_id, inputs, _provenance in usable
            if inputs["params"].get(key) != base_params.get(key)
        ]
        if affected:
            add_reason(code, [base_id, *affected], message)

    if parameter_key is None:
        provenance_mismatch_ids = [
            run_id
            for _record, run_id, _inputs, provenance in usable
            if provenance.get("commonParamsHash") != base_provenance.get("commonParamsHash")
        ]
    else:
        shared_hashes = [
            _parameter_shared_hash(inputs, parameter_key)
            for _record, _run_id, inputs, _provenance in usable
        ]
        if len(set(shared_hashes)) == 1:
            provenance_mismatch_ids = []
        else:
            provenance_mismatch_ids = [run_id for _record, run_id, *_ in usable[1:]]

        parameter_values = [inputs["params"].get(parameter_key) for _, _, inputs, _ in usable]
        if len(set(parameter_values)) < 2:
            add_reason(
                "parameter_not_varied",
                [run_id for _record, run_id, *_ in usable],
                "所选回测参数没有变化，无法形成参数敏感性对照。",
            )
    already_explained_common_mismatch = bool(
        reason_codes
        & {
            "symbols_mismatch",
            "date_coverage_mismatch",
            "decision_schedule_mismatch",
            "adjustment_mismatch",
            "initial_cash_mismatch",
            "position_limit_mismatch",
            "cost_model_mismatch",
            "token_budget_mismatch",
            "research_schedule_mismatch",
        }
    )
    if provenance_mismatch_ids and not already_explained_common_mismatch:
        add_reason("common_params_mismatch", [base_id, *provenance_mismatch_ids], "冻结回测共同参数指纹不同，不能直接比较。")


def _parameter_shared_hash(inputs: Mapping[str, Any], parameter_key: str) -> str:
    shared = dict(inputs)
    params = dict(inputs["params"])
    params.pop(parameter_key, None)
    if parameter_key == "maxParticipationPct":
        params.pop("participationRule", None)
    shared["params"] = params
    if (
        parameter_key == "decisionInterval"
        and params.get("researchInput", "price_only") == "price_only"
    ):
        shared.pop("decisionSchedule", None)
    return sha256_json(shared)


def _compare_component(
    usable: Sequence[tuple[Mapping[str, Any], str, dict[str, Any], ComparisonProvenance]],
    base_inputs: Mapping[str, Any],
    key: str,
    code: str,
    message: str,
    add_reason: Any,
    base_id: str,
) -> None:
    affected = [
        run_id
        for _record, run_id, inputs, _provenance in usable
        if inputs.get(key) != base_inputs.get(key)
    ]
    if affected:
        add_reason(code, [base_id, *affected], message)


def _compare_model_identity(
    records: Sequence[Mapping[str, Any] | None], run_ids: Sequence[str], add_reason: Any,
    *, require_equal: bool = True,
) -> None:
    usable = [(record, run_id) for record, run_id in zip(records, run_ids) if record is not None]
    missing = [
        run_id
        for record, run_id in usable
        if not _optional_string(record.get("modelId"))
        or not _model_config_hash(record)
    ]
    if missing:
        add_reason("model_identity_missing", missing, "模型身份或配置指纹缺失，不能确认比较依据。")

    if not require_equal:
        return

    base = usable[0] if usable else None
    if base is None:
        return
    base_record, base_id = base
    model_ids = [run_id for record, run_id in usable if record.get("modelId") != base_record.get("modelId")]
    if model_ids:
        add_reason("model_id_mismatch", [base_id, *model_ids], "策略比较要求所有回测使用相同模型。")
    config_ids = [
        run_id
        for record, run_id in usable
        if _model_config_hash(record) != _model_config_hash(base_record)
    ]
    if config_ids:
        add_reason("model_config_mismatch", [base_id, *config_ids], "策略比较要求模型配置指纹一致。")


def _compare_strategy_identity(
    run_ids: Sequence[str],
    provenance_rows: Sequence[ComparisonProvenance | None],
    add_reason: Any,
) -> None:
    usable = [(run_id, provenance) for run_id, provenance in zip(run_ids, provenance_rows) if provenance is not None]
    missing = [run_id for run_id, _provenance in zip(run_ids, provenance_rows) if _provenance is None]
    if missing:
        add_reason("strategy_identity_missing", missing, "策略指纹缺失，不能确认模型轴条件。")
    if not usable:
        return
    base_id, base = usable[0]
    affected = [run_id for run_id, provenance in usable if provenance.get("strategyHash") != base.get("strategyHash")]
    if affected:
        add_reason("strategy_mismatch", [base_id, *affected], "模型比较要求所有回测使用相同策略。")


def _has_completed_evaluation(record: Mapping[str, Any]) -> bool:
    metrics = record.get("metrics")
    evaluation = record.get("evaluation")
    if not isinstance(metrics, Mapping) or not metrics:
        return False
    if not isinstance(evaluation, Mapping):
        return False
    in_sample = evaluation.get("inSample")
    out_of_sample = evaluation.get("outOfSample")
    return (
        isinstance(in_sample, Mapping)
        and isinstance(in_sample.get("metrics"), Mapping)
        and isinstance(out_of_sample, Mapping)
        and isinstance(out_of_sample.get("metrics"), Mapping)
    )


def _same_value(values: Sequence[Any]) -> Any:
    if not values or values[0] is None or any(value != values[0] for value in values[1:]):
        return None
    return values[0]


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _model_config_hash(record: Mapping[str, Any]) -> str | None:
    return _optional_string(record.get("modelConfigHash")) or _optional_string(
        record.get("modelFingerprint")
    )


def _optional_nonnegative_int(value: Any) -> int | None:
    try:
        return _canonical_integer(value, "count")
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "COMPARISON_CONTRACT_VERSION",
    "COMPARISON_NOTICE",
    "ComparisonAxis",
    "ComparisonProvenance",
    "ComparisonReason",
    "ComparisonResult",
    "ComparisonRow",
    "ComparisonStatus",
    "build_comparison_provenance",
    "compare_runs",
]
