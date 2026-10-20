"""Strict user-authored investment settings and read-only per-turn projection."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class InvestmentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    budgetCny: float | None = Field(default=None, gt=0, le=1e8, allow_inf_nan=False)
    horizonMonths: int | None = Field(default=None, ge=1, le=120)
    flexibleHorizon: bool | None = None
    maxLossCny: float | None = Field(default=None, ge=0, le=1e8, allow_inf_nan=False)
    cashReserveCny: float | None = Field(default=None, ge=0, le=1e8, allow_inf_nan=False)
    maxPositionPct: float | None = Field(default=None, gt=0, le=100, allow_inf_nan=False)
    market: Literal["CN"] = "CN"
    holdingsStatus: Literal["unknown", "none", "recorded"] = "unknown"

    @model_validator(mode="after")
    def limits_within_budget(self) -> InvestmentProfile:
        if self.budgetCny is not None:
            for value in (self.maxLossCny, self.cashReserveCny):
                if value is not None and value > self.budgetCny:
                    raise ValueError("最大可承受亏损与现金预留不能超过预算")
        return self


def normalize_investment_profile(value: object) -> dict | None:
    from core.web.services.financial_preferences_service import FinancialPreferenceError

    if value is None:
        return None
    try:
        return InvestmentProfile.model_validate(value).model_dump()
    except ValidationError as exc:
        raise FinancialPreferenceError("投资配置无效：请核对金额、期限、比例与预算限制") from exc


def build_investment_context_lines(agent: dict) -> list[str]:
    from core.web.services.financial_assistant_service import PROFILE, ROLE

    metadata = agent.get("metadata") or {}
    if (
        metadata.get("financialAssistantProfile") != PROFILE
        or agent.get("roleKey") != ROLE
        or agent.get("status") != "active"
        or agent.get("primaryMode") != "general"
        or metadata.get("financialAssistantSetup") != "ready"
    ):
        return []
    from .workspace import get_workspace

    lines = [
        "## 本轮投资配置",
        "这是用户显式保存的私有配置，不是情景记忆；即使个人记忆关闭仍按本轮最新配置读取。",
        "配置仅用于当前助手的投资分析，禁止传给公开搜索或外部查询。风险阈值是用户承受范围，不能保证不超损。",
    ]
    try:
        state = get_workspace(str(agent.get("agentId") or ""))
        investment = state["investmentProfile"]
        profile = json.dumps(investment, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        holding_lines = []
        if investment and investment["holdingsStatus"] == "recorded":
            positions = [
                {
                    "stock": {key: row["stock"][key] for key in ("symbol", "ticker", "name", "market")},
                    **{key: row[key] for key in ("quantity", "costPrice", "currency")},
                }
                for row in state["manualPositions"]
            ]
            if positions:
                holding_lines = [
                    "以下仅为用户手动录入的持仓，非交易账本，不含实时价，未与券商核实；不得把测试或模拟记录当作真实资产。",
                    "ManualPositions: " + json.dumps(positions, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                ]
            else:
                holding_lines = ["ManualPositions: null", "用户选择已录入，但手动持仓列表为空，实际持仓未知，不得按空仓分析。"]
    except Exception:
        # Do not reuse a previous turn's budget or interrupt unrelated context.
        return [*lines, "本轮投资配置读取失败：预算不可确认，禁止依据旧预算给出金额；请先恢复读取或请用户重新确认。"]
    return [
        *lines,
        f"InvestmentProfileRevision: {state['revision']}",
        f"InvestmentProfile: {profile}",
        "null 表示未知或未配置，不等于零；未确认预算不得猜测金额，holdingsStatus=unknown 不得当作空仓。",
        *holding_lines,
    ]
