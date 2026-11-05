"""Private prompt/profile evidence owned by one accepted submission.

Only a bounded content-addressed reference crosses queue/journal projections.
This is not an Agent configuration or authorization snapshot: callers overlay
the prompt fields onto the live Agent and retain the existing permission checks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

MAX_ACCEPTED_PROMPT_BYTES = 2 * 1024 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}")
_PROFILE_FIELDS = ("displayName", "agentCode", "promptTemplateId", "personaProfile", "taskProfile")
_SOURCES = frozenset({"admission", "legacy_queue_drain", "legacy_restart_resume"})


def _encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def _config_hash(profile: dict[str, Any], prompt: dict[str, Any]) -> str:
    # capturedAt and admission identity must not invalidate an unchanged prefix.
    return _hash({"profile": profile, "prompt": {key: value for key, value in prompt.items() if key != "capturedAt"}})


def _path(service: Any, session_id: str, digest: str) -> Path:
    # Inherit Session archive/delete/purge along with its private Journal. The
    # directory is outside artifacts/documents, artifact download and body search.
    sessions_root = developer_sandbox.sandboxed_workspace_path(service.PROJECT_ROOT, "sessions").resolve()
    workspace = (sessions_root / service._safe_session_workspace_token(session_id)).resolve()
    # .runtime is already excluded by the shared project tree/search surfaces;
    # do not introduce a new general-purpose hidden-directory exception.
    runtime_directory = workspace / ".runtime"
    private_directory = runtime_directory / ".accepted_prompt_configs"
    root = private_directory.resolve()
    path = (root / f"{digest}.json").resolve()
    if (not workspace.is_relative_to(sessions_root) or not root.is_relative_to(workspace)
            or service._path_is_reparse_point(runtime_directory)
            or service._path_is_reparse_point(private_directory) or not path.is_relative_to(root)):
        raise service.SessionValidationError("Accepted prompt configuration path is invalid.")
    return path


def capture_accepted_prompt_config(
    service: Any,
    session_id: str,
    conversation: dict[str, Any],
    *,
    submission_id: str,
    source: str = "admission",
) -> dict[str, Any] | None:
    """Capture current prompt bytes and only the identity/persona/task fields.

    Files remain immutable alongside the private Session evidence so queued
    and interrupted submissions can survive a backend restart. Public records
    contain neither these bytes nor an arbitrary filesystem path.
    """
    agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    if not agent_id:
        return None
    if not session_id or not submission_id or max(len(session_id), len(agent_id), len(submission_id)) > 512 or source not in _SOURCES:
        raise service.SessionValidationError("Accepted prompt configuration identity is invalid.")
    directory_lock = getattr(service.agent_directory_service, "_STATE_LOCK", None)
    prompt_service = service.prompt_template_service
    prompt_lock = getattr(prompt_service, "PROMPT_TEMPLATE_LOCK", None)
    # Match the Agent management lock order; never call the directory while
    # holding the prompt registry lock in the opposite order.
    with directory_lock if directory_lock is not None else nullcontext():
        current = service.get_agent(agent_id, include_archived=False)
        if not isinstance(current, dict) or str(current.get("agentId") or "") != agent_id:
            raise service.SessionValidationError("Accepted prompt configuration Agent is unavailable.")
        profile = {key: copy.deepcopy(current.get(key)) for key in _PROFILE_FIELDS}
        template_id = str(profile.get("promptTemplateId") or "").strip()
        with prompt_lock if prompt_lock is not None else nullcontext():
            prompt = prompt_service.build_agent_prompt_snapshot(
                template_id,
                agent_id=agent_id,
                agent_code=str(current.get("agentCode") or ""),
                agent_display_name=str(current.get("displayName") or ""),
                core_prompt_root=Path(__file__).resolve().parents[4],
                include_chat_base=str(current.get("primaryMode") or "").strip().lower() == "chat",
            ) if template_id else {}
        if (not isinstance(prompt, dict) or prompt.get("reason")
                or template_id and (not str(prompt.get("content") or "").strip()
                    or prompt.get("agentId") != agent_id or prompt.get("promptTemplateId") != template_id)):
            raise service.SessionValidationError("当前 Agent 提示词不可用，未受理本轮请求。")
        bundle = {
            "schemaVersion": 1,
            "sessionId": session_id,
            "agentId": agent_id,
            "submissionId": submission_id,
            "source": source,
            "profile": profile,
            "promptSnapshot": copy.deepcopy(prompt),
            "contentHash": _config_hash(profile, prompt),
        }
    encoded = _encoded(bundle)
    if len(encoded) > MAX_ACCEPTED_PROMPT_BYTES:
        raise service.SessionValidationError("Accepted prompt configuration exceeds the size limit.")
    digest = hashlib.sha256(encoded).hexdigest()
    path = _path(service, session_id, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Admission already serializes this Session across processes. Exclusive
    # creation prevents overwriting evidence; existing bytes are verified below.
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        with path.open("rb") as stream:
            existing = stream.read(MAX_ACCEPTED_PROMPT_BYTES + 1)
        if existing != encoded:
            raise service.SessionValidationError("Accepted prompt configuration is corrupt.") from None
    return {key: bundle[key] for key in ("schemaVersion", "agentId", "submissionId", "source", "contentHash")} | {"ref": digest}


def load_accepted_prompt_config(
    service: Any,
    session_id: str,
    reference: Any,
    *,
    agent_id: str,
    submission_id: str,
) -> dict[str, Any]:
    """Validate the digest and all three binding identities; never fall back live."""
    try:
        if not isinstance(reference, dict) or reference.get("schemaVersion") != 1:
            raise ValueError
        digest = reference["ref"]
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError
        if (reference.get("agentId") != agent_id or reference.get("submissionId") != submission_id
                or not agent_id or not submission_id or reference.get("source") not in _SOURCES):
            raise ValueError
        path = _path(service, session_id, digest)
        with path.open("rb") as stream:
            raw = stream.read(MAX_ACCEPTED_PROMPT_BYTES + 1)
        if len(raw) > MAX_ACCEPTED_PROMPT_BYTES or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError
        bundle = json.loads(raw)
        if (bundle.get("schemaVersion") != 1 or bundle.get("sessionId") != session_id
                or any(bundle.get(key) != reference.get(key) for key in ("agentId", "submissionId", "source", "contentHash"))):
            raise ValueError
        profile, prompt = bundle["profile"], bundle["promptSnapshot"]
        if not isinstance(profile, dict) or set(profile) != set(_PROFILE_FIELDS) or not isinstance(prompt, dict):
            raise ValueError
        if bundle["contentHash"] != _config_hash(profile, prompt) or prompt.get("reason"):
            raise ValueError
        if profile.get("promptTemplateId") and not str(prompt.get("content") or "").strip():
            raise ValueError
        prompt_digest = hashlib.sha256(str(prompt.get("content") or "").encode("utf-8")).hexdigest()
        if prompt and (prompt.get("agentId") != agent_id
                or prompt.get("promptTemplateId") != profile.get("promptTemplateId")
                or prompt.get("contentHash") not in {prompt_digest, f"sha256:{prompt_digest}"}):
            raise ValueError
        return bundle
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise service.SessionValidationError("受理时的提示词档案缺失或损坏，本轮未执行；请重新提交。") from None


def pin_agent_prompt_profile(agent: dict[str, Any] | None, bundle: dict[str, Any]) -> dict[str, Any] | None:
    """Overlay only prompt-facing fields, leaving live security metadata intact."""
    if agent is None:
        return None
    if str(agent.get("agentId") or "") != bundle.get("agentId"):
        raise ValueError("Accepted prompt configuration belongs to another Agent.")
    pinned = copy.deepcopy(agent)
    for key in _PROFILE_FIELDS:
        pinned[key] = copy.deepcopy(bundle["profile"].get(key))
    pinned["_acceptedPromptConfigHash"] = bundle["contentHash"]
    return pinned


def recovered_prompt_config_reference(service: Any, session_id: str, turn_id: str) -> tuple[Any, str]:
    """Startup continuation inherits its original accepted evidence, if present."""
    events = service._load_session_conversation_events_cached(session_id)
    # Journal order is oldest first. Later user_message records can be guidance
    # for the same Turn; only its original submission owns admission evidence.
    for event in events:
        if str(getattr(event, "turn_id", "") or "") != turn_id or getattr(event, "event_type", "") != service.EVENT_USER_MESSAGE:
            continue
        payload = event.payload or {}
        metadata = payload.get("metadata") or {}
        if (metadata.get("kind") in {"user_guidance", "user_interrupt_guidance"}
                or payload.get("source") == "steer" or metadata.get("source") == "steer"
                or getattr(event, "source", "") == "submit_session_guidance"):
            continue
        if "acceptedPromptConfig" in metadata:
            reference = metadata["acceptedPromptConfig"]
            return (reference if isinstance(reference, dict) else {"invalid": True}), str((reference if isinstance(reference, dict) else {}).get("submissionId") or "")
        return None, ""
    raise service.SessionValidationError("恢复请求缺少原始受理记录，未执行本轮。")
