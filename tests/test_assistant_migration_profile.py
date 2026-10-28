"""Offline migration locks the actual native assistant before bootstrap."""
from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_offline_profile_stays_owned_and_restores_identity_on_restart(tmp_path):
    _run(tmp_path, """
        import json, os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.infrastructure.file_lock import locked_sidecar
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        before = root.parent / 'offline-profile-identity.json'
        assert not native._STARTED
        with offline_migration_profile() as lease:
            lease.check()
            assert lease.root == root.resolve()
            assert native._STARTED and native._AGENT_ID == lease.agent_id
            assert native._SESSION_ID == lease.session_id
            try:
                with locked_sidecar(root / 'host-owner', timeout=0):
                    raise AssertionError('another owner acquired the live lock')
            except TimeoutError:
                pass
            identity = {'agentId': lease.agent_id, 'sessionId': lease.session_id}
            if before.exists():
                assert json.loads(before.read_text()) == identity
            else:
                before.write_text(json.dumps(identity), encoding='utf-8')
        assert not native._STARTED
        try:
            lease.check()
        except RuntimeError:
            pass
        else:
            raise AssertionError('expired migration lease was usable')
    """, config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, """
        import json, os
        from pathlib import Path
        from core.assistant_runtime.migration_profile import offline_migration_profile
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        before = json.loads((root.parent / 'offline-profile-identity.json').read_text())
        with offline_migration_profile() as lease:
            assert {'agentId': lease.agent_id, 'sessionId': lease.session_id} == before
            lease.check()
    """, config_text=TEST_MODEL_CONFIG)


def test_busy_profile_is_rejected_before_bootstrap(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.infrastructure.file_lock import cross_process_file_lock
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        with cross_process_file_lock(root / 'host-owner'):
            try:
                with offline_migration_profile():
                    raise AssertionError('busy profile admitted')
            except TimeoutError:
                pass
            assert not native._STARTED
        assert not (root / 'data').exists()
    """, config_text=TEST_MODEL_CONFIG)


def test_before_bootstrap_runs_under_owner_and_rejection_never_bootstraps(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.infrastructure.file_lock import locked_sidecar
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        calls = []
        def check_owner(actual):
            assert actual == root and not native._STARTED
            try:
                with locked_sidecar(root / 'host-owner', timeout=0):
                    raise AssertionError('hook lacks exclusive owner')
            except TimeoutError:
                pass
            calls.append('checked')
        def reject(actual):
            check_owner(actual)
            raise RuntimeError('permit unavailable')
        try:
            with offline_migration_profile(before_bootstrap=reject):
                raise AssertionError('rejected hook admitted writer')
        except RuntimeError as error:
            assert str(error) == 'permit unavailable'
        assert not native._STARTED and not (root / 'data').exists()
        with offline_migration_profile(before_bootstrap=check_owner) as lease:
            lease.check()
        assert calls == ['checked', 'checked'] and not native._STARTED
    """, config_text=TEST_MODEL_CONFIG)


def test_offline_profile_never_recovers_or_stops_a_pending_native_turn(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        sid = native.bootstrap(root)['assistant']['directSessionId']
        sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: None
        receipt = native.submit('pending fixture', 'migration-pending-1')
        sessions._WORK_RUN_STORE.persist_snapshot('chat_turn', {
            'runId': receipt['turnId'], 'runKind': 'chat_turn', 'sessionId': sid,
            'status': 'running', 'finishedAt': '',
        }, active_run_id=receipt['turnId'])
        os._exit(0)
    """, config_text=TEST_MODEL_CONFIG)
    _run(tmp_path, """
        import os, sys
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile
        from core.web.services import session_service as sessions
        from core.web.services.session import startup_recovery
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        journals = {path: path.read_bytes() for path in root.rglob('turn_journal.jsonl')}
        def forbidden(*args, **kwargs):
            raise AssertionError('offline migration recovered, stopped or submitted a turn')
        startup_recovery.recover_interrupted_session_turns_on_startup = forbidden
        sessions.request_stop_session_turn = forbidden
        def no_network(event, args):
            if event == 'socket.connect':
                raise AssertionError('offline migration contacted a provider')
        sys.addaudithook(no_network)
        with offline_migration_profile() as lease:
            lease.check()
            try:
                native.submit('unexpected', 'not-allowed')
            except RuntimeError:
                pass
            else:
                raise AssertionError('migration profile admitted a new turn')
        assert journals == {path: path.read_bytes() for path in root.rglob('turn_journal.jsonl')}
    """, config_text=TEST_MODEL_CONFIG)


def test_failed_native_shutdown_keeps_profile_locked_until_recovered(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile, retry_offline_migration_shutdown
        from core.infrastructure.file_lock import locked_sidecar
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        original = native.shutdown
        try:
            with offline_migration_profile() as lease:
                native.shutdown = lambda **kwargs: {'closed': False}
        except RuntimeError as error:
            assert str(error) == 'offline_migration_shutdown_unconfirmed'
        else:
            raise AssertionError('unconfirmed native shutdown reported success')
        try:
            with locked_sidecar(root / 'host-owner', timeout=0):
                raise AssertionError('profile lock released before native shutdown')
        except TimeoutError:
            pass
        try:
            lease.check()
        except RuntimeError:
            pass
        else:
            raise AssertionError('expired lease remained active')
        native.shutdown = original
        assert retry_offline_migration_shutdown() is True
        with locked_sidecar(root / 'host-owner', timeout=0):
            assert not native._STARTED
    """, config_text=TEST_MODEL_CONFIG)


def test_failed_bootstrap_cleanup_keeps_profile_locked_until_confirmed(tmp_path):
    _run(tmp_path, """
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        from core.assistant_runtime.migration_profile import offline_migration_profile, retry_offline_migration_shutdown
        from core.infrastructure.file_lock import locked_sidecar
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        _, personal, sessions, _ = native._services()
        original_create, original_close = personal.create_personal_assistant, sessions.shutdown_session_service
        def fail_create(*args, **kwargs): raise ValueError('synthetic bootstrap failure')
        personal.create_personal_assistant = fail_create
        sessions.shutdown_session_service = lambda **kwargs: {'closed': False}
        try:
            with offline_migration_profile():
                raise AssertionError('bootstrap failed but lease was granted')
        except RuntimeError as error:
            assert str(error) == 'offline_migration_shutdown_unconfirmed'
        else:
            raise AssertionError('unconfirmed bootstrap cleanup was accepted')
        try:
            with locked_sidecar(root / 'host-owner', timeout=0):
                raise AssertionError('profile lock released while cleanup was pending')
        except TimeoutError:
            pass
        personal.create_personal_assistant = original_create
        sessions.shutdown_session_service = original_close
        assert retry_offline_migration_shutdown() is True
        with locked_sidecar(root / 'host-owner', timeout=0):
            assert not native._STARTED
    """, config_text=TEST_MODEL_CONFIG)
def test_directory_close_failure_keeps_profile_locked_even_after_writer_stops(tmp_path):
    from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run
    _run(tmp_path, '''
        import os, threading
        from pathlib import Path
        from core.assistant_runtime import native, migration_profile as profile
        from core.web.services.session import directory_runtime as runtime
        from core.infrastructure.file_lock import locked_sidecar
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT']).resolve()
        started, release = threading.Event(), threading.Event()
        original_shutdown = native.shutdown
        native.shutdown = lambda **kwargs: original_shutdown(timeout=.01)
        writer_thread = None
        try:
            try:
                with profile.offline_migration_profile():
                    store = runtime._STORE
                    def blocked(*args):
                        started.set()
                        release.wait(5)
                    store.writer.submit_maintenance(blocked)
                    assert started.wait(2)
                    writer_thread = store.writer._thread
            except RuntimeError as error:
                assert str(error) == 'offline_migration_shutdown_unconfirmed'
            else:
                raise AssertionError('blocked writer reported closed')
            assert writer_thread.is_alive()
            assert runtime.directory_store_project_root() is None
            assert profile.retry_offline_migration_shutdown() is False
            release.set()
            writer_thread.join(5)
            assert not writer_thread.is_alive()
            assert profile.retry_offline_migration_shutdown() is False
            try:
                with locked_sidecar(root / 'host-owner', timeout=0):
                    pass
            except TimeoutError:
                pass
            else:
                raise AssertionError('unconfirmed directory owner released its lock')
        finally:
            release.set()
            if writer_thread:
                writer_thread.join(5)
            native.shutdown = original_shutdown
    ''', config_text=TEST_MODEL_CONFIG)
