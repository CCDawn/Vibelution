# -*- coding: utf-8 -*-
"""Read-only browser user-action telemetry query helpers for Agent tooling."""

from __future__ import annotations

import json
from typing import Any


def user_action_telemetry_query_tool(
    action_prefix: str = "",
    scene_limit: int = 12,
) -> str:
    """Aggregate recent browser user-action telemetry across runtime scenes."""

    try:
        from core.web.services.runtime_scene_service import query_browser_user_action_telemetry

        payload: dict[str, Any] = query_browser_user_action_telemetry(
            action_prefix,
            scene_limit=scene_limit,
        )
    except Exception as exc:
        payload = {
            "status": "error",
            "code": exc.__class__.__name__,
            "message": str(exc),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)
