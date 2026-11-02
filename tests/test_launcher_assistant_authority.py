from __future__ import annotations

import hashlib
import json
import os

import pytest

from core.infrastructure import launcher_assistant_authority as authority


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    authority.install_launcher_authority(None)
    yield tmp_path / "local" / "Vibelution" / "DesktopShell" / "assistant" / "profile"
    authority.install_launcher_authority(None)


def _path(profile):
    return profile / "launcher-authority.json"


def _replace(profile, **changes):
    path = _path(profile)
    payload = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**payload, **changes}), encoding="utf-8")


def test_verifier_never_creates_and_host_initialization_is_stable(profile):
    assert not authority.verify_launcher_authority("x" * 43)
    assert authority.launcher_authority_fingerprint() == ""
    assert not profile.exists()
    token = authority.ensure_launcher_authority(profile)
    assert isinstance(token, str) and len(token) >= 43
    assert authority.ensure_launcher_authority(profile) == token
    assert authority.verify_launcher_authority(token)
    assert authority.launcher_authority_fingerprint() == hashlib.sha256(token.encode()).hexdigest()
    assert authority.current_launcher_authority() is None
    for invalid in (None, "", "wrong" * 10, token + "\n", "x" * 129, {}, 1):
        assert not authority.verify_launcher_authority(invalid)


@pytest.mark.parametrize("status", ["disabled", "revoked"])
def test_disabled_or_revoked_authority_survives_host_reinitialization(profile, status):
    token = authority.ensure_launcher_authority(profile)
    _replace(profile, status=status)
    before = _path(profile).read_bytes()
    assert authority.ensure_launcher_authority(profile) is None
    assert not authority.verify_launcher_authority(token)
    assert authority.launcher_authority_fingerprint() == ""
    assert _path(profile).read_bytes() == before


def test_rotation_immediately_invalidates_previous_token_and_fingerprint(profile):
    previous = authority.ensure_launcher_authority(profile)
    replacement = "rotated_" + "a" * 43
    _replace(profile, token=replacement)
    assert not authority.verify_launcher_authority(previous)
    assert authority.verify_launcher_authority(replacement)
    assert authority.ensure_launcher_authority(profile) == replacement
    assert authority.launcher_authority_fingerprint() == hashlib.sha256(replacement.encode()).hexdigest()


def test_noncanonical_profile_cannot_create_authority(profile, tmp_path):
    other = tmp_path / "test-profile"
    assert authority.ensure_launcher_authority(other) is None
    assert not other.exists()
    assert authority.ensure_launcher_authority(profile.parent) is None
    assert not profile.exists()


def test_profile_falls_back_to_user_local_appdata(profile, tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA")
    expected = tmp_path / "user" / "AppData" / "Local" / "Vibelution" / "DesktopShell" / "assistant" / "profile"
    assert authority.ensure_launcher_authority(profile) is None
    token = authority.ensure_launcher_authority(expected)
    assert authority.verify_launcher_authority(token)


@pytest.mark.parametrize("content", [b"{}", b"[]", b"invalid", b" " * 4097,
    b'{"schemaVersion":true,"status":"enabled","token":"' + b"a" * 43 + b'"}',
    b'{"schemaVersion":1,"status":"enabled","token":"short"}',
    b'{"schemaVersion":1,"status":"enabled","token":"' + b"a" * 43 + b'","status":"disabled"}'])
def test_malformed_existing_authority_is_never_repaired_or_accepted(profile, content):
    profile.mkdir(parents=True)
    _path(profile).write_bytes(content)
    assert authority.ensure_launcher_authority(profile) is None
    assert not authority.verify_launcher_authority("a" * 43)
    assert _path(profile).read_bytes() == content


def test_hardlinked_authority_is_rejected(profile, tmp_path):
    token = authority.ensure_launcher_authority(profile)
    os.link(_path(profile), tmp_path / "alias.json")
    assert not authority.verify_launcher_authority(token)
    assert authority.ensure_launcher_authority(profile) is None


@pytest.mark.parametrize("directory", [False, True])
def test_symlinked_authority_or_profile_is_rejected(profile, tmp_path, directory):
    token = authority.ensure_launcher_authority(profile)
    if directory:
        real = profile.with_name("real-profile")
        profile.rename(real)
        link, target = profile, real
    else:
        real = tmp_path / "real-authority.json"
        _path(profile).rename(real)
        link, target = _path(profile), real
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc.errno}")
    assert not authority.verify_launcher_authority(token)
    assert authority.ensure_launcher_authority(profile) is None


def test_process_authority_is_explicit_and_does_not_read_or_change_file(profile):
    token = authority.ensure_launcher_authority(profile)
    assert authority.current_launcher_authority() is None
    authority.install_launcher_authority(token)
    assert authority.current_launcher_authority() == token
    _replace(profile, status="revoked")
    assert authority.current_launcher_authority() == token
    assert not authority.verify_launcher_authority(token)
    with pytest.raises(ValueError):
        authority.install_launcher_authority("bad\nheader")
    authority.install_launcher_authority(None)
    assert authority.current_launcher_authority() is None
