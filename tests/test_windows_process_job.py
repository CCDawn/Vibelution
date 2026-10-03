from __future__ import annotations

import ctypes
import os
from types import SimpleNamespace

import pytest

from core.infrastructure.windows_process_job import (
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    WindowsProcessJob,
    _ExtendedLimits,
)


@pytest.mark.parametrize(
    ("enabled", "initial_flags", "expected_flags"),
    [
        (False, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x0400, 0x0400),
        (True, 0x0400, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | 0x0400),
    ],
)
def test_set_kill_on_job_close_changes_only_the_requested_limit(enabled, initial_flags, expected_flags):
    calls: dict[str, object] = {}

    class FakeApi:
        def QueryInformationJobObject(self, handle, info_class, buffer, size, _returned):
            assert handle == 12
            assert info_class == JOB_OBJECT_EXTENDED_LIMIT_INFORMATION
            assert size == ctypes.sizeof(_ExtendedLimits)
            ctypes.cast(buffer, ctypes.POINTER(_ExtendedLimits)).contents.basic.flags = initial_flags
            calls["query"] = True
            return 1

        def SetInformationJobObject(self, handle, info_class, buffer, size):
            assert handle == 12
            assert info_class == JOB_OBJECT_EXTENDED_LIMIT_INFORMATION
            assert size == ctypes.sizeof(_ExtendedLimits)
            limits = ctypes.cast(buffer, ctypes.POINTER(_ExtendedLimits)).contents
            calls["flags"] = int(limits.basic.flags)
            return 1

    job = WindowsProcessJob.__new__(WindowsProcessJob)
    job._handle = 12
    api = FakeApi()
    job._api = SimpleNamespace(
        QueryInformationJobObject=api.QueryInformationJobObject,
        SetInformationJobObject=api.SetInformationJobObject,
    )

    job.set_kill_on_job_close(enabled)

    assert calls == {"query": True, "flags": expected_flags}


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object API")
def test_windows_process_job_defaults_to_kill_on_close_and_can_clear_then_restore_it():
    job = WindowsProcessJob()
    try:
        limits = _ExtendedLimits()
        assert job._api.QueryInformationJobObject(
            job._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
            None,
        )
        assert limits.basic.flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        job.set_kill_on_job_close(False)
        limits = _ExtendedLimits()
        assert job._api.QueryInformationJobObject(
            job._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
            None,
        )
        assert not limits.basic.flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        job.set_kill_on_job_close(True)
        limits = _ExtendedLimits()
        assert job._api.QueryInformationJobObject(
            job._handle,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
            None,
        )
        assert limits.basic.flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    finally:
        job.close()
