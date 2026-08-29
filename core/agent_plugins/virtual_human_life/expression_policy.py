"""Explainable contextual expression projection.

This module selects style hints only. It does not replace the native chat,
prompt, safety, or tool-policy path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

_SCOPE_ORDER = {
    "identity_safety": 0,
    "current_request": 1,
    "relationship_boundary": 2,
    "mood": 3,
    "habit": 4,
}


def _matches(condition: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bool, str]:
    reasons: list[str] = []
    for key, expected in condition.items():
        actual = context.get(key)
        if isinstance(expected, list):
            matched = actual in expected
        else:
            matched = actual == expected
        if not matched:
            return False, f"{key} did not match"
        reasons.append(f"{key}={expected!r}")
    return True, ", ".join(reasons) if reasons else "always"


def project_expression_rules(
    rules: Sequence[Mapping[str, Any]],
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    """Return ordered applied rules and an explanation trace."""

    normalized: list[dict[str, Any]] = []
    for raw in rules:
        rule_id = str(raw.get("ruleId") or "").strip()[:160]
        scope = str(raw.get("scope") or "").strip().lower()[:60]
        condition = raw.get("condition") if isinstance(raw.get("condition"), Mapping) else {}
        action = raw.get("action") if isinstance(raw.get("action"), Mapping) else {}
        if not rule_id or scope not in _SCOPE_ORDER or not action:
            continue
        try:
            priority = max(-10_000, min(10_000, int(raw.get("priority") or 0)))
        except (TypeError, ValueError):
            priority = 0
        normalized.append(
            {
                "ruleId": rule_id,
                "scope": scope,
                "priority": priority,
                "condition": deepcopy(dict(condition)),
                "action": deepcopy(dict(action)),
                "dependsOn": [
                    str(item).strip()[:160]
                    for item in list(raw.get("dependsOn") or [])
                    if str(item).strip()
                ][:16],
            }
        )
    normalized.sort(
        key=lambda item: (
            _SCOPE_ORDER[item["scope"]],
            -item["priority"],
            item["ruleId"],
        )
    )
    applied: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    applied_ids: set[str] = set()
    for rule in normalized:
        missing = [item for item in rule["dependsOn"] if item not in applied_ids]
        if missing:
            trace.append(
                {
                    "ruleId": rule["ruleId"],
                    "matched": False,
                    "reason": "dependency_not_applied",
                    "missingDependencies": missing,
                }
            )
            continue
        matched, reason = _matches(rule["condition"], context)
        if not matched:
            trace.append(
                {"ruleId": rule["ruleId"], "matched": False, "reason": reason}
            )
            continue
        projected = {
            **rule,
            "explanation": f"{rule['scope']} matched {reason}",
        }
        applied.append(projected)
        applied_ids.add(rule["ruleId"])
        trace.append(
            {"ruleId": rule["ruleId"], "matched": True, "reason": reason}
        )
    return {"applied": applied, "trace": trace}


__all__ = ["project_expression_rules"]
