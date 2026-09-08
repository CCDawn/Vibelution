import json
from types import SimpleNamespace

import pytest

from core.research.competition.question_result_package import canonical_model_policy
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from core.web.services.team_workflow.research_runtime.meeting_model_route import resolve_meeting_speaker_llm
from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import MeetingReceiptAuthorityError


def _formal_context(monkeypatch):
    required = canonical_model_policy({
        "family": "qwen", "providerIds": ["dashscope"],
        "modelIds": ["qwen-plus", "qwen-max"], "requireOfficialProvider": True,
    })
    policy = {"requiredModelPolicy": required, "modelPolicySha256": required["policySha256"], "routes": {
        "reasoning": {"byProductRole": {"generator": {
            "agentId": "speaker", "productRoleId": "generator", "providerId": "dashscope",
            "modelRef": "dashscope/qwen-plus", "modelId": "qwen-plus",
        }}},
    }}
    run = SimpleNamespace(team_id="team", input_snapshot_json=json.dumps({"modelRoutingPolicy": policy}))
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: SimpleNamespace(get_run=lambda _: run))
    return {"_modelInvocationReceiptAuthority": {
        "workflowRunId": "run-current", "teamId": "team", "modelPolicySha256": required["policySha256"],
    }}


def test_formal_meeting_uses_frozen_model_despite_live_agent_change(monkeypatch):
    context = _formal_context(monkeypatch)
    original = {"agentId": "speaker", "llmBindings": {"dialogue": {"modelId": "dashscope/qwen-max"}}}
    def resolver(agent):
        model_ref = agent["llmBindings"]["dialogue"]["modelId"]
        return SimpleNamespace(model_ref=model_ref, provider_id="dashscope", model=model_ref.split("/")[1])
    resolved = resolve_meeting_speaker_llm(original, context, resolver)
    assert resolved.model == "qwen-plus"
    assert original["llmBindings"]["dialogue"]["modelId"] == "dashscope/qwen-max"


def test_model_alias_drift_is_rejected_before_call(monkeypatch):
    context = _formal_context(monkeypatch)
    with pytest.raises(MeetingReceiptAuthorityError, match="resolved meeting model"):
        resolve_meeting_speaker_llm({"agentId": "speaker"}, context, lambda _: SimpleNamespace(
            model_ref="dashscope/qwen-plus", provider_id="dashscope", model="qwen-max",
        ))


def test_ordinary_chat_keeps_live_agent_binding_without_ledger(monkeypatch):
    monkeypatch.setattr(formal_write_runtime, "get_write_store", lambda: pytest.fail("ordinary chat queried formal Ledger"))
    original = {"agentId": "ordinary"}
    assert resolve_meeting_speaker_llm(original, {}, lambda agent: agent) is original
