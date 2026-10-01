"""Carry one session stop event onto the callables that can actually see it.

The model watcher and the shell killer receive a fresh callable, not the
session interrupt checker. Bound methods and lambdas do not keep attributes
set on that checker, so the stop event has to be copied onto the probe.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

STOP_EVENT_ATTR = "_vibelution_stop_event"


def stop_event_of(source: Any) -> threading.Event | None:
    event = getattr(source, STOP_EVENT_ATTR, None)
    if isinstance(event, threading.Event):
        return event
    return None


def attach_stop_event(checker: Any, event: Any) -> None:
    if isinstance(event, threading.Event):
        setattr(checker, STOP_EVENT_ATTR, event)


def bind_stop_probe(
    checker: Callable[[], str] | None,
    source: Any,
) -> Callable[[], str] | None:
    """Return ``checker`` unchanged, or a probe that also carries the stop event."""

    if not callable(checker):
        return None
    event = stop_event_of(source)
    if event is None or stop_event_of(checker) is event:
        return checker

    def probe() -> str:
        try:
            value = checker()
        except Exception:  # noqa: BLE001 - a broken checker must not keep the request open
            return ""
        return str(value or "")

    setattr(probe, STOP_EVENT_ATTR, event)
    return probe
