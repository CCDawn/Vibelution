from core.llm.payload_builder import current_prompt_cache_partition
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
            turn_identity="turn-1",
            carryover={
                "turnIdentity": "turn-1",
                "terminal": False,
                "goal": "probe",
                "messages": [{"kind": "dict", "role": "user", "content": "probe"}],
            },
            runtime_context="Agent Runtime Context",
            interrupt_checker=lambda: "stop_requested",
        ),
        agent_factory=lambda **kwargs: FakeAgent(**kwargs),
    )

    assert captured == {
        "mode": "self_evolution",
        "workspace_path": "workspace/agent",
        "config": config,
        "carryover": {
            "turnIdentity": "turn-1",
            "terminal": False,
            "goal": "probe",
            "messages": [{"kind": "dict", "role": "user", "content": "probe"}],
        },
        "interrupt_reason": "stop_requested",
        "initial_prompt": "probe",
    }
    assert result.result == {"status": "completed", "summary": "done"}
    assert result.carryover == {"next": "state"}


def test_run_agent_single_turn_passes_runtime_agent_binding_to_factory():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None):
            return {"status": "completed", "prompt": initial_prompt}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeAgent()

    result = run_agent_single_turn(
        AgentSingleTurnRequest(
            mode="self_evolution",
            workspace_path="workspace/observer",
            config="observer-config",
            initial_prompt="observe",
            runtime=AgentTurnRuntimeRequest(
                mode="self_evolution",
                run_kind="self_evolution",
                run_id="self-loop-1",
                session_id="session-observer",
                agent_id="agent-observer",
                llm_slot="dialogue",
                model_id="lan_qwen/qwen3_6",
                cache_scope="observer",
                workspace_path="workspace/observer",
            ),
        ),
        agent_factory=factory,
    )

    assert captured == {
        "mode": "self_evolution",
        "workspace_path": "workspace/observer",
        "config": "observer-config",
        "runtime_agent_binding": {
            "agentId": "agent-observer",
            "llmSlot": "dialogue",
            "directSessionId": "session-observer",
            "workspacePath": "workspace/observer",
            "llmBindings": {
                "dialogue": {
                    "modelId": "lan_qwen/qwen3_6",
                }
            },
        },
    }
    assert result.result["turn_runtime"]["modelId"] == "lan_qwen/qwen3_6"


def test_run_agent_single_turn_forwards_history_through_preparation():
    captured: dict[str, object] = {}
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
    ]

    class FakeAgent:
        def seed_chat_history(self, messages):
            captured["history"] = messages

        def run_single_turn(self, initial_prompt=None):
            captured["initial_prompt"] = initial_prompt
            return {"status": "completed"}

    run_agent_single_turn(
        AgentSingleTurnRequest(
            mode="chat",
            initial_prompt="continue",
            chat_history=history,
        ),
        agent_factory=lambda **_kwargs: FakeAgent(),
    )

    assert captured == {
        "history": history,
        "initial_prompt": "continue",
    }


def test_run_agent_single_turn_can_disable_tools_for_bounded_finalization():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            captured["initial_prompt"] = initial_prompt
            captured["disable_tools"] = disable_tools
            return {"status": "completed", "summary": "final summary"}

    result = run_agent_single_turn(
        AgentSingleTurnRequest(
            mode="self_evolution",
            initial_prompt="summarize now",
            disable_tools=True,
        ),
        agent_factory=lambda **_kwargs: FakeAgent(),
    )

    assert captured == {
        "initial_prompt": "summarize now",
        "disable_tools": True,
    }
    assert result.result["summary"] == "final summary"


def test_prepare_agent_turn_uses_only_matching_nonterminal_carryover():
    captured: dict[str, object] = {}

    class FakeAgent:
        def set_turn_identity(self, turn_identity):
            captured["turn_identity"] = turn_identity

        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def seed_chat_history(self, history):
            captured["history"] = history

    carryover = {
        "turnIdentity": "turn-1",
        "terminal": False,
        "goal": "inspect",
        "messages": [{"kind": "dict", "role": "user", "content": "inspect"}],
    }
    prepare_agent_turn(
        FakeAgent(),
        turn_identity="turn-1",
        carryover=carryover,
        chat_history=[{"role": "assistant", "content": "historical reply"}],
    )

    assert captured == {
        "turn_identity": "turn-1",
        "carryover": carryover,
    }


def test_prepare_agent_turn_rejects_stale_carryover_and_emits_prompt_free_diagnostics():
    captured: dict[str, object] = {}
    history = [{"role": "assistant", "content": "normal history"}]

    class FakeAgent:
        def set_turn_identity(self, turn_identity):
            captured["turn_identity"] = turn_identity

        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def seed_chat_history(self, messages):
            captured["history"] = messages

        def record_turn_preparation_diagnostic(self, fields):
            captured["diagnostic"] = fields

    prepare_agent_turn(
        FakeAgent(),
        turn_identity="turn-new",
        carryover={
            "turnIdentity": "turn-old",
            "terminal": False,
            "goal": "stale secret goal",
            "messages": [{"kind": "dict", "role": "user", "content": "stale secret prompt"}],
        },
        static_runtime_context="static secret context",
        dynamic_runtime_context="dynamic secret context",
        chat_history=history,
    )

    assert "carryover" not in captured
    assert captured["history"] == history
    diagnostic_text = str(captured["diagnostic"])
    assert "secret" not in diagnostic_text
    assert captured["diagnostic"] == {
        "path": "history",
        "carryoverStatus": "identity_mismatch",
        "historyMessageCount": 1,
        "hasTurnIdentity": True,
        "staticContextChars": 21,
        "dynamicContextChars": 22,
    }


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
        runtime_context="Legacy Runtime Context",
        static_runtime_context="Static Runtime Context",
        dynamic_runtime_context="Dynamic Runtime Context",
        interrupt_checker=lambda: "stop_requested",
        chat_history=[{"role": "assistant", "content": "hello"}],
    )

    assert captured == {
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


def test_run_existing_agent_single_turn_always_prepares_before_execution():
    events: list[tuple[str, object]] = []
    history = [{"role": "assistant", "content": "previous"}]

    class FakeAgent:
        def seed_chat_history(self, messages):
            events.append(("prepare", messages))

        def run_single_turn(self, initial_prompt=None):
            events.append(("run", initial_prompt))
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="continue",
        chat_history=history,
    )

    assert result == {"status": "completed"}
    assert events == [("prepare", history), ("run", "continue")]


def test_rejected_carryover_clears_old_active_state_without_history():
    class FakeAgent:
        def __init__(self):
            self.messages = ["old current user"]
            self.goal = "old goal"
            self.turn_identity = "turn-old"

        def set_turn_identity(self, turn_identity):
            self.turn_identity = turn_identity

        def clear_turn_preparation_state(self):
            self.messages = None
            self.goal = ""

        def seed_turn_carryover(self, _carryover):
            raise AssertionError("stale carryover must not be seeded")

    agent = FakeAgent()
    prepare_agent_turn(
        agent,
        turn_identity="turn-new",
        carryover={
            "turnIdentity": "turn-old",
            "terminal": False,
            "goal": "old goal",
            "messages": [{"kind": "dict", "role": "user", "content": "old current user"}],
        },
    )

    assert agent.turn_identity == "turn-new"
    assert agent.messages is None
    assert agent.goal == ""


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


def test_run_existing_agent_single_turn_binds_real_partition_contextvar():
    """The partition scope must be live for the runner body, not just wrapped.

    Payload building reads current_prompt_cache_partition() inside
    agent.run_single_turn, so the real contextvar (not a monkeypatched scope)
    has to carry the partition through execution and be restored afterwards.
    """
    seen: list[str] = []
    before = current_prompt_cache_partition()

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None):
            seen.append(current_prompt_cache_partition())
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="probe",
        prompt_cache_partition="chat-room:room-1:session-1",
    )

    assert result == {"status": "completed"}
    assert seen == ["chat-room:room-1:session-1"]
    assert current_prompt_cache_partition() == before


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


def test_create_agent_runtime_ignores_unsupported_runtime_binding():
    captured: dict[str, object] = {}

    def factory(*, mode=None, workspace_path=None, config=None):
        captured.update({"mode": mode, "workspace_path": workspace_path, "config": config})
        return object()

    created = create_agent_runtime(
        mode="chat",
        workspace_path="workspace/session",
        config="config",
        runtime_agent_binding={"agentId": "agent-a"},
        agent_factory=factory,
    )

    assert created is not None
    assert captured == {
        "mode": "chat",
        "workspace_path": "workspace/session",
        "config": "config",
    }


def test_disable_tools_forwards_through_var_kwargs_runner():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None, **kwargs):
            captured["initial_prompt"] = initial_prompt
            captured["disable_tools"] = kwargs.get("disable_tools")
            return {"status": "completed"}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="summarize",
        disable_tools=True,
    )
    assert result == {"status": "completed"}
    assert captured == {"initial_prompt": "summarize", "disable_tools": True}


def test_prepare_agent_turn_ignores_string_chat_history():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_chat_history(self, messages):
            captured["history"] = messages

        def record_turn_preparation_diagnostic(self, fields):
            captured["diagnostic"] = fields

    prepare_agent_turn(FakeAgent(), chat_history="not-a-history")
    assert "history" not in captured
    assert captured["diagnostic"]["path"] == "fresh"
    assert captured["diagnostic"]["historyMessageCount"] == 0


def test_turn_runner_coerces_bytes_false_flags_and_mapping_request():
    captured: dict[str, object] = {}

    class FakeAgent:
        def set_turn_identity(self, turn_identity):
            captured["turn_identity"] = turn_identity

        def seed_static_runtime_context(self, context):
            captured["static_context"] = context

        def set_turn_interrupt_checker(self, checker):
            captured["interrupt"] = checker

        def run_single_turn(self, initial_prompt=None, disable_tools=False, attachments=None):
            captured["initial_prompt"] = initial_prompt
            captured["disable_tools"] = disable_tools
            captured["attachments"] = attachments
            return {"status": "completed"}

        def export_turn_carryover(self):
            return {"next": "ok"}

    prepare_agent_turn(
        FakeAgent(),
        turn_identity=b"turn-1",
        static_runtime_context=b"static-context",
        interrupt_checker="false",
        chat_history=b'[{"role": "user"}]',
    )
    assert captured["turn_identity"] == "turn-1"
    assert captured["static_context"] == "static-context"
    assert "interrupt" not in captured

    captured.clear()
    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt=b"summarize",
        disable_tools="false",
        attachments="not-attachments",
        prompt_cache_partition=b"",
    )
    assert result == {"status": "completed"}
    assert captured["initial_prompt"] == "summarize"
    assert captured["disable_tools"] is False
    assert captured["attachments"] is None

    captured.clear()
    mapped = run_agent_single_turn(
        {
            "mode": b"self_evolution",
            "initial_prompt": b"probe",
            "disable_tools": "false",
            "turn_identity": b"turn-map",
        },
        agent_factory=lambda **_kwargs: FakeAgent(),
    )
    assert mapped.result["status"] == "completed"
    assert captured["initial_prompt"] == "probe"
    assert captured["disable_tools"] is False


def test_prepare_agent_turn_parses_json_chat_history_without_splitting_strings():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_chat_history(self, messages):
            captured["history"] = messages

        def record_turn_preparation_diagnostic(self, fields):
            captured["diagnostic"] = fields

    prepare_agent_turn(
        FakeAgent(),
        chat_history=b'[{"role": "user", "content": "hi"}]',
    )
    assert captured["history"] == [{"role": "user", "content": "hi"}]
    assert captured["diagnostic"]["historyMessageCount"] == 1
    assert captured["diagnostic"]["path"] == "history"

    captured.clear()
    prepare_agent_turn(
        FakeAgent(),
        chat_history='{"messages": [{"role": "assistant", "content": "ok"}]}',
    )
    assert captured["history"] == [{"role": "assistant", "content": "ok"}]
    assert captured["diagnostic"]["historyMessageCount"] == 1

    captured.clear()
    prepare_agent_turn(FakeAgent(), chat_history="not-a-history")
    assert "history" not in captured
    assert captured["diagnostic"]["historyMessageCount"] == 0


def test_run_existing_agent_single_turn_parses_json_attachments():
    captured: dict[str, object] = {}

    class FakeAgent:
        def run_single_turn(self, initial_prompt=None, disable_tools=False, attachments=None):
            captured["initial_prompt"] = initial_prompt
            captured["disable_tools"] = disable_tools
            captured["attachments"] = attachments
            return {"status": "completed"}

        def export_turn_carryover(self):
            return {}

    result = run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="summarize",
        attachments=b'[{"name": "note.md"}]',
    )
    assert result == {"status": "completed"}
    assert captured["attachments"] == [{"name": "note.md"}]
    assert captured["disable_tools"] is False


def test_run_existing_agent_single_turn_seeds_history_ledger_fingerprint():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_chat_history(self, messages):
            captured["history"] = messages

        def seed_chat_history_ledger_fingerprint(self, fingerprint):
            captured["fingerprint"] = fingerprint

        def run_single_turn(self, initial_prompt=None):
            return {"status": "completed"}

    run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="continue",
        chat_history=[{"role": "user", "content": "first"}],
        chat_history_ledger_fingerprint="fp-stamp",
    )

    assert captured.get("fingerprint") == "fp-stamp"
    assert captured.get("history") == [{"role": "user", "content": "first"}]


def test_run_existing_agent_single_turn_skips_fingerprint_without_history():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_chat_history_ledger_fingerprint(self, fingerprint):
            captured["fingerprint"] = fingerprint

        def run_single_turn(self, initial_prompt=None):
            return {"status": "completed"}

    run_existing_agent_single_turn(
        FakeAgent(),
        initial_prompt="continue",
        chat_history=None,
        chat_history_ledger_fingerprint="fp-stamp",
    )

    assert "fingerprint" not in captured
