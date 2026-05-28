from core.orchestration.turn_runner import (
    AgentSingleTurnRequest,
    create_agent_runtime,
    prepare_agent_turn,
    run_agent_single_turn,
    run_existing_agent_single_turn,
)


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


def test_run_agent_single_turn_seeds_context_and_exports_carryover():
    captured: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, *, mode=None, workspace_path=None, config=None):
            captured["mode"] = mode
            captured["workspace_path"] = workspace_path
            captured["config"] = config

        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def seed_runtime_context(self, context):
            captured["runtime_context"] = context

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
        "runtime_context": "Agent Runtime Context",
        "interrupt_reason": "stop_requested",
        "initial_prompt": "probe",
    }
    assert result.result == {"status": "completed", "summary": "done"}
    assert result.carryover == {"next": "state"}


def test_prepare_agent_turn_seeds_optional_supported_inputs():
    captured: dict[str, object] = {}

    class FakeAgent:
        def seed_turn_carryover(self, carryover):
            captured["carryover"] = carryover

        def seed_runtime_context(self, context):
            captured["runtime_context"] = context

        def set_turn_interrupt_checker(self, checker):
            captured["interrupt_reason"] = checker()

        def seed_chat_history(self, history):
            captured["chat_history"] = history

    prepare_agent_turn(
        FakeAgent(),
        carryover={"previous": "state"},
        runtime_context="Runtime Context",
        interrupt_checker=lambda: "stop_requested",
        chat_history=[{"role": "assistant", "content": "hello"}],
    )

    assert captured == {
        "carryover": {"previous": "state"},
        "runtime_context": "Runtime Context",
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
