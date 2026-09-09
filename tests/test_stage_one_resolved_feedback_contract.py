from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)
from core.web.services.team_workflow import hypothesis_review_executor
from core.web.services.team_workflow import llm_review_runners
from core.web.services.team_workflow.research_runtime import (
    feedback_iterations_artifact_writer as feedback_writer,
)


_PARENT_CANDIDATE = {
    "candidateId": "candidate-a",
    "claim": "原始假说陈述",
    "rationale": "原始依据",
    "differenceFromAlternatives": "原始差异",
    "lineageRefs": [],
    "testablePrediction": "原始预测",
    "falsifier": "原始证伪条件",
    "axisProfile": {},
}


def _revision_receipt() -> dict[str, Any]:
    return ModelInvocationReceipt.from_invocation(
        receipt_id="revision-receipt-1",
        run_id="workflow-run-1",
        node_run_id="review-node-1",
        scope={
            "questionId": "SCI-091",
            "workflowRunId": "workflow-run-1",
            "questionStage": "review",
        },
        provider="test-provider",
        model="test-model",
        requested_model="test-model",
        status=ModelInvocationStatus.SUCCEEDED,
        request_content={"purpose": "hypothesis_revision"},
        response_content={"ok": True},
        started_at_ms=1,
        finished_at_ms=2,
        retry_count=0,
        metadata={
            "questionStage": "review",
            "outcomeKinds": ["review", "revision"],
        },
        evidence_locator={"kind": "hypothesis_review_step"},
    ).to_dict()


def _run_revision(
    *,
    changes: Any = None,
    unresolved: Any = None,
    omit_unresolved: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "revisedCandidate": {
            **_PARENT_CANDIDATE,
            "claim": "修订后的假说陈述，收窄到目标人群",
        },
        "changes": ["收窄了适用边界。"] if changes is None else changes,
        "unresolvedIssues": [] if unresolved is None else unresolved,
    }
    if omit_unresolved:
        payload.pop("unresolvedIssues")

    def runner(*_args: Any) -> hypothesis_review_executor.ProviderBoundReviewResult:
        return hypothesis_review_executor.ProviderBoundReviewResult(
            payload=payload,
            model_invocation_receipt=_revision_receipt(),
        )

    receipts: list[dict[str, Any]] = []
    return hypothesis_review_executor._revision_step(
        {"contextId": "review-context-1"},
        [_PARENT_CANDIDATE],
        {
            "recommendationCandidateId": "candidate-a",
            "rationale": "需要收窄适用边界",
            "riskNotes": "",
        },
        runner=runner,
        round_id="round-1",
        formal_receipts=receipts,
    )


def _feedback_evidence() -> dict[str, Any]:
    return {
        "team_id": "team-feedback",
        "workflow_run_id": "workflow-feedback",
        "node_run_id": "node-feedback-1",
        "question_id": "SCI-091",
        "iteration_round": 1,
        "feedback": {
            "trigger": "评审要求收窄边界",
            "human_feedback": "保持在实测人群内",
            "input_refs": ["review://workflow-feedback/r1"],
            "input_hash": "a" * 64,
        },
        "revision": {
            "changes": ["收窄了适用边界。"],
            "unresolved_issues": [],
            "output_refs": ["hypothesis://workflow-feedback/r2"],
            "output_hash": "b" * 64,
            "status": "completed",
        },
        "source_collection_run_id": "source-feedback",
    }


def test_formal_revision_accepts_resolved_feedback_with_empty_unresolved_issues() -> None:
    result = _run_revision(unresolved=[])

    assert result["revision"]["changes"] == ["收窄了适用边界。"]
    assert result["revision"]["unresolvedIssues"] == []
    assert result["revision"]["actual"] is True
    assert len(result["revision"]["outputHash"]) == 64
    assert result["revisionReceiptRef"] == "revision-receipt-1"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"omit_unresolved": True}, "unresolvedIssues must be a list"),
        ({"unresolved": "still open"}, "unresolvedIssues must be a list"),
        ({"unresolved": [1]}, "unresolvedIssues must contain only non-empty strings"),
        ({"changes": []}, "changes must contain explicit evidence"),
    ],
)
def test_formal_revision_keeps_strict_list_and_actual_change_guards(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ContractValidationError, match=message):
        _run_revision(**kwargs)


def test_feedback_artifact_accepts_empty_unresolved_issues_but_keeps_authority_guards(
    monkeypatch,
) -> None:
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(
        feedback_writer,
        "list_workflow_artifacts",
        lambda *args, **kwargs: list(rows),
    )

    def fake_put(team_id: str, **kwargs: Any) -> dict[str, Any]:
        record = {
            "recordId": kwargs["artifact_identity"],
            "kind": kwargs["kind"],
            "contentHash": feedback_writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(feedback_writer, "put_workflow_artifact", fake_put)

    result = feedback_writer.write_feedback_iterations_artifact(**_feedback_evidence())

    assert result["status"] == "recorded"
    assert result["feedbackIteration"]["unresolved_issues"] == []
    assert result["outputHash"] == "b" * 64
    assert len(result["canonicalRef"]) > 0
    assert len(rows) == 1


@pytest.mark.parametrize(
    "revision_update",
    [
        {},
        {"unresolved_issues": "still open"},
        {"unresolved_issues": [1]},
        {"changes": []},
    ],
)
def test_feedback_artifact_keeps_missing_type_and_changes_guards(
    monkeypatch, revision_update: dict[str, Any]
) -> None:
    calls: list[str] = []

    def unexpected(*args: Any, **kwargs: Any) -> None:
        calls.append("store")

    monkeypatch.setattr(feedback_writer, "list_workflow_artifacts", unexpected)
    monkeypatch.setattr(feedback_writer, "put_workflow_artifact", unexpected)
    evidence = _feedback_evidence()
    if not revision_update:
        evidence["revision"].pop("unresolved_issues")
    else:
        evidence["revision"].update(revision_update)

    result = feedback_writer.write_feedback_iterations_artifact(**evidence)

    assert result["status"] == "blocked"
    assert calls == []


def test_revision_prompt_describes_empty_unresolved_issues_as_valid() -> None:
    prompt = llm_review_runners._REVISION_SYSTEM_PROMPT

    assert "unresolvedIssues 必须存在且为字符串列表" in prompt
    assert "本次反馈全部解决可为空" in prompt
    assert "两者都不能为空" not in prompt


# ----------------------------------------------- A03: required science fields

_A03_RICH_PARENT = {
    **_PARENT_CANDIDATE,
    "lineageRefs": ["literature:ref-1"],
    "axisProfile": {"mechanism": "原始机制", "boundary": "原始边界"},
}


def _run_revision_with_parent(parent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    def runner(*_args: Any) -> hypothesis_review_executor.ProviderBoundReviewResult:
        return hypothesis_review_executor.ProviderBoundReviewResult(
            payload=payload,
            model_invocation_receipt=_revision_receipt(),
        )

    return hypothesis_review_executor._revision_step(
        {"contextId": "review-context-1"},
        [parent],
        {
            "recommendationCandidateId": "candidate-a",
            "rationale": "需要收窄适用边界",
            "riskNotes": "",
        },
        runner=runner,
        round_id="round-1",
        formal_receipts=[],
    )


@pytest.mark.parametrize(
    ("field", "blank"),
    [
        ("testablePrediction", ""),
        ("falsifier", "  "),
        ("axisProfile", {}),
        ("lineageRefs", []),
    ],
)
def test_formal_revision_rejects_explicitly_blanked_required_science_fields(
    field: str, blank: Any
) -> None:
    payload = {
        "revisedCandidate": {**_A03_RICH_PARENT, "claim": "修订后的新陈述", field: blank},
        "changes": ["收窄了适用边界。"],
        "unresolvedIssues": [],
    }

    with pytest.raises(
        ContractValidationError, match=f"revisedCandidate\\.{field}"
    ) as exc_info:
        _run_revision_with_parent(_A03_RICH_PARENT, payload)

    assert "必填科学字段契约" in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("testablePrediction", 123),
        ("falsifier", ["not-a-string"]),
        ("axisProfile", "not-an-object"),
        ("lineageRefs", "literature:ref-1"),
    ],
)
def test_formal_revision_rejects_wrong_typed_required_science_fields(
    field: str, bad_value: Any
) -> None:
    payload = {
        "revisedCandidate": {
            **_A03_RICH_PARENT,
            "claim": "修订后的新陈述",
            field: bad_value,
        },
        "changes": ["收窄了适用边界。"],
        "unresolvedIssues": [],
    }

    with pytest.raises(
        ContractValidationError, match=f"revisedCandidate\\.{field}"
    ) as exc_info:
        _run_revision_with_parent(_A03_RICH_PARENT, payload)

    assert "类型错误" in str(exc_info.value)


def test_formal_revision_allows_completing_parent_empty_fields_and_inheritance() -> None:
    sparse_parent = {
        **_A03_RICH_PARENT,
        "lineageRefs": [],
        "axisProfile": {},
        "testablePrediction": "",
        "falsifier": "",
    }
    completing = {
        "revisedCandidate": {
            **sparse_parent,
            "claim": "补全后的新陈述",
            "testablePrediction": "补全后的预测",
            "falsifier": "补全后的证伪条件",
            "axisProfile": {"mechanism": "补全机制", "boundary": "补全边界"},
        },
        "changes": ["补全了缺失的科学要素。"],
        "unresolvedIssues": [],
    }
    completed = _run_revision_with_parent(sparse_parent, completing)
    completed_row = completed["revision"]["output"]["candidates"][0]
    assert completed["revision"]["actual"] is True
    assert completed_row["testablePrediction"] == "补全后的预测"
    assert completed_row["falsifier"] == "补全后的证伪条件"
    assert completed_row["axisProfile"]["mechanism"] == "补全机制"

    # Keys absent from revisedCandidate keep the inherit-from-parent behavior.
    inheriting = {
        "revisedCandidate": {**_A03_RICH_PARENT, "claim": "另一个新陈述"},
        "changes": ["换个角度表述。"],
        "unresolvedIssues": [],
    }
    inherited = _run_revision_with_parent(_A03_RICH_PARENT, inheriting)
    inherited_row = inherited["revision"]["output"]["candidates"][0]
    assert inherited_row["testablePrediction"] == _A03_RICH_PARENT["testablePrediction"]
    assert inherited_row["lineageRefs"] == _A03_RICH_PARENT["lineageRefs"]


def test_revision_runner_rejects_blanked_science_fields(monkeypatch) -> None:
    payload = {
        "revisedCandidate": {
            **_A03_RICH_PARENT,
            "claim": "修订后的新陈述",
            "testablePrediction": "",
        },
        "changes": ["收窄了适用边界。"],
        "unresolvedIssues": [],
    }
    monkeypatch.setattr(
        llm_review_runners, "_invoke_review_llm", lambda *_args, **_kwargs: payload
    )
    runners = llm_review_runners.build_hypothesis_review_runners(
        {"modelId": "test-model"}, require_provider_receipts=False
    )

    with pytest.raises(
        ContractValidationError, match="revisedCandidate\\.testablePrediction"
    ):
        runners["revision_runner"](
            {"contextId": "ctx-1", "question": "q"},
            dict(_A03_RICH_PARENT),
            [dict(_A03_RICH_PARENT)],
            {"recommendationCandidateId": "candidate-a", "metaReviewId": "m1"},
        )


def test_revision_prompt_forbids_explicitly_blanking_required_science_fields() -> None:
    prompt = llm_review_runners._REVISION_SYSTEM_PROMPT

    assert "不得显式输出空字符串、空对象或空列表" in prompt
    for field in ("testablePrediction", "falsifier", "axisProfile", "lineageRefs"):
        assert field in prompt
