"""Operator asset reads use only synthetic config and images in temporary roots."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from core.assistant_runtime import operator_assets as assets


PNG = b"\x89PNG\r\n\x1a\nfictional-png"
JPEG = b"\xff\xd8\xfffictional-jpeg"
WEBP = b"RIFF\x10\x00\x00\x00WEBPfictional-webp"


@pytest.fixture
def operator(monkeypatch, tmp_path):
    config = tmp_path / "operator" / "config.toml"
    config.parent.mkdir()
    monkeypatch.setattr(assets.public_config, "resolve_config_path", lambda: config)
    monkeypatch.setattr(assets.avatars, "CONFIG_PATH", config)
    monkeypatch.setattr(assets.backgrounds, "CONFIG_PATH", config)
    monkeypatch.setattr(assets.avatars, "_legacy_user_avatar_dir", lambda: tmp_path / "legacy")
    monkeypatch.setattr(assets.backgrounds, "BUNDLED_THEME_BACKGROUND_DIR", tmp_path / "bundled")
    return config


def select(config, kind="avatar", filename="picture.png", *, readability="standard"):
    if kind == "avatar":
        relative = "workspace/user_avatars/" + filename if filename else ""
        text = '[user_profile]\nbio="PRIVATE-BIO"\navatar_image_path=' + json.dumps(relative)
    else:
        relative = "theme_backgrounds/" + filename if filename else ""
        text = '[ui.workbench_theme]\nbackground_image_path=' + json.dumps(relative)
        text += '\nbackground_readability=' + json.dumps(readability)
    config.write_text(text + '\n[private]\nsecret="PRIVATE-SECRET"\n', encoding="utf-8")


def image_file(config, kind="avatar", filename="picture.png", payload=PNG):
    path = config.parent / ("avatars" if kind == "avatar" else "theme_backgrounds") / filename
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(payload)
    return path


def test_revisions_detect_selection_file_and_readability_without_reading_image_bytes(operator, monkeypatch):
    select(operator, "avatar", "a.png")
    first = image_file(operator, filename="a.png")
    image_file(operator, filename="b.png", payload=PNG + b"other")
    def forbidden(*args, **kwargs):
        raise AssertionError("revision must not read image bytes")
    monkeypatch.setattr(assets, "_read_image", forbidden)
    one = assets.operator_asset_revisions()["avatar"]
    assert one and len(one) == 64
    assert assets.operator_asset_revisions()["avatar"] == one
    first.write_bytes(PNG + b"changed")
    two = assets.operator_asset_revisions()["avatar"]
    assert two != one
    select(operator, "avatar", "b.png")
    assert assets.operator_asset_revisions()["avatar"] not in {one, two}
    select(operator, "background", "wall.png", readability="soft")
    image_file(operator, "background", "wall.png")
    soft = assets.operator_asset_revisions()["background"]
    select(operator, "background", "wall.png", readability="strong")
    assert assets.operator_asset_revisions()["background"] != soft
    select(operator, "avatar", "missing.png")
    assert assets.operator_asset_revisions()["avatar"] is None
    image_file(operator, filename="missing.png")
    assert assets.operator_asset_revisions()["avatar"] is not None


def unavailable(kind="avatar"):
    with pytest.raises(ValueError, match="^operator_asset_unavailable$") as error:
        assets.read_operator_asset(kind)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("kind", ["avatar", "background"])
@pytest.mark.parametrize("filename,payload,content_type", [
    ("picture.png", PNG, "image/png"), ("picture.jpg", JPEG, "image/jpeg"),
    ("picture.jpeg", JPEG, "image/jpeg"), ("picture.webp", WEBP, "image/webp"),
])
def test_current_config_bytes_and_closed_projection(operator, kind, filename, payload, content_type):
    select(operator, kind, filename, readability="strong")
    path = image_file(operator, kind, filename, payload)
    original = operator.read_bytes()
    result = assets.read_operator_asset(kind)
    assert result == {"schemaVersion": 1, "kind": kind, "image": {
        "contentType": content_type, "dataBase64": base64.b64encode(payload).decode(),
        "sha256": hashlib.sha256(payload).hexdigest()},
        "readability": "strong" if kind == "background" else "standard"}
    encoded = json.dumps(result)
    assert not any(secret in encoded for secret in (str(operator.parent), "PRIVATE-BIO", "PRIVATE-SECRET", "root", "bio"))
    assert operator.read_bytes() == original and path.read_bytes() == payload
    # Read the current document bytes again rather than a public-config cache.
    select(operator, kind, "")
    assert assets.read_operator_asset(kind)["image"] is None


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_explicit_empty_is_read_only_without_creating_resource_dirs(operator, kind, monkeypatch):
    select(operator, kind, "")
    before = set(operator.parent.rglob("*"))
    def forbidden(*args, **kwargs):
        raise AssertionError("read attempted directory creation")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    assert assets.read_operator_asset(kind) == {
        "schemaVersion": 1, "kind": kind, "image": None, "readability": "standard"}
    assert set(operator.parent.rglob("*")) == before


def test_absent_avatar_selection_and_default_background_follow_bootstrap(operator):
    operator.write_text('[user_profile]\nbio="private"\n', encoding="utf-8")
    assert assets.read_operator_asset("avatar")["image"] is None
    bundled = assets.backgrounds.BUNDLED_THEME_BACKGROUND_DIR
    bundled.mkdir()
    (bundled / assets.backgrounds.DEFAULT_THEME_BACKGROUND_FILENAME).write_bytes(PNG)
    assert base64.b64decode(assets.read_operator_asset("background")["image"]["dataBase64"]) == PNG


def test_canonical_legacy_avatar_fallback_and_custom_background_priority(operator, monkeypatch):
    select(operator)
    legacy = assets.avatars._legacy_user_avatar_dir()
    legacy.mkdir()
    (legacy / "picture.png").write_bytes(PNG)
    assert base64.b64decode(assets.read_operator_asset("avatar")["image"]["dataBase64"]) == PNG
    filename = assets.backgrounds.DEFAULT_THEME_BACKGROUND_FILENAME
    select(operator, "background", filename)
    bundled = assets.backgrounds.BUNDLED_THEME_BACKGROUND_DIR
    bundled.mkdir()
    (bundled / filename).write_bytes(PNG)
    image_file(operator, "background", filename, payload=PNG + b"custom")
    def forbidden(*args, **kwargs):
        raise AssertionError("selected asset read attempted directory creation")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    result = assets.read_operator_asset("background")
    assert base64.b64decode(result["image"]["dataBase64"]) == PNG + b"custom"


@pytest.mark.parametrize("kind,limit", [("avatar", 5 * 1024 * 1024), ("background", 10 * 1024 * 1024)])
def test_exact_image_size_limit_and_limit_plus_one(operator, kind, limit):
    select(operator, kind)
    path = image_file(operator, kind, payload=PNG + b"x" * (limit - len(PNG)))
    assert len(base64.b64decode(assets.read_operator_asset(kind)["image"]["dataBase64"])) == limit
    with path.open("ab") as stream:
        stream.write(b"x")
    unavailable(kind)


@pytest.mark.parametrize("raw", [
    'user_profile="invalid"', '[user_profile]\navatar_image_path=3',
    '[user_profile]\navatar_image_path="https://private/picture.png"',
    '[user_profile]\navatar_image_path="workspace/user_avatars/../picture.png"',
    '[user_profile]\navatar_image_path="C:/private/picture.png"',
    '[user_profile]\navatar_image_path="workspace/user_avatars/picture.svg"', 'invalid = [',
])
def test_invalid_config_and_untrusted_selections_rejected(operator, raw):
    operator.write_text(raw, encoding="utf-8")
    unavailable()


@pytest.mark.parametrize("kind", ["avatar", "background"])
@pytest.mark.parametrize("payload", [b"", b"<svg></svg>", b"<html>private</html>", JPEG])
def test_missing_empty_or_disguised_images_rejected(operator, kind, payload):
    select(operator, kind)
    unavailable(kind)
    image_file(operator, kind, payload=payload)
    unavailable(kind)


def test_missing_config_read_does_not_initialize(operator):
    unavailable()
    assert not operator.exists()
    assert not list(operator.parent.iterdir())


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_hard_link_image_rejected(operator, kind):
    select(operator, kind)
    path = image_file(operator, kind)
    os.link(path, operator.parent / "second-link.png")
    unavailable(kind)


def test_hard_link_config_rejected(operator):
    select(operator, filename="")
    os.link(operator, operator.parent / "second-config.toml")
    unavailable()


def test_symbolic_link_config_rejected_before_read(operator, monkeypatch):
    select(operator, filename="")
    alias = operator.with_name("linked-config.toml")
    try:
        alias.symlink_to(operator)
    except OSError:
        pytest.skip("symbolic links unavailable")
    monkeypatch.setattr(assets.public_config, "resolve_config_path", lambda: alias)
    monkeypatch.setattr(assets.avatars, "CONFIG_PATH", alias)
    unavailable()


@pytest.mark.parametrize("link_directory", [False, True])
def test_symbolic_link_image_or_ancestor_rejected(operator, link_directory):
    select(operator)
    outside = operator.parent.parent / "outside"
    outside.mkdir()
    (outside / "picture.png").write_bytes(PNG)
    target = operator.parent / "avatars"
    try:
        if link_directory:
            target.symlink_to(outside, target_is_directory=True)
        else:
            target.mkdir()
            (target / "picture.png").symlink_to(outside / "picture.png")
    except OSError as error:
        pytest.skip("symbolic links unavailable: " + str(error.winerror if hasattr(error, "winerror") else error.errno))
    unavailable()


def test_config_owner_mismatch_rejected_even_with_empty_selection(operator, monkeypatch):
    select(operator, filename="")
    other = operator.with_name("other-config.toml")
    other.write_bytes(operator.read_bytes())
    monkeypatch.setattr(assets.avatars, "CONFIG_PATH", other)
    unavailable()


def test_selection_change_during_image_read_rejected(operator, monkeypatch):
    select(operator)
    image_file(operator)
    original = assets._read_image
    def changed(*args):
        result = original(*args)
        select(operator, filename="")
        return result
    monkeypatch.setattr(assets, "_read_image", changed)
    unavailable()


@pytest.mark.parametrize("change", ["readability", "malformed", "missing"])
def test_current_config_change_during_read_rejected(operator, monkeypatch, change):
    select(operator, "background")
    image_file(operator, "background")
    original = assets._read_image
    def changed(*args):
        result = original(*args)
        if change == "readability":
            select(operator, "background", readability="strong")
        elif change == "malformed":
            operator.write_text("invalid = [", encoding="utf-8")
        else:
            operator.unlink()
        return result
    monkeypatch.setattr(assets, "_read_image", changed)
    unavailable("background")


def test_opened_file_identity_mismatch_rejected(operator, monkeypatch):
    from types import SimpleNamespace
    select(operator)
    image_file(operator)
    original = os.fstat
    def different_identity(fd):
        info = original(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink,
            st_dev=info.st_dev, st_ino=info.st_ino + 1, st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)
    # Config reads use fstat too, so install only when the image reader begins.
    original_read = assets._read_image
    def read(*args):
        with monkeypatch.context() as patch:
            patch.setattr(os, "fstat", different_identity)
            return original_read(*args)
    monkeypatch.setattr(assets, "_read_image", read)
    unavailable()


@pytest.mark.parametrize("raw", [
    'ui="invalid"', '[ui]\nworkbench_theme="invalid"',
    '[ui.workbench_theme]\nbackground_image_path=3',
    '[ui.workbench_theme]\nbackground_image_path=""\nbackground_readability=3',
])
def test_malformed_background_config_rejected(operator, raw):
    operator.write_text(raw, encoding="utf-8")
    unavailable("background")


@pytest.mark.parametrize("readability,expected", [("soft", "soft"), (" STRONG ", "strong"),
    ("", "standard"), ("unrecognized", "standard")])
def test_background_readability_matches_canonical_normalization(operator, readability, expected):
    select(operator, "background", "", readability=readability)
    assert assets.read_operator_asset("background")["readability"] == expected


def test_replaced_or_modified_file_during_read_rejected(operator, monkeypatch):
    select(operator)
    path = image_file(operator)
    original = Path.open
    class ChangingReader:
        def __enter__(self):
            self.stream = original(path, "rb")
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, size):
            assert size == assets.avatars.MAX_USER_AVATAR_IMAGE_BYTES + 1
            data = self.stream.read(size)
            with original(path, "ab") as writer:
                writer.write(b"changed")
            return data
    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs:
        ChangingReader() if self == path and args == ("rb",) else original(self, *args, **kwargs))
    unavailable()


@pytest.mark.parametrize("kind", ["url", "path", "", None])
def test_only_fixed_resource_kinds_allowed(operator, kind):
    unavailable(kind)
