"""Runtime status (turn status bar) feature flags."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Mapping

from config.public_config import load_public_config
from core.infrastructure.feature_gate import resolve_feature_decision

logger = logging.getLogger(__name__)

_RUNTIME_STATUS_ENABLED_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "runtime_status_enabled_override",
    default=None,
)
_DEFAULT_RUNTIME_STATUS_ENABLED = True


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _agent_runtime_status_policy(agent: Mapping[str, Any] | None) -> dict[str, bool]:
    if not isinstance(agent, Mapping):
        return {
            "enabled": True,
            "inject_into_model": True,
            "show_in_status_rail": True,
        }
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), Mapping) else {}
    raw = metadata.get("runtimeStatus") if isinstance(metadata, Mapping) else None
    if not isinstance(raw, Mapping):
        raw = agent.get("runtimeStatus") if isinstance(agent.get("runtimeStatus"), Mapping) else {}
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "enabled": _coerce_bool(raw.get("enabled"), True),
        "inject_into_model": _coerce_bool(raw.get("injectIntoModel", raw.get("inject_into_model")), True),
        "show_in_status_rail": _coerce_bool(raw.get("showInStatusRail", raw.get("show_in_status_rail")), True),
    }


def is_runtime_status_enabled(
    public_config: dict[str, Any] | None = None,
    *,
    agent: Mapping[str, Any] | None = None,
    requested: bool | None = None,
) -> bool:
    """Operator + agent gate; session/request may only narrow (requested=False)."""

    config = public_config
    if config is None:
        try:
            config = load_public_config()
        except Exception as exc:
            logger.warning("Failed to load public config for runtime_status flag; falling back to defaults. error=%s", exc)
            config = {}

    override = _RUNTIME_STATUS_ENABLED_OVERRIDE.get()
    if requested is None:
        requested = override

    decision = resolve_feature_decision(
        "runtime_status",
        config=config,
        requested=requested,
    )
    if not decision.effective_enabled:
        return False
    policy = _agent_runtime_status_policy(agent)
    if not policy["enabled"]:
        return False
    return True


def is_runtime_status_inject_enabled(
    public_config: dict[str, Any] | None = None,
    *,
    agent: Mapping[str, Any] | None = None,
    requested: bool | None = None,
) -> bool:
    if not is_runtime_status_enabled(public_config, agent=agent, requested=requested):
        return False
    return _agent_runtime_status_policy(agent)["inject_into_model"]


def is_runtime_status_rail_enabled(
    public_config: dict[str, Any] | None = None,
    *,
    agent: Mapping[str, Any] | None = None,
    requested: bool | None = None,
) -> bool:
    if not is_runtime_status_enabled(public_config, agent=agent, requested=requested):
        return False
    return _agent_runtime_status_policy(agent)["show_in_status_rail"]


@contextmanager
def runtime_status_enabled_override(enabled: bool | None):
    if enabled is None:
        yield
        return
    token = _RUNTIME_STATUS_ENABLED_OVERRIDE.set(bool(enabled))
    try:
        yield
    finally:
        _RUNTIME_STATUS_ENABLED_OVERRIDE.reset(token)


def default_agent_runtime_status_policy() -> dict[str, Any]:
    return {
        "enabled": True,
        "injectIntoModel": True,
        "showInStatusRail": True,
    }
