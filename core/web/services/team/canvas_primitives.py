"""Pure team canvas token/geometry helpers.

Claim scope: id/float sanitizers, issue DTO, and edge normalization without
Agent/registry IO. Node/member normalization that needs Agent lookup stays on
the team_service facade (or later packs).
"""

from __future__ import annotations

import re
from typing import Any

from core.chat.chat_task_types import trim_lines

NODE_TYPES = {"role", "agent", "group", "user", "external"}
EDGE_TYPES = {"reports_to", "communication", "collaborates_with", "delegates_to", "observes", "supports"}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


class TeamCanvasValidationError(ValueError):
    """Raised when a pure canvas fragment fails structural validation."""


def safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def issue(
    severity: str,
    code: str,
    message: str,
    *,
    node_id: str = "",
    edge_id: str = "",
    source: str = "",
    target: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "nodeId": node_id,
        "edgeId": edge_id,
        "source": source,
        "target": target,
    }


def normalize_edge(item: Any, index: int, node_ids: set[str]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TeamCanvasValidationError("Team canvas edge must be an object.")
    source = safe_token(item.get("source"), default="", max_length=96)
    target = safe_token(item.get("target"), default="", max_length=96)
    if source not in node_ids or target not in node_ids:
        raise TeamCanvasValidationError("Team canvas edge must reference existing nodes.")
    edge_type = safe_token(item.get("type"), default="collaborates_with", max_length=40)
    return {
        "id": safe_token(item.get("id"), default=f"edge-{index + 1}", max_length=96),
        "source": source,
        "target": target,
        "label": trim_lines(item.get("label") or "", max_lines=1).strip(),
        "type": edge_type if edge_type in EDGE_TYPES else "collaborates_with",
    }


# Private aliases matching historical team_service names.
_safe_token = safe_token
_safe_float = safe_float
_issue = issue
_normalize_edge = normalize_edge
