# -*- coding: utf-8 -*-
"""Evolution test gate — runs pytest before self-restart to prevent broken code propagation."""

import subprocess
import sys
from pathlib import Path
from typing import Tuple


def _resolve_project_root() -> Path:
    p = Path(__file__).parent.parent.parent.resolve()
    if (p / "agent.py").exists():
        return p
    for sp in sys.path:
        if Path(sp, "agent.py").exists():
            return Path(sp).resolve()
    return p


def check_evolution_ready(timeout: int = 120) -> Tuple[bool, str]:
    """Run pytest suite. Returns (passed, message). Called before self-restart.

    Args:
        timeout: max seconds for test run (default 120)

    Returns:
        (passed, message) — passed=True means all tests green
    """
    project_root = _resolve_project_root()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-x", "--tb=short", "-q"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, "All tests passed"
        # Extract failed test summary
        output = result.stdout + result.stderr
        return False, f"Tests failed (exit {result.returncode})\n{output[-1200:]}"
    except subprocess.TimeoutExpired:
        return False, f"Test gate timed out after {timeout}s"
    except Exception as e:
        return False, f"Test gate error: {e}"
