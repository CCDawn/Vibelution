"""Exercise the build owner without rebuilding or refreshing a desktop shell."""
import json
import os
import sys
import time

import psutil
import pytest

from core.launcher import desktop_shell

pytestmark = pytest.mark.serial


def test_build_deadline_retires_helper_and_descendant(tmp_path, monkeypatch):
    pid_file = tmp_path / "build-pids.json"
    script = tmp_path / "build-helper.py"
    script.write_text(
        "import os,sys,subprocess,time,json\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
        f"Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
        "print('controlled build output',flush=True)\ntime.sleep(30)\n",
        encoding="utf8",
    )
    monkeypatch.setattr(desktop_shell, "DESKTOP_SHELL_BUILD_CLEANUP_RESERVE_SECONDS", .5)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            desktop_shell._run_owned_process(
                [sys.executable, str(script)], cwd=tmp_path,
                deadline=started + 1.2, label="controlled build helper",
            )
        assert pid_file.exists(), "the helper must have run before the timeout"
        pids = json.loads(pid_file.read_text())
        assert all(not psutil.pid_exists(pid) for pid in pids)
        assert time.monotonic() - started < 1.7
        assert not desktop_shell._pending_build_retirement_for(tmp_path)
    finally:
        if pid_file.exists():
            for pid in json.loads(pid_file.read_text()):
                try:
                    process = psutil.Process(pid)
                    # Cleanup only this synthetic script's still-living processes.
                    if str(script) in process.cmdline() or "import time;time.sleep(30)" in process.cmdline():
                        process.kill()
                        process.wait(timeout=2)
                except psutil.NoSuchProcess:
                    pass


def _run_failing_build(tmp_path, body, *, stage="node-build"):
    script = tmp_path / "build-fail.py"
    script.write_text("import sys\n" + body, encoding="utf-8")
    with pytest.raises(RuntimeError, match="controlled build failed with exit code 3") as excinfo:
        desktop_shell._run_owned_process(
            [sys.executable, str(script)], cwd=tmp_path,
            deadline=time.monotonic() + 60, label="controlled build", stage=stage,
        )
    return excinfo.value


def test_failed_build_process_carries_stage_and_stderr_first_tail(tmp_path):
    stdout_lines = [f"noise {index}" for index in range(50)] + ["npm ERR! command failed"]
    failure = _run_failing_build(tmp_path, (
        f"sys.stdout.write({chr(10).join(stdout_lines)!r} + '\\n\\n\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('gyp ERR! find VS\\r\\n' + 'E' * 900 + '\\r\\n')\n"
        "sys.exit(3)\n"
    ))
    assert failure.build_stage == "node-build"
    tail = failure.build_output_tail.splitlines()
    assert len(tail) == desktop_shell.BUILD_FAILURE_TAIL_MAX_LINES
    # stderr keeps its lines whole at the end; stdout fills the remaining budget.
    assert tail[-2:] == ["gyp ERR! find VS", "E" * desktop_shell.BUILD_FAILURE_TAIL_MAX_LINE_CHARS]
    assert tail[-3] == "npm ERR! command failed"
    assert tail[0] == "noise 13" and "noise 12" not in tail
    assert all(line.strip() == line and line for line in tail), "blank lines and \\r never spend budget"


def test_failed_build_tail_stays_bounded_for_flooded_output(tmp_path):
    failure = _run_failing_build(tmp_path, (
        "sys.stdout.write('\\n'.join('stdout flood %d' % i for i in range(5000)) + '\\n')\n"
        "sys.stderr.write('x' * (512 * 1024) + '\\nthe real cause\\n')\n"
        "sys.exit(3)\n"
    ))
    tail = failure.build_output_tail
    lines = tail.splitlines()
    assert lines[-1] == "the real cause"
    assert lines[-2] == "x" * desktop_shell.BUILD_FAILURE_TAIL_MAX_LINE_CHARS
    assert lines[:-2] == [f"stdout flood {i}" for i in range(4962, 5000)]
    assert len(tail) <= desktop_shell.BUILD_FAILURE_TAIL_MAX_LINES * (desktop_shell.BUILD_FAILURE_TAIL_MAX_LINE_CHARS + 1)


def test_failed_build_decodes_non_utf8_output_without_raising(tmp_path):
    failure = _run_failing_build(tmp_path, (
        "sys.stderr.buffer.write(b'cp1252 \\x93quoted\\x94 path\\n')\n"
        "sys.exit(3)\n"
    ))
    assert failure.build_output_tail.endswith("path")
    assert "cp1252" in failure.build_output_tail


def test_unstartable_build_process_is_still_tagged_with_its_stage(tmp_path):
    with pytest.raises(OSError) as excinfo:
        desktop_shell._run_owned_process(
            [str(tmp_path / "no-such-node.exe")], cwd=tmp_path,
            deadline=time.monotonic() + 60, label="controlled build", stage="assistant-payload",
        )
    assert excinfo.value.build_stage == "assistant-payload"
    assert not getattr(excinfo.value, "build_output_tail", "")
