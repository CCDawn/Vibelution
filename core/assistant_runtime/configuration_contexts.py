"""Ephemeral completion proof for private configuration control recovery.

Only the owning configuration worker can publish completion, after its native
reference fence has exited. These records contain no configuration or task data.
Unknown release outcomes stay pinned until the exact Launcher host acknowledges
the proof; an ordinary completed/released scope may be evicted safely.
"""
from dataclasses import dataclass
import re
import threading


_LOCK = threading.Lock()
_LIMIT = 512


@dataclass
class _Context:
    broker: object
    worker: threading.Thread
    complete: bool = False
    released: bool = False


_CONTEXTS: dict[str, _Context] = {}
_ACKNOWLEDGED: dict[str, object] = {}


def _remember_ack(context_id, broker):
    while len(_ACKNOWLEDGED) >= _LIMIT:
        del _ACKNOWLEDGED[next(iter(_ACKNOWLEDGED))]
    _ACKNOWLEDGED[context_id] = broker


def valid_context_id(context_id):
    return isinstance(context_id, str) and re.fullmatch(r"cfg-[a-f0-9-]{32,64}", context_id) is not None


def register(broker, context_id):
    if not valid_context_id(context_id):
        raise ValueError("Invalid configuration context")
    with _LOCK:
        if context_id in _CONTEXTS or context_id in _ACKNOWLEDGED:
            raise ValueError("Configuration context already exists")
        if len(_CONTEXTS) >= _LIMIT:
            for key, value in list(_CONTEXTS.items()):
                if value.complete and value.released:
                    _remember_ack(key, value.broker)
                    del _CONTEXTS[key]
                    if len(_CONTEXTS) < _LIMIT:
                        break
        if len(_CONTEXTS) >= _LIMIT:
            raise RuntimeError("Configuration context recovery is pending")
        _CONTEXTS[context_id] = _Context(broker, threading.current_thread())


def complete(broker, context_id, *, released):
    from core.infrastructure.model_reference_fence import model_reference_fence_owned
    # The worker must have exited all configuration mutation scopes before its
    # main-only registry reservation can be recovered, even if release RPC failed.
    if model_reference_fence_owned():
        return False
    with _LOCK:
        value = _CONTEXTS.get(context_id)
        if value is None or value.broker is not broker or value.worker is not threading.current_thread():
            return False
        value.complete = True
        value.released = released is True
        return True


def owned(broker, context_id):
    with _LOCK:
        value = _CONTEXTS.get(context_id)
        return value is not None and value.broker is broker and value.worker is threading.current_thread()


def state(broker, context_id):
    with _LOCK:
        value = _CONTEXTS.get(context_id)
        known = value is not None and value.broker is broker
        return {"schemaVersion": 1, "contextId": context_id, "known": known,
                "workComplete": bool(known and value.complete)}


def acknowledge(broker, context_id):
    with _LOCK:
        if _ACKNOWLEDGED.get(context_id) is broker:
            return {"schemaVersion": 1, "contextId": context_id, "acknowledged": True}
        value = _CONTEXTS.get(context_id)
        accepted = value is not None and value.broker is broker and value.complete
        if accepted:
            _remember_ack(context_id, broker)
            del _CONTEXTS[context_id]
        return {"schemaVersion": 1, "contextId": context_id, "acknowledged": accepted}
