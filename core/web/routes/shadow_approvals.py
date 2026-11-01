"""Shadow-approval observation routes (批四 Lane S, read-only).

影子审批聚合只读端点：回答「关掉某个假设对象（PA 派发豁免 / 外部代理写
always 覆盖 / 低风险 action 窗口）会多出多少 pending」。只读聚合、失败静默
空响应；不带任何 action 语义，也不进 humanAttention（那是停靠/异常车道）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


router = APIRouter(tags=["shadow-approvals"])


class ShadowApprovalSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toolName: StrictStr
    agentId: StrictStr
    turnId: StrictStr
    baselineOutcome: StrictStr
    hypothesisOutcome: StrictStr
    ruleId: StrictStr
    realOutcome: StrictStr
    createdAt: StrictStr


class ShadowApprovalHypothesisSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: StrictStr
    label: StrictStr
    # 关闭该假设对象后「会多出的」pending 数（原自动/会话批准 → 假设下需人工）。
    extraPendingCount: StrictInt
    # 关闭该假设对象后反而免掉的 pending 数（原需人工 → 假设下自动/会话批准）。
    avoidedPendingCount: StrictInt
    recentSamples: dict[str, list[ShadowApprovalSample]] = Field(default_factory=dict)


class ShadowApprovalTelemetry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engaged: StrictInt = 0
    recorded: StrictInt = 0
    ledger_write_failures: StrictInt = 0
    baseline_replica_mismatches: StrictInt = 0
    evaluation_failures: StrictInt = 0
    failureRateMilli: StrictInt = 0


class ShadowApprovalsSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    rowCount: StrictInt
    hypotheses: list[ShadowApprovalHypothesisSummary] = Field(default_factory=list)
    telemetry: ShadowApprovalTelemetry | None = None
    # 只读聚合降级标记：台账不可用/损坏时为 True，其余字段为空零值。
    degraded: bool = False


def _coerce_int(value: Any) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _coerce_str(value: Any) -> str:
    return str(value or "")


@router.get(
    "/shadow-approvals/summary",
    response_model=ShadowApprovalsSummaryResponse,
    response_model_exclude_unset=True,
)
def shadow_approvals_summary() -> dict:
    """Read-only aggregation; any failure degrades to a silent empty view."""

    from core.authorization.shadow_approval_evaluator import shadow_approvals_enabled
    from core.web.services import shadow_approval_ledger

    try:
        summary = shadow_approval_ledger.read_shadow_approval_summary()
    except Exception:
        # 台账读取永不打断端点：双层兜底后的静默空视图。
        return {
            "enabled": shadow_approvals_enabled(),
            "rowCount": 0,
            "hypotheses": [],
            "degraded": True,
        }
    telemetry = summary.get("telemetry")
    return {
        "enabled": bool(summary.get("enabled", shadow_approvals_enabled())),
        "rowCount": _coerce_int(summary.get("rowCount")),
        "degraded": bool(summary.get("degraded", False)),
        "hypotheses": [
            {
                "key": _coerce_str(item.get("key")),
                "label": _coerce_str(item.get("label")),
                "extraPendingCount": _coerce_int(item.get("extraPendingCount")),
                "avoidedPendingCount": _coerce_int(item.get("avoidedPendingCount")),
                "recentSamples": {
                    bucket: [
                        {key: _coerce_str(sample.get(key)) for key in sample}
                        for sample in samples
                        if isinstance(sample, dict)
                    ]
                    for bucket, samples in dict(item.get("recentSamples") or {}).items()
                    if isinstance(samples, list)
                },
            }
            for item in summary.get("hypotheses", [])
            if isinstance(item, dict)
        ],
        "telemetry": (
            {
                "engaged": _coerce_int(telemetry.get("engaged")),
                "recorded": _coerce_int(telemetry.get("recorded")),
                "ledger_write_failures": _coerce_int(telemetry.get("ledger_write_failures")),
                "baseline_replica_mismatches": _coerce_int(telemetry.get("baseline_replica_mismatches")),
                "evaluation_failures": _coerce_int(telemetry.get("evaluation_failures")),
                "failureRateMilli": _coerce_int(telemetry.get("failureRateMilli")),
            }
            if isinstance(telemetry, dict)
            else None
        ),
    }
