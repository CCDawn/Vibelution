"""Shared local web workbench endpoint helpers."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    import toml as tomllib  # type: ignore[no-redef]

from .paths import ensure_global_config_initialized, resolve_config_path


DEFAULT_WORKBENCH_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
CONFIG_PATH = resolve_config_path()


def coerce_port(value: object, default: int) -> int:
    parsed = parse_port(value)
    return parsed if parsed is not None else int(default)


def parse_port(value: object) -> int | None:
    try:
        port = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return port if 0 < port < 65536 else None


def _configured_workbench_port(key: str, default: int) -> int:
    ensure_global_config_initialized(CONFIG_PATH)
    try:
        payload = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return int(default)
    workbench = payload.get("workbench", {})
    if not isinstance(workbench, dict):
        return int(default)
    return coerce_port(workbench.get(key), default)


def _first_env_port(names: tuple[str, ...]) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def configured_backend_port(*, default: int = DEFAULT_BACKEND_PORT, include_env: bool = True) -> int:
    configured_port = _configured_workbench_port("backend_port", default)
    raw_override = _first_env_port(("VIBELUTION_PORT", "AGENT_WORKBENCH_BACKEND_PORT")) if include_env else ""
    if include_env and raw_override:
        env_port = parse_port(raw_override)
        if env_port is not None:
            return env_port
    return configured_port


def configured_frontend_port(*, default: int = DEFAULT_FRONTEND_PORT, include_env: bool = True) -> int:
    configured_port = _configured_workbench_port("frontend_port", default)
    raw_override = _first_env_port(("VIBELUTION_FRONTEND_PORT", "AGENT_WORKBENCH_FRONTEND_PORT")) if include_env else ""
    if include_env and raw_override:
        env_port = parse_port(raw_override)
        if env_port is not None:
            return env_port
    return configured_port


def backend_url(*, host: str = DEFAULT_WORKBENCH_HOST, port: int | None = None) -> str:
    resolved_port = coerce_port(port, configured_backend_port())
    return f"http://{host}:{resolved_port}"


__all__ = [
    "DEFAULT_BACKEND_PORT",
    "DEFAULT_FRONTEND_PORT",
    "DEFAULT_WORKBENCH_HOST",
    "CONFIG_PATH",
    "backend_url",
    "coerce_port",
    "configured_backend_port",
    "configured_frontend_port",
    "parse_port",
]
