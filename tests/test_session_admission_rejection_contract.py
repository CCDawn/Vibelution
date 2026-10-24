"""Only canonical pre-admission guards may assert that no new Turn started."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from core.web.services import session_service
from core.web.services.session import admission_lock, submit


def test_lock_timeout_preserves_busy_type_and_marks_rejected_admission(monkeypatch, tmp_path):
    @contextmanager
    def unavailable(*_args, **_kwargs):
        raise TimeoutError("held by another writer")
        yield
    monkeypatch.setattr(admission_lock, "cross_process_file_lock", unavailable)
    with pytest.raises(session_service.SessionBusyError) as caught:
        admission_lock.SessionAdmissionLock(tmp_path, "session-owned").acquire(timeout=.01)
    assert type(caught.value) is session_service.SessionBusyError
    assert getattr(caught.value, "native_admission_rejected", False) is True
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert caught.value.args == ("Session接纳正忙，请稍后重试。",)


def test_live_owner_guard_marks_only_the_rejected_submission():
    facade = SimpleNamespace(SessionBusyError=session_service.SessionBusyError,
        text_for=lambda _lang, **text: text["zh"])
    error = submit._session_still_running_error(facade, "zh")
    assert type(error) is session_service.SessionBusyError
    assert getattr(error, "native_admission_rejected", False) is True
    assert "当前会话仍在运行" in str(error)


def test_plain_busy_from_unknown_side_effects_has_no_rejection_receipt():
    error = session_service.SessionBusyError("producer response unknown")
    assert getattr(error, "native_admission_rejected", False) is False
