#!/usr/bin/env python3
"""Run the pytest suite inside a Windows job object with a wall-clock watchdog.

Why this exists: pytest-xdist workers occasionally refuse to exit after the
suite finishes. Module-level ThreadPoolExecutors holding non-daemon threads
stuck in untimed waits keep worker processes alive, and on Windows a worker
that sits in no job object survives its parent as an orphan (six workers once
burned 27.7 GB over three days). The workbench got the same containment in
commit 696f59a29 ("fix(launcher): tie each workbench to a Windows job"); this
wrapper applies the identical technique to the test pipeline.

How it works (mirrors desktop/electron/native/workbench-job/job_object.c):
- One job object owns the whole run. It is created with
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE whenever the machine allows it, so every
  remaining process of the run dies with the job handle whenever this wrapper
  exits -- normally, on crash, on Ctrl+C or after the watchdog fires. On
  machines whose security policy rejects that flag (SetInformationJobObject
  fails with ERROR_INVALID_PARAMETER) the job is created without it: the
  wrapper then kills the tree explicitly via TerminateJobObject on every exit
  it survives (watchdog, Ctrl+C, normal end); only a hard crash of the wrapper
  itself could leak members, and the next run's sweep reaps them.
- pytest (and therefore every xdist worker it spawns) is started suspended,
  assigned to the job, then resumed. The wrapper itself stays outside the job,
  so TerminateJobObject can reap the tree without killing the supervisor --
  the same split as Electron holding the workbench job handle.
- A wall-clock watchdog (default 2 hours, --watchdog-hours N) terminates the
  job and exits with code 125.
- Second belt: after pytest exits, stale xdist workers (command line contains
  the execnet bootstrap marker) whose parent process is gone are reaped.

Usage:
    .venv/Scripts/python.exe scripts/run_tests.py [wrapper options] [pytest options]

    # Full regression, loadfile-distributed, serial tests excluded:
    .venv/Scripts/python.exe scripts/run_tests.py -n 6 --dist loadfile -m "not serial"

    # Quick subset plus a deliberately hung child to prove job containment:
    .venv/Scripts/python.exe scripts/run_tests.py --inject-hang tests/test_config_paths.py

Wrapper options (consumed here, never forwarded): --watchdog-hours, --inject-hang.
Every other argument is passed to pytest verbatim.

Exit codes: pytest's own code, 125 on watchdog timeout, 130 on Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.helpers.managed_processes import terminate_processes  # noqa: E402

_VENV_DIR = PROJECT_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
VENV_PYTHON = _VENV_DIR / ("python.exe" if os.name == "nt" else "python")

WATCHDOG_EXIT_CODE = 125
INTERRUPT_EXIT_CODE = 130
DEFAULT_WATCHDOG_HOURS = 2.0
POLL_INTERVAL_SECONDS = 1.0

# execnet (pytest-xdist's transport) starts every remote worker with this
# bootstrap line, so it identifies worker processes unambiguously.
EXECNET_WORKER_MARKER = "exec(eval(sys.stdin"

# Deliberately hung helper used by --inject-hang: non-daemon threads spinning
# in a sleep loop keep the interpreter alive forever, the same shape as the
# executor threads that strand real xdist workers.
HANG_SNIPPET = (
    "import threading, time\n"
    "def _spin():\n"
    "    while True:\n"
    "        time.sleep(1)\n"
    "threading.Thread(target=_spin, daemon=False).start()\n"
    "threading.Thread(target=_spin, daemon=False).join()\n"
)

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000200
    JobObjectExtendedLimitInformation = 9
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    CREATE_SUSPENDED = 0x00000004  # not exposed by the subprocess module

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE


def _create_run_job() -> tuple[int | None, bool]:
    """Create the run job; returns (handle, kill_on_close).

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE is the gold standard: every member dies
    when the last job handle closes, so a crashed wrapper cannot leak the tree.
    Some machines run security software that rejects the flag with
    ERROR_INVALID_PARAMETER even for a process outside any job; the job is then
    created without it and TerminateJobObject is the only kill path, which the
    wrapper performs explicitly on every exit it survives.
    """
    if os.name != "nt":
        return None, False
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, False
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    )
    if _kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        return job, True
    limits.BasicLimitInformation.LimitFlags = 0
    if _kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        return job, False
    _kernel32.CloseHandle(job)
    return None, False


def _assign_process_to_job(job: int, pid: int) -> bool:
    """Assign an arbitrary process to the job (opened fresh by pid)."""
    if os.name != "nt":
        return False
    handle = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(_kernel32.AssignProcessToJobObject(job, handle))
    finally:
        _kernel32.CloseHandle(handle)


def _terminate_job(job: int | None) -> None:
    """Kill every process in the job; the supervisor must not be a member."""
    if os.name == "nt" and job is not None:
        _kernel32.TerminateJobObject(job, 1)


def _close_job(job: int | None) -> None:
    if os.name == "nt" and job is not None:
        _kernel32.CloseHandle(job)


def _resume_process(pid: int) -> bool:
    """Resume a CREATE_SUSPENDED child; psutil stands in for ResumeThread."""
    try:
        import psutil
    except ImportError:
        return False
    try:
        psutil.Process(pid).resume()
    except psutil.Error:
        return False
    return True


class _RunContainment:
    """Job containment for one test run.

    mode "child": the wrapper stays outside the job and every child is spawned
        suspended, assigned to the job, then resumed (the job_object.c dance).
    mode "self": fallback when psutil is unavailable; the wrapper joins the job
        so children inherit it, and TerminateJobObject must never be called.
    mode "none": non-Windows or containment unavailable; children run unbound
        and the tree-kill fallback is the only cleanup.
    """

    def __init__(self) -> None:
        self.job: int | None = None
        self.kill_on_close = False
        self.mode = "none"
        if os.name != "nt":
            return
        job, kill_on_close = _create_run_job()
        if job is None:
            print("[run_tests] WARNING: could not create the Windows job object")
            return
        try:
            import psutil  # noqa: F401
        except ImportError:
            # No psutil means no way to resume suspended children; join the job
            # ourselves instead so children inherit membership.
            if _assign_process_to_job(job, os.getpid()):
                self.job, self.kill_on_close, self.mode = job, kill_on_close, "self"
                print("[run_tests] psutil missing: wrapper joins the job itself")
            else:
                _close_job(job)
                print("[run_tests] WARNING: job containment unavailable")
            return
        self.job, self.kill_on_close, self.mode = job, kill_on_close, "child"
        if kill_on_close:
            print("[run_tests] job containment active: KILL_ON_JOB_CLOSE (tree dies with this wrapper)")
        else:
            print(
                "[run_tests] WARNING: this machine rejects JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE "
                "(security policy); the job still kills the tree via TerminateJobObject on "
                "every exit this wrapper survives, but processes could outlive a hard-crashed wrapper"
            )

    def spawn(self, cmd: list[str], env: dict[str, str], cwd: Path) -> subprocess.Popen[bytes]:
        """Spawn a child process as a member of the run job."""
        if os.name == "nt" and self.mode == "child" and self.job is not None:
            proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, creationflags=CREATE_SUSPENDED)
            if _assign_process_to_job(self.job, proc.pid) and _resume_process(proc.pid):
                return proc
            # Rare: assignment or resume refused. Never leave a suspended
            # zombie; degrade to self-membership so future children inherit.
            proc.kill()
            proc.wait(timeout=5)
            self._degrade_to_self()
        return subprocess.Popen(cmd, cwd=str(cwd), env=env)

    def _degrade_to_self(self) -> None:
        if self.mode != "child":
            return
        self.mode = "self" if self._assign_self() else "none"
        if self.mode == "none":
            _close_job(self.job)
            self.job = None
        print(f"[run_tests] WARNING: child assignment failed; containment degraded to mode={self.mode}")

    def _assign_self(self) -> bool:
        if os.name != "nt" or self.job is None:
            return False
        # Reuse the pid-based helper on our own pid to keep one code path.
        return _assign_process_to_job(self.job, os.getpid())

    def terminate_run(self) -> None:
        """Kill the whole tree while this wrapper stays alive (child mode only)."""
        if self.mode == "child":
            _terminate_job(self.job)

    def close(self) -> None:
        _close_job(self.job)


def _is_execnet_worker_cmdline(cmdline: Sequence[str]) -> bool:
    """True when a command line is an execnet remote bootstrap (an xdist worker).

    The bootstrap is passed as one short ``-c`` payload starting with
    ``import sys``; matching that shape avoids false positives on unrelated
    processes whose script text merely mentions the marker.
    """
    for part in cmdline:
        text = str(part).strip()
        if text.startswith("import sys") and EXECNET_WORKER_MARKER in text:
            return True
    return False


def _sweep_stale_workers() -> int:
    """Reap orphaned xdist workers left behind after the suite exited.

    A worker counts as stale when its command line carries the execnet
    bootstrap, it runs this project's venv interpreter, and its parent process
    is gone. Workers whose parent is still alive belong to some other live run
    and are left alone.
    """
    try:
        import psutil
    except ImportError:
        return 0
    venv_root = str((PROJECT_ROOT / ".venv").resolve()).lower()
    own_pid = os.getpid()
    reaped = 0
    for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            if proc.info["pid"] == own_pid:
                continue
            if not _is_execnet_worker_cmdline(proc.info["cmdline"] or []):
                continue
            exe = str(proc.info["exe"] or "").lower()
            if not exe.startswith(venv_root):
                continue
            if proc.parent() is not None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except psutil.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        except psutil.Error:
            continue
        reaped += 1
    return reaped


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="scripts/run_tests.py",
        add_help=False,
        allow_abbrev=False,
        description="Run pytest inside a Windows job object with a wall-clock watchdog.",
    )
    parser.add_argument(
        "--watchdog-hours",
        type=float,
        default=DEFAULT_WATCHDOG_HOURS,
        metavar="N",
        help=f"kill the whole run after N hours (default {DEFAULT_WATCHDOG_HOURS:g}); exits with code 125",
    )
    parser.add_argument(
        "--inject-hang",
        action="store_true",
        help="spawn a deliberately hung python child inside the job to prove containment",
    )
    namespace, passthrough = parser.parse_known_args(argv)
    if namespace.watchdog_hours <= 0:
        parser.error("--watchdog-hours must be greater than 0")
    return namespace, passthrough


def main(argv: Sequence[str]) -> int:
    opts, pytest_args = _parse_args(argv)
    if VENV_PYTHON.exists():
        python = str(VENV_PYTHON)
    else:
        python = sys.executable
        print(f"[run_tests] WARNING: {VENV_PYTHON} not found; falling back to {python}")

    containment = _RunContainment()
    env = dict(os.environ)
    env["PYTHONFAULTHANDLER"] = "1"

    started = time.monotonic()
    deadline = started + opts.watchdog_hours * 3600.0
    hang_proc: subprocess.Popen[bytes] | None = None
    pytest_proc: subprocess.Popen[bytes] | None = None
    watchdog_fired = False
    interrupted = False
    crashed = False
    pytest_exit: int | None = None
    reaped = 0

    try:
        if opts.inject_hang:
            hang_proc = containment.spawn([python, "-c", HANG_SNIPPET], env, PROJECT_ROOT)
            print(f"[run_tests] injected hang process pid={hang_proc.pid} (dies with the job)")
        pytest_proc = containment.spawn([python, "-m", "pytest", *pytest_args], env, PROJECT_ROOT)
        while pytest_proc.poll() is None:
            if time.monotonic() >= deadline:
                watchdog_fired = True
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        pytest_exit = pytest_proc.returncode
    except KeyboardInterrupt:
        interrupted = True
    except Exception:  # noqa: BLE001 - crash path must still clean the tree
        crashed = True

    try:
        if watchdog_fired or interrupted or crashed:
            reason = (
                "watchdog timeout"
                if watchdog_fired
                else "Ctrl+C" if interrupted else "wrapper error"
            )
            print(f"[run_tests] {reason}: terminating the whole run")
            containment.terminate_run()
            terminate_processes([proc for proc in (pytest_proc, hang_proc) if proc is not None])
        reaped = _sweep_stale_workers()
        # Normal end: in child mode the wrapper is outside the job, so it can
        # finish the job explicitly -- anything still inside is a leak by
        # definition because pytest already exited. Without the job (or in
        # self mode) there is no kill-on-close guarantee, so known live
        # members are killed directly instead.
        if containment.mode == "child":
            if not (watchdog_fired or interrupted or crashed):
                containment.terminate_run()
        else:
            live = [
                proc
                for proc in (pytest_proc, hang_proc)
                if proc is not None and proc.poll() is None
            ]
            if live:
                terminate_processes(live)
        if hang_proc is not None:
            if containment.mode == "child":
                try:
                    hang_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    hang_proc.kill()
                    hang_proc.wait(timeout=5)
            status = (
                "reaped"
                if hang_proc.poll() is not None
                else "still alive at wrapper exit; job handle close is the last kill"
            )
            print(f"[run_tests] injected hang process pid={hang_proc.pid}: {status}")
    finally:
        containment.close()

    elapsed = time.monotonic() - started
    if interrupted:
        exit_code = INTERRUPT_EXIT_CODE
    elif watchdog_fired:
        exit_code = WATCHDOG_EXIT_CODE
    elif crashed:
        exit_code = 1
    else:
        exit_code = pytest_exit if pytest_exit is not None else 1

    pytest_label = "killed" if pytest_exit is None else str(pytest_exit)
    print(
        f"[run_tests] summary: pytest exit code={pytest_label} | elapsed={elapsed:.1f}s | "
        f"watchdog={'fired' if watchdog_fired else 'not triggered'} | stale workers reaped={reaped}"
    )
    if watchdog_fired:
        print(
            f"[run_tests] watchdog fired after {opts.watchdog_hours:g}h and the job was terminated; "
            "raise --watchdog-hours if the run legitimately needs longer."
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
