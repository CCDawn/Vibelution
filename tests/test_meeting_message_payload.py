from __future__ import annotations

import json

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
                            "sourceTypes": ["paper", "preprint"],
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
