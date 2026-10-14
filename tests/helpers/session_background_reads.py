"""Keep native Session background reads within a test's storage lifetime."""
import threading
import time


def settle_session_background_reads(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        readers = [
            worker for worker in threading.enumerate()
            if worker.name == "session-list-cache-refresh"
            or worker.name.startswith("session-create-prompt-warm-")
        ]
        if not readers:
            return
        for worker in readers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        pending = [worker.name for worker in readers if worker.is_alive()]
        assert not pending, f"Session background reads outlived test storage: {pending}"
