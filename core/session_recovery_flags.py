"""Session recovery (restart auto-recovery) feature flags."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Mapping

from config.public_config import load_public_config
from core.infrastructure.feature_gate import resolve_feature_decision

logger = logging.getLogger(__name__)

_SESSION_RECOVERY_ENABLED_OVERRIDE: ContextVar[bool | None] = ContextVar(
    "session_recovery_enabled_override",
    default=None,
)
_DEFAULT_SESSION_RECOVERY_ENABLED = True
_DEFAULT_SESSION_RECOVERY_MAX_AUTO_RETRIES = 2
_MIN_SESSION_RECOVERY_MAX_AUTO_RETRIES = 0
_MAX_SESSION_RECOVERY_MAX_AUTO_RETRIES = 5


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
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


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _clamp_max_auto_retries(value: int) -> int:
    return max(
        _MIN_SESSION_RECOVERY_MAX_AUTO_RETRIES,
        min(_MAX_SESSION_RECOVERY_MAX_AUTO_RETRIES, value),
    )


def _session_recovery_section(source: Any) -> Any:
    """Defensive read of the ``session_recovery`` section from any config shape."""
    if source is None:
        return None
    try:
        if isinstance(source, Mapping):
            return source.get("session_recovery")
        return getattr(source, "session_recovery", None)
    except Exception:
        return None


def is_session_recovery_enabled(
    public_config: dict[str, Any] | None = None,
    *,
    requested: bool | None = None,
) -> bool:
    """Operator gate; callers may only narrow (requested=False), never force-enable."""

    config = public_config
    if config is None:
        try:
            config = load_public_config()
        except Exception as exc:
            logger.warning(
                "Failed to load public config for session_recovery flag; falling back to defaults. error=%s",
                exc,
            )
            config = {}

    override = _SESSION_RECOVERY_ENABLED_OVERRIDE.get()
    if requested is None:
        requested = override
    if requested is not None:
        requested = _coerce_bool(requested, True)

    decision = resolve_feature_decision(
        "session_recovery",
        config=config,
        requested=requested,
    )
    return decision.effective_enabled


def session_recovery_max_auto_retries(source: Any | None = None) -> int:
    """每个被打断对象的自动重发上限；读不到配置或缺字段时回缺省 2。"""

    payload = source
    if payload is None:
        try:
            payload = load_public_config()
        except Exception as exc:
            logger.warning(
                "Failed to load public config for session_recovery flag; falling back to defaults. error=%s",
                exc,
            )
            payload = {}

    section = _session_recovery_section(payload)
    raw: Any = None
    if isinstance(section, Mapping):
        raw = section.get("maxAutoRetries", section.get("max_auto_retries"))
    elif section is not None:
        raw = getattr(section, "max_auto_retries", None)
    if raw is None:
        return _DEFAULT_SESSION_RECOVERY_MAX_AUTO_RETRIES
    return _clamp_max_auto_retries(
        _coerce_int(raw, _DEFAULT_SESSION_RECOVERY_MAX_AUTO_RETRIES)
    )


@contextmanager
def session_recovery_enabled_override(enabled: bool | None):
    if enabled is None:
        yield
        return
    token = _SESSION_RECOVERY_ENABLED_OVERRIDE.set(_coerce_bool(enabled, False))
    try:
        yield
    finally:
        _SESSION_RECOVERY_ENABLED_OVERRIDE.reset(token)
