import threading
import time

import pytest

from core.web.services import personal_assistant_computer_driver as adapter


@pytest.fixture(autouse=True)
def chinese_language(monkeypatch):
    monkeypatch.setattr(adapter, "get_web_language", lambda: "zh")


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
