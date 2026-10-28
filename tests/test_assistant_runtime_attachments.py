"""The Launcher attachment adapter uses the fixed native Session only."""

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


def test_attachment_store_read_submit_and_session_isolation(tmp_path):
    _run(tmp_path, r'''
        import os
        import io
        from pathlib import Path
        from PIL import Image
        from core.assistant_runtime import native
        from core.web.services import session_service as sessions
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            sid = native.bootstrap(root)['assistant']['directSessionId']
            stream = io.BytesIO()
            Image.new('RGB', (2, 2)).save(stream, format='PNG')
            image = stream.getvalue()
            uploaded = native.upload_attachment(image, filename='picture.png', content_type='image/png')
            document = native.upload_attachment(b'hello document', filename='note.txt', content_type='text/plain')
            assert uploaded['kind'] == 'user_image'
            assert document['kind'] == 'user_document'
            assert not ({'path', 'artifactPath', 'url', 'imageUrl', 'downloadUrl'} & uploaded.keys())
            assert native.read_attachment(uploaded['artifactId']) == (image, 'image/png')
            assert native.read_attachment(document['artifactId']) == (b'hello document', 'text/plain')
            from core.web.services.session import image_attachments
            original_resolver = image_attachments.resolve_session_image_artifact
            outside = root / 'outside.png'
            outside.write_bytes(image)
            image_attachments.resolve_session_image_artifact = lambda *_: (outside, 'image/png')
            try:
                try:
                    native.read_attachment(uploaded['artifactId'])
                except native.AssistantSessionError as error:
                    assert error.code == 'ATTACHMENT_NOT_FOUND'
                else:
                    raise AssertionError('outside attachment accepted')
            finally:
                image_attachments.resolve_session_image_artifact = original_resolver
            foreign_id = 'user-doc-foreign.txt'
            foreign_dir = sessions._ensure_session_workspace('foreign-session') / 'artifacts' / 'documents'
            foreign_dir.mkdir(parents=True, exist_ok=True)
            (foreign_dir / foreign_id).write_bytes(b'foreign')
            for invalid in ('../secret.txt', 'missing.txt', foreign_id, 123):
                try:
                    native.read_attachment(invalid)
                except native.AssistantSessionError as error:
                    assert error.code in ('SESSION_INVALID', 'ATTACHMENT_NOT_FOUND')
                else:
                    raise AssertionError('invalid attachment accepted')
            original_submit = sessions._SESSION_EXECUTOR.submit
            sessions._SESSION_EXECUTOR.submit = lambda *args, **kwargs: None
            try:
                for ids in ([document['artifactId'], foreign_id], ['../secret.txt'], 'not-a-list'):
                    try:
                        native.submit('invalid', 'invalid-request', ids)
                    except native.AssistantSessionError as error:
                        assert error.code == 'SESSION_INVALID'
                    else:
                        raise AssertionError('foreign or invalid attachment accepted')
                receipt = native.submit('attached', 'attachment-request', [document['artifactId'], uploaded['artifactId']])
                assert receipt['turnId'] == native.submit('attached', 'attachment-request', [document['artifactId'], uploaded['artifactId']])['turnId']
            finally:
                sessions._SESSION_EXECUTOR.submit = original_submit
                sessions._set_session_running(sid, False)
        finally:
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


def test_attachment_validation_and_lifecycle(tmp_path):
    _run(tmp_path, r'''
        import os
        from pathlib import Path
        from core.assistant_runtime import native
        root = Path(os.environ['VIBELUTION_ASSISTANT_NATIVE_ROOT'])
        try:
            native.bootstrap(root)
            for payload, filename, content_type in (
                (b'', 'a.txt', 'text/plain'),
                (b'not a pdf', 'a.pdf', 'application/pdf'),
                (b'x' * (2 * 1024 * 1024 + 1), 'a.txt', 'text/plain'),
                (b'not an image', 'a.png', 'image/png'),
                (b'x', 'a.exe', 'application/octet-stream'),
            ):
                try:
                    native.upload_attachment(payload, filename=filename, content_type=content_type)
                except native.AssistantSessionError as error:
                    assert error.code == 'SESSION_INVALID'
                else:
                    raise AssertionError('invalid upload accepted')
            original_agent = native._AGENT_ID
            native._AGENT_ID = 'different-agent'
            try:
                for action in (lambda: native.upload_attachment(b'hello', filename='a.txt', content_type='text/plain'),
                               lambda: native.read_attachment('a.txt'),
                               lambda: native.submit('message', 'request', [])):
                    try:
                        action()
                    except native.AssistantSessionError as error:
                        assert error.code == 'ASSISTANT_IDENTITY_INVALID'
                    else:
                        raise AssertionError('rebound identity accepted')
            finally:
                native._AGENT_ID = original_agent
            native._STOP_REQUESTED.set()
            for action in (lambda: native.upload_attachment(b'hello', filename='a.txt', content_type='text/plain'),
                           lambda: native.read_attachment('a.txt'),
                           lambda: native.submit('message', 'request', [])):
                try:
                    action()
                except native.AssistantSessionError as error:
                    assert error.code == 'ASSISTANT_STOPPING'
                else:
                    raise AssertionError('command admitted after stop')
        finally:
            native.shutdown()
    ''', config_text=TEST_MODEL_CONFIG)


def test_upload_rejects_linked_session_directory(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    import pytest
    from core.assistant_runtime import attachments
    from core.assistant_runtime.migration_io import MigrationIOError

    if os.name != 'nt':
        pytest.skip('Windows directory pinning')
    root = tmp_path / 'sessions'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    try:
        (root / 'session').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('creating directory symlinks is unavailable')
    sessions = SimpleNamespace(
        SessionValidationError=ValueError,
        SESSION_USER_IMAGE_MAX_BYTES=8 * 1024 * 1024,
        _sniff_image_extension=lambda _: None,
        developer_sandbox=SimpleNamespace(sandboxed_workspace_path=lambda *_: root),
        PROJECT_ROOT=tmp_path,
        _safe_session_workspace_token=lambda _: 'session',
    )
    called = []
    monkeypatch.setattr(attachments.document_attachments, 'store_session_user_document_attachment', lambda *a, **kw: called.append(True))
    with pytest.raises(MigrationIOError):
        attachments.store(sessions, 'session', b'text', filename='note.txt', content_type='text/plain')
    assert not called
    assert list(outside.iterdir()) == []
