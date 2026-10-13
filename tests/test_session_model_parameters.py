from __future__ import annotations

from contextlib import nullcontext

import pytest

from core.web.services import session_service


def test_llm_options_model_and_parameters_share_one_agent_revision(monkeypatch):
    from core.web.services.session import agent_runtime

    old = {
        "agentId": "agent-a", "configRevision": 4,
        "llmBindings": {"dialogue": {"modelId": "provider/model-a"}},
        "metadata": {"llmReasoningEffort": {"dialogue": "high"}},
    }
    new = {**old, "configRevision": 5, "llmBindings": {"dialogue": {"modelId": "provider/model-b"}}}
    reads = []

    def read_agent(*_args, **_kwargs):
        reads.append(True)
        return old if len(reads) == 1 else new

    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_session_agent_id_snapshot", lambda *_args: "agent-a")
    monkeypatch.setattr(session_service, "get_agent", read_agent)
    monkeypatch.setattr(session_service, "_session_llm_model_choices", lambda: [
        {"modelId": ref, "modelRef": ref, "reasoningEffortValues": ["low", "high"], "defaultReasoningEffort": "low"}
        for ref in ("provider/model-a", "provider/model-b")
    ])
    monkeypatch.setattr(session_service, "_conversation_agent_dialogue_context_window_payload", lambda _cfg, conversation: {
        "limit": 64000 if conversation["_agent"]["configRevision"] == 4 else 32000,
        "maxLimit": 200000,
    })

    result = agent_runtime.get_session_llm_options("session-a")

    assert len(reads) == 1
    assert result["model"]["modelRef"] == "provider/model-a"
    assert result["configRevision"] == 4
    assert result["contextWindow"] == 64000
    assert result["currentReasoningEffort"] == "high"


def _patch_update_dependencies(monkeypatch, *, agent_id="agent-a", model_ref="provider/model-a"):
    agent = {"agentId": agent_id, "configRevision": 4}
    selected = {
        "modelRef": model_ref,
        "reasoningEffortValues": ["low", "high"],
    }
    updates = []
    monkeypatch.setattr(session_service, "session_agent_lifecycle_transaction", nullcontext)
    monkeypatch.setattr(session_service, "_ensure_session_conversation_record", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(session_service, "_ensure_session_mutable", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(session_service, "_session_agent_id_snapshot", lambda *_args, **_kwargs: agent_id)
    monkeypatch.setattr(session_service, "get_agent", lambda *_args, **_kwargs: agent)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda *_args, **_kwargs: selected)
    monkeypatch.setattr(
        session_service,
        "update_agent_model_parameters_if_current",
        lambda *args, **kwargs: updates.append((args, kwargs)),
    )
    expected_response = {"sessionId": "session-a", "agentId": agent_id, "currentModelId": model_ref}
    monkeypatch.setattr(session_service, "get_session_llm_options", lambda *_args, **_kwargs: expected_response)
    return updates, expected_response


def test_session_model_parameter_update_targets_current_agent_model_and_allows_active_turn(monkeypatch):
    updates, expected_response = _patch_update_dependencies(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "_is_session_running",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("active turns do not block next-turn settings")),
    )

    result = session_service.update_session_model_parameters(
        "session-a",
        expected_agent_id="agent-a",
        expected_model_ref="provider/model-a",
        expected_config_revision=4,
        context_window=32768,
        reasoning_effort="high",
    )

    assert result == expected_response
    assert updates == [
        (
            ("agent-a",),
            {
                "expected_model_ref": "provider/model-a",
                "expected_config_revision": 4,
                "context_window": 32768,
                "reasoning_effort": "high",
                "supported_reasoning_efforts": ["low", "high"],
            },
        )
    ]


@pytest.mark.parametrize(
    ("current_agent_id", "current_model_ref"),
    [("agent-b", "provider/model-a"), ("agent-a", "provider/model-b")],
)
def test_session_model_parameter_update_rejects_changed_session_identity(
    monkeypatch,
    current_agent_id,
    current_model_ref,
):
    updates, _expected_response = _patch_update_dependencies(
        monkeypatch,
        agent_id=current_agent_id,
        model_ref=current_model_ref,
    )

    with pytest.raises(session_service.SessionModelParametersConflictError):
        session_service.update_session_model_parameters(
            "session-a",
            expected_agent_id="agent-a",
            expected_model_ref="provider/model-a",
            expected_config_revision=4,
            context_window=32768,
            reasoning_effort="high",
        )

    assert updates == []
