"""Owned research proposals with explicit approval and paper-ledger execution."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from core.web.services import financial_market_service as market
from core.web.services import financial_report_service as reports
from core.web.services import financial_research_service as research
from core.web.services.financial_paper import ledger
from core.web.services.financial_paper import rebalance as paper
from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

from . import decision, store
from .risk import (
    QUOTE_TTL_SECONDS,
    RebalanceConflict,
    RebalanceError,
    RebalanceNotFound,
    build_plan,
    digest,
    normalize_policy,
    normalize_targets,
)

GENERATION_TIMEOUT_SECONDS = 600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(agent_id: str, proposal_id: str, status: str) -> None:
    record_runtime_scene_event_quietly("finance", "portfolio_proposal", f"finance.portfolio_proposal.{status}", outcome=status, lifecycle=True, fields={"agentId": agent_id, "proposalId": proposal_id, "simulationOnly": True})


def _public(proposal: dict) -> dict:
    result = {key: value for key, value in proposal.items() if not key.startswith("_")}
    if result["status"] == "generating" and (_now() - datetime.fromisoformat(result["createdAt"])).total_seconds() > GENERATION_TIMEOUT_SECONDS:
        result["status"] = "failed"
        result["error"] = "生成结果未知，本请求不会自动重试；重新生成将发起新的模型调用"
    return result


def _read_reports(agent_id: str, references: list[dict]) -> tuple[list[dict], list[dict]]:
    if not 1 <= len(references) <= 5:
        raise RebalanceError("请选择1–5份已完成研究报告")
    refs, documents, seen = [], [], set()
    for ref in references:
        identity = (str(ref.get("sessionId") or "").strip(), str(ref.get("turnId") or "").strip())
        if identity in seen:
            raise RebalanceError("研究报告不能重复选择")
        seen.add(identity)
        exported = reports.export_financial_report(agent_id, session_id=identity[0], turn_id=identity[1], format="json")
        document = json.loads(exported["content"])
        text = str(document["content"])
        refs.append({"sessionId": identity[0], "turnId": identity[1], "contentHash": digest(text)})
        documents.append({"sessionId": identity[0], "turnId": identity[1], "completedAt": document["completedAt"], "text": text[:6000], "truncated": len(text) > 6000})
    return refs, documents


def _validate_sources(agent_id: str, proposal: dict) -> None:
    refs, _ = _read_reports(agent_id, proposal["reportRefs"])
    if refs != proposal["reportRefs"]:
        raise RebalanceConflict("研究依据已变化，请重新生成组合建议")


def _quotes(symbols: list[str]) -> dict:
    batch = research.batch_quotes(symbols)
    result = {}
    for symbol in symbols:
        try:
            result[symbol] = ledger._quote_from_batch(symbol, batch)
        except market.MarketDataError:
            continue
    return result


def _plan_hash(proposal: dict) -> str:
    return digest({key: proposal[key] for key in ("proposalId", "targets", "policy", "orders", "summaryReason", "reportRefs", "expiresAt", "_context", "_quotes")})


def _refresh_plan(agent_id: str, proposal: dict, targets: list[dict], policy: dict) -> dict:
    context = paper.read_rebalance_context(agent_id)
    if {row["symbol"] for row in context["positions"]} - set(proposal["_symbols"]):
        raise RebalanceConflict("账户增加了新的持仓，请重新生成包含全部持仓的组合建议")
    normalized = normalize_targets(targets, proposal["_symbols"])
    quotes = _quotes(proposal["_symbols"])
    now = _now()
    plan = build_plan(context, normalized, quotes, policy, now=now)
    expiry = now + timedelta(seconds=QUOTE_TTL_SECONDS)
    for quote in quotes.values():
        try:
            fetched = datetime.fromisoformat(quote["fetchedAt"])
            if fetched.tzinfo is not None:
                expiry = min(expiry, fetched + timedelta(seconds=QUOTE_TTL_SECONDS))
        except (ValueError, TypeError):
            expiry = now
    proposal.update({"targets": normalized, "policy": policy, "riskChecks": plan["riskChecks"], "orders": plan["orders"], "metrics": plan["metrics"], "status": "ready" if plan["canApprove"] else "blocked", "expiresAt": expiry.isoformat(), "error": None, "_context": context, "_quotes": quotes})
    # Bind approval to server-derived account, quotes, sources, policy and exact
    # orders. A new preview invalidates the earlier hash even without a trade.
    proposal["planHash"] = _plan_hash(proposal)
    return proposal


def create_proposal(agent_id: str, payload: dict) -> dict:
    ledger._financial_agent(agent_id)
    proposal_id = store.identifier(payload.get("clientRequestId", ""))
    requested = payload.get("symbols", [])
    if not isinstance(requested, list) or not 1 <= len(requested) <= 10:
        raise RebalanceError("请选择1–10只A股候选")
    symbols = sorted({market.normalize_a_share_symbol(str(symbol)) for symbol in requested})
    if len(symbols) != len(requested):
        raise RebalanceError("候选股票不能重复")
    instruction = str(payload.get("instruction") or "").strip()
    if not 1 <= len(instruction) <= 2000:
        raise RebalanceError("请填写1–2000字的组合目标")
    policy = normalize_policy(payload.get("policy"))
    references = payload.get("reports", [])
    request_hash = digest({"symbols": symbols, "instruction": instruction, "policy": policy, "reports": references})
    with store.lock(agent_id, proposal_id):
        try:
            existing = store.read(agent_id, proposal_id)
        except RebalanceNotFound:
            existing = None
        if existing:
            if existing["_requestHash"] != request_hash:
                raise RebalanceConflict("请求标识已用于不同组合，请重新生成")
            return _public(existing)
    context = paper.read_rebalance_context(agent_id)
    symbols = sorted(set(symbols) | {row["symbol"] for row in context["positions"]})
    if len(symbols) > 20:
        raise RebalanceError("候选与已有持仓合计不能超过20只")
    refs, documents = _read_reports(agent_id, references)
    model_id, model_config = decision.resolve_model(agent_id)
    quotes = _quotes(symbols)
    if len(quotes) != len(symbols):
        raise RebalanceError("候选或已有持仓缺少行情，尚未调用模型")
    quote_checks = build_plan(context, [{"symbol": symbol, "weightPct": 0.0, "reason": "调用前只检查行情"} for symbol in symbols], quotes, policy, now=_now())["riskChecks"]
    if any(not row["passed"] for row in quote_checks if row["code"] in {"quote_coverage", "quote_freshness"}):
        raise RebalanceError("行情已过期或时间不明，尚未调用模型；请刷新行情后再试")
    proposal = {"proposalId": proposal_id, "agentId": agent_id, "status": "generating", "createdAt": _now().isoformat(), "expiresAt": "", "modelId": model_id, "reportRefs": refs, "targets": [], "summaryReason": "", "riskChecks": [], "orders": [], "metrics": {"equityYuan": "0.00", "cashAfterYuan": context["cashYuan"], "turnoverPct": "0.00", "feesYuan": "0.00"}, "policy": policy, "planHash": "", "error": None, "execution": None, "_requestHash": request_hash, "_symbols": symbols}
    with store.lock(agent_id, proposal_id):
        try:
            existing = store.read(agent_id, proposal_id)
        except RebalanceNotFound:
            existing = None
        if existing:
            if existing["_requestHash"] != request_hash:
                raise RebalanceConflict("请求标识已用于不同组合")
            return _public(existing)
        store.write(agent_id, proposal)
    _event(agent_id, proposal_id, "generating")
    try:
        inferred = decision.infer(agent_id, proposal_id, model_id, model_config, {"symbols": symbols, "instruction": instruction, "policy": policy, "reports": documents, "account": context, "quotes": quotes, "simulationOnly": True})
        if (_now() - datetime.fromisoformat(proposal["createdAt"])).total_seconds() > GENERATION_TIMEOUT_SECONDS:
            raise RebalanceError("模型结果超过本次有效时间，请明确重新生成")
        _validate_sources(agent_id, proposal)
        proposal["_modelDecision"] = inferred
        proposal["summaryReason"] = inferred["summaryReason"]
        _refresh_plan(agent_id, proposal, inferred["targets"], policy)
    except Exception as exc:  # noqa: BLE001 - persist unknown provider outcome; never retry or leak provider details
        proposal["status"] = "failed"
        proposal["error"] = str(exc) if isinstance(exc, RebalanceError) else "组合生成未完成，本请求不会自动重试；请检查模型、研究依据和行情后重新生成"
    with store.lock(agent_id, proposal_id):
        store.write(agent_id, proposal)
    _event(agent_id, proposal_id, proposal["status"])
    return _public(proposal)


def list_proposals(agent_id: str) -> dict:
    return {"items": [get_proposal(agent_id, item["proposalId"]) for item in store.list_items(agent_id)]}


def get_proposal(agent_id: str, proposal_id: str) -> dict:
    proposal = store.read(agent_id, proposal_id)
    # If the process stopped after the atomic ledger write but before updating
    # the proposal artifact, project the authoritative batch without re-executing.
    if proposal.get("planHash"):
        batch = paper.find_rebalance(agent_id, proposal_id, proposal["planHash"])
        if batch:
            proposal["status"] = "executed"
            proposal["execution"] = {"batchId": batch["batchId"], "executedAt": batch["createdAt"]}
    return _public(proposal)


def preview_proposal(agent_id: str, proposal_id: str, payload: dict) -> dict:
    with store.lock(agent_id, proposal_id):
        proposal = store.read(agent_id, proposal_id)
        if proposal["status"] not in {"ready", "blocked"}:
            raise RebalanceConflict("只有已生成且未执行的建议可以重新检查")
        if paper.find_rebalance(agent_id, proposal_id, proposal["planHash"]):
            raise RebalanceConflict("该建议已执行，不能修改")
        _validate_sources(agent_id, proposal)
        targets = normalize_targets(payload.get("targets", []), proposal["_symbols"])
        policy = normalize_policy(payload.get("policy"))
        if targets != proposal["targets"] or policy != proposal["policy"]:
            proposal["summaryReason"] = "已按手动调整的目标仓位与风险限制重新检查。"
        _refresh_plan(agent_id, proposal, targets, policy)
        store.write(agent_id, proposal)
    return _public(proposal)


def approve_proposal(agent_id: str, proposal_id: str, payload: dict) -> dict:
    if payload.get("confirmSimulation") is not True:
        raise RebalanceError("需要明确批准本次模拟调仓")
    with store.lock(agent_id, proposal_id):
        proposal = store.read(agent_id, proposal_id)
        if payload.get("planHash") != proposal["planHash"] or not proposal["planHash"]:
            raise RebalanceConflict("方案已变化，请重新检查后批准")
        if _plan_hash(proposal) != proposal["planHash"]:
            raise RebalanceConflict("已保存方案的内容校验失败，请重新检查后批准")
        batch = paper.find_rebalance(agent_id, proposal_id, proposal["planHash"])
        if not batch:
            if proposal["status"] != "ready":
                raise RebalanceConflict("本次风控未通过，不能批准模拟调仓")
            if _now() >= datetime.fromisoformat(proposal["expiresAt"]):
                raise RebalanceConflict("方案已过期，请重新检查行情与风控")
            _validate_sources(agent_id, proposal)
            context = paper.read_rebalance_context(agent_id)
            if context["ledgerFingerprint"] != proposal["_context"]["ledgerFingerprint"]:
                raise RebalanceConflict("模拟账户已变化，请重新检查后批准")
            plan = build_plan(context, proposal["targets"], proposal["_quotes"], proposal["policy"], now=_now())
            if not plan["canApprove"] or plan["orders"] != proposal["orders"]:
                raise RebalanceConflict("行情或风险条件已变化，请重新检查")
            batch = paper.execute_rebalance(agent_id, batch_id=proposal_id, request_hash=proposal["planHash"], expected_ledger_fingerprint=context["ledgerFingerprint"], orders=[{key: row[key] for key in ("symbol", "side", "quantity", "reason")} for row in plan["orders"]], quotes=proposal["_quotes"], metadata={"proposalId": proposal_id, "planHash": proposal["planHash"], "reportRefs": proposal["reportRefs"]}, expires_at=proposal["expiresAt"])
        proposal["status"] = "executed"
        proposal["execution"] = {"batchId": batch["batchId"], "executedAt": batch["createdAt"]}
        store.write(agent_id, proposal)
    _event(agent_id, proposal_id, "executed")
    return _public(proposal)
