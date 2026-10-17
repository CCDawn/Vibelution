"""Desktop automation fails closed around identity, freshness and real effects."""
import json
from pathlib import Path

import pytest

from core.web.services import personal_assistant_desktop_service as service


OWNER = ("assistant", "direct-session", "turn-1")


class Driver:
    def __init__(self, path, **kwargs):
        self.calls = []
        self.closed = False
        self.value = "before"
        self.title = "vibelution-cua-test.txt - Notepad"
        self.on_action = None
        self.ignore_input = False

    def call(self, name, arguments, *, cancel_checker=None):
        self.calls.append((name, arguments))
        if name == "list_windows":
            result = {"windows": [{"pid": 42, "window_id": 123, "title": self.title}]}
        elif name == "get_window_state":
            result = {"window_title": self.title, "snapshot_id": "s00000001", "elements_complete": True, "elements": [
                {"role": "TextInput", "label": "Text editor", "value": self.value,
                 "element_token": "s00000001:3"},
                {"role": "Tab", "label": "private unrelated tab"},
                {"role": "MenuItem", "label": "File"},
            ]}
        elif name == "set_value":
            if not self.ignore_input:
                self.value = arguments["value"]
            if self.on_action:
                self.on_action()
            result = {"status": "sent"}
        else:
            result = {"status": "sent"}
        return {"structuredContent": result}

    def close(self):
        self.closed = True


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    document = tmp_path / "vibelution-cua-test.txt"
    document.write_text("before", encoding="utf-8")
    binary = tmp_path / "cua-driver.exe"
    binary.touch()
    config = tmp_path / "scope.json"
    config.write_text(json.dumps({"enabled": True, "binaryPath": str(binary),
        "testFile": str(document), "window": {"pid": 42, "windowId": 123,
                                               "processCreateTime": 123.4}}), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_DESKTOP_CUA_CONFIG", str(config))
    driver = Driver(binary)
    monkeypatch.setattr(service, "CuaDriverClient", lambda *a, **kw: driver)
    monkeypatch.setattr(service, "_is_notepad", lambda pid: pid == 42)
    monkeypatch.setattr(service, "_process_birth", lambda pid: 123.4)
    monkeypatch.setattr(service, "_lock_path", lambda: tmp_path / "desktop.lock")
    service._observations.clear()
    service._retired.clear()
    monkeypatch.setattr(service, "_quarantine", None)
    return driver, document


def call(action="observe", owner=OWNER, checker=lambda: "", **args):
    return service.execute(owner, action=action, cancel_checker=checker, **args)


def test_observation_is_scoped_and_opaque(desktop):
    driver, _ = desktop
    result = call()
    assert result["ok"] and result["observationId"]
    assert result["text"] == "before" and result["modality"] == "uia"
    assert "private unrelated tab" not in json.dumps(result)
    assert "s00000001" not in json.dumps(result)
    assert driver.closed
    assert all(args.get("include_screenshot") is False
               for name, args in driver.calls if name == "get_window_state")


@pytest.mark.parametrize("change", ["foreign", "expired", "title", "value", "file"])
def test_changed_or_foreign_observation_never_sends_input(desktop, change, monkeypatch):
    driver, document = desktop
    observed = call()
    owner = OWNER
    if change == "foreign":
        owner = ("assistant", "direct-session", "other-turn")
    elif change == "expired":
        monkeypatch.setattr(service, "OBSERVATION_SECONDS", -1)
    elif change == "title":
        driver.title = "private.txt - Notepad"
    elif change == "value":
        driver.value = "human changed it"
    else:
        document.write_text("changed outside", encoding="utf-8")
    result = call("type_text", owner=owner, observation_id=observed["observationId"], text="after")
    assert result["ok"] is False
    assert not any(name in {"type_text", "set_value"} for name, _ in driver.calls)


def test_type_readback_and_single_use_observation(desktop):
    driver, _ = desktop
    observed = call()
    result = call("type_text", observation_id=observed["observationId"], text="中文 🙂\nline")
    assert result["ok"] and result["status"] == "completed"
    assert result["text"] == "中文 🙂\nline"
    assert not call("type_text", observation_id=observed["observationId"], text="again")["ok"]
    sent = next(args for name, args in driver.calls if name == "set_value")
    assert sent["pid"] == 42 and sent["window_id"] == 123
    assert sent["element_token"] == "s00000001:3"
    assert sent["delivery_mode"] == "background"
    assert not any(name == "type_text" for name, _ in driver.calls)


def test_sent_input_without_observed_effect_is_not_completed(desktop):
    driver, _ = desktop
    driver.ignore_input = True
    observed = call()
    result = call("type_text", observation_id=observed["observationId"], text="after")
    assert not result["ok"] and result["status"] == "unverified"


def test_save_sent_without_file_effect_is_not_completed(desktop):
    driver, _ = desktop
    driver.value = "not saved"
    observed = call()
    result = call("save", observation_id=observed["observationId"])
    assert not result["ok"] and result["status"] == "unverified"
    assert not any(args.get("delivery_mode") == "foreground" for _, args in driver.calls)
    assert result["foregroundSaveAvailable"] is True
    assert not any(name == "press_key" for name, _ in driver.calls)


def test_empty_uia_value_requires_explicit_zero_character_status(desktop):
    driver, _ = desktop
    original = driver.call
    zero_count = False
    def empty_state(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "get_window_state":
            elements = result["structuredContent"]["elements"]
            elements[0].pop("value")
            elements[0].update(role="Document", actions=["set_value"])
            if zero_count:
                elements.append({"role": "Text", "label": "0 characters"})
        return result
    driver.call = empty_state
    assert not call()["ok"]
    zero_count = True
    result = call()
    assert result["ok"] and result["text"] == ""


def test_partial_accessibility_tree_is_not_used_for_actions(desktop):
    driver, _ = desktop
    original = driver.call
    def partial(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "get_window_state":
            result["structuredContent"]["elements_complete"] = False
            result["structuredContent"]["truncated"] = True
        return result
    driver.call = partial
    assert not call()["ok"]


def test_windows_nonexhaustive_flag_alone_is_not_a_truncated_response(desktop):
    driver, _ = desktop
    original = driver.call
    def windows_snapshot(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "get_window_state":
            result["structuredContent"].update(elements_complete=False, truncated=False,
                                                returned_element_count=3, total_element_count=3)
        return result
    driver.call = windows_snapshot
    assert call()["ok"]


def test_refused_native_save_does_not_send_background_keyboard_input(desktop):
    driver, _ = desktop
    driver.value = "not saved"
    original = driver.call
    def refuse_menu(name, args, **kwargs):
        if name == "invoke_menu":
            driver.calls.append((name, args))
            return {"isError": True, "structuredContent": {"refusal": {"code": "menu_path_unavailable"}}}
        return original(name, args, **kwargs)
    driver.call = refuse_menu
    observed = call()
    result = call("save", observation_id=observed["observationId"])
    assert result["status"] == "unverified" and result["foregroundSaveAvailable"]
    assert not any(name == "press_key" for name, _ in driver.calls)


def test_foreground_save_requires_prior_verified_noop_and_checks_file(desktop):
    driver, document = desktop
    driver.value = "not saved"
    observed = call()
    assert not call("save_foreground", observation_id=observed["observationId"])["ok"]
    observed = call()
    background = call("save", observation_id=observed["observationId"])
    original = driver.call
    def save_on_foreground(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "press_key" and args["delivery_mode"] == "foreground":
            document.write_text(driver.value, encoding="utf-8")
        return result
    driver.call = save_on_foreground
    result = call("save_foreground", observation_id=background["observationId"])
    assert result["ok"] and result["status"] == "completed"
    assert any(a.get("delivery_mode") == "foreground" for _, a in driver.calls)


def test_stop_during_input_cannot_publish_late_success_or_reopen(desktop):
    driver, _ = desktop
    stopped = False
    def checker():
        return "stop" if stopped else ""
    def stop():
        nonlocal stopped
        stopped = True
    driver.on_action = stop
    observed = call()
    result = call("type_text", checker=checker, observation_id=observed["observationId"], text="after")
    assert not result["ok"] and result["status"] == "cancelled" and driver.closed
    assert not call()["ok"]


def test_end_retires_turn_without_start_session(desktop):
    driver, _ = desktop
    assert call("end")["ok"]
    assert not call()["ok"]
    assert not any(name == "start_session" for name, _ in driver.calls)


def test_disabled_and_unbounded_actions_rejected_before_driver(desktop, monkeypatch):
    driver, _ = desktop
    monkeypatch.delenv("VIBELUTION_DESKTOP_CUA_CONFIG")
    assert not call()["ok"]
    assert not driver.calls
    assert not call("press_key", text="cmd.exe")["ok"]


def test_tool_identity_failure_never_reaches_desktop(monkeypatch):
    from tools import personal_assistant_desktop_tools as tools
    monkeypatch.setattr(tools, "_identity", lambda: (_ for _ in ()).throw(ValueError("unbound")))
    monkeypatch.setattr(service, "execute", lambda *a, **k: pytest.fail("identity bypass"))
    assert not json.loads(tools.personal_assistant_desktop_observe_tool())["ok"]


def test_reused_process_id_is_refused_before_document_read(desktop, monkeypatch):
    driver, _ = desktop
    monkeypatch.setattr(service, "_process_birth", lambda pid: 999.9)
    assert not call()["ok"]
    assert not driver.calls


def test_same_title_in_another_window_is_never_read(desktop):
    driver, _ = desktop
    original = driver.call
    def other_window(name, args, **kwargs):
        result = original(name, args, **kwargs)
        if name == "list_windows":
            result["structuredContent"]["windows"][0]["window_id"] = 999
        return result
    driver.call = other_window
    assert not call()["ok"]
    assert not any(n == "get_window_state" for n, _ in driver.calls)


def test_failed_driver_retirement_quarantines_input_and_end_can_retry(desktop):
    driver, _ = desktop
    def fail():
        raise RuntimeError("still running")
    driver.close = fail
    result = call()
    assert result["status"] == "unknown" and not result["ok"]
    assert not service._guard.locked()
    assert not call(owner=("assistant", "direct-session", "turn-2"))["ok"]
    driver.close = lambda: None
    assert call("end", owner=("assistant", "direct-session", "turn-2"))["ok"]
    assert service._quarantine is None


def test_config_fallback_uses_only_this_instance_data_home(desktop, monkeypatch, tmp_path):
    config = Path(service.os.environ["VIBELUTION_DESKTOP_CUA_CONFIG"])
    target = tmp_path / "instance-data" / "runtime" / "desktop-cua-scope.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(config.read_bytes())
    monkeypatch.delenv("VIBELUTION_DESKTOP_CUA_CONFIG")
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(target.parent.parent))
    assert call()["ok"]


def test_quarantine_holds_os_lease_until_driver_retirement(desktop, tmp_path):
    import subprocess
    import sys
    from scripts.windowless_subprocess import no_window_subprocess_kwargs
    driver, _ = desktop
    def fail():
        raise RuntimeError("not retired")
    driver.close = fail
    assert call()["status"] == "unknown"
    code = """
import sys
from pathlib import Path
from core.infrastructure.file_lock import locked_sidecar
try:
    with locked_sidecar(Path(sys.argv[1]), lock_path=Path(sys.argv[1]), timeout=0):
        pass
except TimeoutError:
    raise SystemExit(3)
"""
    def child_lock():
        return subprocess.run([sys.executable, "-c", code, str(tmp_path / "desktop.lock")],
                              capture_output=True, timeout=10,
                              **no_window_subprocess_kwargs()).returncode
    try:
        assert child_lock() == 3, "a second instance acquired the quarantined desktop lease"
    finally:
        driver.close = lambda: None
        assert call("end")["ok"]
    assert child_lock() == 0
