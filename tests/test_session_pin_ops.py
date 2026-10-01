"""Session pin service op: directory write, error mapping, and cache invalidation."""

from __future__ import annotations

import pytest

from core.web.services.session import session_pin_ops


class _FakeRepository:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self.rows = rows or {}
        self.calls: list[tuple[str, bool]] = []

    def set_session_pinned(self, session_id: str, *, pinned: bool):
        self.calls.append((session_id, pinned))

        class _Future:
            def __init__(self, payload: dict | None) -> None:
                self._payload = payload

            def result(self, timeout: float = 5) -> dict | None:
                return self._payload

        if session_id not in self.rows:
            return _Future(None)
        return _Future(
            {
                "sessionId": session_id,
                "action": "pinned" if pinned else "unpinned",
                "pinnedAtMs": 1234 if pinned else None,
            }
        )


class _FakeStore:
    def __init__(self, repository: _FakeRepository) -> None:
        self.repository = repository


class _StubService:
    """Minimal facade exposing only the attributes session_pin_ops touches."""

    def __init__(self, real_service, invalidated: list[bool]) -> None:
        self._real = real_service
        self._invalidated = invalidated

    def __getattr__(self, name: str):
        return getattr(self._real, name)

    def _invalidate_session_list_cache(self) -> None:
        self._invalidated.append(True)

    def record_runtime_scene_event(self, *args, **kwargs) -> None:
        return None


@pytest.fixture
def pinned_service(monkeypatch: pytest.MonkeyPatch):
    """Wire the session facade onto a fake directory store."""
    from core.web.services import session_service
    from core.web.services.session import directory_runtime

    repository = _FakeRepository({"session-1": {"sessionId": "session-1"}})
    invalidated: list[bool] = []
    monkeypatch.setattr(
        session_pin_ops,
        "_service",
        lambda: _StubService(session_service, invalidated),
    )
    monkeypatch.setattr(
        directory_runtime,
        "get_open_directory_store",
        lambda: _FakeStore(repository),
    )
    return repository, invalidated


def test_pin_sets_directory_state_and_invalidates_list_cache(pinned_service):
    repository, invalidated = pinned_service
    result = session_pin_ops.set_chat_session_pinned("session-1", pinned=True)
    assert result == {"id": "session-1", "pinned": True, "pinnedAtMs": 1234}
    assert repository.calls == [("session-1", True)]
    assert invalidated == [True]


def test_unpin_clears_directory_state(pinned_service):
    repository, invalidated = pinned_service
    result = session_pin_ops.set_chat_session_pinned("session-1", pinned=False)
    assert result["pinned"] is False
    assert result["pinnedAtMs"] is None
    assert repository.calls == [("session-1", False)]
    assert invalidated == [True]


def test_pin_unknown_session_maps_to_not_found(pinned_service):
    from core.web.services import session_service

    with pytest.raises(session_service.SessionNotFoundError):
        session_pin_ops.set_chat_session_pinned("missing", pinned=True)


def test_pin_requires_session_id():
    from core.web.services import session_service

    with pytest.raises(session_service.SessionNotFoundError):
        session_pin_ops.set_chat_session_pinned("  ", pinned=True)


def test_pin_without_directory_store_maps_to_validation(monkeypatch: pytest.MonkeyPatch):
    from core.web.services import session_service
    from core.web.services.session import directory_runtime

    monkeypatch.setattr(directory_runtime, "get_open_directory_store", lambda: None)
    with pytest.raises(session_service.SessionValidationError):
        session_pin_ops.set_chat_session_pinned("session-1", pinned=True)
