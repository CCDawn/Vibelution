"""Canonical Agent configuration identity and permission presets."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
from typing import Any


AGENT_CONFIG_SCHEMA_VERSION = 2
DEFAULT_PERMISSION_PRESET = "request_approval"
PERMISSION_PRESETS = {
    "request_approval",
    "auto_review",
    "full_access",
}


def normalize_permission_preset(value: Any, *, strict: bool = False) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in PERMISSION_PRESETS:
        return normalized
    if strict and normalized:
        raise ValueError(f"Unsupported Agent permission preset: {normalized}")
    return DEFAULT_PERMISSION_PRESET


def permission_runtime_contract(value: Any) -> dict[str, str]:
    preset = normalize_permission_preset(value, strict=True)
    if preset == "auto_review":
        return {
            "preset": preset,
            "sandboxMode": "workspace_write",
            "approvalPolicy": "on_request",
            "approvalsReviewer": "auto_review",
        }
    if preset == "full_access":
        return {
            "preset": preset,
            "sandboxMode": "danger_full_access",
            "approvalPolicy": "never",
            "approvalsReviewer": "none",
        }
    return {
        "preset": preset,
        "sandboxMode": "workspace_write",
        "approvalPolicy": "on_request",
        "approvalsReviewer": "user",
    }


def canonical_agent_config_payload(agent: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(agent or {})
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "displayName": str(payload.get("displayName") or "").strip(),
        "llmBindings": copy.deepcopy(
            payload.get("llmBindings")
            if isinstance(payload.get("llmBindings"), dict)
            else {}
        ),
        "reasoningEffortBySlot": copy.deepcopy(
            metadata.get("llmReasoningEffort")
            if isinstance(metadata.get("llmReasoningEffort"), dict)
            else {}
        ),
        "promptTemplateId": str(payload.get("promptTemplateId") or "").strip(),
        "toolPolicyId": str(payload.get("toolPolicyId") or "").strip(),
        "toolPolicy": copy.deepcopy(
            payload.get("toolPolicy")
            if isinstance(payload.get("toolPolicy"), dict)
            else {}
        ),
        "memoryPolicyId": str(payload.get("memoryPolicyId") or "").strip(),
        "memoryPolicy": copy.deepcopy(
            payload.get("memoryPolicy")
            if isinstance(payload.get("memoryPolicy"), dict)
            else {}
        ),
        "contextCompressionPolicy": copy.deepcopy(
            payload.get("contextCompressionPolicy")
            if isinstance(payload.get("contextCompressionPolicy"), dict)
            else {}
        ),
        "delegationPolicy": copy.deepcopy(
            metadata.get("delegationPolicy")
            if isinstance(metadata.get("delegationPolicy"), dict)
            else {}
        ),
        "supervisionPolicy": copy.deepcopy(
            metadata.get("supervisionPolicy")
            if isinstance(metadata.get("supervisionPolicy"), dict)
            else {}
        ),
        "personaProfile": copy.deepcopy(
            metadata.get("personaProfile")
            if isinstance(metadata.get("personaProfile"), dict)
            else {}
        ),
        "taskProfile": copy.deepcopy(
            metadata.get("taskProfile")
            if isinstance(metadata.get("taskProfile"), dict)
            else {}
        ),
        "permissionPreset": normalize_permission_preset(
            payload.get("permissionPreset")
        ),
        "status": str(payload.get("status") or "active").strip() or "active",
    }


def agent_config_hash(agent: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        canonical_agent_config_payload(agent),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def materialize_agent_config_identity(
    agent: dict[str, Any],
    *,
    increment_if_changed: bool = False,
    previous_hash: str = "",
) -> bool:
    before = {
        "configSchemaVersion": agent.get("configSchemaVersion"),
        "configRevision": agent.get("configRevision"),
        "configHash": agent.get("configHash"),
        "permissionPreset": agent.get("permissionPreset"),
    }
    agent["configSchemaVersion"] = AGENT_CONFIG_SCHEMA_VERSION
    agent["permissionPreset"] = normalize_permission_preset(
        agent.get("permissionPreset")
    )
    try:
        current_revision = max(0, int(agent.get("configRevision") or 0))
    except (TypeError, ValueError):
        current_revision = 0
    current_revision = current_revision or 1
    next_hash = agent_config_hash(agent)
    old_hash = str(previous_hash or agent.get("configHash") or "").strip()
    if increment_if_changed and old_hash and next_hash != old_hash:
        current_revision += 1
    agent["configRevision"] = current_revision
    agent["configHash"] = next_hash
    after = {
        "configSchemaVersion": agent.get("configSchemaVersion"),
        "configRevision": agent.get("configRevision"),
        "configHash": agent.get("configHash"),
        "permissionPreset": agent.get("permissionPreset"),
    }
    return before != after
