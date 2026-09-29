"""Session message-level curation: include/exclude single assistant messages.

Claim scope: per-message curation decisions routed through the existing chat
capture -> review queue -> positive/negative dataset pipeline. No parallel
data store is introduced; the review queue stays the only decision authority.

Unlike ``create_chat_review_candidate_from_session`` this module intentionally
does not take a busy guard: the curation target is an already-settled
assistant message (status ``completed``), not a growing live segment, so a
running session never blocks curating its historical turns.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

from typing import Any

from core.evaluation.chat_case_lifecycle import (
    NEGATIVE_DATASET_NAME,
    POSITIVE_DATASET_NAME,
)
from core.evaluation.chat_dataset_capture import (
    approve_chat_candidate,
    load_candidate_payload,
    record_negative_chat_candidate,
)
from core.evaluation.chat_review_queue import (
    get_review_item,
    list_review_items,
    normalize_review_status,
)
from core.evaluation.chat_segmenter import build_latest_task_segment
from core.web.services.session.session_ops import _turn_items_visible_text

_INCLUDE_REVIEWER_NOTE = "inline: 用户在对话中勾选加入数据集"
_EXCLUDE_REVIEWER_NOTE = "inline: 用户在对话中标记排除"

_ACTION_TO_REVIEW_STATUS = {
    "include": "positive",
    "exclude": "negative",
}
_REVIEW_STATUS_TO_ACTION = {
    "positive": "include",
    "negative": "exclude",
}
_REVIEW_STATUS_TO_DATASET_NAME = {
    "positive": POSITIVE_DATASET_NAME,
    "negative": NEGATIVE_DATASET_NAME,
}


def _service():
    from core.web.services import session_service

    return session_service


def set_session_message_curation(session_id: str, message_id: str, *, action: str) -> dict[str, Any]:
    """Route a single-message curation decision into the chat dataset pipeline.

    The capture window ends exactly at the clicked message so the produced
    segment stops at it. Replay-safe: re-issuing the same decision returns the
    existing record; switching sides after a decision (or discarding it)
    conflicts and must go through the review workspace.
    """

    s = _service()
    lang = s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in _ACTION_TO_REVIEW_STATUS:
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="未知策展操作，只能是加入数据集或排除。",
                en="Unknown curation action. Use include or exclude.",
            )
        )
    if not normalized_session_id:
        raise s.SessionValidationError(s.text_for(lang, zh="会话 ID 不能为空。", en="Session id is required."))
    if not normalized_message_id:
        raise s.SessionValidationError(s.text_for(lang, zh="消息 ID 不能为空。", en="Message id is required."))

    _, conversations = s._load_conversations()
    conversation = next(
        (item for item in conversations if str(item.get("id") or "").strip() == normalized_session_id),
        None,
    )
    if conversation is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    messages = s._session_ledger_visible_messages(normalized_session_id)
    message = next(
        (
            item
            for item in messages
            if str(item.get("id") or "").strip() == normalized_message_id
            and str(item.get("role") or "").strip().lower() == "assistant"
        ),
        None,
    )
    if message is None:
        s._record_session_message_curation_event(
            "blocked",
            session_id=normalized_session_id,
            outcome="message_not_curatable",
            level="warning",
            fields={"messageId": normalized_message_id, "action": normalized_action},
        )
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="找不到这条助手消息，或它不是可策展的助手回复。",
                en="This assistant message was not found or is not a curatable assistant reply.",
            )
        )
    message_status = str(message.get("status") or "").strip().lower()
    if message_status not in {"", "completed"}:
        s._record_session_message_curation_event(
            "blocked",
            session_id=normalized_session_id,
            outcome="message_not_settled",
            level="warning",
            fields={"messageId": normalized_message_id, "action": normalized_action, "messageStatus": message_status},
        )
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="这条消息还在生成中或未成功收口，完成后才能策展。",
                en="This message is still streaming or did not settle successfully. Curate it once it completes.",
            )
        )
    capture_text = s._sanitize_message_content("assistant", message.get("content") or "")
    if not capture_text:
        capture_text = s._sanitize_message_content("assistant", _turn_items_visible_text(message))
    if not capture_text.strip():
        s._record_session_message_curation_event(
            "blocked",
            session_id=normalized_session_id,
            outcome="message_without_text",
            level="warning",
            fields={"messageId": normalized_message_id, "action": normalized_action},
        )
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="这条消息没有可采样的文本内容。",
                en="This message has no text content to capture.",
            )
        )

    turns = s._build_chat_turn_records_from_messages(messages)
    turn_index = next(
        (
            index
            for index, turn in enumerate(turns)
            if str((turn.metadata or {}).get("assistant_message_id") or "") == normalized_message_id
        ),
        None,
    )
    if turn_index is None:
        s._record_session_message_curation_event(
            "blocked",
            session_id=normalized_session_id,
            outcome="turn_not_found",
            level="warning",
            fields={"messageId": normalized_message_id, "action": normalized_action},
        )
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh="这条消息没有可采样的用户-助手轮次。",
                en="This message has no capturable user-assistant turn.",
            )
        )
    window = turns[: turn_index + 1]
    model_id = str((window[-1].metadata or {}).get("llm_model_id") or "").strip()
    target_status = _ACTION_TO_REVIEW_STATUS[normalized_action]

    service = s.ChatDatasetCaptureService(project_root=s.PROJECT_ROOT)
    try:
        candidate = service.capture_candidate(
            mode="chat",
            session_id=normalized_session_id,
            source_log_path=s._resolve_chat_source_log_path(),
            turns=window,
            require_auto_capture=False,
            apply_quality_filters=False,
            min_turns=1,
            max_turns=len(window),
        )
    except Exception as exc:
        s._record_session_message_curation_event(
            "failed",
            session_id=normalized_session_id,
            outcome="failed",
            level="error",
            fields={
                "messageId": normalized_message_id,
                "action": normalized_action,
                "errorType": exc.__class__.__name__,
            },
        )
        raise

    if candidate is None:
        capture_enabled = bool(getattr(service.config.evolution.chat_dataset, "enabled", False))
        if not capture_enabled:
            s._record_session_message_curation_event(
                "blocked",
                session_id=normalized_session_id,
                outcome="capture_disabled",
                level="warning",
                fields={"messageId": normalized_message_id, "action": normalized_action},
            )
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="当前配置未启用 chat 数据集采集，不能策展对话消息。",
                    en="Chat dataset capture is disabled in the current configuration.",
                )
            )
        segment = build_latest_task_segment(
            window,
            session_id=normalized_session_id,
            mode="chat",
            min_turns=1,
            max_turns=len(window),
        )
        existing_candidate_id = segment.segment_id if segment is not None else ""
        item = get_review_item(existing_candidate_id, service.paths.review_queue_path) if existing_candidate_id else None
        if item is None:
            s._record_session_message_curation_event(
                "blocked",
                session_id=normalized_session_id,
                outcome="queue_item_missing",
                level="warning",
                fields={"messageId": normalized_message_id, "action": normalized_action},
            )
            raise s.SessionMessageCurationStateError(
                s.text_for(
                    lang,
                    zh="这个片段已有历史记录但审核队列里找不到，请刷新后重试。",
                    en="This excerpt has an earlier record but is missing from the review queue. Refresh and try again.",
                )
            )
        current_status = normalize_review_status(item.get("status"))
        if current_status == "pending":
            candidate_payload = _load_existing_candidate_payload(item)
            candidate_id = existing_candidate_id
        elif current_status == target_status:
            s._record_session_message_curation_event(
                "applied",
                session_id=normalized_session_id,
                outcome="idempotent",
                fields={
                    "messageId": normalized_message_id,
                    "action": normalized_action,
                    "candidateId": existing_candidate_id,
                },
            )
            return {
                "sessionId": normalized_session_id,
                "messageId": normalized_message_id,
                "action": normalized_action,
                "status": "included" if normalized_action == "include" else "excluded",
                "candidateId": existing_candidate_id,
                "caseId": existing_candidate_id,
                "modelId": model_id,
                "datasetName": _REVIEW_STATUS_TO_DATASET_NAME[target_status],
                "summary": s.text_for(
                    lang,
                    zh="这条消息所在的片段已经在对应数据集中，无需重复操作。",
                    en="This message's excerpt is already in the target dataset. No further action needed.",
                ),
            }
        else:
            s._record_session_message_curation_event(
                "blocked",
                session_id=normalized_session_id,
                outcome="conflict",
                level="warning",
                fields={
                    "messageId": normalized_message_id,
                    "action": normalized_action,
                    "candidateId": existing_candidate_id,
                    "currentStatus": current_status,
                },
            )
            raise s.SessionMessageCurationStateError(
                s.text_for(
                    lang,
                    zh="这条消息所在的片段已进入另一侧数据集（或已丢弃），不能重复策展。",
                    en="This message's excerpt already lives in the other dataset (or was discarded) and cannot be curated again.",
                )
            )
    else:
        candidate_payload = candidate.to_dict()
        candidate_id = candidate.candidate_id

    if normalized_action == "include":
        sample = approve_chat_candidate(
            candidate_payload=candidate_payload,
            project_root=s.PROJECT_ROOT,
            reviewer_note=_INCLUDE_REVIEWER_NOTE,
        )
    else:
        sample = record_negative_chat_candidate(
            candidate_payload=candidate_payload,
            project_root=s.PROJECT_ROOT,
            reviewer_note=_EXCLUDE_REVIEWER_NOTE,
            reason_code="inline_exclude",
            error_type="user_reported",
        )
    case_id = str(sample.get("case_id") or candidate_id).strip()
    s._record_session_message_curation_event(
        "applied",
        session_id=normalized_session_id,
        outcome=target_status,
        fields={
            "messageId": normalized_message_id,
            "action": normalized_action,
            "candidateId": candidate_id,
            "caseId": case_id,
            "modelId": model_id,
        },
    )
    return {
        "sessionId": normalized_session_id,
        "messageId": normalized_message_id,
        "action": normalized_action,
        "status": "included" if normalized_action == "include" else "excluded",
        "candidateId": candidate_id,
        "caseId": case_id,
        "modelId": model_id,
        "datasetName": _REVIEW_STATUS_TO_DATASET_NAME[target_status],
        "summary": s.text_for(
            lang,
            zh=(
                "已把这条消息所在的片段纳入正例数据集。"
                if normalized_action == "include"
                else "已把这条消息所在的片段纳入负例数据集，并记录排除原因。"
            ),
            en=(
                "Added this message's excerpt to the positive dataset."
                if normalized_action == "include"
                else "Added this message's excerpt to the negative dataset with its exclusion reason."
            ),
        ),
    }


def get_session_message_curation(session_id: str) -> dict[str, Any]:
    """Derive per-message curation state from the review queue for one session."""

    s = _service()
    lang = s.get_web_language()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))
    # Existence-only check: the loaded conversation object was never used past
    # the 404 gate. Read the single session runtime row from the same chat-state
    # store that backs _load_conversations() instead of loading and fully
    # normalizing every conversation. Visibility semantics stay identical: the
    # old set had no hidden/internal filtering, so hidden sessions still resolve
    # here, and agent-directory stubs (absent from the store) still 404.
    conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
    if conversation is None:
        raise s.SessionNotFoundError(s.text_for(lang, zh="未找到当前会话。", en="Session not found."))

    capture_enabled = bool(getattr(s.get_config().evolution.chat_dataset, "enabled", False))
    from core.evaluation.chat_dataset_capture import resolve_chat_dataset_paths

    paths = resolve_chat_dataset_paths(project_root=s.PROJECT_ROOT)
    decisions: dict[str, dict[str, Any]] = {}
    for item in list_review_items(paths.review_queue_path):
        if str(item.get("session_id") or "").strip() != normalized_session_id:
            continue
        status = normalize_review_status(item.get("status"))
        action = _REVIEW_STATUS_TO_ACTION.get(status)
        if action is None:
            continue
        reviewed_at = str(item.get("reviewed_at") or "")
        candidate_id = str(item.get("candidate_id") or "").strip()
        segment = item.get("segment") if isinstance(item.get("segment"), dict) else {}
        for raw_turn in list(segment.get("conversation_turns") or []):
            if not isinstance(raw_turn, dict):
                continue
            turn_metadata = raw_turn.get("metadata") if isinstance(raw_turn.get("metadata"), dict) else {}
            assistant_message_id = str(turn_metadata.get("assistant_message_id") or "").strip()
            if not assistant_message_id:
                continue
            existing = decisions.get(assistant_message_id)
            if existing is not None and str(existing.get("decidedAt") or "") >= reviewed_at:
                continue
            decisions[assistant_message_id] = {
                "messageId": assistant_message_id,
                "action": action,
                "modelId": str(turn_metadata.get("llm_model_id") or "").strip(),
                "candidateId": candidate_id,
                "decidedAt": reviewed_at,
            }
    items = sorted(decisions.values(), key=lambda row: (row["decidedAt"], row["messageId"]))
    counts: dict[str, dict[str, Any]] = {}
    for row in items:
        model_id = str(row.get("modelId") or "")
        bucket = counts.setdefault(model_id, {"modelId": model_id, "included": 0, "excluded": 0})
        bucket["included" if row["action"] == "include" else "excluded"] += 1
    counts_by_model = sorted(
        counts.values(),
        key=lambda row: (-(row["included"] + row["excluded"]), row["modelId"]),
    )
    return {
        "sessionId": normalized_session_id,
        "captureEnabled": capture_enabled,
        "items": items,
        "countsByModel": counts_by_model,
    }


def _load_existing_candidate_payload(item: dict[str, Any]) -> dict[str, Any]:
    raw_excerpt_path = str(item.get("raw_excerpt_path") or "").strip()
    if raw_excerpt_path:
        try:
            payload = load_candidate_payload(raw_excerpt_path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload
    return dict(item)


def _record_session_message_curation_event(
    phase: str,
    *,
    session_id: str,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "chat_review",
            f"message_curation_{phase}",
            f"chat_review.message_curation.{phase}",
            level=level,
            outcome=outcome,
            message="Session message curation event.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "source": "inline_message_action",
                **(fields or {}),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-message-curation.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "phase": phase,
                "outcome": outcome,
                **(fields or {}),
            },
        )
    except Exception:
        return


__all__ = [
    "get_session_message_curation",
    "set_session_message_curation",
]
