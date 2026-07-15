from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.windowless_subprocess import no_window_subprocess_kwargs


def test_windows_subprocess_policy_suppresses_console_windows() -> None:
    kwargs = no_window_subprocess_kwargs(creationflags=0x00000200)

    if os.name != "nt":
        assert kwargs == {}
        return

    assert kwargs["creationflags"] & int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert kwargs["creationflags"] & 0x00000200
    assert kwargs["startupinfo"].wShowWindow == int(getattr(subprocess, "SW_HIDE", 0))


def test_windowless_policy_is_used_by_high_risk_process_owners() -> None:
    project_root = Path(__file__).resolve().parents[1]
    owners = (
        "scripts/local_quality_gate.py",
        "scripts/integration_audit.py",
        "scripts/remote_test_runner.py",
        "core/infrastructure/background_tasks.py",
        "core/infrastructure/boot_pipeline.py",
        "core/infrastructure/test_gate.py",
        "core/restarter_manager/restarter.py",
        "core/web/services/config_service.py",
        "tools/python_intelligence_tools.py",
    )

    for relative_path in owners:
        source = (project_root / relative_path).read_text(encoding="utf-8")
        assert "no_window_subprocess_kwargs" in source, relative_path
