"""Evidence parsing and isolation tests; these do not claim real model E2E."""
import hashlib
import os
from pathlib import Path
import tempfile

import pytest

from scripts import assistant_acceptance_support as support


def event(kind, name="", args=None, result=None, *, call_id="call-1", session="s1", turn="t1", timestamp="2026-01-01T00:00:00Z"):
    return {"eventType": kind, "toolCallId": call_id, "sessionId": session, "turnId": turn,
            "timestamp": timestamp, "payload": {"toolCall": {"name": name, "arguments": args or {}, "result": result}}}


def streamed_events():
    return [event("tool_call_started", "exec_command", {"cmd": "python -m unittest tests -v"}),
            event("tool_result", result={"terminalSessionId": "terminal-1", "stderr": "Ran 2 tests in 0.01s\n\nOK\n"}),
            event("tool_call_started", "write_stdin", {"session_id": "terminal-1"}, call_id="poll-1"),
            event("tool_result", result={"terminalSessionId": "terminal-1", "exitCode": 0}, call_id="poll-1")]


def test_terminal_output_and_later_empty_exit_are_bound():
    proof = support.terminal_evidence(streamed_events(), "python -m unittest tests -v", expected_tests=2)
    assert proof["testExitCode"] == 0
    assert proof["terminals"][0]["exitCode"] == 0
    assert "stderr" not in str(proof) and "Ran 2 tests" not in str(proof)


@pytest.mark.parametrize("mutation", ["other_terminal", "other_turn", "other_session", "nonzero", "wrong_test_count", "mismatched_result_terminal"])
def test_terminal_does_not_borrow_unrelated_success(mutation):
    events = streamed_events()
    expected_tests = 2
    if mutation == "other_terminal":
        events[2]["payload"]["toolCall"]["arguments"]["session_id"] = "other"
        events[3]["payload"]["toolCall"]["result"]["terminalSessionId"] = "other"
    elif mutation == "other_turn":
        events[2]["turnId"] = events[3]["turnId"] = "other-turn"
    elif mutation == "other_session":
        events[2]["sessionId"] = events[3]["sessionId"] = "other-session"
    elif mutation == "nonzero":
        events[3]["payload"]["toolCall"]["result"]["exitCode"] = 1
    elif mutation == "wrong_test_count":
        expected_tests = 3
    else:
        events[3]["payload"]["toolCall"]["result"]["terminalSessionId"] = "different-returned-terminal"
    assert support.terminal_evidence(events, "python -m unittest tests -v", expected_tests)["testExitCode"] is None


def test_tool_call_id_collision_cannot_bind_across_turns():
    rows = support.tool_calls([event("tool_call_started", "read_file_tool", {"file_path": "private-input"}),
                               event("tool_result", result="opaque", turn="other")])
    assert rows[0]["callName"] == ""
    assert rows[0]["args"] == {}
    assert rows[0]["resultText"] == "opaque"


def test_inline_call_id_field_is_supported():
    start = event("tool_call_started", "exec_command", {"cmd": "test"})
    end = event("tool_result", result={"exitCode": 0})
    for row in (start, end):
        row.pop("toolCallId")
        row["payload"]["toolCall"]["callId"] = "inline"
    assert support.tool_calls([start, end])[0]["callName"] == "exec_command"


@pytest.fixture
def private_home():
    # The repository deliberately puts pytest tmp_path at C:\vtmp; acceptance
    # itself must keep its stricter real system-temp boundary.
    with tempfile.TemporaryDirectory(prefix="assistant-unit-") as root:
        yield Path(root)


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "source.toml"
    path.write_text('''[llm]
schema_version = 2
[llm.providers.private]
protocol = "openai"
base_url = "http://127.0.0.1:1"
credential_ref = "none"
requires_credential = false
[llm.providers.private.models.model]
model = "model"
[llm.profiles.primary]
model_ref = "private/model"
''', encoding="utf-8")
    return path


def test_context_initialization_is_private_and_does_not_launch(private_home, config_file, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("context initialization must not start a process")
    monkeypatch.setattr(support.subprocess, "Popen", forbidden)
    monkeypatch.setattr(support.acceptance_runtime, "start_instance", forbidden)
    before_env = os.environ.copy()
    source_before = config_file.read_bytes()
    fixture = support.AssistantAcceptanceFixture(private_home / "isolated", config_file, "private/model")
    with fixture:
        assert fixture.host_process is None and fixture.backends == {}
        for name in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "VIBELUTION_PROJECTS_HOME", "VIBELUTION_CONFIG_HOME", "TEMP"):
            assert Path(fixture.env[name]).is_relative_to(fixture.home)
        assert os.environ == before_env
        assert fixture.configuration_evidence()["sourceConfigObservedChange"] is False
    assert config_file.read_bytes() == source_before
    assert fixture.cleanup == {"assistantStopped": True, "backendsStopped": True}


def test_source_configuration_concurrent_change_is_reported(private_home, config_file):
    fixture = support.AssistantAcceptanceFixture(private_home / "isolated", config_file, "private/model")
    original = config_file.read_bytes()
    with fixture:
        config_file.write_bytes(original + b"\n# operator concurrent edit\n")
    report = fixture.configuration_evidence()
    assert report["sourceConfigSnapshotSha256"] == hashlib.sha256(original).hexdigest()
    assert report["sourceConfigObservedChange"] is True
    assert "operator concurrent edit" not in str(report)


def test_backend_runtime_layout_passes_real_formal_data_guard(private_home, config_file):
    fixture = support.AssistantAcceptanceFixture(private_home / "isolated", config_file, "private/model")
    with fixture:
        with support.base.environment(fixture.env):
            formal_root = support.acceptance_runtime._formal_data_root()
            assert formal_root.is_relative_to(Path(fixture.env["USERPROFILE"]))
            # The old case-home layout includes the private formal-data root.
            # Exercise the real guard; no process/provider is started here.
            with pytest.raises(ValueError, match="must not overlap formal Vibelution data"):
                support.acceptance_runtime._instance_paths(instance_id="layout-probe", runtime_home=fixture.home)
            paths = support.acceptance_runtime._instance_paths(instance_id="layout-probe", runtime_home=fixture.runtime_home)
            assert fixture.runtime_home == fixture.home / "backends"
            assert paths["runtimeHome"] == fixture.runtime_home
            assert paths["configRoot"] == fixture.runtime_home / "layout-probe" / "config"
            assert paths["dataRoot"] == fixture.runtime_home / "layout-probe" / "data"
            assert not fixture.runtime_home.is_relative_to(formal_root)
            assert not formal_root.is_relative_to(fixture.runtime_home)


def test_nonempty_home_is_never_reused(private_home, config_file):
    home = private_home / "existing"
    home.mkdir()
    sentinel = home / "keep"
    sentinel.write_text("untouched", encoding="utf-8")
    with pytest.raises(support.AcceptanceFailure, match="runtime_home_must_be_unused"):
        with support.AssistantAcceptanceFixture(home, config_file, "private/model"):
            pytest.fail("must refuse existing fixture state")
    assert sentinel.read_text(encoding="utf-8") == "untouched"


def test_host_restart_waits_for_old_process_exit(tmp_path, config_file, monkeypatch):
    fixture = support.AssistantAcceptanceFixture(tmp_path / "isolated", config_file, "private/model")
    class Live:
        def poll(self):
            return None
    fixture.host_process = Live()
    monkeypatch.setattr(fixture, "stop_host", lambda: None)
    monkeypatch.setattr(fixture, "start_host", lambda: pytest.fail("must not restart before old process exit"))
    with pytest.raises(support.AcceptanceFailure, match="old_assistant_host_still_running"):
        fixture.restart_host()


def test_duplicate_backend_id_cannot_change_its_root(private_home, config_file):
    fixture = support.AssistantAcceptanceFixture(private_home / "isolated", config_file, "private/model")
    with fixture:
        backend = support.Backend("acceptance-primary", fixture.source, "private-instance", "http://127.0.0.1:1", fixture.home / "runtime")
        fixture.backends[backend.project_id] = backend
        assert fixture.start_backend() is backend
        with pytest.raises(support.AcceptanceFailure, match="project_id_root_changed"):
            fixture.start_backend(root=private_home / "other")
        fixture.backends.clear()  # No real backend was created by this unit test.


def test_backend_owner_is_retained_when_post_start_resolution_fails(private_home, config_file, monkeypatch):
    import vibelution_storage
    stopped = []
    monkeypatch.setattr(support.acceptance_runtime, "start_instance", lambda **kwargs: {"backendUrl": "http://127.0.0.1:1"})
    def fail_resolution(*args):
        raise RuntimeError("controlled resolution failure")
    monkeypatch.setattr(vibelution_storage, "resolve_project_runtime_home", fail_resolution)
    def stop(**kwargs):
        stopped.append(kwargs["instance_id"])
        return {"status": "stopped"}
    monkeypatch.setattr(support.acceptance_runtime, "stop_instance", stop)
    monkeypatch.setattr(support.acceptance_runtime, "status_instance", lambda **kwargs: {"status": "stopped", "processAlive": {"backend": False}})
    fixture = support.AssistantAcceptanceFixture(private_home / "isolated", config_file, "private/model")
    with pytest.raises(RuntimeError, match="controlled resolution failure"):
        with fixture:
            fixture.start_backend()
    assert len(stopped) == 1 and stopped[0].startswith("target-")
    assert fixture.cleanup["backendsStopped"] is True
