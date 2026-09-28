"""Bounded runtime-scene telemetry for Agent tool authorization."""

from __future__ import annotations

from typing import Any


MAX_DIFF_TOOL_NAMES = 8
# 每决策 per-tool 原因事件最多列出的工具数：聚合事件之外的补充审计面，必须有界。
MAX_DECISION_REASON_TOOLS = MAX_DIFF_TOOL_NAMES
MAX_REASON_MESSAGE_CHARS = 160


def record_authorization_decision(report: Any) -> None:
    decision = report.decision
    _record(
        "tool.authorization.decision",
        message="Canonical tool authorization decision resolved.",
        outcome="resolved",
        level="info",
        fields={
            "agentId": decision.agent_id,
            "turnId": decision.turn_id,
            "policyId": decision.policy_id,
            "policyVersion": decision.policy_version,
            "registryVersion": decision.registry_version,
            "registryFingerprint": str(report.registry_fingerprint or "")[:64],
            "decisionFingerprint": str(decision.decision_fingerprint or "")[:64],
            "visibleCount": len(decision.visible_tools),
            "executableCount": len(decision.executable_tools),
            "denyCodeCounts": dict(report.deny_code_counts),
            "durationMs": max(0, int(report.duration_ms or 0)),
        },
    )
    _record_decision_reasons(report)


def _record_decision_reasons(report: Any) -> None:
    """Parallel per-tool structured denial audit for the same decision.

    Complements (never replaces) the aggregate ``tool.authorization.decision``
    event: same schema, plus bounded per-tool ``gateId``/``reasonCode``/
    ``ruleId`` entries so every denial is auditable back to its rule source.
    """

    decision = report.decision
    denied = tuple(getattr(decision, "denied", ()) or ())
    entries = [
        _deny_reason_entry(name, reason)
        for name, reason in denied[:MAX_DECISION_REASON_TOOLS]
    ]
    if not entries:
        return
    _record(
        "tool.authorization.decision_reasons",
        message="Per-tool canonical authorization denial reasons recorded.",
        outcome="resolved",
        level="info",
        fields={
            "agentId": str(getattr(decision, "agent_id", "") or ""),
            "turnId": str(getattr(decision, "turn_id", "") or ""),
            "policyId": str(getattr(decision, "policy_id", "") or ""),
            "policyVersion": getattr(decision, "policy_version", 0),
            "decisionFingerprint": str(getattr(decision, "decision_fingerprint", "") or "")[:64],
            "deniedCount": len(denied),
            "deniedTools": entries,
        },
    )


def _deny_reason_entry(tool_name: Any, reason: Any) -> dict[str, Any]:
    code = getattr(reason, "code", "")
    return {
        "toolName": str(tool_name or "").strip(),
        "phase": str(getattr(reason, "phase", "") or ""),
        "reasonCode": str(getattr(code, "value", code) or ""),
        "gateId": str(getattr(reason, "gate_id", "") or ""),
        "ruleId": str(getattr(reason, "rule_id", "") or ""),
        "message": str(getattr(reason, "message", "") or "")[:MAX_REASON_MESSAGE_CHARS],
    }


def record_execution_denial_reason(
    *,
    tool_name: str,
    gate_id: str,
    reason_code: str = "",
    rule_id: str = "",
    agent_id: str = "",
    turn_id: str = "",
    decision_fingerprint: str = "",
) -> None:
    """Parallel structured audit for one execution-time denial.

    ``gateId`` is the execution gate that fired (for example
    ``tool_not_executable``); ``reasonCode``/``ruleId`` carry the decision-level
    deny rule when the canonical decision explains the denial.
    """

    _record(
        "tool.authorization.execution_denied_reason",
        message="Per-tool execution denial reason recorded.",
        outcome="blocked",
        level="warning",
        fields={
            "toolName": str(tool_name or "").strip()[:120],
            "gateId": str(gate_id or "").strip(),
            "reasonCode": str(reason_code or "").strip(),
            "ruleId": str(rule_id or "").strip(),
            "agentId": str(agent_id or "").strip(),
            "turnId": str(turn_id or "").strip(),
            "decisionFingerprintPresent": bool(str(decision_fingerprint or "").strip()),
        },
    )


def record_authorization_failure(*, runtime: dict[str, Any], error: Exception, duration_ms: int = 0) -> None:
    agent = runtime.get("agent") if isinstance(runtime.get("agent"), dict) else {}
    _record(
        "tool.authorization.failed",
        message="Canonical tool authorization failed closed.",
        outcome="failed",
        level="warning",
        fields={
            "agentId": str(runtime.get("agentId") or agent.get("agentId") or "").strip(),
            "turnId": str(runtime.get("turnId") or runtime.get("runId") or "").strip(),
            "errorType": type(error).__name__,
            "durationMs": max(0, int(duration_ms or 0)),
        },
    )


def _record(event_code: str, *, message: str, outcome: str, level: str, fields: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "tool_authorization",
            "decision",
            event_code,
            message=message,
            outcome=outcome,
            level=level,
            fields=fields,
        )
    except Exception:
        return
