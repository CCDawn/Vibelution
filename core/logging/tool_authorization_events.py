"""Bounded runtime-scene telemetry for Agent tool authorization."""

from __future__ import annotations

from typing import Any


MAX_DIFF_TOOL_NAMES = 8


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
