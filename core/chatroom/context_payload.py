"""Versioned structured output contract for ordinary chat-room speakers.

The visible projection and the machine protocol are produced by one model
call.  Only the visible projection is copied to the legacy ``content`` field;
the protocol remains an internal Room Store projection.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.orchestration.output_boundary import sanitize_assistant_visible_text

CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION = 1
CHAT_ROOM_CONTEXT_PAYLOAD_KIND = "chat_room_context_payload"
PARSE_STATUS_STRUCTURED = "structured"
PARSE_STATUS_INVALID = "invalid"

_PROTOCOL_KEYS = (
    "agreements",
    "disagreements",
    "risks",
    "actionItems",
    "evidenceRequests",
    "stateUpdates",
)


class ChatRoomContextPayloadError(ValueError):
    """Raised when a chat-room model output violates the output contract."""


def chat_room_context_output_contract() -> str:
    """Return the stable prompt fragment shared by all ordinary chat rooms."""

    return """群聊结构化输出合同：
只输出一个 JSON 对象，不要使用 Markdown 代码围栏，也不要在对象前后添加说明。
对象必须符合以下结构：
{
  "schemaVersion": 1,
  "display": {
    "conclusion": "一句可独立阅读的当前判断",
    "sections": [
      {"title": "依据或下一步", "bullets": ["短句一", "短句二"]}
    ]
  },
  "protocol": {
    "agreements": ["明确支持的陈述"],
    "disagreements": [
      {"issue": "分歧", "positions": ["角色：立场"], "unresolvedReason": "原因"}
    ],
    "risks": ["风险"],
    "actionItems": [
      {"ownerRoleId": "负责角色", "action": "动作", "dueGate": "完成闸门", "status": "proposed|accepted|completed|blocked"}
    ],
    "evidenceRequests": [
      {"request": "所需证据", "reason": "原因"}
    ],
    "stateUpdates": [
      {"itemId": "服务端给出的条目 ID", "status": "新状态"}
    ]
  }
}
没有内容的数组必须保留为空数组。不要自报 actor、room、round、message ref 或来源身份；这些字段由服务端附加。"""


def _text(value: Any, *, field: str, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ChatRoomContextPayloadError(f"{field} must be a non-empty string")
    return result


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ChatRoomContextPayloadError(f"{field} must be a list")
    return value


def _string_list(value: Any, *, field: str) -> list[str]:
    return [_text(item, field=f"{field}[]") for item in _list(value, field=field)]


def _object_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _list(value, field=field):
        if not isinstance(item, Mapping):
            raise ChatRoomContextPayloadError(f"{field}[] must be an object")
        result.append(dict(item))
    return result


def _normalize_display(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChatRoomContextPayloadError("display must be an object")
    sections: list[dict[str, Any]] = []
    for section in _object_list(value.get("sections"), field="display.sections"):
        sections.append(
            {
                "title": _text(section.get("title"), field="display.sections[].title"),
                "bullets": _string_list(
                    section.get("bullets"), field="display.sections[].bullets"
                ),
            }
        )
    return {
        "conclusion": _text(value.get("conclusion"), field="display.conclusion"),
        "sections": sections,
    }


def _normalize_disagreements(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _object_list(value, field="protocol.disagreements"):
        result.append(
            {
                "issue": _text(item.get("issue"), field="protocol.disagreements[].issue"),
                "positions": _string_list(
                    item.get("positions"), field="protocol.disagreements[].positions"
                ),
                "unresolvedReason": _text(
                    item.get("unresolvedReason"),
                    field="protocol.disagreements[].unresolvedReason",
                ),
            }
        )
    return result


def _normalize_actions(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    allowed = {"proposed", "accepted", "completed", "blocked"}
    for item in _object_list(value, field="protocol.actionItems"):
        status = _text(
            item.get("status") or "proposed",
            field="protocol.actionItems[].status",
        ).lower()
        if status not in allowed:
            raise ChatRoomContextPayloadError(
                "protocol.actionItems[].status must be proposed, accepted, completed, or blocked"
            )
        result.append(
            {
                "ownerRoleId": _text(
                    item.get("ownerRoleId"), field="protocol.actionItems[].ownerRoleId"
                ),
                "action": _text(item.get("action"), field="protocol.actionItems[].action"),
                "dueGate": _text(
                    item.get("dueGate"), field="protocol.actionItems[].dueGate"
                ),
                "status": status,
            }
        )
    return result


def _normalize_evidence_requests(value: Any) -> list[dict[str, Any]]:
    # Evidence request payloads differ between ordinary and formal challenge
    # rooms.  Keep JSON-compatible fields while rejecting empty/non-object
    # entries; the reducer treats the object as an opaque, cited fact.
    result: list[dict[str, Any]] = []
    for item in _object_list(value, field="protocol.evidenceRequests"):
        normalized = json.loads(json.dumps(item, ensure_ascii=False, sort_keys=True))
        if not normalized:
            raise ChatRoomContextPayloadError(
                "protocol.evidenceRequests[] must not be empty"
            )
        result.append(normalized)
    return result


def _normalize_state_updates(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in _object_list(value, field="protocol.stateUpdates"):
        normalized = {
            "itemId": _text(item.get("itemId"), field="protocol.stateUpdates[].itemId"),
            "status": _text(item.get("status"), field="protocol.stateUpdates[].status").lower(),
        }
        if item.get("note") is not None:
            normalized["note"] = _text(
                item.get("note"), field="protocol.stateUpdates[].note", required=False
            )
        result.append(normalized)
    return result


def _normalize_protocol(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChatRoomContextPayloadError("protocol must be an object")
    missing = [key for key in _PROTOCOL_KEYS if key not in value]
    if missing:
        raise ChatRoomContextPayloadError(
            "protocol is missing required list fields: " + ", ".join(missing)
        )
    return {
        "agreements": _string_list(value.get("agreements"), field="protocol.agreements"),
        "disagreements": _normalize_disagreements(value.get("disagreements")),
        "risks": _string_list(value.get("risks"), field="protocol.risks"),
        "actionItems": _normalize_actions(value.get("actionItems")),
        "evidenceRequests": _normalize_evidence_requests(value.get("evidenceRequests")),
        "stateUpdates": _normalize_state_updates(value.get("stateUpdates")),
    }


def _validated_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ChatRoomContextPayloadError("chat-room output must be a JSON object")
    if value.get("schemaVersion") != CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION:
        raise ChatRoomContextPayloadError(
            f"schemaVersion must be {CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION}"
        )
    return {
        "schemaVersion": CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION,
        "kind": CHAT_ROOM_CONTEXT_PAYLOAD_KIND,
        "display": _normalize_display(value.get("display")),
        "protocol": _normalize_protocol(value.get("protocol")),
    }


def _compatibility_content(payload: Mapping[str, Any]) -> str:
    display = payload["display"]
    lines = [display["conclusion"]]
    for section in display["sections"]:
        if not section["bullets"]:
            continue
        lines.extend(["", f"{section['title']}："])
        lines.extend(f"- {item}" for item in section["bullets"])
    return "\n".join(lines).strip()


def _empty_payload(raw_text: str, error: Exception) -> dict[str, Any]:
    return {
        "schemaVersion": CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION,
        "kind": CHAT_ROOM_CONTEXT_PAYLOAD_KIND,
        "display": {"conclusion": "", "sections": []},
        "protocol": {key: [] for key in _PROTOCOL_KEYS},
        "audit": {
            "parseStatus": PARSE_STATUS_INVALID,
            "errorCode": "chat_room_context_payload_invalid",
            "errorMessage": str(error),
            "rawModelOutput": raw_text,
        },
    }


def ingest_chat_room_context_output(raw_output: Any) -> dict[str, Any]:
    """Parse one speaker output without retrying or promoting invalid text."""

    raw_text = sanitize_assistant_visible_text(raw_output)
    try:
        parsed = json.loads(raw_text)
        payload = _validated_payload(parsed)
    except (json.JSONDecodeError, ChatRoomContextPayloadError, TypeError) as exc:
        return {"content": raw_text, "contextPayload": _empty_payload(raw_text, exc)}

    payload["audit"] = {
        "parseStatus": PARSE_STATUS_STRUCTURED,
        "rawModelOutput": raw_text,
    }
    return {"content": _compatibility_content(payload), "contextPayload": payload}


def structured_protocol_from_message(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """Adapt ordinary and formal challenge payloads to one reducer input."""

    candidates = (
        (message.get("contextPayload"), CHAT_ROOM_CONTEXT_PAYLOAD_KIND),
        (message.get("messagePayload"), "challenge_meeting_message"),
    )
    for payload, expected_kind in candidates:
        if not isinstance(payload, Mapping):
            continue
        audit = payload.get("audit")
        if (
            payload.get("schemaVersion") == 1
            and str(payload.get("kind") or "").strip() == expected_kind
            and isinstance(audit, Mapping)
            and str(audit.get("parseStatus") or "").strip() == PARSE_STATUS_STRUCTURED
            and isinstance(payload.get("protocol"), Mapping)
        ):
            protocol = dict(payload["protocol"])
            for key in _PROTOCOL_KEYS:
                protocol.setdefault(key, [])
            protocol.setdefault("knowledgeCandidates", [])
            return protocol
    return None


__all__ = [
    "CHAT_ROOM_CONTEXT_PAYLOAD_KIND",
    "CHAT_ROOM_CONTEXT_PAYLOAD_SCHEMA_VERSION",
    "ChatRoomContextPayloadError",
    "chat_room_context_output_contract",
    "ingest_chat_room_context_output",
    "structured_protocol_from_message",
]
