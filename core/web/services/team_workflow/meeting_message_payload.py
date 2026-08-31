"""Versioned Challenge Cup meeting-message ingestion and projection.

The model emits one JSON object. The service validates it before any display
projection, preserves the complete visible model output for audit, and derives
the legacy ``content`` field from the same object. Invalid output stays
readable and untruncated but is never promoted to structured protocol facts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from core.orchestration.output_boundary import sanitize_assistant_visible_text


MESSAGE_PAYLOAD_SCHEMA_VERSION = 1
MESSAGE_PAYLOAD_KIND = "challenge_meeting_message"
PARSE_STATUS_STRUCTURED = "structured"
PARSE_STATUS_INVALID = "invalid"

_PROTOCOL_LIST_KEYS = (
    "agreements",
    "disagreements",
    "risks",
    "actionItems",
    "knowledgeCandidates",
    "proposedCandidates",
    "evidenceRequests",
)


class MeetingMessagePayloadError(ValueError):
    """Raised when model output does not satisfy the versioned contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "message_payload_invalid")


def meeting_message_output_contract() -> str:
    """Prompt fragment for one machine-validated meeting response object."""

    return """挑战杯会议结构化输出合同：
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
    "agreements": ["已经形成的共识"],
    "disagreements": [
      {"issue": "尚未收敛的分歧", "positions": ["角色：立场"], "unresolvedReason": "未收敛原因"}
    ],
    "risks": ["需要直接暴露的风险"],
    "actionItems": [
      {"ownerRoleId": "负责角色", "action": "下一动作", "dueGate": "完成闸门"}
    ],
    "knowledgeCandidates": ["待进入知识治理的条目"],
    "proposedCandidates": [
      {"candidateId": "候选 ID", "statement": "候选陈述", "rationale": "提出理由", "proposedBy": "角色"}
    ],
    "evidenceRequests": [
      {
        "rationale": "为什么需要补证据",
        "candidateRefs": ["关联候选"],
        "searchEnvelope": {"keywords": ["检索词"], "sourceTypes": ["paper"], "evidenceLevels": ["peer_reviewed"]},
        "requirements": {"minEvidenceLevel": "medium", "completeness": "stage-one"}
      }
    ]
  }
}
没有内容的数组必须保留为空数组。display 给人阅读，protocol 给 closure digest 与证据搜集消费；不要再输出行式协议标记。"""


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            f"{field} must be a non-empty string",
        )
    return text


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            f"{field} must be a list",
        )
    return [_required_text(item, field=f"{field}[]") for item in value]


def _mapping_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            f"{field} must be a list",
        )
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise MeetingMessagePayloadError(
                "message_payload_schema_invalid",
                f"{field}[] must be an object",
            )
        items.append(dict(item))
    return items


def _normalize_display(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            "display must be an object",
        )
    raw_sections = value.get("sections")
    if not isinstance(raw_sections, list):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            "display.sections must be a list",
        )
    sections: list[dict[str, Any]] = []
    for section in raw_sections:
        if not isinstance(section, Mapping):
            raise MeetingMessagePayloadError(
                "message_payload_schema_invalid",
                "display.sections[] must be an object",
            )
        sections.append(
            {
                "title": _required_text(
                    section.get("title"),
                    field="display.sections[].title",
                ),
                "bullets": _string_list(
                    section.get("bullets"),
                    field="display.sections[].bullets",
                ),
            }
        )
    return {
        "conclusion": _required_text(
            value.get("conclusion"),
            field="display.conclusion",
        ),
        "sections": sections,
    }


def _normalize_disagreements(value: Any) -> list[dict[str, Any]]:
    items = _mapping_list(value, field="protocol.disagreements")
    return [
        {
            "issue": _required_text(item.get("issue"), field="protocol.disagreements[].issue"),
            "positions": _string_list(
                item.get("positions"),
                field="protocol.disagreements[].positions",
            ),
            "unresolvedReason": _required_text(
                item.get("unresolvedReason"),
                field="protocol.disagreements[].unresolvedReason",
            ),
        }
        for item in items
    ]


def _normalize_action_items(value: Any) -> list[dict[str, str]]:
    items = _mapping_list(value, field="protocol.actionItems")
    return [
        {
            "ownerRoleId": _required_text(
                item.get("ownerRoleId"),
                field="protocol.actionItems[].ownerRoleId",
            ),
            "action": _required_text(
                item.get("action"),
                field="protocol.actionItems[].action",
            ),
            "dueGate": _required_text(
                item.get("dueGate"),
                field="protocol.actionItems[].dueGate",
            ),
        }
        for item in items
    ]


def _normalize_proposed_candidates(value: Any) -> list[dict[str, str]]:
    items = _mapping_list(value, field="protocol.proposedCandidates")
    return [
        {
            "candidateId": _required_text(
                item.get("candidateId"),
                field="protocol.proposedCandidates[].candidateId",
            ),
            "statement": _required_text(
                item.get("statement"),
                field="protocol.proposedCandidates[].statement",
            ),
            "rationale": _required_text(
                item.get("rationale"),
                field="protocol.proposedCandidates[].rationale",
            ),
            "proposedBy": _required_text(
                item.get("proposedBy"),
                field="protocol.proposedCandidates[].proposedBy",
            ),
        }
        for item in items
    ]


def _normalize_evidence_requests(value: Any) -> list[dict[str, Any]]:
    items = _mapping_list(value, field="protocol.evidenceRequests")
    normalized: list[dict[str, Any]] = []
    for item in items:
        search_envelope = item.get("searchEnvelope")
        if not isinstance(search_envelope, Mapping):
            raise MeetingMessagePayloadError(
                "message_payload_schema_invalid",
                "protocol.evidenceRequests[].searchEnvelope must be an object",
            )
        requirements = item.get("requirements")
        if not isinstance(requirements, Mapping):
            raise MeetingMessagePayloadError(
                "message_payload_schema_invalid",
                "protocol.evidenceRequests[].requirements must be an object",
            )
        normalized.append(
            {
                "rationale": _required_text(
                    item.get("rationale"),
                    field="protocol.evidenceRequests[].rationale",
                ),
                "candidateRefs": _string_list(
                    item.get("candidateRefs"),
                    field="protocol.evidenceRequests[].candidateRefs",
                ),
                "searchEnvelope": {
                    "keywords": _string_list(
                        search_envelope.get("keywords"),
                        field="protocol.evidenceRequests[].searchEnvelope.keywords",
                    ),
                    "sourceTypes": _string_list(
                        search_envelope.get("sourceTypes"),
                        field="protocol.evidenceRequests[].searchEnvelope.sourceTypes",
                    ),
                    "evidenceLevels": _string_list(
                        search_envelope.get("evidenceLevels"),
                        field="protocol.evidenceRequests[].searchEnvelope.evidenceLevels",
                    ),
                },
                "requirements": {
                    "minEvidenceLevel": _required_text(
                        requirements.get("minEvidenceLevel"),
                        field="protocol.evidenceRequests[].requirements.minEvidenceLevel",
                    ),
                    "completeness": _required_text(
                        requirements.get("completeness"),
                        field="protocol.evidenceRequests[].requirements.completeness",
                    ),
                },
            }
        )
    return normalized


def _normalize_protocol(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            "protocol must be an object",
        )
    missing = [key for key in _PROTOCOL_LIST_KEYS if key not in value]
    if missing:
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            "protocol is missing required list fields: " + ", ".join(missing),
        )
    return {
        "agreements": _string_list(value.get("agreements"), field="protocol.agreements"),
        "disagreements": _normalize_disagreements(value.get("disagreements")),
        "risks": _string_list(value.get("risks"), field="protocol.risks"),
        "actionItems": _normalize_action_items(value.get("actionItems")),
        "knowledgeCandidates": _string_list(
            value.get("knowledgeCandidates"),
            field="protocol.knowledgeCandidates",
        ),
        "proposedCandidates": _normalize_proposed_candidates(
            value.get("proposedCandidates"),
        ),
        "evidenceRequests": _normalize_evidence_requests(
            value.get("evidenceRequests"),
        ),
    }


def _validated_model_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            "meeting message output must be a JSON object",
        )
    if value.get("schemaVersion") != MESSAGE_PAYLOAD_SCHEMA_VERSION:
        raise MeetingMessagePayloadError(
            "message_payload_schema_invalid",
            f"schemaVersion must be {MESSAGE_PAYLOAD_SCHEMA_VERSION}",
        )
    return {
        "schemaVersion": MESSAGE_PAYLOAD_SCHEMA_VERSION,
        "kind": MESSAGE_PAYLOAD_KIND,
        "display": _normalize_display(value.get("display")),
        "protocol": _normalize_protocol(value.get("protocol")),
    }


def _compatibility_content(payload: Mapping[str, Any]) -> str:
    display = payload.get("display") if isinstance(payload.get("display"), Mapping) else {}
    protocol = payload.get("protocol") if isinstance(payload.get("protocol"), Mapping) else {}
    lines = [_required_text(display.get("conclusion"), field="display.conclusion")]
    for section in list(display.get("sections") or []):
        if not isinstance(section, Mapping):
            continue
        title = _optional_text(section.get("title"))
        bullets = [_optional_text(item) for item in list(section.get("bullets") or [])]
        bullets = [item for item in bullets if item]
        if not title or not bullets:
            continue
        lines.extend(["", f"{title}：", *(f"- {item}" for item in bullets)])
    for agreement in list(protocol.get("agreements") or []):
        lines.extend(["", f"共识：{agreement}"])
    for disagreement in list(protocol.get("disagreements") or []):
        if isinstance(disagreement, Mapping):
            issue = _optional_text(disagreement.get("issue"))
            if issue:
                lines.extend(["", f"分歧：{issue}"])
    for evidence_request in list(protocol.get("evidenceRequests") or []):
        if isinstance(evidence_request, Mapping):
            rationale = _optional_text(evidence_request.get("rationale"))
            if rationale:
                lines.extend(["", f"需补证据：{rationale}"])
    return "\n".join(lines).strip()


def ingest_meeting_message_output(raw_output: Any) -> dict[str, Any]:
    """Validate a full visible model output before deriving display content."""

    raw_text = sanitize_assistant_visible_text(raw_output)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        error = MeetingMessagePayloadError(
            "message_payload_json_invalid",
            f"meeting message output is not valid JSON: {exc.msg}",
        )
    else:
        try:
            payload = _validated_model_payload(parsed)
        except MeetingMessagePayloadError as exc:
            error = exc
        else:
            payload["audit"] = {
                "parseStatus": PARSE_STATUS_STRUCTURED,
                "rawModelOutput": raw_text,
            }
            return {
                "messagePayload": payload,
                "content": _compatibility_content(payload),
            }

    return {
        "messagePayload": {
            "schemaVersion": MESSAGE_PAYLOAD_SCHEMA_VERSION,
            "kind": MESSAGE_PAYLOAD_KIND,
            "display": {"conclusion": "", "sections": []},
            "protocol": {key: [] for key in _PROTOCOL_LIST_KEYS},
            "audit": {
                "parseStatus": PARSE_STATUS_INVALID,
                "errorCode": error.code,
                "errorMessage": str(error),
                "rawModelOutput": raw_text,
            },
        },
        "content": raw_text,
    }


def structured_protocol_from_message(message: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = message.get("messagePayload")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schemaVersion") != MESSAGE_PAYLOAD_SCHEMA_VERSION:
        return None
    if str(payload.get("kind") or "").strip() != MESSAGE_PAYLOAD_KIND:
        return None
    audit = payload.get("audit") if isinstance(payload.get("audit"), Mapping) else {}
    if str(audit.get("parseStatus") or "").strip() != PARSE_STATUS_STRUCTURED:
        return None
    protocol = payload.get("protocol")
    return dict(protocol) if isinstance(protocol, Mapping) else None


__all__ = [
    "MESSAGE_PAYLOAD_KIND",
    "MESSAGE_PAYLOAD_SCHEMA_VERSION",
    "MeetingMessagePayloadError",
    "ingest_meeting_message_output",
    "meeting_message_output_contract",
    "structured_protocol_from_message",
]
