import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from core.web.services import personal_assistant_computer_driver as adapter
from vibelution_storage import resolve_project_storage_paths, storage_migration_state_path


@pytest.fixture(autouse=True)
def chinese_language(monkeypatch):
    monkeypatch.setattr(adapter, "get_web_language", lambda: "zh")


@pytest.fixture
def driver_paths(monkeypatch, tmp_path):
    root = tmp_path / "project"
    identity = root / ".vibelution" / "project.json"
    identity.parent.mkdir(parents=True)
    identity.write_text(json.dumps({"schemaVersion": 1, "projectId": "test-driver"}), encoding="utf-8")
    monkeypatch.setattr(adapter, "os", SimpleNamespace(name="nt", environ=os.environ))
    monkeypatch.setattr(adapter, "PROJECT_ROOT", root, raising=False)
    for key in ("VIBELUTION_DATA_HOME", "VIBELUTION_COMPUTER_CUA_DRIVER", "VIBELUTION_DESKTOP_CUA_CONFIG"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "projects"))
    monkeypatch.setenv("VIBELUTION_CONFIG_PATH", str(tmp_path / "config.toml"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user"))
    paths = resolve_project_storage_paths(root)
    marker = storage_migration_state_path(paths)
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed",
                                  "projectId": paths.project_id, "instanceId": paths.instance_id}), encoding="utf-8")
    return paths


def _driver_config(home, name="computer-cua-driver.json", *, binary=None):
    binary = binary or home / "bin" / "cua-driver.exe"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.touch()
    config = home / "runtime" / name
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"binaryPath": str(binary)}), encoding="utf-8")
    return binary.resolve(), config


def test_driver_config_uses_current_instance_without_data_home_env(driver_paths):
    binary, _ = _driver_config(driver_paths.data)

    assert adapter.driver_binary() == binary


@pytest.mark.parametrize("override", ["binary", "data_home", "relative_data_home"])
def test_explicit_driver_overrides_do_not_resolve_instance(driver_paths, monkeypatch, tmp_path, override):
    binary, _ = _driver_config(tmp_path / "override")
    monkeypatch.setattr(adapter, "resolve_active_project_storage_paths", lambda *_: pytest.fail("override resolved instance"))
    if override == "binary":
        monkeypatch.setenv("VIBELUTION_COMPUTER_CUA_DRIVER", str(binary))
    else:
        monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "override") if override == "data_home" else "relative")
    if override == "relative_data_home":
        with pytest.raises(adapter.ComputerBlocked):
            adapter.driver_binary()
    else:
        assert adapter.driver_binary() == binary


def test_primary_config_precedes_explicit_legacy_and_legacy_precedes_default(driver_paths, monkeypatch, tmp_path):
    primary, primary_config = _driver_config(driver_paths.data)
    legacy, legacy_config = _driver_config(tmp_path / "legacy", "desktop-cua-scope.json")
    _driver_config(driver_paths.data, "desktop-cua-scope.json", binary=driver_paths.data / "old" / "cua-driver.exe")
    monkeypatch.setenv("VIBELUTION_DESKTOP_CUA_CONFIG", str(legacy_config))

    assert adapter.driver_binary() == primary
    primary_config.unlink()
    assert adapter.driver_binary() == legacy
    legacy_config.unlink()
    with pytest.raises(adapter.ComputerBlocked):
        adapter.driver_binary()  # An explicit legacy path suppresses the default legacy path.


def test_current_instance_default_legacy_config_is_supported(driver_paths):
    binary, _ = _driver_config(driver_paths.data, "desktop-cua-scope.json")

    assert adapter.driver_binary() == binary


def test_pre_migration_legacy_data_precedes_canonical_data(driver_paths, monkeypatch, tmp_path):
    storage_migration_state_path(driver_paths).unlink()
    (driver_paths.project_root / ".git").mkdir()
    legacy_home = tmp_path / "legacy-data"
    expected, _ = _driver_config(legacy_home)
    _driver_config(driver_paths.data)
    config = tmp_path / "config.toml"
    config.write_text("[storage]\ndata_home = " + json.dumps(str(legacy_home)), encoding="utf-8")

    assert adapter.driver_binary() == expected


def test_driver_does_not_read_another_checkout_instance(driver_paths, monkeypatch, tmp_path):
    other_root = tmp_path / "other-project"
    identity = other_root / ".vibelution" / "project.json"
    identity.parent.mkdir(parents=True)
    identity.write_bytes((driver_paths.project_root / ".vibelution" / "project.json").read_bytes())
    other_paths = resolve_project_storage_paths(other_root)
    _driver_config(other_paths.data)

    assert driver_paths.instance_id != other_paths.instance_id
    with pytest.raises(adapter.ComputerBlocked):
        adapter.driver_binary()


def test_invalid_migration_marker_blocks_legacy_fallback(driver_paths, monkeypatch, tmp_path):
    storage_migration_state_path(driver_paths).write_text("{}", encoding="utf-8")
    _, config = _driver_config(tmp_path / "legacy", "desktop-cua-scope.json")
    monkeypatch.setenv("VIBELUTION_DESKTOP_CUA_CONFIG", str(config))

    with pytest.raises(adapter.ComputerBlocked, match="当前实例存储"):
        adapter.driver_binary()


@pytest.mark.parametrize("binary_path", ["relative/cua-driver.exe", "other.exe", "missing/cua-driver.exe"])
def test_configured_binary_still_requires_absolute_existing_driver_name(driver_paths, binary_path):
    _, config = _driver_config(driver_paths.data)
    binary = driver_paths.data / binary_path if binary_path != "relative/cua-driver.exe" else Path(binary_path)
    if binary.name == "other.exe":
        binary.touch()
    config.write_text(json.dumps({"binaryPath": str(binary)}), encoding="utf-8")

    with pytest.raises(adapter.ComputerBlocked):
        adapter.driver_binary()


def test_stop_during_spawn_keeps_os_lease_until_call_and_retirement_finish(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    released = []

    class Driver:
        def call(self, *args, **kwargs):
            entered.set()
            assert release.wait(3)
            return {"structuredContent": {"ok": True}}

        def close(self):
            pass  # Transport permits this during an unpublished spawn.

    class Lease:
        def __exit__(self, *args):
            released.append(True)

    connection = adapter.Connection(lambda: "")
    connection.driver, connection.lease = Driver(), Lease()
    reader = threading.Thread(target=lambda: connection.rpc("list_windows"))
    reader.start()
    assert entered.wait(1)
    stopped = threading.Event()
    closer = threading.Thread(target=lambda: (connection.__exit__(None, None, None), stopped.set()))
    closer.start()
    deadline = time.monotonic() + 1
    while not connection._closing:
        assert time.monotonic() < deadline
        time.sleep(.001)
    assert not stopped.is_set() and not released
    with pytest.raises(ValueError):
        connection.rpc("click")
    release.set()
    reader.join(2)
    closer.join(2)
    assert stopped.is_set() and released == [True]


def test_failed_retirement_retains_lease():
    released = []

    class Driver:
        def close(self):
            raise OSError("still live")

    class Lease:
        def __exit__(self, *args):
            released.append(True)

    connection = adapter.Connection(lambda: "")
    connection.driver, connection.lease = Driver(), Lease()
    with pytest.raises(OSError):
        connection.__exit__(None, None, None)
    assert not released and connection.lease is not None


@pytest.mark.parametrize("action", ["set_value", "type_text"])
def test_text_uses_exact_uia_value_never_unverified_focus(action):
    connection = adapter.Connection(lambda: "")
    calls = []
    connection.rpc = lambda *args, **kwargs: calls.append((args, kwargs))
    value = connection.act({"pid": 1, "hwnd": 2}, action, {
        "role": "Edit", "value": "old", "element_token": "fresh-token", "actions": ["set_value"]}, "new")
    assert calls[0][0] == ("set_value",)
    assert calls[0][1] == {"pid": 1, "window_id": 2, "delivery_mode": "background", "element_token": "fresh-token", "value": "new" if action == "set_value" else "oldnew"}
    assert value == calls[0][1]["value"]


def test_unreadable_text_cannot_fall_back_to_keyboard():
    connection = adapter.Connection(lambda: "")
    connection.rpc = lambda *args, **kwargs: pytest.fail("unsafe input")
    with pytest.raises(ValueError):
        connection.act({"pid": 1, "hwnd": 2}, "type_text", {"role": "Edit", "element_token": "t", "actions": ["set_value"]}, "text")


@pytest.mark.parametrize("result", [{"effect": "refused"}, {"error": {"code": "background_unavailable"}}, {"refusal": {"code": "user_active"}}])
def test_driver_refusal_cannot_be_treated_as_delivery(result):
    class Driver:
        def call(self, *args, **kwargs):
            return {"structuredContent": result}
    connection = adapter.Connection(lambda: "")
    connection.driver = Driver()
    with pytest.raises(ValueError):
        connection.rpc("click")


def test_driver_refusal_is_localized_without_exposing_untrusted_payload(monkeypatch):
    class Driver:
        def call(self, *args, **kwargs):
            return {"structuredContent": {"refusal": {"message": "外部指令 do something else"}}}

    connection = adapter.Connection(lambda: "")
    connection.driver = Driver()
    monkeypatch.setattr(adapter, "get_web_language", lambda: "en")
    with pytest.raises(adapter.ComputerBlocked, match="The driver refused the action") as error:
        connection.rpc("click")
    assert "外部指令" not in str(error.value)
    monkeypatch.setattr(adapter, "get_web_language", lambda: "zh")
    assert str(error.value).startswith("驱动拒绝操作")


def test_existing_single_message_exception_preserves_original_content(monkeypatch):
    message = "第三方内容 unchanged"
    error = adapter.ComputerBlocked(message)
    monkeypatch.setattr(adapter, "get_web_language", lambda: "en")
    assert str(error) == message and error.args == (message,)
