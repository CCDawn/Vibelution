from core.orchestration.turn_runner import (
    AgentSingleTurnRequest,
    call_agent_factory_with_supported_kwargs,
    create_agent_runtime,
    prepare_agent_turn,
    run_agent_single_turn,
    run_existing_agent_single_turn,
)
from core.orchestration.turn_runtime import (
    AgentTurnRuntimeRequest,
    build_prompt_cache_partition,
    prepare_agent_turn_runtime,
    runtime_metadata_env,
)


class _FakePromptCachePartitionScope:
    def __init__(self, events, partition):
        self.events = events
        self.partition = partition

    def __enter__(self):
        self.events.append(("enter", self.partition))

    def __exit__(self, exc_type, exc, tb):
        self.events.append(("exit", self.partition))
        return False


def test_create_agent_runtime_uses_shared_agent_factory():
    captured = {}
    agent = object()

    def factory(**kwargs):
        captured.update(kwargs)
        return agent

    created = create_agent_runtime(
        mode="chat",
        workspace_path="workspace/session",
        config="config",
        agent_factory=factory,
    )

    assert created is agent
    assert captured == {
        "mode": "chat",
        "workspace_path": "workspace/session",
        "config": "config",
    }


def test_call_agent_factory_with_supported_kwargs_filters_by_signature():
    captured = {}
    agent = object()

    def factory(*, config=None):
        captured["config"] = config
        return agent

    created = call_agent_factory_with_supported_kwargs(
        factory,
        workspace_path="workspace/session",
        config="config",
    )

    assert created is agent
    assert captured == {"config": "config"}


def test_call_agent_factory_with_supported_kwargs_supports_var_kwargs():
    captured = {}
    agent = object()

    def factory(**kwargs):
        captured.update(kwargs)
        return agent

    created = call_agent_factory_with_supported_kwargs(
        factory,
        workspace_path="workspace/session",
        config="config",
    )

    assert created is agent
    assert captured == {
        "workspace_path": "workspace/session",
        "config": "config",
    }


def test_call_agent_factory_with_supported_kwargs_calls_no_arg_factory():
    agent = object()

    def factory():
        return agent

    created = call_agent_factory_with_supported_kwargs(
        factory,
        workspace_path="workspace/session",
        config="config",
    )

    assert created is agent


def test_run_agent_single_turn_seeds_context_and_exports_carryover():
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, *, mode=None, workspace_path=None, config=None):
            captured["mode"] = mode
            captured["workspace_path"] = workspace_path
            captured["config"] = config

        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def set_turn_interrupt_checker(self, checker):
            captured["interrupt_reason"] = checker()

        def run_single_turn(self, initial_prompt=None):
            captured["initial_prompt"] = initial_prompt
            return {"status": "completed", "summary": "done"}

        def export_turn_carryover(self):
            return {"next": "state"}

    config = object()
    result = run_agent_single_turn(
        AgentSingleTurnRequest(
            mode="self_evolution",
            workspace_path="workspace/agent",
            config=config,
            initial_prompt="probe",
            carryover={"previous": "state"},
            runtime_context="Agent Runtime Context",
            interrupt_checker=lambda: "stop_requested",
        ),
        agent_factory=lambda **kwargs: FakeAgent(**kwargs),
    )

    assert captured == {
        "mode": "self_evolution",
        "workspace_path": "workspace/agent",
        "config": config,
        "carryover": {"previous": "state"},
        "interrupt_reason": "stop_requested",
        "initial_prompt": "probe",
    }
    assert result.result == {"status": "completed", "summary": "done"}
    assert result.carryover == {"next": "state"}


def test_prepare_agent_turn_runtime_builds_stable_isolated_prompt_cache_partitions():
    chat = prepare_agent_turn_runtime(
        AgentTurnRuntimeRequest(
            mode="chat",
            run_kind="chat_turn",
            run_id="turn-1",
            session_id="session-a",
            agent_id="agent-a",
            llm_slot="dialogue",
            model_id="model-a",
        )
    )
    same_chat = prepare_agent_turn_runtime(
        AgentTurnRuntimeRequest(
            mode="chat",
            run_kind="chat_turn",
            run_id="turn-2",
            session_id="session-a",
            agent_id="agent-a",
            llm_slot="dialogue",
            model_id="model-a",
        )
    )
    self_turn = prepare_agent_turn_runtime(
        AgentTurnRuntimeRequest(
            mode="self_evolution",
            run_kind="self_evolution",
            run_id="self-run-1",
            session_id="session-a",
            agent_id="agent-a",
            llm_slot="dialogue",
            model_id="model-a",
        )
    )

    assert chat.prompt_cache_partition == same_chat.prompt_cache_partition
    assert chat.prompt_cache_partition != self_turn.prompt_cache_partition
    assert chat.metadata["runKind"] == "chat_turn"
    assert chat.metadata["promptCachePartitionHash"]
    assert chat.metadata["promptCachePartitionChars"] == len(chat.prompt_cache_partition)
    assert "run:turn-1" not in chat.prompt_cache_partition


def test_build_prompt_cache_partition_keeps_supervised_roles_isolated():
    baseline = build_prompt_cache_partition(
        mode="supervised_evolution",
        run_kind="supervised_evaluation",
        session_id="supervised-session",
        agent_id="agent-supervised",
        llm_slot="dialogue",
        model_id="model-a",
        cache_scope="baseline",
    )
    candidate = build_prompt_cache_partition(
        mode="supervised_evolution",
        run_kind="supervised_evaluation",
        session_id="supervised-session",
        agent_id="agent-supervised",
        llm_slot="dialogue",
        model_id="model-a",
        cache_scope="candidate",
    )

    assert baseline != candidate
    assert "mode:supervised_evolution" in baseline
    assert "kind:supervised_evaluation" in baseline
    assert "scope:baseline" in baseline
    assert "scope:candidate" in candidate


def test_runtime_metadata_env_exports_safe_facade_fields_only():
    env = runtime_metadata_env(
        prepare_agent_turn_runtime(
            AgentTurnRuntimeRequest(
                mode="supervised_evolution",
                run_kind="supervised_evaluation",
                run_id="harness-run-1",
                session_id="session-baseline",
                agent_id="agent-supervised-baseline",
                llm_slot="dialogue",
                model_id="model-a",
                cache_scope="baseline",
            )
        )
    )

    assert env == {
        "VIBELUTION_TURN_MODE": "supervised_evolution",
        "VIBELUTION_TURN_RUN_KIND": "supervised_evaluation",
        "VIBELUTION_TURN_RUN_ID": "harness-run-1",
        "VIBELUTION_TURN_SESSION_ID": "session-baseline",
        "VIBELUTION_TURN_AGENT_ID": "agent-supervised-baseline",
        "VIBELUTION_TURN_LLM_SLOT": "dialogue",
        "VIBELUTION_TURN_MODEL_ID": "model-a",
        "VIBELUTION_TURN_CACHE_SCOPE": "baseline",
        "VIBELUTION_TURN_PROMPT_CACHE_PARTITION": (
            "mode:supervised_evolution|kind:supervised_evaluation|agent:agent-supervised-baseline|"
            "session:session-baseline|slot:dialogue|model:model-a|scope:baseline"
        ),
    }


def test_prepare_agent_turn_seeds_optional_supported_inputs():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def seed_static_runtime_context(self, context):
            captured["static_runtime_context"] = context

        def mark_runtime_context_seeded_by_host(self):
            captured["runtime_context_seeded_by_host"] = True

        def set_turn_interrupt_checker(self, checker):
            captured["interrupt_reason"] = checker()

        def seed_chat_history(self, history):
            captured["chat_history"] = history

    prepare_agent_turn(
        FakeAgent(),
        carryover={"previous": "state"},
        runtime_context="Legacy Runtime Context",
        static_runtime_context="Static Runtime Context",
        dynamic_runtime_context="Dynamic Runtime Context",
        interrupt_checker=lambda: "stop_requested",
        chat_history=[{"role": "assistant", "content": "hello"}],
    )

    assert captured == {
        "carryover": {"previous": "state"},
        "static_runtime_context": "Static Runtime Context",
        "runtime_context_seeded_by_host": True,
        "interrupt_reason": "stop_requested",
        "chat_history": [{"role": "assistant", "content": "hello"}],
    }


def test_run_existing_agent_single_turn_passes_supported_optional_kwargs():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None, disable_tools=False, attachments=None):
            captured["initial_prompt"] = initial_prompt
            captured["disable_tools"] = disable_tools
            captured["attachments"] = attachments
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="probe",
        disable_tools=True,
        attachments=[{"kind": "image"}],
    )

    assert result == {"status": "completed"}
    assert captured == {
        "initial_prompt": "probe",
        "disable_tools": True,
        "attachments": [{"kind": "image"}],
    }


def test_run_existing_agent_single_turn_wraps_runner_with_prompt_cache_partition(monkeypatch):
    events: list[tuple[str, str]] = []

    def fake_scope(partition):
        return _FakePromptCachePartitionScope(events, partition)

    monkeypatch.setattr("core.orchestration.turn_runner.prompt_cache_partition_scope", fake_scope)

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None):
            events.append(("run", initial_prompt))
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="probe",
        prompt_cache_partition="agent:a|session:s|slot:dialogue|model:m",
    )

    assert result == {"status": "completed"}
    assert events == [
        ("enter", "agent:a|session:s|slot:dialogue|model:m"),
        ("run", "probe"),
        ("exit", "agent:a|session:s|slot:dialogue|model:m"),
    ]


def test_run_existing_agent_single_turn_omits_unsupported_optional_kwargs():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None):
            captured["initial_prompt"] = initial_prompt
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="probe",
        disable_tools=True,
        attachments=[{"kind": "image"}],
    )

    assert result == {"status": "completed"}
    assert captured == {"initial_prompt": "probe"}
