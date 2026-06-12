import json

from langchain_core.messages import SystemMessage

from core.context.segments import (
    build_context_manifest,
    build_context_segment,
    normalize_context_manifest,
)
from core.context.volatility import VOLATILE_CONTEXT_HEADERS, is_volatile_context_text
from core.infrastructure.llm_utils import is_volatile_system_context_message
from core.llm import client as llm_client
from core.web.services import session_service


def test_shared_volatile_headers_drive_agent_and_llm_classification():
    for header in VOLATILE_CONTEXT_HEADERS:
        text = f"{header}\nvalue"
        assert is_volatile_context_text(text)
        assert is_volatile_system_context_message(SystemMessage(content=text))
        assert llm_client._is_volatile_context_content(text)

    stable_text = "## Agent Static Context\nstable"
    assert not is_volatile_context_text(stable_text)
    assert not is_volatile_system_context_message(SystemMessage(content=stable_text))
    assert not llm_client._is_volatile_context_content(stable_text)


def test_context_manifest_marks_cacheable_volatile_and_omitted_segments():
    stable = build_context_segment(
        "agent_context",
        "agent context",
        content="stable project context",
        kind="agent_static_context",
        lifecycle="stable",
        placement="system_prefix",
        cache_policy="cacheable",
        retention="persist",
        authority=80,
        volatility=10,
    )
    skill = build_context_segment(
        "skill",
        "skill",
        content="full skill payload",
        kind="slash_payload",
        lifecycle="turn",
        placement="before_current_user",
        cache_policy="volatile",
        retention="current_turn_only",
        authority=70,
        volatility=95,
    )
    omitted = build_context_segment(
        "dynamic_runtime_context",
        "dynamic runtime context",
        content="raw runtime details",
        status="omitted",
        kind="runtime_observation",
        lifecycle="turn",
        placement="omitted",
        cache_policy="never_cache",
        retention="current_turn_only",
        included_in_model_input=False,
        volatility=90,
    )

    manifest = build_context_manifest(
        turn_id="turn-1",
        recorded_at="2026-06-12T12:00:00Z",
        source="runtime_assembly",
        segments=[stable, skill, omitted],
        limit_tokens=4096,
        prompt_cache_partition="project:vibelution|agent:a|model:m",
    )

    assert manifest["schemaVersion"] == 1
    assert manifest["ordering"] == ["agent_context", "skill", "dynamic_runtime_context"]
    assert manifest["modelInputOrdering"] == ["agent_context", "skill"]
    assert manifest["cache"]["cacheableSegmentCount"] == 1
    assert manifest["cache"]["volatileSegmentCount"] == 1
    assert manifest["cache"]["firstVolatileSegmentIndex"] == 1
    assert manifest["cache"]["stablePrefixHash"]
    assert manifest["cache"]["promptCachePartitionHash"]
    assert manifest["segments"][2]["includedInModelInput"] is False
    assert manifest["segments"][2]["status"] == "omitted"
    assert "raw runtime details" not in json.dumps(manifest, ensure_ascii=False)


def test_legacy_context_composition_normalizes_to_manifest_shape():
    manifest = normalize_context_manifest(
        {
            "turnId": "legacy-turn",
            "segments": [
                {
                    "key": "current_user",
                    "label": "current user",
                    "chars": 12,
                    "tokens": 4,
                    "itemCount": 1,
                    "includedInModelInput": "false",
                }
            ],
        }
    )

    assert manifest is not None
    assert manifest["schemaVersion"] == 1
    assert manifest["segments"][0]["kind"] == "current_user"
    assert manifest["segments"][0]["includedInModelInput"] is False
    assert manifest["budgets"]["usedTokens"] == 0
    assert manifest["ordering"] == ["current_user"]
    assert manifest["modelInputOrdering"] == []
    assert "cache" in manifest
    assert "budgets" in manifest


def test_session_context_composition_records_lifecycle_and_cache_metadata(monkeypatch):
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda conversation: {
            "limit": 8192,
            "source": "test",
            "modelId": "model-a",
            "agentId": "agent-a",
        },
    )

    manifest = session_service._build_last_context_composition(
        conversation={"id": "session-a", "agentId": "agent-a"},
        turn_id="turn-context",
        user_message="current request",
        history_messages=[{"role": "user", "content": "old"}],
        active_task={"title": "task", "goal": "goal"},
        runtime_context_block="## Agent Static Context\nstable",
        dynamic_runtime_context_block="## Agent Runtime Context\ndynamic",
        guidance_context_block="## Recent Operator Guidance\nlatest",
        guidance_context_included=False,
        skill_runtime_context_block="## Slash Skill Context\nskill",
        skill_runtime_context_included=True,
        attachments=[],
        prompt_cache_partition="project:vibelution|agent:a|model:m",
    )

    by_key = {item["key"]: item for item in manifest["segments"]}
    assert manifest["schemaVersion"] == 1
    assert by_key["agent_context"]["cachePolicy"] == "cacheable"
    assert by_key["agent_context"]["placement"] == "system_prefix"
    assert by_key["dynamic_runtime_context"]["includedInModelInput"] is False
    assert by_key["dynamic_runtime_context"]["status"] == "omitted"
    assert by_key["guidance"]["includedInModelInput"] is False
    assert by_key["skill"]["includedInModelInput"] is True
    assert by_key["skill"]["placement"] == "before_current_user"
    assert manifest["modelInputOrdering"] == [
        "agent_context",
        "history",
        "skill",
        "current_user",
    ]
    assert manifest["cache"]["cacheableSegmentCount"] == 1
    assert manifest["cache"]["volatileSegmentCount"] >= 2
    assert manifest["cache"]["promptCachePartitionHash"]
