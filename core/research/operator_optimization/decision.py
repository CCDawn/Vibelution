"""Structured decision contract for the post-evidence operator loop."""

from __future__ import annotations

from typing import Literal

from .contracts import Contract, Identity, Text


class OperatorIterationDecision(Contract):
    """One immutable decision bound to one durable feedback request."""

    schemaVersion: Literal[1] = 1
    decisionId: Identity
    kind: Literal["continue", "stop"]
    reason: Text
    decidedBy: Identity


__all__ = ["OperatorIterationDecision"]
