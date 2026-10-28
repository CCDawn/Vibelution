"""Launcher native runtime contracts run in fresh, isolated processes."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEST_MODEL_CONFIG = '''
[llm]
schema_version = 2
[llm.providers.local]
label = "Isolated test provider"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:9/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false
[llm.providers.local.protocols]
default = "chat_completions"
allowed = ["chat_completions"]
[llm.providers.local.models.test]
upstream_id = "test"
label = "Test"
enabled = true
context_window = 8192
[llm.profiles.primary]
model_ref = "local/test"
'''


@pytest.fixture(autouse=True)
def _private_operator_config(tmp_path, monkeypatch, reset_singletons):
    # In-process native admission tests also load model settings. DATA_HOME
    # alone does not isolate the config loader's persisted schema upgrades.
    config_path = tmp_path / "operator" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(TEST_MODEL_CONFIG, encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("VIBELUTION_CONFIG_HOME", str(config_path.parent))
    from config import settings

    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(settings, "_config_path", str(config_path))


def _run(tmp_path: Path, code: str, *, role: str = "launcher_assistant", root: str | None = None, config_text: str = ""):
    native_root = tmp_path / "native"
    native_root.mkdir(exist_ok=True)
    config = tmp_path / "config.toml"
    config.write_text(config_text, encoding="utf-8")
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("VIBELUTION_") and "API_KEY" not in key.upper()
           and key.upper() != "OPENAI_ADMIN_KEY"}
    private_user = tmp_path / "user"
    private_local = private_user / "AppData" / "Local"
    private_roaming = private_user / "AppData" / "Roaming"
    private_temp = tmp_path / "tmp"
    for directory in (private_local, private_roaming, private_temp):
        directory.mkdir(parents=True, exist_ok=True)
    env.update({
        "VIBELUTION_PROCESS_ROLE": role,
        "VIBELUTION_ASSISTANT_NATIVE_ROOT": str(native_root) if root is None else root,
        "VIBELUTION_DATA_HOME": str(native_root / "data"),
        "VIBELUTION_CONFIG_PATH": str(config),
        "VIBELUTION_PROJECTS_HOME": str(tmp_path / "projects"),
        "USERPROFILE": str(private_user),
        "HOME": str(private_user),
        "LOCALAPPDATA": str(private_local),
        "APPDATA": str(private_roaming),
        "TEMP": str(private_temp), "TMP": str(private_temp), "TMPDIR": str(private_temp),
        # The OpenAI SDK requires a nonempty key even for this loopback mock.
        # Never inherit an operator credential into the synthetic provider.
        "OPENAI_API_KEY": "isolated-loopback-test-key",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "ASSISTANT_TEST_WRITE_ROOT": str(tmp_path),
    })
    audit = """
import os, sys
from pathlib import Path
_write_root = Path(os.environ['ASSISTANT_TEST_WRITE_ROOT']).resolve()
def _audit(event, args):
    if event == 'open':
        path, mode, flags = args
        if isinstance(path, int) or not (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
            return
        paths = [path]
    elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
        paths = [args[0]]
    elif event in ('os.rename', 'os.replace'):
        paths = list(args[:2])
    else:
        return
    for path in paths:
        # Python/platform subprocess probing opens the standard discard device.
        # It is not a persisted file; every other outside write stays forbidden.
        if event == 'open' and os.path.normcase(os.fsdecode(path)) == os.path.normcase(os.devnull):
            continue
        resolved = Path(os.fsdecode(path)).resolve()
        if (resolved.name == 'active.json' and resolved.is_relative_to(_write_root / 'projects')
                and event == 'open'):
            import traceback
            traceback.print_stack(limit=14)
        if not resolved.is_relative_to(_write_root):
            raise AssertionError('native runtime wrote outside isolated home: ' + str(resolved))
sys.addaudithook(_audit)
"""
    result = subprocess.run(
        [sys.executable, "-c", audit + textwrap.dedent(code)], cwd=REPO, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-6000:]


@pytest.mark.parametrize("role", ["", "workbench"])
def test_native_root_requires_explicit_process_role(tmp_path, role):
    _run(tmp_path, """
        from pathlib import Path
        from core.infrastructure.native_runtime import resolve_native_project_root, is_launcher_assistant_process
        default = Path.cwd()
        assert resolve_native_project_root(default) == default
        assert not is_launcher_assistant_process()
        from core.web.services import session_service, agent_directory_service
        from core.launcher import desktop_shell
        from core.runtime_manager.work_run_store import WorkRunStore
        from core.runtime_manager import constants
        from importlib import import_module
        from vibelution_storage import resolve_active_project_storage_paths
        assert session_service.PROJECT_ROOT == default
        assert agent_directory_service.PROJECT_ROOT == default
        assert desktop_shell.PROJECT_ROOT == default
        assert session_service._WORK_RUN_STORE.root == WorkRunStore().root
        assert constants.PROJECT_ROOT == default
        assert constants.PROJECT_STORAGE == resolve_active_project_storage_paths(default)
        logger_module = import_module('core.logging.logger')
        assert logger_module._PROJECT_ROOT == default
        assert Path(logger_module.LOG_ROOT) == constants.PROJECT_STORAGE.logs
        from core.web.services import runtime_scene_service, team_service, team_knowledge_service, virtual_human_life_service, tool_registry_service, personal_affairs_service
        for owner in (runtime_scene_service, team_service, team_knowledge_service, virtual_human_life_service, tool_registry_service, personal_affairs_service):
            assert owner.PROJECT_ROOT == default
        assert personal_affairs_service.get_personal_affairs_service().store.plugin_root('ordinary-agent') == default / 'agents' / 'ordinary-agent' / 'plugins' / 'personal-affairs'
        assert tool_registry_service.SOURCE_ROOT == default
        from core.assistant_runtime import native
        try:
            native.bootstrap(default)
        except RuntimeError:
            pass
        else:
            raise AssertionError('ordinary process provisioned a Launcher assistant')
    """, role=role)


@pytest.mark.parametrize("root", ["", "relative/native"])
def test_assistant_role_rejects_missing_or_relative_root(tmp_path, root):
    _run(tmp_path, """
        try:
            import core.infrastructure.native_runtime
        except ValueError:
            pass
        else:
            raise AssertionError("invalid assistant root accepted")
    """, root=root)


def test_native_process_root_is_frozen_before_service_import(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.infrastructure.native_runtime import resolve_native_project_root, is_launcher_assistant_process
        expected = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'] = str(expected / 'changed')
        os.environ['VIBELUTION_PROCESS_ROLE'] = 'workbench'
        from core.web.services import session_service, agent_directory_service
        from core.launcher import desktop_shell
        assert resolve_native_project_root(Path.cwd()) == expected
        assert is_launcher_assistant_process()
        assert session_service.PROJECT_ROOT == expected
        assert agent_directory_service.PROJECT_ROOT == expected
        assert desktop_shell.PROJECT_ROOT == expected
    """)


def test_native_role_preserves_explicit_target_runtime_descriptor(tmp_path):
    _run(tmp_path, """
        import json, os
        from pathlib import Path
        from core.infrastructure.native_runtime import assistant_native_root
        from core.runtime_manager import constants
        from core.external_agent.backend_client import ManagedAgentBackendClient
        from vibelution_storage import resolve_project_runtime_home
        root = assistant_native_root()
        target = root.parent / 'registered-target'
        identity = target / '.vibelution' / 'project.json'
        identity.parent.mkdir(parents=True)
        identity.write_text(json.dumps({'schemaVersion': 1, 'projectId': 'assistant-target-test'}))
        runtime = resolve_project_runtime_home(target)
        assert runtime != constants.RUNTIME_ROOT
        assert not runtime.is_relative_to(root)
        descriptor = runtime / 'launcher' / 'state.json'
        descriptor.parent.mkdir(parents=True)
        descriptor.write_text(json.dumps({'url': 'http://127.0.0.1:12345', 'runtimeProjectRoot': str(target)}))
        client = ManagedAgentBackendClient(target, state_path=root / 'test-client.json')
        assert client._runtime_descriptor()['baseUrl'] == 'http://127.0.0.1:12345'
        assert constants.RUNTIME_ROOT == root / '.runtime'
    """)


@pytest.mark.parametrize("developer_mode", [False, True])
def test_native_bootstrap_uses_real_directory_and_keeps_custom_policy(tmp_path, developer_mode):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import session_service, agent_directory_service as directory
        from core.web.services.session import directory_runtime
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        expected_tools = ['personal_assistant_action_tool', 'personal_assistant_manage_tool',
            'personal_affairs_tool', 'append_personal_memory_tool', 'supersede_personal_memory_tool',
            'search_agent_private_memory_tool', 'compress_context_tool',
            'personal_assistant_computer_observe_tool', 'personal_assistant_computer_action_tool']
        original_create = directory.create_agent_instance
        def checked_create(**kwargs):
            assert kwargs['initial_tool_policy']['allowedTools'] == expected_tools
            assert kwargs['initial_tool_policy']['preferredTools'] == expected_tools
            return original_create(**kwargs)
        directory.create_agent_instance = checked_create
        try:
            first = native.bootstrap(root)['assistant']
            assert directory_runtime.is_directory_store_open()
            assert directory_runtime.directory_store_project_root() == root
            assert directory_runtime.conversation_store_path(root).exists()
            assert not (root / '.vibelution' / 'project.json').exists()
            assert not (root / '.git').exists()
            assert directory.registry_path().is_relative_to(root.parent)
            assert directory_runtime.conversation_store_path(root).is_relative_to(root.parent)
            assert session_service._WORK_RUN_STORE.root.is_relative_to(root)
            other_project_files = [str(path.relative_to(root.parent)) for path in (root.parent / 'projects').rglob('*') if path.is_file()]
            assert not other_project_files, other_project_files[:12]
            assert first['profile'] == 'personal_assistant_v1'
            assert first['setupStatus'] == 'ready'
            sid = first['directSessionId']
            assert sid and native.get_detail(sid)['id'] == sid
            agent = directory.get_agent(first['agentId'])
            assert agent['toolPolicy']['allowedTools'] == expected_tools
            assert agent['toolPolicy']['preferredTools'] == expected_tools
            assert 'project_id' in agent['taskProfile']['constraints']
            for capability in ('personal_affairs_tool', 'append_personal_memory_tool', 'supersede_personal_memory_tool', 'search_agent_private_memory_tool', 'compress_context_tool'):
                assert capability in agent['taskProfile']['responsibilities']
            agents = directory.list_agents(detail='summary')
            assert len(agents) == 1, [(row['displayName'], row.get('createdBy')) for row in agents]
            assert native.bootstrap(root)['assistant']['agentId'] == first['agentId']
            for unknown in ('', 'not-owned'):
                try:
                    native.get_detail(unknown)
                except session_service.SessionNotFoundError:
                    pass
                else:
                    raise AssertionError('foreign session accepted')
            try:
                native.bootstrap(root / 'other')
            except ValueError:
                pass
            else:
                raise AssertionError('runtime root switched')
            policy = directory.get_agent(first['agentId'])['toolPolicy']
            old_tools = expected_tools[:-2]
            directory.update_agent_instance(first['agentId'], tool_policy={**policy, 'allowedTools': old_tools, 'preferredTools': old_tools})
            assert native.shutdown()['closed']
            assert not directory_runtime.is_directory_store_open()
            second = native.bootstrap(root)['assistant']
            assert second['directSessionId'] == sid
            assert directory.get_agent(first['agentId'])['toolPolicy']['allowedTools'] == expected_tools
            directory.update_agent_instance(first['agentId'], tool_policy={'allowedTools': [], 'networkAccess': 'none'})
            assert native.shutdown()['closed']
            assert native.bootstrap(root)['assistant']['directSessionId'] == sid
            assert directory.get_agent(first['agentId'])['toolPolicy']['allowedTools'] == []
        finally:
            native.shutdown()
    """, config_text='[launcher.developer_mode]\nenabled = true\n' if developer_mode else '')


def test_native_submit_reuses_journal_idempotency(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            sid = native.bootstrap(root)['assistant']['directSessionId']
            # Keep the native admission, journal, and directory real. Only the
            # model worker is disabled so this test cannot contact a provider.
            scheduled = []
            original_submit = sessions._SESSION_EXECUTOR.submit
            sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: scheduled.append((args, kwargs))
            first = native.submit('请记住这个测试请求', 'native-request-1')
            second = native.submit('请记住这个测试请求', 'native-request-1')
            assert first['turnId'] == second['turnId']
            assert len(scheduled) == 1
            try:
                native.submit('不同的请求内容', 'native-request-1')
            except native.AssistantSessionError as error:
                assert error.code == 'SESSION_INVALID'
            else:
                raise AssertionError('conflicting request id accepted')
            for request_id in ('', '   '):
                try:
                    native.submit('hello', request_id)
                except ValueError:
                    pass
                else:
                    raise AssertionError('missing idempotency key accepted')
            sessions._SESSION_EXECUTOR.submit = original_submit
            # No worker owns this test turn; settle its running marker before
            # invoking the production shutdown path.
            sessions._set_session_running(sid, False)
            detail = native.get_detail(sid)
            assert sum(item.get('role') == 'user' for item in detail['messages']) == 1
        finally:
            native.shutdown()
    """, config_text=TEST_MODEL_CONFIG)


def test_native_bootstrap_recovers_crash_left_turn_and_queue(tmp_path):
    _run(tmp_path, """
        import json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        sid = native.bootstrap(root)['assistant']['directSessionId']
        sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: None
        receipt = native.submit('恢复前未完成的请求', 'crash-request-1')
        queued = native.submit('恢复后继续的排队请求', 'crash-request-2')
        assert queued['status'] == 'queued'
        sessions._WORK_RUN_STORE.persist_snapshot('chat_turn', {
            'runId': receipt['turnId'], 'runKind': 'chat_turn', 'sessionId': sid,
            'status': 'running', 'finishedAt': '',
        }, active_run_id=receipt['turnId'])
        (root / 'test-crash.json').write_text(json.dumps({'sessionId': sid, 'turnId': receipt['turnId']}))
        os._exit(0)
    """, config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, """
        import json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        from core.chat.turn_journal import load_turn_events, EVENT_SESSION_RECOVERY_RESUMED
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        old = json.loads((root / 'test-crash.json').read_text())
        scheduled = []
        sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: scheduled.append((args, kwargs))
        try:
            current = native.bootstrap(root)['assistant']
            assert current['directSessionId'] == old['sessionId']
            events = load_turn_events(root, old['sessionId'])
            recovered = [event for event in events if event.event_type == EVENT_SESSION_RECOVERY_RESUMED]
            assert len(recovered) == 1
            assert recovered[0].payload['recovery']['recoveredTurnId'] == old['turnId']
            assert len(scheduled) >= 2  # Native queue drain and native turn resume.
            state = sessions.load_session_chat_state(root, old['sessionId'])
            assert state['session_recovery']['attempts'] == 1
            native.bootstrap(root)
            assert len([event for event in load_turn_events(root, old['sessionId']) if event.event_type == EVENT_SESSION_RECOVERY_RESUMED]) == 1
            sessions._set_session_running(old['sessionId'], False)
        finally:
            native.shutdown()
    """, config_text=TEST_MODEL_CONFIG)


@pytest.mark.parametrize("developer_mode", [False, True])
def test_native_model_worker_keeps_default_stores_in_profile(tmp_path, developer_mode):
    _run(tmp_path, """
        import json, os, threading, time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from pathlib import Path

        requests = []
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                self.send_response(200)
                if payload.get('stream'):
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    for delta, reason in [({'role': 'assistant'}, None), ({'content': 'NATIVE_WORKER_OK'}, None), ({}, 'stop')]:
                        item = {'id': 'local-test', 'object': 'chat.completion.chunk', 'model': 'test', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}
                        self.wfile.write(('data: ' + json.dumps(item) + '\\n\\n').encode())
                    self.wfile.write(b'data: [DONE]\\n\\n')
                else:
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'id': 'local-test', 'object': 'chat.completion', 'model': 'test', 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'NATIVE_WORKER_OK'}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 4, 'total_tokens': 14}}).encode())

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        config_path = Path(os.environ['VIBELUTION_CONFIG_PATH'])
        config_path.write_text(config_path.read_text().replace('127.0.0.1:9', '127.0.0.1:' + str(provider.server_port)))

        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        from core.runtime_manager import constants, evolution_store, work_run_store
        from core.logging.unified_logger import logger
        from core.infrastructure.workspace_manager import get_workspace
        from core.prompt_manager.prompt_manager import _get_dynamic_root, _get_static_root
        from core.web.services import prompt_template_service
        from core.llm.usage_ledger import usage_ledger_path
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            sid = native.bootstrap(root)['assistant']['directSessionId']
            receipt = native.submit('请只回复完成标记', 'native-worker-1')
            deadline = time.monotonic() + 30
            while sessions._is_session_running(sid) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert not sessions._is_session_running(sid), 'native worker did not settle'
            detail = native.get_detail(sid)
            assert requests, ('native worker never reached the local provider', detail['messages'])
            assert 'NATIVE_WORKER_OK' in json.dumps(detail['messages'], ensure_ascii=False), detail['messages']
            assert constants.PROJECT_ROOT == root
            assert constants.RUNTIME_ROOT == root / '.runtime'
            assert evolution_store.EVOLUTION_DIR.is_relative_to(root)
            assert work_run_store.WORK_RUNS_DIR.is_relative_to(root)
            assert Path(logger.conversation._log_dir).is_relative_to(root)
            owned_paths = [get_workspace()._db_path, usage_ledger_path(),
                           _get_dynamic_root() / 'DYNAMIC.md', prompt_template_service.prompt_template_path()]
            assert all(path.exists() and path.is_relative_to(root) for path in owned_paths), owned_paths
            assert _get_static_root().is_dir()
            assert not _get_static_root().is_relative_to(root)
            assert prompt_template_service.KNOWLEDGE_STEWARD_PROMPT_PATH.is_file()
            assert not prompt_template_service.KNOWLEDGE_STEWARD_PROMPT_PATH.is_relative_to(root)
            # Reproduce the real-worker lease/index reads without injecting a
            # store: even a read may create the native lock sidecar.
            evolution_store.load_active_run_snapshot('self')
            evolution_store.load_active_run_snapshot('supervised')
            work_run_store.WorkRunStore().load_active_snapshot('agent_run')
            assert native.submit('请只回复完成标记', 'native-worker-1')['turnId'] == receipt['turnId']
            assert native.shutdown()['closed']
            logger.transcript.shutdown(timeout=2)
            other_files = [str(path.relative_to(root.parent)) for path in (root.parent / 'projects').rglob('*') if path.is_file()]
            assert not other_files, other_files[:15]
            assert list((root / 'logs' / 'conversations').glob('conversation_*.jsonl'))
            assert not (root / '.vibelution' / 'project.json').exists()
        finally:
            native.shutdown()
            provider.shutdown()
            provider.server_close()
            thread.join(timeout=2)
    """, config_text=TEST_MODEL_CONFIG + ('\n[launcher.developer_mode]\nenabled = true\n' if developer_mode else ''))


def test_private_detail_uses_native_light_projection_and_keeps_identity_gate(monkeypatch):
    from types import SimpleNamespace

    from core.assistant_runtime import native
    calls = []
    class MissingSession(ValueError):
        pass
    def detail(session_id, **kwargs):
        calls.append((session_id, kwargs))
        return {"id": session_id, "agentId": "assistant-1", "messages": []}
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": {"agentId": "assistant-1", "directSessionId": "session-1"}})
    monkeypatch.setattr(native, "_services", lambda: (None, None, SimpleNamespace(
        get_session_detail=detail, SessionNotFoundError=MissingSession), None))
    assert native.get_detail("session-1")["id"] == "session-1"
    assert calls == [("session-1", {"include_secondary": False})]
    with pytest.raises(MissingSession):
        native.get_detail("another-session")
    assert len(calls) == 1


@pytest.fixture
def assistant_command_session(tmp_path, monkeypatch):
    import threading

    from core.assistant_runtime import native
    from core.chat.conversation_branches import analyze_conversation_branches
    from core.chat.conversation_ledger import (
        append_conversation_event,
        load_conversation_events,
    )
    from core.web.services import session_service as sessions
    from tests.helpers.web_chat_state import _reset_seeded_session_runtime
    from tests.test_session_submit import _prepare_default_submit_session

    sid = _prepare_default_submit_session(tmp_path, monkeypatch)
    for kind, payload in (("turn_started", {}), ("user_message", {"content": "original request"}),
                          ("assistant_message", {"content": "partial answer"}), ("turn_interrupted", {})):
        append_conversation_event(tmp_path, sid, "old-turn", kind, payload=payload,
                                  status="stopped" if kind == "turn_interrupted" else "")
    events = load_conversation_events(tmp_path, sid)
    agent_id = sessions.load_session_chat_state(tmp_path, sid)["agent_id"]
    expected = {"turnId": "old-turn", "headId": analyze_conversation_branches(events).active_leaf_id,
                "ledgerSeq": events[-1].sequence, "agentId": agent_id}
    identity = {"agentId": agent_id, "directSessionId": sid}
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_SESSION_ID", sid)
    monkeypatch.setattr(native, "_AGENT_ID", agent_id, raising=False)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": identity})
    scheduled = []
    monkeypatch.setattr(sessions, "_schedule_session_turn", lambda context: scheduled.append(context))
    yield native, sessions, sid, expected, scheduled, identity
    _reset_seeded_session_runtime(sid)


def test_fixed_session_continue_uses_real_snapshot_admission_and_same_request_replay(assistant_command_session, tmp_path, monkeypatch):
    from core.chat.conversation_ledger import load_conversation_events

    native, sessions, sid, expected, scheduled, _ = assistant_command_session
    monkeypatch.setattr(native, "submit", lambda *_: pytest.fail("continue used unguarded string submission"))
    first = native.continue_turn("continue-1", expected)
    again = native.continue_turn("continue-1", expected)
    assert first["turnId"] == again["turnId"] != "old-turn"
    assert len(scheduled) == 1 and scheduled[0]["raw_user_message"] == "继续"
    users = [event for event in load_conversation_events(tmp_path, sid) if event.event_type == "user_message"]
    assert [event.payload["content"] for event in users][-2:] == ["original request", "继续"]
    assert users[-1].correlation_id == "continue-1"
    assert not sessions.load_session_chat_state(tmp_path, sid).get("queued_turns")


def test_assistant_quiescence_rejects_concurrent_commands_without_losing_original_request(assistant_command_session, tmp_path):
    import threading
    from core.chat.conversation_ledger import load_conversation_events

    native, sessions, sid, expected, scheduled, _ = assistant_command_session
    before = load_conversation_events(tmp_path, sid)
    results = []
    draft, request_id = "保留草稿 e\u0301", "original-request-123"
    def submit():
        try:
            native.submit(draft, request_id)
        except native.AssistantSessionError as exc:
            results.append(exc.code)
    with native.session_quiescence():
        thread = threading.Thread(target=submit)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        with pytest.raises(native.AssistantSessionError, match="ASSISTANT_QUIESCING"):
            native.continue_turn("continue-original", expected)
        with pytest.raises(native.AssistantSessionError, match="ASSISTANT_QUIESCING"):
            native.stop("old-turn")
        assert native.shutdown() == {"closed": False, "code": "NATIVE_QUIESCENCE_ACTIVE"}
        assert not native._STOP_REQUESTED.is_set()
        assert results == ["ASSISTANT_QUIESCING"]
        assert load_conversation_events(tmp_path, sid) == before and not scheduled
    receipt = native.submit(draft, request_id)
    users = [event for event in load_conversation_events(tmp_path, sid) if event.event_type == "user_message"]
    assert users[-1].payload["content"] == draft and users[-1].correlation_id == request_id
    assert native.submit(draft, request_id)["turnId"] == receipt["turnId"]
    assert len(scheduled) == 1


def test_assistant_quiescence_will_not_stop_running_or_queued_turns(assistant_command_session, tmp_path, monkeypatch):
    from core.chat.conversation_ledger import load_conversation_events
    from core.web.services.session.queued_turns import enqueue_session_queued_turn

    native, sessions, sid, _, _, _ = assistant_command_session
    sessions._set_session_running(sid, True)
    try:
        before = load_conversation_events(tmp_path, sid)
        with pytest.raises(native.AssistantSessionError, match="ASSISTANT_QUIESCENCE_BUSY"):
            with native.session_quiescence():
                pytest.fail("running session entered quiescence")
        assert sessions._is_session_running(sid)
        assert load_conversation_events(tmp_path, sid) == before
    finally:
        sessions._set_session_running(sid, False)
    # The real native queue stores and preserves the user's accepted draft.
    monkeypatch.setattr(sessions, "_schedule_session_queued_turn_drain", lambda _: None)
    enqueue_session_queued_turn(sid, content="queued draft", attachments=[], references=[],
                                mental_model_enabled=None, runtime_status_enabled=None,
                                turn_mode="chat", write_intent=None, client_submission_id="queued-original")
    before_state = sessions.load_session_chat_state(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError, match="ASSISTANT_QUIESCENCE_BUSY"):
        with native.session_quiescence():
            pytest.fail("queued session entered quiescence")
    assert sessions.load_session_chat_state(tmp_path, sid) == before_state


@pytest.mark.anyio
async def test_assistant_quiescence_does_not_cancel_an_external_running_dispatch(assistant_command_session, tmp_path):
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start

    native, _, _, _, _, _ = assistant_command_session
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    receipt = await start(service)
    assert receipt["receipt"]["status"] == "running"
    before = service.list_dispatches()
    # This component deliberately does not certify external dispatches as
    # drained; the owner must fence and drain them before a real migration.
    with native.session_quiescence():
        assert service.list_dispatches() == before
    assert service.list_dispatches() == before
    assert not any(name in {"cancel", "shutdown"} for name, _ in probe.calls)


@pytest.mark.parametrize("status", ["pending", "unknown"])
def test_assistant_quiescence_refuses_pending_or_unknown_approval(assistant_command_session, monkeypatch, status):
    from core.web.services.session import tool_approvals

    native, _, _, _, _, _ = assistant_command_session
    monkeypatch.setattr(tool_approvals, "list_tool_approval_requests", lambda _: [{"status": status}])
    with pytest.raises(native.AssistantSessionError, match="ASSISTANT_QUIESCENCE_BUSY"):
        with native.session_quiescence():
            pytest.fail("unsettled approval entered quiescence")
    assert not native._QUIESCING


def test_assistant_quiescence_waits_for_command_already_in_admission(assistant_command_session, monkeypatch):
    import threading

    native, sessions, sid, _, scheduled, _ = assistant_command_session
    admitted, release, observed = threading.Event(), threading.Event(), []
    original_submit = sessions.submit_session_message_lightweight
    def slow_submit(*args, **kwargs):
        receipt = original_submit(*args, **kwargs)
        admitted.set()
        assert release.wait(3)
        return receipt
    monkeypatch.setattr(sessions, "submit_session_message_lightweight", slow_submit)
    def acquire():
        try:
            with native.session_quiescence():
                observed.append("entered")
        except native.AssistantSessionError as exc:
            observed.append(exc.code)
    submitter = threading.Thread(target=lambda: native.submit("已有请求", "already-admitted"))
    submitter.start()
    assert admitted.wait(3)
    barrier = threading.Thread(target=acquire)
    barrier.start()
    try:
        assert not barrier.join(timeout=0.1) and barrier.is_alive()
        release.set()
        submitter.join(timeout=3)
        barrier.join(timeout=3)
        assert not submitter.is_alive() and not barrier.is_alive()
        assert observed == ["ASSISTANT_QUIESCENCE_BUSY"]
        assert len(scheduled) == 1 and sessions._is_session_running(sid)
    finally:
        release.set()
        submitter.join(timeout=3)
        barrier.join(timeout=3)


@pytest.mark.parametrize("field,value", [("turnId", "stale"), ("headId", "stale"),
                                         ("ledgerSeq", 1), ("agentId", "other")])
def test_fixed_session_continue_rejects_stale_snapshot_without_journal_or_queue_writes(assistant_command_session, tmp_path, field, value):
    from core.chat.conversation_ledger import load_conversation_events

    native, sessions, sid, expected, scheduled, _ = assistant_command_session
    before = load_conversation_events(tmp_path, sid)
    state = sessions.load_session_chat_state(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError) as error:
        native.continue_turn("continue-1", {**expected, field: value})
    assert error.value.code == "SESSION_CONFLICT"
    assert load_conversation_events(tmp_path, sid) == before
    assert sessions.load_session_chat_state(tmp_path, sid) == state
    assert not scheduled


def test_fixed_session_stop_validates_turn_then_holds_queue_with_native_user_stop(assistant_command_session, tmp_path, monkeypatch):
    from core.web.services.session import control

    native, sessions, sid, _, _, _ = assistant_command_session
    controller = sessions.SessionTurnControl(session_id=sid, turn_id="running-turn")
    monkeypatch.setattr(sessions, "_is_session_running", lambda _: True)
    monkeypatch.setattr(sessions, "_get_session_turn_control", lambda _: controller)
    monkeypatch.setattr(sessions, "_cancel_queued_session_turn", lambda *_: False)
    monkeypatch.setattr(sessions, "_record_chat_next_state_signal", lambda **_: None)
    cascades = []
    monkeypatch.setattr(control, "_cascade_stop_descendant_runtime_tasks", lambda *args, **kwargs: cascades.append((args, kwargs)))
    state = sessions.load_session_chat_state(tmp_path, sid)
    state["queued_turns"] = [{"id": "held-row", "content": "next task"}]
    sessions.save_session_chat_state(tmp_path, sid, state)
    state = sessions.load_session_chat_state(tmp_path, sid)
    with pytest.raises(native.AssistantSessionError) as error:
        native.stop("stale-turn")
    assert error.value.code == "SESSION_CONFLICT"
    assert not controller.snapshot()["stopRequested"]
    assert sessions.load_session_chat_state(tmp_path, sid) == state
    result = native.stop("running-turn")
    assert result["stopRequested"] is True
    held = sessions.load_session_chat_state(tmp_path, sid)
    assert held["queued_turns"] == state["queued_turns"]
    assert held["queued_turn_hold"]["turnId"] == "running-turn"
    assert held["queued_turn_hold"]["reason"] == "user_stop"
    assert cascades[0][0] == (sid,) and cascades[0][1]["turn_id"] == "running-turn"


@pytest.mark.parametrize("changed", ["directSessionId", "agentId"])
@pytest.mark.parametrize("operation", ["stop", "continue", "send"])
def test_fixed_session_commands_refuse_identity_rebinding(assistant_command_session, monkeypatch, changed, operation):
    native, sessions, _, expected, scheduled, identity = assistant_command_session
    identity[changed] = "replacement"
    monkeypatch.setattr(sessions, "request_stop_session_turn", lambda *_a, **_k: pytest.fail("rebound stop admitted"))
    monkeypatch.setattr(sessions, "submit_session_message_lightweight", lambda *_a, **_k: pytest.fail("rebound send admitted"))
    with pytest.raises(native.AssistantSessionError) as error:
        if operation == "send":
            native.submit("message", "send-1")
        elif operation == "stop":
            native.stop("old-turn")
        else:
            native.continue_turn("c", expected)
    assert error.value.code == "ASSISTANT_IDENTITY_INVALID"
    assert not scheduled


@pytest.mark.parametrize("operation", ["stop", "continue"])
def test_commands_waiting_for_owner_lock_cannot_enter_after_shutdown_begins(assistant_command_session, monkeypatch, operation):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    native, sessions, _, expected, scheduled, _ = assistant_command_session
    lifecycle_stops = []
    monkeypatch.setattr(sessions, "stop_session_service_admission", lambda: None)
    monkeypatch.setattr(sessions, "shutdown_session_service", lambda **_: {"closed": True})
    monkeypatch.setattr(sessions, "request_stop_session_turn", lambda *args, **kwargs: lifecycle_stops.append(kwargs) or {})
    monkeypatch.setattr(native, "_services", lambda: (None, None, sessions, SimpleNamespace(shutdown_session_directory_runtime=lambda **_: None)))
    waiting = threading.Event()

    def command():
        waiting.set()
        with pytest.raises(native.AssistantSessionError) as error:
            native.stop("old-turn") if operation == "stop" else native.continue_turn("c", expected)
        return error.value.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        with native._LOCK:
            pending = pool.submit(command)
            assert waiting.wait(2)
            closing = pool.submit(native.shutdown)
            assert native._STOP_REQUESTED.wait(2)
        assert pending.result(timeout=3) == "ASSISTANT_STOPPING"
        assert closing.result(timeout=3) == {"closed": True}
    assert not scheduled
    assert lifecycle_stops == [{"fast_ack": True, "stop_reason": "launcher_assistant_shutdown"}]


@pytest.mark.parametrize("operation", ["stop", "continue"])
def test_unstarted_commands_do_not_open_native_services(monkeypatch, operation):
    import threading

    from core.assistant_runtime import native

    monkeypatch.setattr(native, "_STARTED", False)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_services", lambda: pytest.fail("unstarted command opened native services"))
    with pytest.raises(native.AssistantSessionError) as error:
        native.stop("old-turn") if operation == "stop" else native.continue_turn("c", {})
    assert error.value.code == "ASSISTANT_NOT_READY"


@pytest.mark.parametrize("timeout", [0.0, 0.04], ids=["nonblocking", "bounded_wait"])
def test_native_shutdown_lock_admission_is_bounded_without_opening_session(monkeypatch, timeout):
    import threading
    import time

    from core.assistant_runtime import native

    lock = threading.RLock()
    held, release, finished = threading.Event(), threading.Event(), threading.Event()
    stop = threading.Event()
    state = object()
    monkeypatch.setattr(native, "_LOCK", lock)
    monkeypatch.setattr(native, "_STOP_REQUESTED", stop)
    monkeypatch.setattr(native, "_STARTED", state)
    monkeypatch.setattr(native, "_SESSION_ID", "fixed-session")
    monkeypatch.setattr(native, "_AGENT_ID", "fixed-agent")
    monkeypatch.setattr(native, "_services", lambda: pytest.fail("busy shutdown opened native services"))
    outcome = {}

    def holder():
        with lock:
            held.set()
            release.wait(3)

    def closing():
        start = time.monotonic()
        try:
            outcome["result"] = native.shutdown(timeout=timeout)
        except BaseException as error:
            outcome["error"] = error
        finally:
            outcome["elapsed"] = time.monotonic() - start
            finished.set()

    owner = threading.Thread(target=holder, daemon=True)
    caller = threading.Thread(target=closing, daemon=True)
    owner.start()
    assert held.wait(1)
    try:
        caller.start()
        returned_while_held = finished.wait(0.5)
        assert stop.is_set()
        # New operator-source reads fail before attempting the still-owned lock.
        with pytest.raises(native.AssistantSessionError) as denied:
            with native._source_command():
                pytest.fail("source read admitted after shutdown was requested")
        assert denied.value.code == "ASSISTANT_STOPPING"
    finally:
        release.set()
        owner.join(1)
        caller.join(1)
    assert returned_while_held, "shutdown waited for lock release beyond its admission budget"
    assert "error" not in outcome
    assert outcome["result"] == {"closed": False, "code": "NATIVE_SHUTDOWN_ADMISSION_BUSY"}
    assert outcome["elapsed"] <= timeout + 0.25
    assert native._STARTED is state
    assert native._SESSION_ID == "fixed-session" and native._AGENT_ID == "fixed-agent"
    # A later call can close normally once admission is available.
    monkeypatch.setattr(native, "_STARTED", False)
    assert native.shutdown(timeout=0) == {"closed": True}


@pytest.mark.parametrize("closed", [False, True])
def test_native_shutdown_lock_wait_consumes_the_original_drain_deadline(monkeypatch, closed):
    import threading
    from types import SimpleNamespace

    from core.assistant_runtime import native

    clock, acquired, released, deadlines, store_timeouts = [100.0], [], [], [], []

    class AdmissionLock:
        def acquire(self, blocking=True, timeout=-1):
            acquired.append((blocking, timeout))
            clock[0] += 0.4
            return True

        def release(self):
            released.append(True)

        def __enter__(self):
            self.acquire()

        def __exit__(self, *_):
            self.release()

    expected = {"closed": closed, "pendingExecutors": [] if closed else ["owned-work"]}
    sessions = SimpleNamespace(
        stop_session_service_admission=lambda: None,
        request_stop_session_turn=lambda *args, **kwargs: None,
        shutdown_session_service=lambda *, deadline: deadlines.append(deadline) or expected,
        SessionNotFoundError=type("MissingSession", (Exception,), {}),
    )
    runtime = SimpleNamespace(shutdown_session_directory_runtime=lambda *, timeout: store_timeouts.append(timeout))
    monkeypatch.setattr(native, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(native, "_LOCK", AdmissionLock())
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_SESSION_ID", "fixed-session")
    monkeypatch.setattr(native, "_AGENT_ID", "fixed-agent")
    monkeypatch.setattr(native, "_services", lambda: (None, None, sessions, runtime))
    assert native.shutdown(timeout=1.0) == expected
    assert acquired == [(True, pytest.approx(1.0))]
    assert deadlines == [pytest.approx(101.0)]
    assert store_timeouts == ([pytest.approx(0.6)] if closed else [])
    assert released == [True]
    assert native._STARTED is (not closed)
    assert native._SESSION_ID == ("" if closed else "fixed-session")


def test_native_shutdown_releases_admission_lock_when_the_existing_owner_raises(monkeypatch):
    import threading

    from core.assistant_runtime import native

    lock = threading.Lock()
    monkeypatch.setattr(native, "_LOCK", lock)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_services", lambda: (_ for _ in ()).throw(RuntimeError("owned shutdown failed")))
    with pytest.raises(RuntimeError, match="owned shutdown failed"):
        native.shutdown(timeout=0)
    assert lock.acquire(blocking=False)
    lock.release()
    assert native._STARTED is True


@pytest.mark.parametrize("expected", [None, {}, {"turnId": "x"},
                                      {"turnId": "x", "headId": "h", "ledgerSeq": True, "agentId": "a"}])
def test_native_continuation_rejects_missing_or_malformed_snapshot(assistant_command_session, expected):
    native, _, _, _, scheduled, _ = assistant_command_session
    with pytest.raises(native.AssistantSessionError) as error:
        native.continue_turn("c", expected)
    assert error.value.code == "SESSION_INVALID"
    assert not scheduled


def test_launcher_assistant_own_session_can_continue_without_a_model_worker(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.chat.conversation_branches import analyze_conversation_branches
        from core.chat.conversation_ledger import append_conversation_event, load_conversation_events
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            assistant = native.bootstrap(root)['assistant']
            sid = assistant['directSessionId']
            scheduled = []
            sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: scheduled.append((args, kwargs))
            append_conversation_event(root, sid, 'stopped-turn', 'turn_started', status='running')
            append_conversation_event(root, sid, 'stopped-turn', 'user_message', payload={'content': 'original request'})
            append_conversation_event(root, sid, 'stopped-turn', 'turn_interrupted', status='stopped')
            before = load_conversation_events(root, sid)
            expected = {'turnId': 'stopped-turn', 'headId': analyze_conversation_branches(before).active_leaf_id,
                        'ledgerSeq': before[-1].sequence, 'agentId': assistant['agentId']}
            first = native.continue_turn('own-continue-1', expected)
            again = native.continue_turn('own-continue-1', expected)
            assert first['accepted'] is True and first['sessionId'] == sid
            assert first['turnId'] == again['turnId'] != 'stopped-turn'
            assert len(scheduled) == 1
            assert load_conversation_events(root, sid)[:len(before)] == before
            sessions._set_session_running(sid, False)
        finally:
            native.shutdown()
    """, config_text=TEST_MODEL_CONFIG)


@pytest.fixture
def native_source(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    from core.assistant_runtime import native
    from core.chat import turn_journal
    real_load = turn_journal.load_turn_events

    runtime = {"agentId": "assistant-a", "sessionId": "own-session", "turnId": "turn-a"}
    def event(kind, sequence, *, turn_id="turn-a", **changes):
        payload = {"agentId": "assistant-a", "source": "raw"} if kind == "turn_started" else {
            "content": "只回复 E3_RECEIPT_3E159D2DFC294ED1", "source": "raw", "metadata": {"clientSubmissionId": "operator-1"}}
        return SimpleNamespace(event_type=kind, turn_id=turn_id, session_id="own-session", event_id="event-" + str(sequence),
            sequence=sequence, source="submit_session_message", source_kind="", correlation_id="operator-1",
            visible_in_model=True, payload=payload, **changes)
    events = [event("turn_started", 1), event("user_message", 2)]
    directory = SimpleNamespace(PROJECT_ROOT=tmp_path, current_agent_runtime=lambda: dict(runtime))
    sessions = SimpleNamespace(PROJECT_ROOT=tmp_path, SessionNotFoundError=type("Missing", (Exception,), {}),
        SessionBusyError=type("Busy", (Exception,), {}), SessionValidationError=type("Invalid", (Exception,), {}))
    opened = SimpleNamespace(directory_store_project_root=lambda: tmp_path, get_open_directory_store=lambda: object())
    monkeypatch.setattr(native, "assistant_native_root", lambda: tmp_path)
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_AGENT_ID", "assistant-a")
    monkeypatch.setattr(native, "_SESSION_ID", "own-session")
    monkeypatch.setattr(native, "_services", lambda: (directory, None, sessions, opened))
    monkeypatch.setattr(native, "_projection", lambda: pytest.fail("source read entered projection/repair"))
    reads = []
    monkeypatch.setattr(turn_journal, "load_turn_events", lambda root, session: reads.append((root, session)) or events)
    return SimpleNamespace(native=native, runtime=runtime, directory=directory, sessions=sessions, opened=opened,
        events=events, event=event, reads=reads, root=tmp_path, real_load=real_load)


def test_native_source_reads_only_admitted_fixed_operator_event(native_source):
    env = native_source
    result = env.native.read_task_source(dict(env.runtime))
    assert result == {**env.runtime, "eventId": "event-2", "content": "只回复 E3_RECEIPT_3E159D2DFC294ED1"}
    assert env.reads == [(env.root, "own-session")]


@pytest.mark.parametrize("change", ["runtime_agent", "runtime_session", "runtime_turn", "empty_turn", "root", "role", "unstarted"])
def test_native_source_identity_denied_before_journal_access(native_source, monkeypatch, change):
    env = native_source
    supplied = dict(env.runtime)
    if change.startswith("runtime_"):
        supplied[{"runtime_agent": "agentId", "runtime_session": "sessionId", "runtime_turn": "turnId"}[change]] = "other"
    elif change == "empty_turn":
        supplied["turnId"] = ""
    elif change == "root":
        env.directory.PROJECT_ROOT = env.root / "other"
    elif change == "role":
        monkeypatch.setattr(env.native, "assistant_native_root", lambda: (_ for _ in ()).throw(RuntimeError("not assistant")))
    else:
        monkeypatch.setattr(env.native, "_STARTED", False)
    with pytest.raises(env.native.AssistantSessionError):
        env.native.read_task_source(supplied)
    assert not env.reads


@pytest.mark.parametrize("change", ["terminal", "other_turn", "duplicate", "proactive", "actor", "imported", "no_submission", "other_start_agent", "metadata_turn", "start_submission"])
def test_native_source_rejects_nonoperator_or_noncurrent_events(native_source, change):
    env = native_source
    user = env.events[1]
    if change == "terminal":
        env.events.append(env.event("turn_completed", 3))
    elif change == "other_turn":
        user.turn_id = "other"
    elif change == "duplicate":
        env.events.append(env.event("user_message", 3))
    elif change == "proactive":
        user.source_kind = "proactive"
    elif change == "actor":
        user.payload["metadata"]["actor"] = "other-agent"
    elif change == "imported":
        user.source = "legacy_import"
    elif change == "no_submission":
        user.payload["metadata"] = {}
    elif change == "metadata_turn":
        user.payload["metadata"]["turnId"] = "other"
    elif change == "start_submission":
        env.events[0].correlation_id = "other-submission"
    else:
        env.events[0].payload["agentId"] = "other-agent"
    with pytest.raises(env.native.AssistantSessionError):
        env.native.read_task_source(dict(env.runtime))


def test_native_original_source_reference_reads_original_after_new_turn(native_source):
    env = native_source
    original = env.native.read_task_source(dict(env.runtime))
    env.events.append(env.event("turn_completed", 3))
    env.events.extend([env.event("turn_started", 4, turn_id="turn-new"), env.event("user_message", 5, turn_id="turn-new")])
    env.runtime["turnId"] = "turn-new"
    assert env.native.read_task_source(dict(env.runtime), source_ref=original) == original


def test_native_source_real_journal_keeps_exact_bytes_without_hydration(native_source, monkeypatch):
    from core.chat import turn_journal
    env = native_source
    path = env.root / "turn_journal.jsonl"
    monkeypatch.setattr(turn_journal, "turn_journal_path", lambda *_args: path)
    monkeypatch.setattr(turn_journal, "load_turn_events", env.real_load)
    text = "🧭原文 e\u0301：E3_RECEIPT_3E159D2DFC294ED1\r\n只做原任务"
    turn_journal.append_turn_events(env.root, "own-session", "turn-a", [
        {"event_type": "turn_started", "source": "submit_session_message", "correlation_id": "operator-real",
         "payload": {"agentId": "assistant-a", "source": "raw"}},
        {"event_type": "user_message", "source": "submit_session_message", "correlation_id": "operator-real",
         "payload": {"content": text, "source": "raw", "metadata": {"clientSubmissionId": "operator-real", "turnId": "turn-a"}}},
    ])
    before = path.read_bytes()
    result = env.native.read_task_source(dict(env.runtime))
    assert result["content"] == text and path.read_bytes() == before


@pytest.mark.anyio
async def test_native_source_context_survives_worker_to_host_loop_portal(native_source, monkeypatch):
    import asyncio
    from contextvars import ContextVar
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.dispatch import DispatchService
    from core.chat import turn_journal

    env = native_source
    actor = ContextVar("trusted_source_test_actor", default={})
    observed, starts = [], []
    def current_runtime():
        observed.append(dict(actor.get()))
        return dict(actor.get())
    env.directory.current_agent_runtime = current_runtime
    path = env.root / "portal_journal.jsonl"
    monkeypatch.setattr(turn_journal, "turn_journal_path", lambda *_args: path)
    monkeypatch.setattr(turn_journal, "load_turn_events", env.real_load)
    marker = "E3_RECEIPT_3E159D2DFC294ED1"
    turn_journal.append_turn_events(env.root, "own-session", "turn-a", [
        {"event_type": "turn_started", "source": "submit_session_message", "correlation_id": "operator-portal",
         "payload": {"agentId": "assistant-a", "source": "raw"}},
        {"event_type": "user_message", "source": "submit_session_message", "correlation_id": "operator-portal",
         "payload": {"content": "委派开始：只回复 " + marker + "。委派结束", "source": "raw",
                     "metadata": {"clientSubmissionId": "operator-portal", "turnId": "turn-a"}}},
    ])
    class Client:
        async def diagnostics(self):
            return {}
        async def start_task(self, **kwargs):
            starts.append(kwargs)
            return {"taskId": "native-portal", "status": "running"}
    service = DispatchService(env.root / "profile", {"target": env.root / "project"}, client_factory=lambda *_args, **_kwargs: Client())
    bind_actions(service, asyncio.get_running_loop())
    token = actor.set(dict(env.runtime))
    before = path.read_bytes()
    try:
        result = await asyncio.to_thread(execute_action, "dispatch", {"project_id": "target", "agent_id": "coder",
            "dispatch_id": "portal-source", "task_source": {"start_after": "委派开始：", "end_before": "。委派结束"}},
            runtime=dict(env.runtime))
        assert result["nativeTaskId"] == "native-portal"
        assert observed == [env.runtime] and starts[0]["task"] == "只回复 " + marker
        assert actor.get() == env.runtime and path.read_bytes() == before
    finally:
        actor.reset(token)
        unbind_actions(service)
    with pytest.raises(env.native.AssistantSessionError):
        env.native.read_task_source(dict(env.runtime))


@pytest.mark.anyio
@pytest.mark.parametrize("stopping", [False, True], ids=["busy", "shutdown_waiting_worker"])
async def test_native_source_busy_refuses_without_blocking_host_loop_or_writes(native_source, stopping):
    import asyncio
    import threading
    import time
    from core.assistant_runtime.dispatch import DispatchError, DispatchService

    env = native_source
    held, release = threading.Event(), threading.Event()
    def shutdown_owner():
        with env.native._LOCK:
            if stopping:
                env.native._STOP_REQUESTED.set()
            held.set()
            release.wait(2)
    owner = threading.Thread(target=shutdown_owner)
    owner.start()
    assert held.wait(1)
    # Bounded fail-safe permits the old blocking implementation to finish so
    # RED diagnoses the cycle rather than hanging the test process.
    watchdog = threading.Timer(1, release.set)
    watchdog.start()
    clients = []
    service = DispatchService(env.root / "profile", {"target": env.root / "project"},
        client_factory=lambda *_args, **_kwargs: clients.append(True) or pytest.fail("busy source reached SDK"))
    async def ping():
        await asyncio.sleep(0.01)
        return time.monotonic()
    before = time.monotonic()
    try:
        pending = asyncio.create_task(service.dispatch_from_source("target", agent_id="coder", dispatch_id="busy-source",
            runtime=dict(env.runtime), task_source={}))
        probe = asyncio.create_task(ping())
        with pytest.raises(DispatchError) as denied:
            await pending
        probe_at = await probe
        assert denied.value.code == "TASK_SOURCE_UNAVAILABLE"
        assert probe_at - before < 0.5 and time.monotonic() - before < 0.5
        assert not clients and not env.reads and not list((env.root / "profile").rglob("*.json"))
    finally:
        release.set()
        watchdog.cancel()
        owner.join(timeout=2)
        assert not owner.is_alive()


def test_native_source_stop_between_precheck_and_acquire_is_refused_and_released(native_source, monkeypatch):
    import threading
    env = native_source
    actual, held = threading.RLock(), []
    class ShutdownRaceLock:
        def acquire(self, *, blocking):
            assert blocking is False
            acquired = actual.acquire(blocking=False)
            held.append(acquired)
            env.native._STOP_REQUESTED.set()
            return acquired
        def release(self):
            actual.release()
            held.pop()
    monkeypatch.setattr(env.native, "_LOCK", ShutdownRaceLock())
    with pytest.raises(env.native.AssistantSessionError) as error:
        env.native.read_task_source(dict(env.runtime))
    assert error.value.code == "ASSISTANT_STOPPING" and not env.reads and held == []


@pytest.mark.anyio
async def test_native_source_journal_io_does_not_block_host_event_loop(native_source, monkeypatch):
    import asyncio
    import threading
    import time
    from core.assistant_runtime.dispatch import DispatchService
    from core.chat import turn_journal
    env = native_source
    entered, release = threading.Event(), threading.Event()
    def slow_journal(*_args):
        entered.set()
        release.wait(2)
        return env.events
    monkeypatch.setattr(turn_journal, "load_turn_events", slow_journal)
    class Client:
        async def diagnostics(self):
            return {}
        async def start_task(self, **_kwargs):
            return {"taskId": "native-source-io", "status": "running"}
    service = DispatchService(env.root / "profile", {"target": env.root / "project"}, client_factory=lambda *_args, **_kwargs: Client())
    watchdog = threading.Timer(1, release.set)
    watchdog.start()
    before = time.monotonic()
    pending = asyncio.create_task(service.dispatch_from_source("target", agent_id="coder", dispatch_id="source-io",
        runtime=dict(env.runtime), task_source={}))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        await asyncio.sleep(0.01)
        assert time.monotonic() - before < 0.5 and not pending.done()
        release.set()
        assert (await pending)["nativeTaskId"] == "native-source-io"
    finally:
        release.set()
        watchdog.cancel()
        if not pending.done():
            await pending
