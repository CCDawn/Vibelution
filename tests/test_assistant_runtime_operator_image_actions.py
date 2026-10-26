"""Operator image actions run against isolated temporary config and resources."""

import base64
import json
import os
from pathlib import Path
import tomllib

import pytest

from core.assistant_runtime import local_actions, operator_image_actions as actions
from tools import pa_settings_actions as settings


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=")


@pytest.fixture
def operator(tmp_path, monkeypatch):
    from config import operator_config_transaction as transaction, public_config

    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    fixture = Path(__file__).parent / "fixtures/config/llm_schema_v2_provider.toml"
    path.write_text(fixture.read_text(encoding="utf-8") + '''
[user_profile]
display_name = "Temp Operator"
avatar_preset = "spark"
avatar_image_path = ""

[ui.workbench_theme]
background_image_path = ""
background_readability = "standard"
''', encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(path))
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(public_config, "CONFIG_PATH", path)
    monkeypatch.setattr(public_config, "resolve_config_path", lambda: path)
    monkeypatch.setattr(transaction, "CONFIG_PATH", path)
    monkeypatch.setattr(transaction, "reload_config", lambda *_: None)
    monkeypatch.setattr(settings, "_config_path", lambda: path)
    monkeypatch.setattr(actions.assets.avatars, "CONFIG_PATH", path)
    monkeypatch.setattr(actions.assets.backgrounds, "CONFIG_PATH", path)
    monkeypatch.setattr(actions.assets.backgrounds, "BUNDLED_THEME_BACKGROUND_DIR", tmp_path / "bundled")
    def forbidden_legacy():
        pytest.fail("image actions must never consult formal legacy data")
    monkeypatch.setattr(actions.assets.avatars, "_legacy_user_avatar_dir", forbidden_legacy)
    for owner in (actions.assets.avatars, actions.assets.backgrounds):
        monkeypatch.setattr(owner, "record_runtime_scene_event", lambda *a, **kw: None)
    return path


def resource(operator, kind="avatar", filename="sample.png", data=PNG):
    root = operator.parent / ("avatars" if kind == "avatar" else "theme_backgrounds")
    root.mkdir(exist_ok=True)
    image = root / filename
    image.write_bytes(data)
    prefix = "workspace/user_avatars/" if kind == "avatar" else "theme_backgrounds/"
    return prefix + filename, image


def run(action="select", **parameters):
    return local_actions.execute("operator_image_" + action, parameters, {"agentId": "native-assistant"})


def read(operator):
    return tomllib.loads(operator.read_text(encoding="utf-8"))


def success(kind, selection):
    return {"ok": True, "status": "applied", "verified": True, "kind": kind, "selection": selection}


def test_image_actions_are_closed_ordinary_local_actions():
    contracts = local_actions.contracts()
    for name in ("operator_image_options", "operator_image_select"):
        assert name in contracts
        assert contracts[name]["governed"] is False
        assert contracts[name]["parameters"]["additionalProperties"] is False
    assert "预设头像" in contracts["operator_image_select"]["description"]
    assert "import_operator_image" not in contracts


@pytest.mark.parametrize("action,parameters", [
    ("options", {"kind": "avatar", "offset": True}),
    ("options", {"kind": "avatar", "offset": -1}),
    ("options", {"kind": "avatar", "offset": 10001}),
    ("options", {"kind": "avatar", "limit": 0}),
    ("options", {"kind": "avatar", "limit": 13}),
    ("options", {"kind": "avatar", "limit": "6"}),
    ("options", {"kind": "other"}),
    ("options", {"kind": "avatar", "root": "private"}),
    ("select", {"kind": "avatar", "path": None}),
    ("select", {"kind": "avatar", "path": 1}),
    ("select", {"kind": "avatar", "path": "x" * 241}),
    ("select", {"kind": "avatar", "path": "", "governed": True}),
])
def test_closed_strict_invalid_input_never_writes(operator, action, parameters):
    before = operator.read_bytes()
    assert run(action, **parameters)["error"] == "invalid_input"
    assert operator.read_bytes() == before


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_paginated_options_are_logical_safe_bounded_paths(operator, kind):
    valid = [resource(operator, kind, f"image-{i:02}.png")[0] for i in range(15)]
    resource(operator, kind, "broken.png", b"private invalid image")
    resource(operator, kind, "ignored.txt")
    first = run("options", kind=kind)
    assert first == {"ok": True, "kind": kind, "options": valid[:6], "total": 15, "nextOffset": 6}
    assert run("options", kind=kind, offset=6, limit=12)["options"] == valid[6:]
    assert run("options", kind=kind, offset=10000)["nextOffset"] is None
    assert str(operator.parent) not in json.dumps(first)


def test_options_reads_only_signature_and_rejects_oversized_directory(operator, monkeypatch):
    resource(operator)
    monkeypatch.setattr(actions.assets, "_read_image", lambda *_: pytest.fail("options read full image"))
    original_open = Path.open
    reads = []
    class HeaderReader:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, size=-1):
            reads.append(size)
            assert size == 12
            return self.stream.read(size)
    def bounded_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return HeaderReader(stream) if path.suffix == ".png" else stream
    monkeypatch.setattr(Path, "open", bounded_open)
    assert len(run("options", kind="avatar")["options"]) == 1
    assert reads == [12]
    root = operator.parent / "avatars"
    for i in range(1000):
        (root / f"item-{i}.txt").touch()
    assert not run("options", kind="avatar")["ok"]


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_select_switch_clear_and_idempotence_use_only_canonical_config_writer(operator, monkeypatch, kind):
    before = read(operator)
    one, _ = resource(operator, kind, "one.png")
    two, _ = resource(operator, kind, "two.png")
    original = settings._transaction
    writes = []
    def transaction(*args):
        writes.append(args[3])
        return original(*args)
    monkeypatch.setattr(settings, "_transaction", transaction)
    assert run(kind=kind, path=one) == success(kind, one)
    unchanged = operator.read_bytes()
    assert run(kind=kind, path=one) == success(kind, one)
    assert operator.read_bytes() == unchanged and len(writes) == 1
    assert run(kind=kind, path=two) == success(kind, two)
    assert run(kind=kind, path="") == success(kind, "")
    assert writes == ["pa_operator_image_select"] * 3
    assert read(operator) == before


@pytest.mark.parametrize("kind,value", [
    ("avatar", "C:/private.png"), ("avatar", "https://example.test/image.png"),
    ("avatar", "workspace/user_avatars/../image.png"), ("avatar", "workspace/user_avatars/missing.png"),
    ("avatar", "workspace/user_avatars\\image.png"), ("background", "theme_backgrounds/missing.png"),
    ("background", "theme_backgrounds/nested/image.png"), ("background", "file:///private.png"),
])
def test_invalid_or_unavailable_selection_does_not_write_or_use_legacy(operator, kind, value):
    before = operator.read_bytes()
    result = run(kind=kind, path=value)
    assert not result["ok"] and result["status"] == "not_applied"
    assert operator.read_bytes() == before
    assert value not in json.dumps(result)


def test_only_registered_bundled_backgrounds_can_be_selected(operator):
    owner = actions.assets.backgrounds
    owner.BUNDLED_THEME_BACKGROUND_DIR.mkdir()
    (owner.BUNDLED_THEME_BACKGROUND_DIR / owner.DEFAULT_THEME_BACKGROUND_FILENAME).write_bytes(PNG)
    (owner.BUNDLED_THEME_BACKGROUND_DIR / "unregistered.png").write_bytes(PNG)
    assert run(kind="background", path=owner.DEFAULT_THEME_BACKGROUND_PATH) == success("background", owner.DEFAULT_THEME_BACKGROUND_PATH)
    assert not run(kind="background", path="theme_backgrounds/unregistered.png")["ok"]


@pytest.mark.parametrize("kind", ["avatar", "background"])
@pytest.mark.parametrize("bad", ["signature", "empty", "hardlink", "symlink", "oversize", "directory"])
def test_unsafe_images_are_never_candidates_or_selected(operator, kind, bad):
    logical, path = resource(operator, kind)
    if bad == "signature":
        path.write_bytes(b"\xff\xd8\xffwrong-type")
    elif bad == "empty":
        path.write_bytes(b"")
    elif bad == "hardlink":
        os.link(path, operator.parent / "hardlink.png")
    elif bad == "symlink":
        path.unlink()
        outside = operator.parent / "outside.png"
        outside.write_bytes(PNG)
        try:
            path.symlink_to(outside)
        except OSError:
            pytest.skip("symlink creation unavailable")
    elif bad == "oversize":
        limit = 5 * 1024 * 1024 if kind == "avatar" else 10 * 1024 * 1024
        path.write_bytes(PNG + b"x" * limit)
    else:
        path.unlink()
        path.mkdir()
    before = operator.read_bytes()
    assert not run(kind=kind, path=logical)["ok"]
    assert run("options", kind=kind)["options"] == []
    assert operator.read_bytes() == before


def test_linked_resource_ancestor_and_owner_config_mismatch_rejected(operator, monkeypatch):
    real = operator.parent / "real"
    real.mkdir()
    (real / "sample.png").write_bytes(PNG)
    root = operator.parent / "avatars"
    try:
        root.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert not run(kind="avatar", path="workspace/user_avatars/sample.png")["ok"]
    monkeypatch.setattr(actions.assets.avatars, "CONFIG_PATH", operator.parent / "other.toml")
    assert not run(kind="avatar", path="")["ok"]


def test_hardlinked_and_linked_config_cannot_be_written(operator, monkeypatch):
    before = operator.read_bytes()
    alias = operator.with_name("hardlink.toml")
    os.link(operator, alias)
    assert not run(kind="avatar", path="")["ok"]
    assert operator.read_bytes() == before
    alias.unlink()
    alias = operator.with_name("symlink.toml")
    try:
        alias.symlink_to(operator)
    except OSError:
        pytest.skip("symlink creation unavailable")
    monkeypatch.setattr(actions.assets.public_config, "resolve_config_path", lambda: alias)
    monkeypatch.setattr(actions.assets.avatars, "CONFIG_PATH", alias)
    assert not run(kind="avatar", path="")["ok"]
    assert operator.read_bytes() == before


@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_real_upload_stores_temp_image_then_applies_one_transaction(operator, monkeypatch, kind):
    before = read(operator)
    writes = []
    original = settings._transaction
    def transaction(*args):
        writes.append(args[3])
        return original(*args)
    monkeypatch.setattr(settings, "_transaction", transaction)
    result = actions.import_operator_image(kind, "临时头像.png", "image/png", base64.b64encode(PNG).decode())
    assert result == success(kind, result["selection"])
    root = operator.parent / ("avatars" if kind == "avatar" else "theme_backgrounds")
    assert (root / result["selection"].split("/")[-1]).read_bytes() == PNG
    assert writes == ["pa_operator_image_select"]
    after = read(operator)
    assert after["llm"] == before["llm"] and after["user_profile"]["avatar_preset"] == "spark"
    assert "dataBase64" not in json.dumps(result) and str(operator) not in json.dumps(result)


def test_upload_does_not_put_bytes_filename_or_path_into_owner_events(operator, monkeypatch):
    events = []
    monkeypatch.setattr(actions.assets.avatars, "record_runtime_scene_event", lambda *a, **kw: events.append((a, kw)))
    encoded = base64.b64encode(PNG).decode()
    result = actions.import_operator_image("avatar", "private-filename.png", "image/png", encoded)
    assert result["ok"] and events
    logged = json.dumps(events)
    assert encoded not in logged and "private-filename" not in logged and str(operator.parent) not in logged


def test_upload_rejects_linked_target_directory_before_owner_store(operator, monkeypatch):
    outside = operator.parent / "outside"
    outside.mkdir()
    try:
        (operator.parent / "avatars").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    monkeypatch.setattr(actions.assets.avatars, "store_user_avatar_image", lambda **_: pytest.fail("linked root reached store"))
    result = actions.import_operator_image("avatar", "image.png", "image/png", base64.b64encode(PNG).decode())
    assert not result["ok"] and not list(outside.iterdir())


@pytest.mark.parametrize("updates", [
    {"kind": "other"}, {"kind": []}, {"filename": "../x.png"}, {"filename": "C:\\secret.png"},
    {"filename": ""}, {"filename": "x\n.png"}, {"content_type": "image/svg+xml"},
    {"content_type": "image/png; charset=utf8"}, {"data_base64": "not base64"},
    {"data_base64": ""}, {"data_base64": base64.b64encode(b"private-invalid").decode()},
    {"data_base64": None},
])
def test_upload_validates_all_parameters_before_store(operator, monkeypatch, updates):
    params = {"kind": "avatar", "filename": "image.png", "content_type": "image/png", "data_base64": base64.b64encode(PNG).decode()}
    params.update(updates)
    monkeypatch.setattr(actions.assets.avatars, "store_user_avatar_image", lambda **_: pytest.fail("invalid upload reached store"))
    before = operator.read_bytes()
    result = actions.import_operator_image(**params)
    assert not result["ok"] and result["status"] == "not_applied"
    assert operator.read_bytes() == before
    assert "private-invalid" not in json.dumps(result)


@pytest.mark.parametrize("kind,limit", [("avatar", 5 * 1024 * 1024), ("background", 10 * 1024 * 1024)])
def test_upload_checks_encoded_length_before_decode_and_decoded_limit(operator, monkeypatch, kind, limit):
    original = actions.base64.b64decode
    monkeypatch.setattr(actions.base64, "b64decode", lambda *_a, **_k: pytest.fail("oversize reached decoder"))
    assert actions.import_operator_image(kind, "image.png", "image/png", "A" * (4 * ((limit + 2) // 3) + 1))["error"] == "invalid_input"
    monkeypatch.setattr(actions.base64, "b64decode", original)
    payload = PNG + b"x" * (limit + 1 - len(PNG))
    assert not actions.import_operator_image(kind, "image.png", "image/png", base64.b64encode(payload).decode())["ok"]


@pytest.mark.parametrize("kind,limit", [("avatar", 5 * 1024 * 1024), ("background", 10 * 1024 * 1024)])
def test_upload_accepts_exact_owner_size_limit(operator, kind, limit):
    payload = PNG + b"x" * (limit - len(PNG))
    result = actions.import_operator_image(kind, "limit.png", "image/png", base64.b64encode(payload).decode())
    assert result["ok"]


@pytest.mark.parametrize("content_type,filename,payload", [
    ("image/jpeg", "photo.jpeg", b"\xff\xd8\xffjpeg-fixture"),
    ("image/webp", "photo.webp", b"RIFF\x10\x00\x00\x00WEBPwebp-fixture"),
])
def test_upload_accepts_other_owner_image_formats(operator, content_type, filename, payload):
    result = actions.import_operator_image("avatar", filename, content_type, base64.b64encode(payload).decode())
    assert result["ok"]
    assert run("options", kind="avatar")["options"] == [result["selection"]]


def test_upload_conflict_retains_legal_resource_and_peer_edit_without_retry(operator, monkeypatch):
    from config import operator_config_transaction as transaction

    original = transaction.apply_operator_config_transaction
    calls = []
    def concurrent(prepared):
        text = operator.read_text(encoding="utf-8").replace("Temp Operator", "Peer edit")
        operator.write_text(text, encoding="utf-8")
        calls.append(text)
        return original(prepared)
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", concurrent)
    result = actions.import_operator_image("avatar", "test.png", "image/png", base64.b64encode(PNG).decode())
    assert result == {"ok": False, "status": "not_applied", "verified": False, "error": "config_conflict"}
    assert len(calls) == 1 and operator.read_text(encoding="utf-8") == calls[0]
    assert len(list((operator.parent / "avatars").iterdir())) == 1
    assert read(operator)["user_profile"]["avatar_image_path"] == ""


def test_write_failure_and_failed_verification_never_echo_errors_or_success(operator, monkeypatch):
    from config import operator_config_transaction as transaction

    logical, _ = resource(operator)
    def failure(*_):
        raise RuntimeError("secret /private/config.toml")
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", failure)
    result = run(kind="avatar", path=logical)
    assert result["status"] == "unknown" and "secret" not in json.dumps(result)
    monkeypatch.setattr(transaction, "apply_operator_config_transaction", lambda _: None)
    assert not run(kind="avatar", path=logical)["ok"]


def test_post_write_concurrent_selection_change_does_not_report_success(operator, monkeypatch):
    logical, _ = resource(operator)
    original = settings._select_operator_image
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        text = operator.read_text(encoding="utf-8").replace(logical, "")
        operator.write_text(text, encoding="utf-8")
        return result
    monkeypatch.setattr(settings, "_select_operator_image", changed)
    result = run(kind="avatar", path=logical)
    assert not result["ok"] and result["status"] == "unknown"


def test_legacy_settings_whitelist_still_rejects_custom_avatar(operator):
    before = operator.read_bytes()
    assert not settings.settings_update([{"section": "user_profile", "key": "avatar_image_path", "value": ""}])["ok"]
    assert operator.read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace-pinning contract")
def test_windows_directory_lock_probe_allows_children_and_blocks_rename(tmp_path):
    from core.web.services.personal_assistant_project.windows_read import lock_source_directory

    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "resources"
    with lock_source_directory(parent, parent):
        root.mkdir()
        with lock_source_directory(parent, root):
            child = root / "created.png"
            with child.open("xb") as stream:
                stream.write(PNG)
            assert child.read_bytes() == PNG
            with pytest.raises(OSError):
                root.rename(parent / "renamed-resources")
            with pytest.raises(OSError):
                parent.rename(tmp_path / "renamed-parent")
    root.rename(parent / "after-release")


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace-pinning contract")
@pytest.mark.parametrize("kind", ["avatar", "background"])
@pytest.mark.parametrize("attack", ["root", "parent"])
def test_upload_pins_directories_against_postcheck_redirect(operator, monkeypatch, kind, attack):
    owner = actions.assets.avatars if kind == "avatar" else actions.assets.backgrounds
    root = operator.parent / ("avatars" if kind == "avatar" else "theme_backgrounds")
    foreign = operator.parent.parent / "foreign"
    foreign.mkdir()
    blocked = []
    target = root if attack == "root" else operator.parent
    moved = target.with_name(target.name + "-moved")

    def redirect():
        try:
            target.rename(moved)
        except OSError:
            blocked.append(True)
        else:
            target.symlink_to(foreign, target_is_directory=True)

    if attack == "root":
        root.mkdir()
        name = "store_user_avatar_image" if kind == "avatar" else "store_theme_background_image"
        original = getattr(owner, name)
        def attack_store(**kwargs):
            redirect()
            return original(**kwargs)
        monkeypatch.setattr(owner, name, attack_store)
    else:
        original = Path.mkdir
        def attack_mkdir(path, *args, **kwargs):
            if path == root and not blocked:
                redirect()
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "mkdir", attack_mkdir)

    result = actions.import_operator_image(kind, "photo.png", "image/png", base64.b64encode(PNG).decode())
    assert blocked == [True], "postcheck namespace replacement was not blocked"
    assert result["ok"], result
    assert not list(foreign.iterdir()), "redirect wrote to another Temp directory"


@pytest.mark.parametrize("kind", ["avatar", "background"])
@pytest.mark.parametrize("hardlink", [False, True])
def test_canonical_store_random_collision_never_overwrites_existing_resource(operator, monkeypatch, kind, hardlink):
    owner = actions.assets.avatars if kind == "avatar" else actions.assets.backgrounds
    monkeypatch.setattr(owner.time, "time", lambda: 1234)
    monkeypatch.setattr(owner.secrets, "token_hex", lambda _: "cafe1234")
    prefix = "avatar" if kind == "avatar" else "background"
    _, existing = resource(operator, kind, f"{prefix}-1234-cafe1234-photo.png", PNG + b"original")
    foreign = operator.parent / "foreign.png"
    if hardlink:
        os.link(existing, foreign)
    before = existing.read_bytes()
    store = owner.store_user_avatar_image if kind == "avatar" else owner.store_theme_background_image
    with pytest.raises(FileExistsError):
        store(filename="photo.png", content_type="image/png", data_base64=base64.b64encode(PNG).decode())
    assert existing.read_bytes() == before
    if hardlink:
        assert foreign.read_bytes() == before


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace-pinning contract")
@pytest.mark.parametrize("kind", ["avatar", "background"])
def test_upload_transaction_completes_under_directory_lease(operator, monkeypatch, kind):
    import traceback
    from config import operator_config_transaction as transaction

    diagnostics = []
    root = operator.parent / ("avatars" if kind == "avatar" else "theme_backgrounds")
    def assert_pinned():
        for target in (operator.parent, root):
            with pytest.raises(OSError):
                target.rename(target.with_name(target.name + "-during-transaction"))

    original_context = actions._context
    context_calls = []
    def checked_context(*args):
        if context_calls:
            assert_pinned()
        context_calls.append(True)
        return original_context(*args)
    monkeypatch.setattr(actions, "_context", checked_context)
    original = settings._transaction_failure
    def record(exc):
        diagnostics.append({"type": type(exc).__name__, "errno": getattr(exc, "errno", None),
                            "winerror": getattr(exc, "winerror", None),
                            "message": str(exc).replace(str(operator.parent.parent), "<TEMP>")[:400],
                            "frames": [(Path(frame.filename).name, frame.name, frame.lineno)
                                       for frame in traceback.extract_tb(exc.__traceback__)[-8:]]})
    def capture(exc):
        record(exc)
        return original(exc)
    monkeypatch.setattr(settings, "_transaction_failure", capture)
    for name in ("_strict_atomic_write", "load_public_config", "build_effective_config"):
        original_operation = getattr(transaction, name)
        def checked(*args, _original=original_operation, _name=name, **kwargs):
            try:
                if _name == "_strict_atomic_write" and args[0] == operator:
                    assert_pinned()
                return _original(*args, **kwargs)
            except Exception as exc:
                record(exc)
                raise
        monkeypatch.setattr(transaction, name, checked)
    result = actions.import_operator_image(kind, "photo.png", "image/png", base64.b64encode(PNG).decode())
    assert result["ok"], json.dumps(diagnostics)
    assert len(context_calls) == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace-pinning contract")
@pytest.mark.parametrize("lease", ["parent", "both"])
@pytest.mark.parametrize("share_write", [False, True])
def test_windows_directory_lease_atomic_child_replace_probe(tmp_path, lease, share_write):
    from contextlib import ExitStack
    from core.web.services.personal_assistant_project import windows_read

    lock_source_directory = windows_read.lock_source_directory

    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "resources"
    root.mkdir()
    config = parent / "config.toml"
    config.write_bytes(b"before")
    candidate = parent / "candidate.tmp"
    with ExitStack() as stack:
        stack.enter_context(lock_source_directory(parent, parent, allow_child_replacement=share_write))
        if lease == "both":
            stack.enter_context(lock_source_directory(parent, root, allow_child_replacement=share_write))
        candidate.write_bytes(b"after")
        if share_write:
            os.replace(candidate, config)
            assert config.read_bytes() == b"after"
        else:
            with pytest.raises(OSError):
                os.replace(candidate, config)
        with pytest.raises(OSError):
            parent.rename(tmp_path / "parent-renamed")
        if lease == "both":
            with pytest.raises(OSError):
                root.rename(parent / "root-renamed")
