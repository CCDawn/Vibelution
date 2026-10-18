"""Business outcomes remain distinct from successful native Turn completion."""
from __future__ import annotations

import json

import pytest

from core.web.services.team_workflow.generic.result_contract import evaluate_result


INVALID = {"succeeded": False, "failureCode": "business_result_invalid", "evidenceRefs": []}


def test_reported_failure_is_not_a_successful_business_outcome():
    content = json.dumps({
        "taskStatus": "failed", "problemCode": "acceptance.failed",
        "evidenceRefs": ["test:acceptance/payment-declined"],
    })

    assert evaluate_result("outcome_v1", content) == {
        "succeeded": False, "failureCode": "acceptance.failed",
        "evidenceRefs": ["test:acceptance/payment-declined"],
    }


@pytest.mark.parametrize("problem_field", [{}, {"problemCode": ""}])
def test_actual_success_keeps_evidence_in_reported_order(problem_field):
    refs = ["test:payment-accepted", "artifact:receipt.json"]
    assert evaluate_result("outcome_v1", json.dumps({
        "taskStatus": "succeeded", "evidenceRefs": refs, **problem_field,
    })) == {"succeeded": True, "failureCode": "", "evidenceRefs": refs}


@pytest.mark.parametrize("task_field", [{}, {"taskStatus": "succeeded"}])
def test_native_status_control_field_is_not_a_business_result_field(task_field):
    assert evaluate_result("outcome_v1", json.dumps({
        "status": "succeeded", "evidenceRefs": ["test:ok"], **task_field,
    })) == INVALID


@pytest.mark.parametrize("payload", [
    {}, [], None, True, 1, "succeeded",
    {"taskStatus": "succeeded"},
    {"taskStatus": True, "evidenceRefs": ["test:ok"]},
    {"taskStatus": "completed", "evidenceRefs": ["test:ok"]},
    {"taskStatus": "succeeded", "evidenceRefs": []},
    {"taskStatus": "succeeded", "evidenceRefs": "test:ok"},
    {"taskStatus": "succeeded", "evidenceRefs": [True]},
    {"taskStatus": "succeeded", "evidenceRefs": [1]},
    {"taskStatus": "succeeded", "evidenceRefs": [None]},
    {"taskStatus": "succeeded", "evidenceRefs": [{}]},
    {"taskStatus": "succeeded", "evidenceRefs": [""]},
    {"taskStatus": "succeeded", "evidenceRefs": [" \t\n"]},
    {"taskStatus": "succeeded", "evidenceRefs": ["x" * 501]},
    {"taskStatus": "succeeded", "evidenceRefs": ["test:ok"] * 21},
    {"taskStatus": "succeeded", "evidenceRefs": ["test:ok"], "extra": False},
    {"taskStatus": "succeeded", "evidenceRefs": ["test:ok"], "problemCode": False},
    {"taskStatus": "succeeded", "evidenceRefs": ["test:ok"], "problemCode": "still.failed"},
    {"taskStatus": "failed", "evidenceRefs": ["test:failed"]},
    {"taskStatus": "failed", "evidenceRefs": ["test:failed"], "problemCode": True},
])
def test_invalid_schema_fails_closed(payload):
    assert evaluate_result("outcome_v1", json.dumps(payload)) == INVALID


@pytest.mark.parametrize("code", ["", "has space", "line\n", "失败", "x" * 81, 1, None])
def test_failure_requires_a_stable_machine_problem_code(code):
    assert evaluate_result("outcome_v1", json.dumps({
        "taskStatus": "failed", "problemCode": code, "evidenceRefs": ["test:failed"],
    })) == INVALID


@pytest.mark.parametrize("code", ["x", "test.failure:v1-2_3", "x" * 80])
def test_failure_preserves_a_valid_problem_code(code):
    assert evaluate_result("outcome_v1", json.dumps({
        "taskStatus": "failed", "problemCode": code, "evidenceRefs": ["test:failed"],
    })) == {"succeeded": False, "failureCode": code, "evidenceRefs": ["test:failed"]}


@pytest.mark.parametrize("content", [
    "", "not JSON", "{", "```json\n{}\n```", "Result: {}", "{} trailing",
    '{"taskStatus":"failed","taskStatus":"succeeded","evidenceRefs":["test:ok"]}',
    "[" * 1500 + "]" * 1500,
])
def test_invalid_json_or_ambiguous_json_fails_closed(content):
    assert evaluate_result("outcome_v1", content) == INVALID


def test_maximum_evidence_count_and_reference_length_are_accepted():
    refs = [str(number) + "x" * (500 - len(str(number))) for number in range(20)]
    assert evaluate_result("outcome_v1", json.dumps({
        "taskStatus": "succeeded", "evidenceRefs": refs,
    }))["evidenceRefs"] == refs


def test_content_length_limit_applies_before_parsing():
    content = json.dumps({"taskStatus": "succeeded", "evidenceRefs": ["test:ok"]})
    bounded = content + " " * (12_000 - len(content))
    assert evaluate_result("outcome_v1", bounded)["succeeded"] is True
    assert evaluate_result("outcome_v1", bounded + " ") == INVALID


@pytest.mark.parametrize("contract", ["", "outcome_v2", "OUTCOME_V1", None, True])
def test_unknown_contract_fails_closed(contract):
    assert evaluate_result(contract, json.dumps({
        "taskStatus": "succeeded", "evidenceRefs": ["test:ok"],
    })) == INVALID


@pytest.mark.parametrize("content", ["普通结果正文", "", "failed", "x" * 12_001])
def test_legacy_text_keeps_existing_native_success_behavior(content):
    assert evaluate_result("text", content) == {
        "succeeded": True, "failureCode": "", "evidenceRefs": [],
    }
