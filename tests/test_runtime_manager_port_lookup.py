import os
import socket

import pytest

from core.runtime_manager import workbench_controller


def test_listening_pid_for_port_resolves_own_listener_without_psutil(monkeypatch):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    probe.listen(1)
    port = probe.getsockname()[1]
    try:
        monkeypatch.setattr(
            workbench_controller,
            "_listening_pid_for_port_psutil",
            lambda _port: pytest.fail(
                "psutil fallback must not run when the win32 lookup resolves the listener"
            ),
        )
        assert workbench_controller._listening_pid_for_port(port) == os.getpid()
    finally:
        probe.close()


def test_listening_pid_for_port_returns_zero_after_listener_closes():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    probe.listen(1)
    port = probe.getsockname()[1]
    probe.close()
    assert workbench_controller._listening_pid_for_port(port) == 0
