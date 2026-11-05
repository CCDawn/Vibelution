"""Preserve quoted directory identities only for the fixed native action tool."""
from __future__ import annotations

import json
import unicodedata


def project_directory_labels(content: str, *, tool_name: str) -> str | None:
    """Return a closed data projection; other results retain normal filtering.

    Names can resemble instructions. They remain untrusted JSON values, never
    workflow fields, and must not disappear from an otherwise complete catalog.
    The producer discriminator is added by the local canonical tool wrapper.
    """
    if tool_name != "personal_assistant_action_tool":
        return None

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate directory field")
            result[key] = value
        return result

    try:
        payload = json.loads(content, object_pairs_hook=unique)
        if (not isinstance(payload, dict) or payload.get("source") != "launcher-assistant"
                or payload.get("untrustedContent") is not True
                or type(payload.get("directoryVersion")) is not int or payload["directoryVersion"] != 1
                or payload.get("scope") != "all_registered_agents"):
            return None
        project_id = payload.get("projectId")
        if (not isinstance(project_id, str) or not 1 <= len(project_id) <= 160
                or any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in project_id)):
            return None
        from pydantic import ValidationError

        from core.web.services.external_management.contracts import (
            AgentDirectoryResponse,
        )

        fields = {key: value for key, value in payload.items() if key not in {"source", "projectId", "directoryVersion"}}
        try:
            directory = AgentDirectoryResponse.model_validate(fields).model_dump(exclude_unset=True)
        except ValidationError:
            return None
        return json.dumps({"source": "launcher-assistant", "projectId": project_id,
                           "directoryVersion": 1, **directory}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError):
        return None
