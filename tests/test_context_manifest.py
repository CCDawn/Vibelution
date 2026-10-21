import json

from langchain_core.messages import SystemMessage

from core.context.segments import (
    build_context_manifest,
    build_context_segment,
    normalize_context_manifest,
)
from core.context.skill_contract import (
    ACTIVE_SKILL_CONTEXT_HEADER,
    build_active_skill_contract,
    build_active_skill_runtime_context,
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


def test_active_skill_contract_is_compact_and_volatile(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n"
        "# BRT\n\n"
        "- Must ask one question at a time.\n"
        "- Do not treat user words as confirmed requirements.\n"
        "Full private implementation details stay in the source document only.\n",
        encoding="utf-8",
    )

    class Skill:
        name = "brt"
        path = skill_path
        description = "BRT gate"
        content = skill_path.read_text(encoding="utf-8")
        content_hash = "hash-a"
        content_length = len(content)

    contract = build_active_skill_contract(
        {"command": "brt", "args": "设计上下文", "_skill": Skill()},
        activated_at="2026-06-12T12:00:00Z",
        activated_turn_id="turn-a",
    )
    context = build_active_skill_runtime_context(contract)

    assert contract is not None
    assert contract["command"] == "brt"
    assert contract["skillHash"] == "hash-a"
    assert "content" not in contract
    assert "Full private implementation details" not in json.dumps(contract, ensure_ascii=False)
    assert context.startswith(ACTIVE_SKILL_CONTEXT_HEADER)
    assert "Must ask one question at a time." in context
    assert is_volatile_context_text(context)
    assert is_volatile_system_context_message(SystemMessage(content=context))
    assert llm_client._is_volatile_context_content(context)


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


def test_context_composition_history_stats_cache_hit_matches_full_recompute(monkeypatch):
    from core.web.services.session import projection as session_projection

    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda conversation: {"limit": 8192, "source": "test", "modelId": "model-a", "agentId": "agent-a"},
    )
    # recordedAt 是唯一非确定性字段；冻结后命中输出可与全量重算逐字段相等。
    monkeypatch.setattr(session_service, "_now_timestamp", lambda: "2026-06-12T12:00:00Z")
    session_projection._CONTEXT_COMPOSITION_HISTORY_STATS_CACHE.clear()
    chars_calls = []
    real_message_list_chars = session_service._message_list_chars

    def counting_message_list_chars(messages):
        chars_calls.append(len(messages))
        return real_message_list_chars(messages)

    monkeypatch.setattr(session_service, "_message_list_chars", counting_message_list_chars)
    history = [
        {"role": "user", "content": "old question " + "x" * 400},
        {"role": "assistant", "content": "prior reply " + "y" * 300},
    ]
    kwargs = {
        "conversation": {"id": "session-stats-cache", "agentId": "agent-a"},
        "turn_id": "turn-1",
        "user_message": "current request",
        "history_messages": history,
        "active_task": None,
        "prompt_cache_partition": "",
    }

    first = session_service._build_last_context_composition(**kwargs)
    assert len(chars_calls) == 1
    second = session_service._build_last_context_composition(**kwargs)
    assert len(chars_calls) == 1  # 同一列表对象：命中 memo，不再全量重扫
    assert second == first  # 缓存命中输出与全量重算逐字段相等
    history_segment = next(item for item in second["segments"] if item["key"] == "history")
    assert history_segment["chars"] == real_message_list_chars(history)
    assert history_segment["contentPreview"] == session_service._message_list_content_preview(history)


def test_context_composition_history_stats_cache_invalidates_on_new_history(monkeypatch):
    from core.web.services.session import projection as session_projection

    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda conversation: {"limit": 8192, "source": "test", "modelId": "model-a", "agentId": "agent-a"},
    )
    session_projection._CONTEXT_COMPOSITION_HISTORY_STATS_CACHE.clear()
    history = [{"role": "user", "content": "old question " + "x" * 400}]
    kwargs = {
        "conversation": {"id": "session-stats-invalidate", "agentId": "agent-a"},
        "turn_id": "turn-1",
        "user_message": "current request",
        "history_messages": history,
        "active_task": None,
        "prompt_cache_partition": "",
    }

    def history_chars_of(composition):
        return next(item for item in composition["segments"] if item["key"] == "history")["chars"]

    first = session_service._build_last_context_composition(**kwargs)
    assert history_chars_of(first) == session_service._message_list_chars(history)

    # 签名自然失效：新列表（增长）重算，不复用旧值。
    grown_history = history + [{"role": "user", "content": "follow-up turn message"}]
    grown = session_service._build_last_context_composition(**{**kwargs, "history_messages": grown_history})
    assert history_chars_of(grown) == session_service._message_list_chars(grown_history)
    assert history_chars_of(grown) > history_chars_of(first)

    # 不同内容、不同对象：不得拿到 stale chars（身份键不命中）。
    other_content = [{"role": "user", "content": "z" * (len(history[0]["content"]) + 5)}]
    other = session_service._build_last_context_composition(
        **{**kwargs, "history_messages": other_content}
    )
    assert history_chars_of(other) == session_service._message_list_chars(other_content)
    assert history_chars_of(other) != history_chars_of(first)
    other_preview = next(
        item for item in other["segments"] if item["key"] == "history"
    )["contentPreview"]
    first_preview = next(
        item for item in first["segments"] if item["key"] == "history"
    )["contentPreview"]
    assert other_preview != first_preview


def test_cached_history_composition_stats_identity_hit_and_eviction(monkeypatch):
    from core.web.services.session import projection as session_projection

    session_projection._CONTEXT_COMPOSITION_HISTORY_STATS_CACHE.clear()
    history = [{"role": "user", "content": "a" * 123}, {"role": "assistant", "content": "b" * 45}]
    chars, preview = session_service._cached_history_composition_stats("session-helper", history)
    assert chars == session_service._message_list_chars(history)
    assert preview == session_service._message_list_content_preview(history)

    # 同一对象再次调用：返回同一对统计，不再触发全量扫描。
    real_message_list_chars = session_service._message_list_chars
    chars_calls = []
    monkeypatch.setattr(
        session_service,
        "_message_list_chars",
        lambda messages: (chars_calls.append(len(messages)), real_message_list_chars(messages))[1],
    )
    chars_again, preview_again = session_service._cached_history_composition_stats("session-helper", history)
    assert chars_calls == []
    assert (chars_again, preview_again) == (chars, preview)

    # 会话数超上限：FIFO 逐出，逐出后重算仍正确。
    monkeypatch.setattr(session_projection, "_CONTEXT_COMPOSITION_HISTORY_STATS_CACHE_MAX_SESSIONS", 1)
    other_history = [{"role": "user", "content": "c" * 7}]
    other_chars, _ = session_service._cached_history_composition_stats("session-helper-b", other_history)
    assert other_chars == session_service._message_list_chars(other_history)
    assert len(session_projection._CONTEXT_COMPOSITION_HISTORY_STATS_CACHE) == 1
    evicted_chars, evicted_preview = session_service._cached_history_composition_stats(
        "session-helper", history
    )
    assert evicted_chars == chars
    assert evicted_preview == preview
    session_projection._CONTEXT_COMPOSITION_HISTORY_STATS_CACHE.clear()
