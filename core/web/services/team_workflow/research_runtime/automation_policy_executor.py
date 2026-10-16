"""Automation policy kill switch (retired auto-advance machine, thin layer).

The T8 auto-advance ladder (activation credential, G12 calibration gate,
drain mode, capability switches, the per-decision-point executors and the
activation audit store) was retired together with the challenge-cup
archive cut: the ladder never activated and the plan documents mark T8 as
historical ("T8 不再收口").  What survives here is the one piece other
surfaces still depend on to keep retired automation dormant:

* :func:`kill_switch_enabled` — the global auto-advance kill switch.
  ``VIBELUTION_AUTO_ADVANCE_DISABLED`` truthy OR challenge archive mode
  (封存模式, ``archive_mode``) being on means no auto-advance may run
  anywhere.  ``runtime_factory._sweep_auto_advance_closure_best_effort``
  consults it before the (still-live) budget-exhaustion closure sweep; the
  archived-chain guards in ``outbox_pump`` / ``reaper`` / ``web.lifecycle``
  read ``archive_mode`` directly and do not import this module.
"""

from __future__ import annotations

import os

AUTO_ADVANCE_DISABLED_ENV = "VIBELUTION_AUTO_ADVANCE_DISABLED"

_KILL_SWITCH_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def kill_switch_enabled() -> bool:
    """True when auto-advance must not execute anywhere.

    Two sources: the ``VIBELUTION_AUTO_ADVANCE_DISABLED`` env truthy, or
    challenge archive mode (封存模式) being on — archiving a batch means
    read-only visibility, so every auto-advance decision stays dormant.
    """

    if os.environ.get(AUTO_ADVANCE_DISABLED_ENV, "").strip().lower() in (
        _KILL_SWITCH_TRUE_VALUES
    ):
        return True
    from .archive_mode import challenge_archive_mode_enabled

    return challenge_archive_mode_enabled()


__all__ = [
    "AUTO_ADVANCE_DISABLED_ENV",
    "kill_switch_enabled",
]
