"""Neutral avatar discovery must reuse a persistently read-only native library."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from tests.test_assistant_runtime_native import TEST_MODEL_CONFIG, _run


@pytest.mark.parametrize("developer_mode", [False, True])
def test_actual_native_avatar_library_cold_read_has_no_persistent_writes(tmp_path, developer_mode):
    config = TEST_MODEL_CONFIG + ("\n[launcher.developer_mode]\nenabled = true\n" if developer_mode else "")
    _run(tmp_path, """
        import json, os, sys
        from pathlib import Path
        from core.web.services import agent_directory_service as directory
        from core.web.services.external_management.native import NativeAgentGateway
        from core.infrastructure import developer_sandbox
        from config.public_config import read_existing_config_snapshot
        from core.web.services.agent_directory import mutations
        root = Path(os.environ['ASSISTANT_TEST_WRITE_ROOT']) / 'target'
        identity = root / '.vibelution' / 'project.json'
        identity.parent.mkdir(parents=True)
        identity.write_text(json.dumps({'schemaVersion': 1, 'projectId': 'avatar-library-fixture'}), encoding='utf-8')
        assets = root / 'assets' / directory.AGENT_AVATAR_ASSET_DIR_NAME
        assets.mkdir(parents=True)
        (assets / 'fixture-avatar.png').write_bytes(b'fixture: metadata-only read; no content decoding')
        config_path = Path(os.environ['VIBELUTION_CONFIG_PATH'])
        developer = 'enabled = true' in config_path.read_text()
        if developer:
            active = developer_sandbox._active_state_path(root)
            active.parent.mkdir(parents=True)
            active.write_text(json.dumps({'schemaVersion': 1, 'sandboxId': 'dev-existing'}), encoding='utf-8')
            (developer_sandbox._sandbox_root(root, 'dev-existing') / 'workspace').mkdir(parents=True)
        mutations._AVATAR_DIR_CACHE.clear()
        directory.PROJECT_ROOT = root
        assert 'core.web.services.session_service' not in sys.modules
        home = Path(os.environ['ASSISTANT_TEST_WRITE_ROOT'])
        before = {str(path.relative_to(home)): path.read_bytes() for path in home.rglob('*') if path.is_file()}
        writes = []
        def observe(event, args):
            if event == 'socket.connect':
                raise AssertionError('avatar candidate reads must not use a network')
            if event == 'open':
                path, _mode, flags = args
                if isinstance(path, int) or not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                    return
                paths = [path]
            elif event in ('os.mkdir', 'os.remove', 'os.rmdir'):
                paths = [args[0]]
            elif event in ('os.rename', 'os.replace'):
                paths = args[:2]
            else:
                return
            writes.extend(event + ':' + Path(os.fsdecode(path)).name for path in paths)
        sys.addaudithook(observe)
        with directory.scoped_project_root(root):
            snapshot = read_existing_config_snapshot(config_path)
            legacy = developer_sandbox.existing_sandboxed_workspace_path(root, 'avatars', public_config=snapshot)
            dirs = (('custom', config_path.parent / directory.AGENT_AVATAR_CONFIG_DIR_NAME / directory.AGENT_AVATAR_CONFIG_AGENT_DIR_NAME),
                ('bundled', assets), ('legacy', legacy))
            assert not mutations._AVATAR_DIR_CACHE
            result = NativeAgentGateway(root).avatar_options()
            assert 'core.web.services.session_service' not in sys.modules
            assert result == mutations.agent_avatar_options_snapshot(dirs)
        after = {str(path.relative_to(home)): path.read_bytes() for path in home.rglob('*') if path.is_file()}
        assert any(row['filename'] == 'fixture-avatar.png' for row in result)
        assert not writes, writes[:20]
        assert before == after, sorted(set(after) - set(before))
    """, role="workbench", config_text=config)


@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.service import ManagementService, TargetIdentity
    calls = []
    rows = [{'filename': f'avatar-{index}.png', 'path': f'workspace/avatars/avatar-{index}.png'} for index in range(35)]
    class Native:
        def avatar_options(self):
            calls.append('native')
            return rows
    binding = {'projectId': 'project', 'instanceId': 'instance'}
    service = ManagementService(tmp_path / 'management', identity=lambda: TargetIdentity(binding, 'authority'), native=Native())
    grant = service.bind({'client_id': 'launcher', 'expected_binding': binding, 'scopes': ['agents:read']})
    headers = {CONTROL_TOKEN_HEADER: get_control_token(), route.SUBJECT_HEADER: grant['subject_id'], route.CAPABILITY_HEADER: grant['subject_capability']}
    monkeypatch.setattr(route, '_SERVICE', service)
    app = FastAPI(); app.include_router(route.router)
    return SimpleNamespace(client=TestClient(app), headers=headers, service=service, calls=calls, rows=rows, root=tmp_path, binding=binding)


URL = '/v1/launcher-assistant-management/avatar-options'


def test_avatar_route_closed_pagination_is_a_read_without_intent_or_grant_writes(env, monkeypatch):
    before = {path: path.read_bytes() for path in env.root.rglob('*') if path.is_file()}
    monkeypatch.setattr(env.service.store, 'write', lambda *_args: pytest.fail('read wrote grant or intent'))
    monkeypatch.setattr(env.service.store, 'lock', lambda *_args: pytest.fail('read acquired write ledger lock'))
    result = env.client.get(URL + '?offset=30&limit=3', headers=env.headers)
    assert result.status_code == 200, result.text
    assert result.json() == {'options': env.rows[30:33], 'total': 35, 'offset': 30, 'nextOffset': 33, 'untrustedContent': True}
    assert env.client.get(URL + '?offset=35&limit=30', headers=env.headers).json()['options'] == []
    assert before == {path: path.read_bytes() for path in env.root.rglob('*') if path.is_file()}


def test_avatar_route_refuses_an_unpageable_full_native_snapshot(env):
    env.rows[:] = [env.rows[0]] * 50001
    result = env.client.get(URL + '?offset=50000&limit=30', headers=env.headers)
    assert result.status_code == 503 and result.json() == {'detail': {'code': 'AVATAR_LIBRARY_UNAVAILABLE'}}


def test_native_avatar_snapshot_rejects_more_than_fifty_thousand_candidates(tmp_path, monkeypatch):
    from core.web.services.agent_directory import mutations
    monkeypatch.setattr(mutations, '_cached_agent_avatar_dir_filenames', lambda *_args: tuple(f'choice-{n}.png' for n in range(50001)))
    with pytest.raises(ValueError, match='Avatar snapshot limit exceeded'):
        mutations.agent_avatar_options_snapshot((('bundled', tmp_path),))


def test_native_uppercase_raster_candidate_roundtrips_read_dto_and_existing_avatar_write(tmp_path):
    from core.web.services.agent_directory import mutations
    from core.web.services.external_management.contracts import AgentAvatar, AvatarOptionsResponse
    folder = tmp_path / 'bundled'; folder.mkdir()
    for name in ('choice.PNG', 'photo.JpEg', 'image.WEBP', 'unregistered.SVG'):
        (folder / name).write_bytes(b'only native metadata lookup')
    mutations._AVATAR_DIR_CACHE.clear()
    rows = mutations.agent_avatar_options_snapshot((('bundled', folder),))
    assert {row['filename'] for row in rows} == {'choice.PNG', 'photo.JpEg', 'image.WEBP'}
    page = AvatarOptionsResponse.model_validate({'options': rows, 'offset': 0, 'total': len(rows), 'nextOffset': None, 'untrustedContent': True})
    for option in page.options:
        write = AgentAvatar.model_validate({'agent_id': 'ordinary', 'expected_updated_at': 'stamp', 'avatar_image_path': option.path})
        assert write.avatar_image_path == option.path


@pytest.mark.parametrize('page', [
    {'options': [{'filename': 'one.png', 'path': 'workspace/avatars/one.png'}], 'total': 2, 'offset': 0, 'nextOffset': None},
    {'options': [], 'total': 2, 'offset': 0, 'nextOffset': None},
    {'options': [], 'total': 50001, 'offset': 50000, 'nextOffset': None},
    {'options': [{'filename': 'one.png', 'path': 'workspace/avatars/one.png'}], 'total': 1, 'offset': 0, 'nextOffset': 1},
], ids=['truncated_middle', 'empty_middle', 'oversized_total', 'invalid_last_page'])
def test_avatar_response_never_advertises_a_truncated_page_as_complete(page):
    from pydantic import ValidationError
    from core.web.services.external_management.contracts import AvatarOptionsResponse
    with pytest.raises(ValidationError):
        AvatarOptionsResponse.model_validate({**page, 'untrustedContent': True})


@pytest.mark.parametrize('query', ['offset=-1', 'offset=50001', 'offset=1.5', 'offset=true', 'limit=0', 'limit=31', 'path=/private', 'model_id=guess', 'offset=1&offset=2'])
def test_avatar_route_rejects_unregistered_or_invalid_query_before_native_read(env, query):
    assert env.client.get(URL + '?' + query, headers=env.headers).status_code == 422
    assert env.calls == []


def test_avatar_route_requires_operator_control_and_existing_agents_read_scope(env):
    assert env.client.get(URL).status_code == 403
    assert env.client.get(URL, headers={**env.headers, 'X-Vibelution-Management-Capability': 'x' * 48}).status_code == 403
    other = env.service.bind({'client_id': 'other', 'expected_binding': env.binding, 'scopes': ['agents:avatar']})
    from core.web.routes.launcher_assistant_management import SUBJECT_HEADER, CAPABILITY_HEADER
    assert env.client.get(URL, headers={**env.headers, SUBJECT_HEADER: other['subject_id'], CAPABILITY_HEADER: other['subject_capability']}).status_code == 403
    assert env.calls == []


@pytest.mark.parametrize('changed', ['projectId', 'instanceId', 'authority'])
def test_avatar_route_rejects_changed_target_identity_before_native_read(env, changed):
    from core.web.services.external_management.service import TargetIdentity
    binding = dict(env.binding)
    authority = 'authority'
    if changed == 'authority':
        authority = 'different-authority'
    else:
        binding[changed] = 'different-' + changed
    env.service.identity = lambda: TargetIdentity(binding, authority)
    result = env.client.get(URL, headers=env.headers)
    assert result.status_code == 409
    assert result.json() == {'detail': {'code': 'TARGET_BINDING_CHANGED'}}
    assert env.calls == []


@pytest.mark.parametrize('patch', [{'filename': '../escape.png'}, {'path': '/private/avatar.png'}, {'path': 'workspace/avatars/other.png'}, {'url': 'https://private'}, {'filename': 3}])
def test_avatar_route_validates_every_candidate_before_paging(env, patch):
    env.rows[-1] = {**env.rows[-1], **patch}
    result = env.client.get(URL + '?limit=1', headers=env.headers)
    assert result.status_code == 503 and result.json() == {'detail': {'code': 'AVATAR_LIBRARY_UNAVAILABLE'}}


def test_native_avatar_snapshot_reuses_ordering_marks_and_never_loads_content_or_routing(tmp_path, monkeypatch):
    from pathlib import Path
    from core.web.services import agent_directory_service as directory
    from core.web.services.agent_directory import mutations
    dirs = tuple((source, tmp_path / source) for source in ('custom', 'bundled', 'legacy'))
    for _, path in dirs:
        path.mkdir()
    model_mark = directory.AGENT_AVATAR_MODEL_FILENAMES[0]
    for name in ('z-choice.png', 'a-choice.png', model_mark):
        (dirs[0][1] / name).write_bytes(b'no content reading')
    (dirs[2][1] / 'a-choice.png').write_bytes(b'duplicate native candidate')
    mutations._AVATAR_DIR_CACHE.clear()
    def forbidden(*_args, **_kwargs):
        pytest.fail('snapshot read file contents or reentered implicit routing')
    with monkeypatch.context() as guarded:
        guarded.setattr(Path, 'open', forbidden)
        guarded.setattr(Path, 'mkdir', forbidden)
        guarded.setattr(mutations, '_agent_avatar_storage_dirs', forbidden)
        guarded.setattr(directory, 'list_agent_avatar_options', forbidden)
        rows = mutations.agent_avatar_options_snapshot(dirs)
    assert rows == [{'filename': name, 'path': 'workspace/avatars/' + name} for name in ('a-choice.png', 'z-choice.png')]
    (dirs[1][1] / model_mark).write_bytes(b'bundled model mark')
    mutations._AVATAR_DIR_CACHE.clear()
    rows = mutations.agent_avatar_options_snapshot(dirs)
    assert sum(row['filename'] == model_mark for row in rows) == 1


def test_avatar_native_checks_target_binding_before_config_or_library(tmp_path, monkeypatch):
    from config import public_config
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementError
    monkeypatch.setattr(public_config, 'read_existing_config_snapshot', lambda *_: pytest.fail('wrong root read config'))
    monkeypatch.setattr(directory, 'PROJECT_ROOT', tmp_path / 'different-bound-root')
    with pytest.raises(ManagementError, match='TARGET_BINDING_CHANGED'):
        NativeAgentGateway(tmp_path).avatar_options()


def test_avatar_native_rejects_a_different_scoped_project_before_config(tmp_path, monkeypatch):
    from config import public_config
    from core.web.services import agent_directory_service as directory
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementError
    monkeypatch.setattr(directory, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(public_config, 'read_existing_config_snapshot', lambda *_: pytest.fail('wrong root read config'))
    with directory.scoped_project_root(tmp_path / 'different-scoped-root'):
        with pytest.raises(ManagementError, match='TARGET_BINDING_CHANGED'):
            NativeAgentGateway(tmp_path).avatar_options()


def test_avatar_native_unavailable_developer_authority_does_not_create_or_fallback(tmp_path, monkeypatch):
    from core.web.services import agent_directory_service as directory, session_service as sessions
    from core.web.services.external_management.native import NativeAgentGateway
    from core.web.services.external_management.service import ManagementError
    monkeypatch.setattr(directory, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(sessions, 'PROJECT_ROOT', tmp_path)
    config = tmp_path / 'config.toml'; config.write_text('[launcher.developer_mode]\nenabled=true', encoding='utf-8')
    monkeypatch.setattr(directory, 'CONFIG_PATH', config)
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    paths = set(tmp_path.rglob('*'))
    with pytest.raises(ManagementError, match='AVATAR_LIBRARY_UNAVAILABLE'):
        NativeAgentGateway(tmp_path).avatar_options()
    assert before == {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    assert paths == set(tmp_path.rglob('*'))
