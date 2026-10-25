"""Shared paths and defaults for the runtime manager."""

from __future__ import annotations

from pathlib import Path

from config.workbench import DEFAULT_WORKBENCH_HOST, configured_backend_port
from core.infrastructure.native_runtime import is_launcher_assistant_process, resolve_native_project_root
from vibelution_storage import resolve_active_project_storage_paths

PROJECT_ROOT = resolve_native_project_root(Path(__file__).resolve().parents[2])
if is_launcher_assistant_process():
    # The Launcher profile is not a project checkout and has no project ID.
    # Default local stores stay in that profile; explicit target-project
    # descriptor resolution still goes through the normal storage resolver.
    PROJECT_STORAGE = None
    RUNTIME_ROOT = PROJECT_ROOT / ".runtime"
    LOG_ROOT = PROJECT_ROOT / "logs"
else:
    PROJECT_STORAGE = resolve_active_project_storage_paths(PROJECT_ROOT)
    RUNTIME_ROOT = PROJECT_STORAGE.runtime
    LOG_ROOT = PROJECT_STORAGE.logs
RUNTIME_MANAGER_DIR = RUNTIME_ROOT / "runtime-manager"
INBOX_DIR = RUNTIME_MANAGER_DIR / "inbox"
PROCESSING_DIR = RUNTIME_MANAGER_DIR / "processing"
RESULTS_DIR = RUNTIME_MANAGER_DIR / "results"
INTERRUPTS_DIR = RUNTIME_MANAGER_DIR / "interrupts"
RESTART_INTENTS_DIR = RUNTIME_MANAGER_DIR / "restart-intents"
STATE_PATH = RUNTIME_MANAGER_DIR / "state.json"
PID_PATH = RUNTIME_MANAGER_DIR / "daemon.pid"
DAEMON_IDENTITY_PATH = RUNTIME_MANAGER_DIR / "daemon.identity.json"
DAEMON_LOCK_PATH = RUNTIME_MANAGER_DIR / "daemon.lock"
EVENTS_PATH = RUNTIME_MANAGER_DIR / "events.jsonl"
DAEMON_STDOUT_PATH = RUNTIME_MANAGER_DIR / "daemon.out.log"
DAEMON_STDERR_PATH = RUNTIME_MANAGER_DIR / "daemon.err.log"
DAEMON_LOG_MAX_BYTES = 64 * 1024 * 1024
DAEMON_LOG_BACKUP_COUNT = 3

LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
PYTHON_LAUNCHER_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
LAUNCHER_STATE_PATH = RUNTIME_ROOT / "launcher" / "state.json"

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
