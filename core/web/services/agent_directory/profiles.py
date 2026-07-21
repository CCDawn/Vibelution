"""Pure Agent persona/task profile normalizers.

Claim scope: profile field contracts only. Do not put registry IO, list/get API,
or tool/memory policy normalization here.
"""

from __future__ import annotations

import re
from typing import Any

from core.chat.chat_task_types import trim_lines

AGENT_PERSONA_PROFILE_TEXT_FIELDS = (
    "gender",
    "age",
    "pronouns",
    "personality",
    "communicationStyle",
    "background",
    "collaborationPreference",
    "identityNotes",
)
AGENT_PERSONA_PROFILE_FIELDS = (*AGENT_PERSONA_PROFILE_TEXT_FIELDS, "expertise")
AGENT_PERSONA_PROFILE_TEXT_LINE_LIMITS = {
    "gender": 1,
    "age": 1,
    "pronouns": 1,
    "personality": 4,
    "communicationStyle": 4,
    "background": 6,
    "collaborationPreference": 4,
    "identityNotes": 6,
}
AGENT_TASK_PROFILE_TEXT_FIELDS = (
    "mission",
    "responsibilities",
    "preferredTasks",
    "avoidTasks",
    "successCriteria",
    "deliverables",
    "constraints",
    "handoffNotes",
)
AGENT_TASK_PROFILE_FIELDS = (*AGENT_TASK_PROFILE_TEXT_FIELDS, "taskTypes")
AGENT_TASK_PROFILE_TEXT_LINE_LIMITS = {
    "mission": 4,
    "responsibilities": 8,
    "preferredTasks": 8,
    "avoidTasks": 6,
    "successCriteria": 6,
    "deliverables": 6,
    "constraints": 6,
    "handoffNotes": 6,
}


def normalize_persona_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    raw = profile if isinstance(profile, dict) else {}
    normalized: dict[str, Any] = {}
    for field in AGENT_PERSONA_PROFILE_TEXT_FIELDS:
        normalized[field] = trim_lines(
            str(raw.get(field) or ""),
            max_lines=AGENT_PERSONA_PROFILE_TEXT_LINE_LIMITS.get(field, 3),
        ).strip()
    expertise_values: list[str] = []
    raw_expertise = raw.get("expertise")
    if isinstance(raw_expertise, str):
        candidates = re.split(r"[,，;；\n]+", raw_expertise)
    elif isinstance(raw_expertise, (list, tuple)):
        candidates = list(raw_expertise)
    else:
        candidates = []
    seen: set[str] = set()
    for item in candidates:
        value = trim_lines(str(item or ""), max_lines=1).strip()
        if not value or value in seen:
            continue
        expertise_values.append(value[:80].rstrip())
        seen.add(value)
        if len(expertise_values) >= 12:
            break
    normalized["expertise"] = expertise_values
    return normalized


def agent_persona_profile_has_content(profile: dict[str, Any] | None) -> bool:
    return _persona_profile_has_content(normalize_persona_profile(profile))


def _persona_profile_has_content(profile: dict[str, Any]) -> bool:
    return any(str(profile.get(field) or "").strip() for field in AGENT_PERSONA_PROFILE_TEXT_FIELDS) or bool(
        profile.get("expertise")
    )


def normalize_task_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    raw = profile if isinstance(profile, dict) else {}
    normalized: dict[str, Any] = {}
    for field in AGENT_TASK_PROFILE_TEXT_FIELDS:
        normalized[field] = trim_lines(
            str(raw.get(field) or ""),
            max_lines=AGENT_TASK_PROFILE_TEXT_LINE_LIMITS.get(field, 4),
        ).strip()
    task_types: list[str] = []
    raw_task_types = raw.get("taskTypes")
    if isinstance(raw_task_types, str):
        candidates = re.split(r"[,，;；\n]+", raw_task_types)
    elif isinstance(raw_task_types, (list, tuple)):
        candidates = list(raw_task_types)
    else:
        candidates = []
    seen: set[str] = set()
    for item in candidates:
        value = trim_lines(str(item or ""), max_lines=1).strip()
        if not value or value in seen:
            continue
        task_types.append(value[:80].rstrip())
        seen.add(value)
        if len(task_types) >= 16:
            break
    normalized["taskTypes"] = task_types
    return normalized


def agent_task_profile_has_content(profile: dict[str, Any] | None) -> bool:
    return _task_profile_has_content(normalize_task_profile(profile))


def _task_profile_has_content(profile: dict[str, Any]) -> bool:
    return any(str(profile.get(field) or "").strip() for field in AGENT_TASK_PROFILE_TEXT_FIELDS) or bool(
        profile.get("taskTypes")
    )
