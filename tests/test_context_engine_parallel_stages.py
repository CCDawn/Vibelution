"""Contract tests for the cache-prefix context block prefetch optimization.

The optimization must be invisible: packet bytes, stage ordering, interrupt
checkpoints and exception types stay identical to the serial path, while the
four disjoint cache-prefix blocks actually run concurrently.
"""

import threading
import time

import pytest

from core.orchestration import context_engine
from core.web.services import agent_directory_service, prompt_template_service
from core.web.services.agent_directory import episodic_memory


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_directory_service,
        "_configured_model_library_ids",
        lambda: {"model-primary", "model-research-broad"},
    )
    with context_engine._RESEARCH_ORG_CONTEXT_CACHE_LOCK:
        context_engine._RESEARCH_ORG_CONTEXT_CACHE.clear()
    with context_engine._PROJECT_AGENT_REGISTRY_CACHE_LOCK:
        context_engine._PROJECT_AGENT_REGISTRY_CACHE.clear()
    with context_engine._ACTIVE_AGENT_DIRECTORY_CACHE_LOCK:
        context_engine._ACTIVE_AGENT_DIRECTORY_CACHE.clear()
    context_engine.reset_session_context_freeze_cache()


def _make_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    return agent_directory_service.create_agent_instance(
        display_name="并行上下文 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        direct_session_id="session-parallel",
    )


def test_stage_submission_overlaps_on_separate_threads(monkeypatch):
    """A barrier proves both stages are live at the same time."""
    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "1")
    barrier = threading.Barrier(3)

    def stage():
        barrier.wait(timeout=5)
        return "ok"

    first = context_engine._submit_context_stage(stage)
    second = context_engine._submit_context_stage(stage)
    barrier.wait(timeout=5)  # only reachable when both stages run concurrently

    assert first.result()[0] == "ok"
    assert second.result()[0] == "ok"


def test_serial_fallback_creates_no_threads(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "0")
    before = threading.active_count()
    holder = context_engine._submit_context_stage(lambda: "value")
    assert holder.result()[0] == "value"
    assert threading.active_count() == before


def test_stage_exception_is_reraised_on_collecting_thread(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "1")

    def boom():
        raise ValueError("stage boom")

    holder = context_engine._submit_context_stage(boom)
    with pytest.raises(ValueError, match="stage boom"):
        holder.result()


def test_stage_elapsed_is_measured_inside_stage(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "1")

    def slow():
        time.sleep(0.03)
        return "done"

    value, elapsed_ms = context_engine._submit_context_stage(slow).result()
    assert value == "done"
    assert elapsed_ms >= 15


def test_build_agent_context_parallel_matches_serial(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, monkeypatch)

    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "0")
    serial = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-parallel",
        run_id="turn-1",
        agent_snapshot=agent,
    )

    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "1")
    context_engine.reset_session_context_freeze_cache()
    parallel = context_engine.build_agent_context(
        agent["agentId"],
        session_id="session-parallel",
        run_id="turn-1",
        agent_snapshot=agent,
    )

    for field in (
        "context_block",
        "static_context_block",
        "dynamic_context_block",
        "context_segments",
        "memory_policy",
        "tool_policy",
        "group_context_events",
        "inbox_messages",
        "episodic_events",
    ):
        assert getattr(parallel, field) == getattr(serial, field), field

    for key in (
        "episodicEventsMs",
        "runtimeContextBlockMs",
        "promptTemplateContextMs",
        "publicStructureContextMs",
        "totalDurationMs",
    ):
        assert key in parallel.timings


def test_interrupt_checkpoint_is_unchanged_under_parallel(tmp_path, monkeypatch):
    """The prefetch must not move the stop checkpoints around data stages."""
    agent = _make_agent(tmp_path, monkeypatch)
    monkeypatch.setenv("VIBELUTION_CONTEXT_PARALLEL_STAGES", "1")
    stages = []
    original = episodic_memory.list_episodic_events

    def tracked(*args, **kwargs):
        stages.append("episodic")
        return original(*args, **kwargs)

    monkeypatch.setattr(episodic_memory, "list_episodic_events", tracked)

    def interrupt_checker():
        return "operator requested stop" if "episodic" in stages else ""

    with pytest.raises(context_engine.AgentContextInterrupted) as exc_info:
        context_engine.build_agent_context(
            agent["agentId"],
            session_id="session-parallel",
            run_id="turn-1",
            agent_snapshot=agent,
            interrupt_checker=interrupt_checker,
        )

    assert stages == ["episodic"]
    assert exc_info.value.stage == "prepare_agent_context.group_context_events"
    assert exc_info.value.reason == "operator requested stop"
