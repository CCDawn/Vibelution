"""Error types shared by the operator-config lock helpers.

Kept dependency-free so any config module (and the Launcher bridges) can import
it without pulling in ``public_config``.
"""
from __future__ import annotations


class ConfigEditLockBusy(RuntimeError):
    """The operator config edit lock could not be acquired within its budget.

    Subclasses ``RuntimeError`` so existing callers that only catch
    ``RuntimeError`` keep the same behaviour. Read-only callers that merely
    wanted the config to exist (port resolution, public-config loads) catch
    this and degrade to what is already on disk instead of failing the whole
    process: a concurrent writer must not turn a read into an error.
    """
