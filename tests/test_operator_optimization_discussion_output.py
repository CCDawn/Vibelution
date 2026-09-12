import json

import pytest

from core.llm.semantic_messages import SemanticOutputSchema
from core.research.operator_optimization.discussion_contracts import (
    OperatorDiscussionMessage,
)
from core.web.services.team_workflow.operator_optimization.discussion_output import (
    OperatorDiscussionOutputError,
    ingest_output,
    output_contract,
    validated_result,
)


def _message(**changes):
    payload = {
        "schemaVersion": 1,
        "contribution": "冻结 workload 上先比较 row fusion 的收益与寄存器压力。",
        "result": None,
    }
    payload.update(changes)
    return payload


def test_operator_discussion_output_uses_strict_dedicated_schema():
    contract = output_contract()

    assert isinstance(contract, SemanticOutputSchema)
    assert contract.strict is True
    assert contract.name.startswith("operator_discussion")
    assert contract.schema["additionalProperties"] is False
    assert "result" in contract.schema["properties"]
    assert contract.schema["properties"]["result"]["anyOf"][-1] == {"type": "null"}


def test_ingest_output_returns_only_validated_structured_payload():
    raw = json.dumps(_message(), ensure_ascii=False)

    payload = ingest_output(raw)

    assert payload == _message()
    assert validated_result({"operatorDiscussionPayload": payload}).contribution.startswith("冻结")


def test_selected_result_is_validated_without_fabricating_hypothesis():
    selected = _message(
        result={"status": "selected", "reason": "证据支持继续做受控比较"}
    )

    with pytest.raises(OperatorDiscussionOutputError):
        ingest_output(selected)


def test_message_reader_never_falls_back_to_raw_model_output_or_visible_content():
    raw = json.dumps(_message(), ensure_ascii=False)

    with pytest.raises(OperatorDiscussionOutputError, match="structured"):
        validated_result({"content": raw, "rawModelOutput": raw})

    with pytest.raises(OperatorDiscussionOutputError, match="rawModelOutput"):
        ingest_output({"rawModelOutput": raw})


def test_validated_result_rejects_unknown_structured_payload_fields():
    with pytest.raises(OperatorDiscussionOutputError):
        validated_result({"operatorDiscussionPayload": {**_message(), "unexpected": True}})


def test_validated_result_returns_domain_message():
    result = validated_result({"operatorDiscussionPayload": _message()})

    assert isinstance(result, OperatorDiscussionMessage)
    assert result.result is None


@pytest.mark.parametrize("key", ["structuredOutput", "structuredPayload", "payload", "content"])
def test_generic_message_fields_cannot_supply_operator_result(key):
    with pytest.raises(OperatorDiscussionOutputError):
        validated_result({key: _message()})
