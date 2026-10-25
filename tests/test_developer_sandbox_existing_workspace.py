"""Existing read routing never creates a developer sandbox or changes mode."""
import json

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core.infrastructure import developer_sandbox as owner
    root = tmp_path / 'project'; root.mkdir()
    state = root / 'active.json'
    monkeypatch.setattr(owner, '_active_state_path', lambda _: state)
    monkeypatch.setattr(owner, '_sandbox_root', lambda _, token: root / 'sandboxes' / token)
    monkeypatch.setattr(owner, 'formal_workspace_path', lambda _, *parts: root.joinpath('formal', *parts))
    def forbidden(*_args, **_kwargs):
        pytest.fail('existing routing attempted initialization/config loading')
    for name in ('_ensure_active_state', 'load_public_config', 'is_developer_mode_enabled', 'seeded_sandbox_workspace_path'):
        monkeypatch.setattr(owner, name, forbidden)
    return owner, root, state


def test_existing_workspace_uses_formal_only_when_mode_is_false_or_absent(env):
    owner, root, _ = env
    for config in ({}, {'launcher': {'developer_mode': {'enabled': False}}}):
        assert owner.existing_sandboxed_workspace_path(root, 'avatars', public_config=config) == root / 'formal' / 'avatars'
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('mode', ['true', 1, None, [], {'enabled': 'false'}])
def test_existing_workspace_rejects_malformed_mode(env, mode):
    owner, root, _ = env
    config = {'launcher': {'developer_mode': mode if isinstance(mode, dict) else {'enabled': mode}}}
    with pytest.raises(ValueError, match='EXISTING_WORKSPACE_UNAVAILABLE'):
        owner.existing_sandboxed_workspace_path(root, public_config=config)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('payload', [None, 'broken', {}, {'schemaVersion': 2, 'sandboxId': 'dev-one'},
    {'schemaVersion': 1, 'sandboxId': '../other'}, {'schemaVersion': 1, 'sandboxId': ' dev-one'},
    {'schemaVersion': 1, 'sandboxId': 'dev-one'}])
def test_existing_developer_workspace_never_falls_back_when_authority_is_missing(env, payload):
    owner, root, state = env
    if payload is not None:
        state.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding='utf-8')
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with pytest.raises(ValueError, match='EXISTING_WORKSPACE_UNAVAILABLE'):
        owner.existing_sandboxed_workspace_path(root, 'avatars', public_config={'launcher': {'developer_mode': {'enabled': True}}})
    assert before == {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert not (root / 'sandboxes').exists()


def test_existing_developer_workspace_reads_only_the_proven_existing_root(env):
    owner, root, state = env
    workspace = root / 'sandboxes' / 'dev-one' / 'workspace'; workspace.mkdir(parents=True)
    state.write_text(json.dumps({'schemaVersion': 1, 'sandboxId': 'dev-one'}), encoding='utf-8')
    result = owner.existing_sandboxed_workspace_path(root, 'avatars', public_config={'launcher': {'developer_mode': {'enabled': True}}})
    assert result == workspace / 'avatars' and not result.exists()


@pytest.mark.parametrize('destination', ['outside', 'same-parent'])
def test_existing_developer_workspace_rejects_a_redirected_sandbox(env, monkeypatch, destination):
    from pathlib import Path
    owner, root, state = env
    workspace = root / 'sandboxes' / 'dev-one' / 'workspace'; workspace.mkdir(parents=True)
    state.write_text(json.dumps({'schemaVersion': 1, 'sandboxId': 'dev-one'}), encoding='utf-8')
    original = Path.resolve
    alias = root / 'outside' / 'dev-one' if destination == 'outside' else root / 'sandboxes' / 'dev-two'
    def redirected(path, *args, **kwargs):
        if path.is_relative_to(workspace.parent):
            return alias / path.relative_to(workspace.parent)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', redirected)
    with pytest.raises(ValueError, match='EXISTING_WORKSPACE_UNAVAILABLE'):
        owner.existing_sandboxed_workspace_path(root, 'avatars', public_config={'launcher': {'developer_mode': {'enabled': True}}})
