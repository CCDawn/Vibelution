from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.orchestration import context_engine
from core.web.services import agent_directory_service
from core.web.services.agent_directory import episodic_memory
from tests.test_context_engine import _use_tmp_project_root


def test_native_finance_context_excludes_lessons_and_keeps_old_preferences(
    tmp_path, monkeypatch
):
    """Generic context has no trusted stock/date scope for finance lessons."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Finance memory scope test",
        role_key="financial_advisor",
        primary_mode="general",
        prompt_template_id="prompt-chat-default",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        metadata={
            "financialAssistantProfile": "financial_assistant_v1",
            "financialAssistantSetup": "ready",
        },
    )

    newest = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    episodes = [
        {
            "episodeId": "provenance-only-lesson",
            "kind": "note",
            "text": "PROVENANCE_LESSON_MUST_NOT_LEAK",
            "financialLesson": {"validationId": "validation-1"},
            "refs": [],
            "occurredAt": newest.isoformat(),
            "validUntil": "",
        },
        {
            "episodeId": "financial-lesson",
            "eventId": "financial-lesson",
            "kind": "note",
            "text": "FINANCIAL_LESSON_MUST_NOT_LEAK: only for 600519 after 2026-10-12",
            "refs": [{"type": "item", "id": "financial-validation:validation-1"}],
            "occurredAt": (newest + timedelta(seconds=1)).isoformat(),
            "validUntil": "",
        }
    ]
    episodes.extend(
        {
            "episodeId": f"ordinary-{index}",
            "eventId": f"ordinary-{index}",
            "kind": "note",
            "text": f"ordinary memory marker {index}",
            "refs": [],
            "occurredAt": (newest - timedelta(minutes=index)).isoformat(),
            "validUntil": "",
        }
        for index in range(1, 210)
    )
    episodes.append(
        {
            "episodeId": "old-stable-preference",
            "eventId": "old-stable-preference",
            "kind": "preference",
            "text": "OLD_STABLE_PREFERENCE_MUST_REMAIN_AVAILABLE",
            "refs": [],
            "occurredAt": "2020-01-01T00:00:00+00:00",
            "validUntil": "",
        }
    )
    # This full ordered snapshot stands in for the store's lossless list API;
    # the store API itself is owned by the concurrent episodic-memory lane.
    monkeypatch.setattr(
        episodic_memory,
        "list_episodic_events",
        lambda _agent_id, *, include_superseded=False: list(episodes),
        raising=False,
    )
    monkeypatch.setattr(
        agent_directory_service,
        "list_current_episodic_events",
        lambda _agent_id, *, limit: list(episodes[:limit]),
    )

    packet = context_engine.build_agent_context(
        agent["agentId"], session_id="finance-memory-scope", run_id="turn-1"
    )

    assert "FINANCIAL_LESSON_MUST_NOT_LEAK" not in packet.context_block
    assert "PROVENANCE_LESSON_MUST_NOT_LEAK" not in packet.context_block
    assert "OLD_STABLE_PREFERENCE_MUST_REMAIN_AVAILABLE" in packet.context_block
    assert len(packet.episodic_events) == 9
    assert sum(item.get("kind") == "preference" for item in packet.episodic_events) == 1
    assert sum(item.get("kind") != "preference" for item in packet.episodic_events) == 8
    assert all(
        not any(
            isinstance(ref, dict)
            and ref.get("type") == "item"
            and str(ref.get("id") or "").startswith("financial-validation:")
            for ref in item.get("refs") or []
        )
        for item in packet.episodic_events
    )
