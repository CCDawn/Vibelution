from __future__ import annotations

import json
import pytest

from core.web.services.team_workflow import meeting_message_payload as payloads


def _structured_output() -> str:
    return json.dumps(
        {
            "schemaVersion": 1,
            "display": {
                "conclusion": "当前证据只能支持间接外推，不能升级候选。",
                "sections": [
                    {
                        "title": "审计发现",
                        "bullets": [
                            "Tao 2014 不在目标作用域内。",
                            "Elgindi 2021 只能作为间接支持。",
                        ],
                    },
                    {
                        "title": "证据边界",
                        "bullets": [
                            "尚无光滑初值真 NS 有限时间爆破的直接证据。",
                            "2022 年后的进展仍需检索。",
                        ],
                    },
                    {
                        "title": "下一步",
                        "bullets": [
                            "补齐论文与预印本。",
                            "按证据等级回填。",
                            "完成 lineage 复核。",
                            "保留最终哨兵 LAST-LINE。",
                        ],
                    },
                ],
            },
            "protocol": {
                "agreements": ["现有锚点只能作为间接支持。"],
                "disagreements": [],
                "risks": ["2022 年后的进展尚未覆盖。"],
                "actionItems": [
                    {
                        "ownerRoleId": "knowledge_steward",
                        "action": "补齐检索并回填证据等级",
                        "dueGate": "before_candidate_promotion",
                    }
                ],
                "knowledgeCandidates": [],
                "proposedCandidates": [],
                "evidenceRequests": [
                    {
                        "rationale": "缺少直接证据",
                        "candidateRefs": ["sci-002-c034eaea9"],
                        "searchEnvelope": {
                            "keywords": ["smooth initial data Navier-Stokes blowup"],
                            "sourceTypes": ["paper"],
                            "evidenceLevels": ["peer_reviewed", "preprint"],
                        },
                        "requirements": {
                            "minEvidenceLevel": "medium",
                            "completeness": "stage-one",
                        },
                    }
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def test_ingestion_preserves_full_structured_output_before_projection() -> None:
    raw_output = _structured_output()
    assert len(raw_output.splitlines()) > 20

    ingested = payloads.ingest_meeting_message_output(raw_output)

    message_payload = ingested["messagePayload"]
    assert message_payload["schemaVersion"] == 1
    assert message_payload["kind"] == "challenge_meeting_message"
    assert message_payload["audit"]["parseStatus"] == "structured"
    assert message_payload["audit"]["rawModelOutput"] == raw_output
    assert message_payload["display"]["sections"][-1]["bullets"][-1] == "保留最终哨兵 LAST-LINE。"
    assert "LAST-LINE" in ingested["content"]
    assert "EVIDENCE_REQUEST" not in ingested["content"]


def test_single_json_fence_is_an_output_envelope_not_invalid_json() -> None:
    raw_output = "```json\n" + _structured_output() + "\n```"
    ingested = payloads.ingest_meeting_message_output(raw_output)
    assert ingested["messagePayload"]["audit"]["parseStatus"] == "structured"
    assert ingested["messagePayload"]["audit"]["rawModelOutput"] == raw_output
    assert "LAST-LINE" in ingested["content"]


def test_prose_around_json_is_not_silently_accepted() -> None:
    ingested = payloads.ingest_meeting_message_output("说明\n```json\n" + _structured_output() + "\n```")
    assert ingested["messagePayload"]["audit"]["parseStatus"] == "invalid"


def test_invalid_output_is_preserved_without_twenty_line_truncation() -> None:
    raw_output = "\n".join(f"第 {index:02d} 行" for index in range(1, 31))

    ingested = payloads.ingest_meeting_message_output(raw_output)

    message_payload = ingested["messagePayload"]
    assert message_payload["audit"]["parseStatus"] == "invalid"
    assert message_payload["audit"]["errorCode"] == "message_payload_json_invalid"
    assert message_payload["audit"]["rawModelOutput"] == raw_output
    assert ingested["content"] == raw_output
    assert ingested["content"].splitlines()[-1] == "第 30 行"


def test_output_contract_names_the_single_versioned_object() -> None:
    contract = payloads.meeting_message_output_contract()

    assert "只输出一个 JSON 对象" in contract
    assert '"schemaVersion": 1' in contract
    assert '"display"' in contract
    assert '"protocol"' in contract
    assert "AGREE:" not in contract
    assert "EVIDENCE_REQUEST:" not in contract


@pytest.mark.parametrize(
    "section,field,value,error_code",
    [
        ("searchEnvelope", "sourceTypes", ["survey"], "search_sourceTypes_invalid"),
        ("searchEnvelope", "evidenceLevels", ["systematic_review"], "search_evidenceLevels_invalid"),
        ("searchEnvelope", "keywords", [], "search_keywords_required"),
        ("requirements", "minEvidenceLevel", "industry_report", "requirements_evidence_level_invalid"),
    ],
)
def test_meeting_rejects_requests_that_collection_cannot_consume(section, field, value, error_code):
    raw = json.loads(_structured_output())
    raw["protocol"]["evidenceRequests"][0][section][field] = value
    ingested = payloads.ingest_meeting_message_output(json.dumps(raw))
    audit = ingested["messagePayload"]["audit"]
    assert audit["parseStatus"] == "invalid"
    assert audit["errorCode"] == error_code
    assert "protocol.evidenceRequests[0]" in audit["errorMessage"]


def test_meeting_request_normalization_matches_collection_and_prompt_enums():
    from core.web.services.team_workflow.source_collection import facade
    from core.web.services.team_workflow.meeting_runtime import validate_evidence_request_draft

    raw = json.loads(_structured_output())
    request = raw["protocol"]["evidenceRequests"][0]
    request["searchEnvelope"]["sourceTypes"] = [s.upper() for s in sorted(facade.SEARCH_ENVELOPE_SOURCE_TYPES)]
    request["searchEnvelope"]["evidenceLevels"] = sorted(facade.SEARCH_ENVELOPE_EVIDENCE_LEVELS)
    payload = payloads.ingest_meeting_message_output(json.dumps(raw))["messagePayload"]
    assert payload["audit"]["parseStatus"] == "structured"
    accepted = payload["protocol"]["evidenceRequests"][0]
    downstream, errors = validate_evidence_request_draft(accepted, {})
    assert errors == []
    assert accepted["searchEnvelope"] == downstream["searchEnvelope"]
    contract = payloads.meeting_message_output_contract()
    assert json.dumps(sorted(facade.SEARCH_ENVELOPE_SOURCE_TYPES)) in contract
    assert json.dumps(sorted(facade.SEARCH_ENVELOPE_EVIDENCE_LEVELS)) in contract


def test_nested_protocol_objects_must_match_the_versioned_schema() -> None:
    malformed = json.loads(_structured_output())
    malformed["protocol"]["proposedCandidates"] = [
        {"candidateId": "candidate-without-statement"},
    ]
    malformed["protocol"]["evidenceRequests"] = [
        {"rationale": "missing search envelope"},
    ]

    ingested = payloads.ingest_meeting_message_output(
        json.dumps(malformed, ensure_ascii=False),
    )

    assert ingested["messagePayload"]["audit"]["parseStatus"] == "invalid"
    assert ingested["messagePayload"]["audit"]["errorCode"] == "message_payload_schema_invalid"
    assert ingested["messagePayload"]["protocol"]["proposedCandidates"] == []


def test_structured_candidate_preserves_optional_grounding_fields() -> None:
    structured = json.loads(_structured_output())
    structured["protocol"]["proposedCandidates"] = [
        {
            "candidateId": "draft-a",
            "statement": "腺苷积累损害记忆巩固",
            "rationale": "受体机制明确",
            "proposedBy": "challenge_cup_hypothesis",
            "lineageRefs": ["evidence:accepted-1", "evidence:boundary-1"],
            "testablePrediction": "阻断 A1 受体后记忆表现应恢复",
            "falsifier": "阻断 A1 受体后记忆表现仍不恢复",
            "axisProfile": {
                "mechanism": "腺苷 A1 受体介导",
                "intervention": "阻断 A1 受体",
                "observable": "记忆表现",
                "population": "睡眠剥夺受试者",
                "boundary": "急性睡眠剥夺",
            },
        }
    ]

    ingested = payloads.ingest_meeting_message_output(
        json.dumps(structured, ensure_ascii=False)
    )

    candidate = ingested["messagePayload"]["protocol"]["proposedCandidates"][0]
    assert candidate["lineageRefs"] == [
        "evidence:accepted-1",
        "evidence:boundary-1",
    ]
    assert candidate["testablePrediction"] == "阻断 A1 受体后记忆表现应恢复"
    assert candidate["falsifier"] == "阻断 A1 受体后记忆表现仍不恢复"
    assert candidate["axisProfile"]["mechanism"] == "腺苷 A1 受体介导"


def test_native_schema_rejects_unknown_source_type_and_matches_ingestion():
    from jsonschema import Draft202012Validator

    contract = payloads.meeting_message_structured_output_contract()
    def thaw(value):
        from collections.abc import Mapping
        if isinstance(value, Mapping):
            return {key: thaw(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [thaw(item) for item in value]
        return value
    schema = thaw(contract.schema)
    validator = Draft202012Validator(schema)
    value = json.loads(_structured_output())
    assert list(validator.iter_errors(value)) == []
    assert contract.validator(value)["protocol"]
    value["protocol"]["evidenceRequests"][0]["searchEnvelope"]["sourceTypes"] = ["technical_report"]
    assert list(validator.iter_errors(value))
    with pytest.raises(payloads.MeetingMessagePayloadError, match="technical_report"):
        contract.validator(value)
