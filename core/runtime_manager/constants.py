"""Shared paths and defaults for the runtime manager."""

from __future__ import annotations

from pathlib import Path

from config.workbench import DEFAULT_WORKBENCH_HOST, configured_backend_port


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_MANAGER_DIR = PROJECT_ROOT / ".runtime" / "runtime-manager"
INBOX_DIR = RUNTIME_MANAGER_DIR / "inbox"
PROCESSING_DIR = RUNTIME_MANAGER_DIR / "processing"
RESULTS_DIR = RUNTIME_MANAGER_DIR / "results"
INTERRUPTS_DIR = RUNTIME_MANAGER_DIR / "interrupts"
RESTART_INTENTS_DIR = RUNTIME_MANAGER_DIR / "restart-intents"
STATE_PATH = RUNTIME_MANAGER_DIR / "state.json"
PID_PATH = RUNTIME_MANAGER_DIR / "daemon.pid"
EVENTS_PATH = RUNTIME_MANAGER_DIR / "events.jsonl"
DAEMON_STDOUT_PATH = RUNTIME_MANAGER_DIR / "daemon.out.log"
DAEMON_STDERR_PATH = RUNTIME_MANAGER_DIR / "daemon.err.log"
DAEMON_LOG_MAX_BYTES = 16 * 1024 * 1024
DAEMON_LOG_BACKUP_COUNT = 3

LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
PYTHON_LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
LAUNCHER_STATE_PATH = PROJECT_ROOT / ".runtime" / "launcher" / "state.json"

DEFAULT_HOST = DEFAULT_WORKBENCH_HOST
DEFAULT_PORT = configured_backend_port()
DEFAULT_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
DEFAULT_HEALTH_URL = f"{DEFAULT_URL}/api/health"

DAEMON_LOOP_INTERVAL_SECONDS = 0.45
DEFAULT_COMMAND_WAIT_SECONDS = 45.0


def ensure_runtime_manager_dirs() -> None:
    """Create the runtime-manager directory tree if it is missing."""

    for path in (RUNTIME_MANAGER_DIR, INBOX_DIR, PROCESSING_DIR, RESULTS_DIR, INTERRUPTS_DIR, RESTART_INTENTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
