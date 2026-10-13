"""Canonical, owner-scoped financial lesson lifecycle over episodic memory."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.web.services.agent_directory import episodic_memory


def _validation():
    from . import validation
    return validation


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _state(event: dict) -> str:
    return "active" if not event.get("validUntil") else "superseded" if event.get("supersededByEpisodeId") else "revoked"


def _owned(event: dict, record: dict) -> bool:
    v = _validation()
    return all(v._has_ref(event.get("refs"), ref_type=kind, ref_id=identifier) for kind, identifier in (
        ("item", v._LESSON_REF_PREFIX + record["id"]),
        ("session", record["sessionId"]),
        ("item", v._TURN_REF_PREFIX + record["turnId"]),
    ))


def events_for(entry: dict, events: list[dict]) -> list[dict]:
    """Accept service provenance, or the exact pre-upgrade confirmed snapshot."""
    record = entry["record"]
    legacy = record.get("lesson") or {}
    found = []
    for event in events:
        if not _owned(event, record):
            continue
        marker = event.get("financialLesson")
        if isinstance(marker, dict):
            valid = (marker.get("schemaVersion") == 1
                and marker.get("validationId") == record["id"]
                and marker.get("sessionId") == record["sessionId"]
                and marker.get("turnId") == record["turnId"]
                and event.get("agentId") == record["agentId"]
                and marker.get("textHash") == _hash(event.get("text", "")))
        else:
            valid = (event.get("episodeId") == legacy.get("id")
                and event.get("text") == legacy.get("text")
                and event.get("refs") == legacy.get("refs")
                # Legacy hashes fingerprinted the unnormalized request, while
                # the canonical store trimmed blank lines and indentation.
                # Exact saved ID/body/refs plus its recorded request receipt
                # authenticate the legacy content; that hash is not body hash.
                and len(str(entry.get("lessonTextHash") or "")) == 64
                and _validation()._has_ref(event.get("refs"), ref_type="item",
                    ref_id=_validation()._LESSON_REQUEST_REF_PREFIX + str(entry.get("lessonClientRequestId") or "")))
        if valid:
            found.append(event)
    return sorted(found, key=lambda e: (int((e.get("financialLesson") or {}).get("version") or 1), str(e.get("occurredAt") or ""), str(e.get("episodeId") or "")), reverse=True)


def project(entry: dict, events: list[dict]) -> dict:
    v = _validation()
    record = v._project_record(entry["record"])
    versions = events_for(entry, events)
    active = [event for event in versions if _state(event) == "active"]
    # Ambiguous concurrent/corrupt records must never select an arbitrary lesson.
    record["lesson"] = v._lesson_view(active[0]) if len(active) == 1 else None
    record["lessonState"] = "active" if len(active) == 1 else "revoked" if any(_state(e) == "revoked" for e in versions) else "superseded" if versions else "absent"
    record["lessonHistory"] = [
        {
            "lessonId": event["episodeId"], "text": event["text"],
            "state": _state(event), "createdAt": event["occurredAt"],
            "supersededBy": event.get("supersededByEpisodeId") or None,
            "revokedAt": event.get("validUntil") or None,
        } for event in versions
    ]
    return record


def _marker(record: dict, event: dict) -> dict:
    return {"schemaVersion": 1, "validationId": record["id"],
        "sessionId": record["sessionId"], "turnId": record["turnId"],
        "textHash": _hash(event["text"])}


def mutate(agent_id: str, validation_id: str, *, action: str, client_request_id: str,
           text: str = "", expected_lesson_id: str = "") -> dict[str, Any]:
    v = _validation()
    owner = v._normalize_identifier(agent_id, "assistantAgentId")
    agent = v._agent(owner)
    if action != "revoke" and (agent.get("memoryPolicy") or {}).get("enabled") is False:
        raise v.FinancialValidationError("此助手的个人记忆已关闭", 409)
    request_id = v._normalize_uuid(client_request_id, "保存请求标识")
    identifier = v._normalize_uuid(validation_id, "核验记录标识")
    text = str(text).strip()
    if action != "revoke" and (not text or len(text) > 500 or len(text.splitlines()) > 40 or any(ord(c) < 32 and c not in "\n\r\t" for c in text)):
        raise v.FinancialValidationError("教训需为 1 至 500 字，最多 40 行")
    expected = str(expected_lesson_id or "").strip()
    if action != "save" and not expected:
        raise v.FinancialValidationError("缺少预期教训版本")
    command_hash = _hash(json.dumps([identifier, action, expected, text], ensure_ascii=False))
    path = v._store_path(owner)
    try:
        with v._locked_store(path, owner) as store:
            entry = v._find_entry(store, identifier)
            record = entry["record"]
            if action != "revoke":
                if record.get("status") != "verified" or record.get("outcome") not in {"hit", "miss"}:
                    raise v.FinancialValidationError("只有已核验的研究才能保存教训", 409)
                v._verify_frozen_source(owner, record, entry)
            with episodic_memory.episodic_transaction(owner, require_enabled=action != "revoke") as tx:
                versions = events_for(entry, tx.events)
                replay = None
                for event in tx.events:
                    marker = event.get("financialLesson")
                    marker = marker if isinstance(marker, dict) else {}
                    for receipt in (marker.get("command"), marker.get("revocation")):
                        if isinstance(receipt, dict) and receipt.get("requestId") == request_id:
                            if receipt.get("hash") != command_hash:
                                raise v.FinancialValidationError("此请求标识已用于另一项教训操作", 409)
                            replay = event
                    # Old requests remain consumed, even after upgrade/revocation.
                    if v._has_ref(event.get("refs"), ref_type="item", ref_id=v._LESSON_REQUEST_REF_PREFIX + request_id) and not marker.get("command"):
                        if event not in versions or action != "save" or event.get("text") != v.directory.trim_lines(text, max_lines=40):
                            raise v.FinancialValidationError("此保存标识已用于另一条教训", 409)
                        replay = event
                if replay is not None:
                    if action != "revoke" and _state(replay) != "active":
                        raise v.FinancialValidationError("此请求对应的教训已替代或作废", 409)
                    return v._lesson_view(replay) if action == "save" else project(entry, tx.events)
                current = [event for event in versions if _state(event) == "active"]
                if len(current) > 1:
                    raise v.FinancialValidationError("教训存在多个有效版本，未应用修改", 409)
                if action == "save" and current:
                    raise v.FinancialValidationError("此核验记录已有确认教训，请修订现有版本", 409)
                if action != "save" and (not current or current[0]["episodeId"] != expected):
                    raise v.FinancialValidationError("教训版本已变化，请刷新后重试", 409)
                # Preserve authenticated legacy history as canonical provenance.
                for event in versions:
                    if not isinstance(event.get("financialLesson"), dict):
                        event["agentId"] = owner
                        event["financialLesson"] = _marker(record, event)
                        tx._dirty = True
                receipt = {"requestId": request_id, "hash": command_hash}
                if action == "revoke":
                    current[0]["financialLesson"]["revocation"] = receipt
                    tx.supersede(expected)
                    result = None
                else:
                    refs = [{"type": "item", "id": v._LESSON_REF_PREFIX + identifier},
                        {"type": "session", "id": record["sessionId"]},
                        {"type": "item", "id": v._TURN_REF_PREFIX + record["turnId"]},
                        {"type": "item", "id": v._LESSON_REQUEST_REF_PREFIX + request_id}]
                    result = tx.append(kind="note", text=text, refs=refs)
                    result["financialLesson"] = {**_marker(record, result), "command": receipt,
                        "version": max((int((e.get("financialLesson") or {}).get("version") or 1) for e in versions), default=0) + 1}
                    if action == "revise":
                        tx.supersede(expected, successor_episode_id=result["episodeId"])
                projected = project(entry, tx.events)
            # Episodes commit first. A crash here is recovered by canonical refs
            # and receipts above; metadata never becomes the content authority.
            record["lesson"] = None
            record["lessonEpisodeId"] = result["episodeId"] if result else ""
            record["revision"] = int(record.get("revision") or 0) + 1
            projected["revision"] = record["revision"]
            entry.pop("lessonClientRequestId", None)
            entry.pop("lessonTextHash", None)
            entry.pop("lessonRefs", None)
            v._save_locked(path, store)
        event_action = {"save": "saved", "revise": "revised", "revoke": "revoked"}[action]
        v._record_validation_scene_event("financial.validation.lesson_" + event_action, "lesson", record, reason="lesson_" + event_action)
        return v._lesson_view(result) if action == "save" else projected
    except v.directory.AgentDirectoryError as exc:
        raise v.FinancialValidationError(str(exc), 409) from exc
