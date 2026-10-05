"""Pure normalization and decision helpers for per-Agent perception policy v1.

This module defines configuration intent only. It does not grant repository,
team, memory, or knowledge access; callers must intersect an allowed scope with
the current identity and ACL before reading any source.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
PERCEPTION_SOURCES = ("personal", "team", "knowledge", "projects")
PERCEPTION_MODES = ("off", "manual", "auto")
PERCEPTION_TRIGGERS = ("task", "update", "background")
NOTIFICATION_MODES = ("important", "all", "quiet")

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_SCOPE_IDS = 256
_MAX_INTERVAL_MINUTES = 10_080
_MAX_DAILY_RUNS = 96
_MAX_CALLS_PER_RUN = 32
_MAX_INPUT_TOKENS_PER_RUN = 131_072
_MAX_RESULT_CHARS = 50_000
_MAX_TOPICS = 8
_MAX_TOPIC_CHARS = 200


class AgentPerceptionPolicyError(ValueError):
    """Raised when a persisted or requested perception policy is malformed."""


def default_agent_perception_policy() -> dict[str, Any]:
    """Return a fresh, closed v1 policy suitable for an unsaved UI draft."""

    triggers = {trigger: False for trigger in PERCEPTION_TRIGGERS}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "enabled": False,
        "sources": {
            "personal": {"mode": "off", "triggers": dict(triggers)},
            "team": {"mode": "off", "teamIds": [], "triggers": dict(triggers)},
            "knowledge": {
                "mode": "off",
                "scope": "selected",
                "knowledgeBaseIds": [],
                "excludedKnowledgeBaseIds": [],
                "triggers": dict(triggers),
            },
            "projects": {"mode": "off", "triggers": dict(triggers)},
        },
        "background": {
            "enabled": False,
            "intervalMinutes": 60,
            "dailyMaxRuns": 4,
            "maxCallsPerRun": 8,
            "maxInputTokensPerRun": 16_000,
            "maxConcurrent": 1,
            "maxResultChars": 12_000,
            "topics": [],
        },
        "notifications": {"mode": "important"},
    }


def normalize_agent_perception_policy(
    value: Mapping[str, object] | None,
) -> dict[str, Any]:
    """Validate a v1 policy and return a deterministic JSON-ready structure.

    Missing fields use closed defaults. Unknown fields, unsupported schema
    versions, wrong primitive types, and unbounded values fail explicitly.
    List-like IDs are de-duplicated and sorted for stable persistence and hashes.
    """

    if value is None:
        return default_agent_perception_policy()

    root = _mapping(value, "policy")
    _reject_unknown_keys(
        root,
        {"schemaVersion", "enabled", "sources", "background", "notifications"},
        "policy",
    )
    schema_version = _strict_int(root.get("schemaVersion", SCHEMA_VERSION), "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise AgentPerceptionPolicyError(
            f"unsupported schemaVersion {schema_version}; expected {SCHEMA_VERSION}"
        )

    enabled = _strict_bool(root.get("enabled", False), "enabled")
    raw_sources = _mapping(root.get("sources", {}), "sources")
    _reject_unknown_keys(raw_sources, set(PERCEPTION_SOURCES), "sources")
    sources = {
        source: _normalize_source_policy(source, raw_sources.get(source, {}))
        for source in PERCEPTION_SOURCES
    }

    background = _normalize_background_policy(root.get("background", {}))
    notifications = _normalize_notification_policy(root.get("notifications", {}))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "enabled": enabled,
        "sources": sources,
        "background": background,
        "notifications": notifications,
    }


def agent_perception_policy_fingerprint(
    value: Mapping[str, object] | None,
) -> str:
    """Return a stable SHA-256 fingerprint for a normalized policy."""

    normalized = normalize_agent_perception_policy(value)
    canonical = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def decide_agent_perception(
    policy: Mapping[str, object] | None,
    *,
    source: str,
    trigger: str,
    requested_by_user: bool = False,
    requested_scope_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Explain whether one requested perception read passes its configured gate.

    ``policy=None`` means the Agent has never been configured and therefore
    preserves legacy behavior: ``enforced`` is false and ``allowed`` is None.
    An explicit policy with ``enabled=False`` is enforced as closed. For an
    allowed result, ``scope`` describes only configured selection intent; the
    caller remains responsible for applying identity and ACL checks.
    """

    if source not in PERCEPTION_SOURCES:
        raise AgentPerceptionPolicyError(f"unknown source {source!r}")
    if trigger not in PERCEPTION_TRIGGERS:
        raise AgentPerceptionPolicyError(f"unknown trigger {trigger!r}")
    if type(requested_by_user) is not bool:
        raise AgentPerceptionPolicyError("requested_by_user must be a boolean")
    if source == "knowledge":
        requested_ids = _normalize_scoped_knowledge_base_sequence(
            requested_scope_ids, "requested_scope_ids"
        )
    else:
        requested_ids = _normalize_requested_scope_ids(requested_scope_ids)

    if policy is None:
        return _decision(
            enforced=False,
            allowed=None,
            reason="policy_not_configured",
            source=source,
            trigger=trigger,
            mode=None,
        )

    normalized = normalize_agent_perception_policy(policy)
    source_policy = normalized["sources"][source]
    mode = source_policy["mode"]

    if not normalized["enabled"]:
        return _decision(
            enforced=True,
            allowed=False,
            reason="perception_disabled",
            source=source,
            trigger=trigger,
            mode=mode,
        )
    if mode == "off":
        return _decision(
            enforced=True,
            allowed=False,
            reason="source_disabled",
            source=source,
            trigger=trigger,
            mode=mode,
        )

    direct_user_query = trigger == "task" and requested_by_user
    if mode == "manual":
        if trigger != "task":
            return _decision(
                enforced=True,
                allowed=False,
                reason="manual_only",
                source=source,
                trigger=trigger,
                mode=mode,
            )
        if not requested_by_user:
            return _decision(
                enforced=True,
                allowed=False,
                reason="user_request_required",
                source=source,
                trigger=trigger,
                mode=mode,
            )
    elif mode == "auto" and not direct_user_query:
        if trigger == "background" and not normalized["background"]["enabled"]:
            return _decision(
                enforced=True,
                allowed=False,
                reason="background_disabled",
                source=source,
                trigger=trigger,
                mode=mode,
            )
        if not source_policy["triggers"][trigger]:
            return _decision(
                enforced=True,
                allowed=False,
                reason="trigger_disabled",
                source=source,
                trigger=trigger,
                mode=mode,
            )
        if trigger == "background" and normalized["background"]["dailyMaxRuns"] == 0:
            return _decision(
                enforced=True,
                allowed=False,
                reason="daily_run_budget_zero",
                source=source,
                trigger=trigger,
                mode=mode,
            )

    scope, scope_error = _effective_scope(source, source_policy, requested_ids)
    if scope_error:
        return _decision(
            enforced=True,
            allowed=False,
            reason=scope_error,
            source=source,
            trigger=trigger,
            mode=mode,
        )
    return _decision(
        enforced=True,
        allowed=True,
        reason="allowed",
        source=source,
        trigger=trigger,
        mode=mode,
        scope=scope,
    )


def _normalize_source_policy(source: str, value: object) -> dict[str, Any]:
    path = f"sources.{source}"
    source_value = _mapping(value, path)
    allowed_keys = {"mode", "triggers"}
    if source == "team":
        allowed_keys.add("teamIds")
    elif source == "knowledge":
        allowed_keys.update(
            {"scope", "knowledgeBaseIds", "excludedKnowledgeBaseIds"}
        )
    _reject_unknown_keys(source_value, allowed_keys, path)

    mode = source_value.get("mode", "off")
    if not isinstance(mode, str) or mode not in PERCEPTION_MODES:
        raise AgentPerceptionPolicyError(
            f"{path}.mode must be one of {', '.join(PERCEPTION_MODES)}"
        )
    normalized: dict[str, Any] = {
        "mode": mode,
        "triggers": _normalize_triggers(source_value.get("triggers", {}), f"{path}.triggers"),
    }
    if source == "team":
        normalized["teamIds"] = _normalize_ids(
            source_value.get("teamIds", []), f"{path}.teamIds"
        )
    elif source == "knowledge":
        scope = source_value.get("scope", "selected")
        if not isinstance(scope, str) or scope not in {"selected", "all_authorized"}:
            raise AgentPerceptionPolicyError(
                f"{path}.scope must be 'selected' or 'all_authorized'"
            )
        knowledge_ids = _normalize_scoped_knowledge_base_ids(
            source_value.get("knowledgeBaseIds", []),
            f"{path}.knowledgeBaseIds",
        )
        excluded_ids = _normalize_scoped_knowledge_base_ids(
            source_value.get("excludedKnowledgeBaseIds", []),
            f"{path}.excludedKnowledgeBaseIds",
        )
        if scope == "all_authorized" and knowledge_ids:
            raise AgentPerceptionPolicyError(
                f"{path}.knowledgeBaseIds must be empty for all_authorized scope"
            )
        normalized.update(
            {
                "scope": scope,
                "knowledgeBaseIds": knowledge_ids,
                "excludedKnowledgeBaseIds": excluded_ids,
            }
        )
    return normalized


def _normalize_triggers(value: object, path: str) -> dict[str, bool]:
    triggers = _mapping(value, path)
    _reject_unknown_keys(triggers, set(PERCEPTION_TRIGGERS), path)
    return {
        trigger: _strict_bool(triggers.get(trigger, False), f"{path}.{trigger}")
        for trigger in PERCEPTION_TRIGGERS
    }


def _normalize_background_policy(value: object) -> dict[str, Any]:
    path = "background"
    source = _mapping(value, path)
    _reject_unknown_keys(
        source,
        {
            "enabled",
            "intervalMinutes",
            "dailyMaxRuns",
            "maxCallsPerRun",
            "maxInputTokensPerRun",
            "maxConcurrent",
            "maxResultChars",
            "topics",
        },
        path,
    )

    enabled = _strict_bool(source.get("enabled", False), f"{path}.enabled")
    interval = _bounded_int(
        source.get("intervalMinutes", 60),
        f"{path}.intervalMinutes",
        minimum=15,
        maximum=_MAX_INTERVAL_MINUTES,
    )
    daily_runs = _bounded_int(
        source.get("dailyMaxRuns", 4),
        f"{path}.dailyMaxRuns",
        minimum=0,
        maximum=_MAX_DAILY_RUNS,
    )
    calls = _bounded_int(
        source.get("maxCallsPerRun", 8),
        f"{path}.maxCallsPerRun",
        minimum=1,
        maximum=_MAX_CALLS_PER_RUN,
    )
    input_tokens = _bounded_int(
        source.get("maxInputTokensPerRun", 16_000),
        f"{path}.maxInputTokensPerRun",
        minimum=1,
        maximum=_MAX_INPUT_TOKENS_PER_RUN,
    )
    max_concurrent = _strict_int(source.get("maxConcurrent", 1), f"{path}.maxConcurrent")
    if max_concurrent != 1:
        raise AgentPerceptionPolicyError(f"{path}.maxConcurrent must equal 1")
    result_chars = _bounded_int(
        source.get("maxResultChars", 12_000),
        f"{path}.maxResultChars",
        minimum=1,
        maximum=_MAX_RESULT_CHARS,
    )
    topics = _normalize_topics(source.get("topics", []), f"{path}.topics")
    if enabled and not topics:
        raise AgentPerceptionPolicyError(
            f"{path}.topics must contain a user-defined topic when background is enabled"
        )
    return {
        "enabled": enabled,
        "intervalMinutes": interval,
        "dailyMaxRuns": daily_runs,
        "maxCallsPerRun": calls,
        "maxInputTokensPerRun": input_tokens,
        "maxConcurrent": max_concurrent,
        "maxResultChars": result_chars,
        "topics": topics,
    }


def _normalize_topics(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise AgentPerceptionPolicyError(f"{path} must be a list of strings")
    if len(value) > _MAX_TOPICS:
        raise AgentPerceptionPolicyError(f"{path} must contain at most {_MAX_TOPICS} topics")
    normalized: set[str] = set()
    for index, raw_topic in enumerate(value):
        topic_path = f"{path}[{index}]"
        if not isinstance(raw_topic, str):
            raise AgentPerceptionPolicyError(f"{topic_path} must be a string")
        if len(raw_topic) > _MAX_TOPIC_CHARS:
            raise AgentPerceptionPolicyError(
                f"{topic_path} must contain at most {_MAX_TOPIC_CHARS} characters"
            )
        for character in raw_topic:
            category = unicodedata.category(character)
            if category.startswith("C") and not character.isspace():
                raise AgentPerceptionPolicyError(
                    f"{topic_path} contains a control or formatting character"
                )
        topic = " ".join(raw_topic.split())
        if not topic:
            raise AgentPerceptionPolicyError(f"{topic_path} must not be empty")
        normalized.add(topic)
    return sorted(normalized)


def _normalize_notification_policy(value: object) -> dict[str, str]:
    path = "notifications"
    source = _mapping(value, path)
    _reject_unknown_keys(source, {"mode"}, path)
    mode = source.get("mode", "important")
    if not isinstance(mode, str) or mode not in NOTIFICATION_MODES:
        raise AgentPerceptionPolicyError(
            f"{path}.mode must be one of {', '.join(NOTIFICATION_MODES)}"
        )
    return {"mode": mode}


def _effective_scope(
    source: str,
    policy: Mapping[str, Any],
    requested_ids: list[str] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    if source == "team":
        configured_ids = policy["teamIds"]
        if not configured_ids:
            return None, "empty_scope"
        if requested_ids is None:
            effective_ids = configured_ids
        elif not requested_ids:
            return None, "empty_scope"
        elif not set(requested_ids).issubset(configured_ids):
            return None, "scope_outside_policy"
        else:
            effective_ids = requested_ids
        return {"kind": "selected", "ids": effective_ids}, None

    if source == "knowledge":
        excluded_ids = set(policy["excludedKnowledgeBaseIds"])
        if policy["scope"] == "all_authorized":
            if requested_ids is None:
                return {
                    "kind": "all_authorized",
                    "excludedIds": sorted(excluded_ids),
                }, None
            if not requested_ids:
                return None, "empty_scope"
            if not set(requested_ids).isdisjoint(excluded_ids):
                return None, "scope_outside_policy"
            return {"kind": "selected", "ids": requested_ids}, None

        configured_ids = sorted(set(policy["knowledgeBaseIds"]) - excluded_ids)
        if not configured_ids:
            return None, "empty_scope"
        if requested_ids is None:
            effective_ids = configured_ids
        elif not requested_ids:
            return None, "empty_scope"
        elif not set(requested_ids).issubset(configured_ids):
            return None, "scope_outside_policy"
        else:
            effective_ids = requested_ids
        return {"kind": "selected", "ids": effective_ids}, None

    if requested_ids is not None:
        if not requested_ids:
            return None, "empty_scope"
        return {"kind": "selected", "ids": requested_ids}, None
    return {"kind": "personal" if source == "personal" else "project_index"}, None


def _decision(
    *,
    enforced: bool,
    allowed: bool | None,
    reason: str,
    source: str,
    trigger: str,
    mode: str | None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "enforced": enforced,
        "allowed": allowed,
        "reason": reason,
        "source": source,
        "trigger": trigger,
        "mode": mode,
        "scope": scope,
    }


def _normalize_requested_scope_ids(
    value: Sequence[str] | None,
) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AgentPerceptionPolicyError("requested_scope_ids must be a sequence of IDs")
    if len(value) > _MAX_SCOPE_IDS:
        raise AgentPerceptionPolicyError(
            f"requested_scope_ids must contain at most {_MAX_SCOPE_IDS} IDs"
        )
    ids = {_normalize_id(item, f"requested_scope_ids[{index}]") for index, item in enumerate(value)}
    return sorted(ids)


def _normalize_ids(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise AgentPerceptionPolicyError(f"{path} must be a list of IDs")
    if len(value) > _MAX_SCOPE_IDS:
        raise AgentPerceptionPolicyError(
            f"{path} must contain at most {_MAX_SCOPE_IDS} IDs"
        )
    return sorted({_normalize_id(item, f"{path}[{index}]") for index, item in enumerate(value)})


def _normalize_scoped_knowledge_base_ids(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise AgentPerceptionPolicyError(f"{path} must be a list of IDs")
    if len(value) > _MAX_SCOPE_IDS:
        raise AgentPerceptionPolicyError(
            f"{path} must contain at most {_MAX_SCOPE_IDS} IDs"
        )
    return sorted(
        {
            _normalize_scoped_knowledge_base_id(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        }
    )


def _normalize_scoped_knowledge_base_sequence(
    value: Sequence[str] | None, path: str
) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise AgentPerceptionPolicyError(f"{path} must be a sequence of IDs")
    if len(value) > _MAX_SCOPE_IDS:
        raise AgentPerceptionPolicyError(
            f"{path} must contain at most {_MAX_SCOPE_IDS} IDs"
        )
    return sorted(
        {
            _normalize_scoped_knowledge_base_id(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        }
    )


def _normalize_scoped_knowledge_base_id(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise AgentPerceptionPolicyError(
            f"{path} must be an owner-scoped knowledge base ID in the form "
            "team:<ownerId>:<baseId> or agent:<ownerId>:<baseId>"
        )
    parts = value.split(":")
    if (
        len(parts) != 3
        or parts[0] not in {"team", "agent"}
        or not _ID_PATTERN.fullmatch(parts[1])
        or not _ID_PATTERN.fullmatch(parts[2])
    ):
        raise AgentPerceptionPolicyError(
            f"{path} must be an owner-scoped knowledge base ID in the form "
            "team:<ownerId>:<baseId> or agent:<ownerId>:<baseId>"
        )
    return value


def _normalize_id(value: object, path: str) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise AgentPerceptionPolicyError(
            f"{path} must be a 1-128 character ASCII ID using letters, digits, '.', '_', ':', or '-'"
        )
    return value


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AgentPerceptionPolicyError(f"{path} must be an object")
    return value


def _reject_unknown_keys(
    value: Mapping[str, object],
    allowed: set[str],
    path: str,
) -> None:
    unknown = [key for key in value if not isinstance(key, str) or key not in allowed]
    if unknown:
        rendered = ", ".join(sorted(repr(key) for key in unknown))
        raise AgentPerceptionPolicyError(f"{path} contains unknown key(s): {rendered}")


def _strict_bool(value: object, path: str) -> bool:
    if type(value) is not bool:
        raise AgentPerceptionPolicyError(f"{path} must be a boolean")
    return value


def _strict_int(value: object, path: str) -> int:
    if type(value) is not int:
        raise AgentPerceptionPolicyError(f"{path} must be an integer")
    return value


def _bounded_int(value: object, path: str, *, minimum: int, maximum: int) -> int:
    result = _strict_int(value, path)
    if result < minimum or result > maximum:
        raise AgentPerceptionPolicyError(
            f"{path} must be between {minimum} and {maximum}"
        )
    return result
