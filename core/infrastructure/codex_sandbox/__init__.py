"""Cross-platform Codex CLI sandbox adapter package.

The host platform, Codex executable, shell and sandbox argv are resolved
automatically here; the public execution orchestration stays in
``core.infrastructure.codex_cli_sandbox``.
"""

from core.infrastructure.codex_sandbox.environment import (
    sandbox_process_environment,
    scrub_credential_environment,
)
from core.infrastructure.codex_sandbox.platform import host_platform, is_posix, is_windows
from core.infrastructure.codex_sandbox.process import (
    sandbox_popen_kwargs,
    terminate_process_tree,
)
from core.infrastructure.codex_sandbox.resolver import resolve_codex_executable
from core.infrastructure.codex_sandbox.shell import (
    ShellAdapter,
    create_shell_adapter,
)

__all__ = [
    "ShellAdapter",
    "create_shell_adapter",
    "host_platform",
    "is_posix",
    "is_windows",
    "resolve_codex_executable",
    "sandbox_popen_kwargs",
    "sandbox_process_environment",
    "scrub_credential_environment",
    "terminate_process_tree",
]
