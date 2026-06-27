"""Compatibility alias for Launcher-owned reset maintenance."""

from __future__ import annotations

import sys

from core.launcher import maintenance_reset as _launcher_reset

sys.modules[__name__] = _launcher_reset
