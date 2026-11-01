"""Preserve exact registered JSON Schema data, never model-supplied controls."""
import hashlib
import json
from collections import OrderedDict
from threading import RLock

_LOCK = RLock()
_EMITTED: OrderedDict[str, None] = OrderedDict()
_MAX_CONTRACTS = 512


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def clear_action_contracts():
    with _LOCK:
        _EMITTED.clear()


def remember_action_contract(contract):
    """Called only by the local registered describe producer, never tool data."""
    raw = _canonical({"source": "launcher-assistant", "untrustedContent": True, **contract})
    if len(raw) <= 8000:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        with _LOCK:
            _EMITTED[digest] = None
            _EMITTED.move_to_end(digest)
            while len(_EMITTED) > _MAX_CONTRACTS:
                _EMITTED.popitem(last=False)


def project_action_contract(content: str, *, tool_name: str) -> str | None:
    if tool_name != "personal_assistant_action_tool" or len(content) > 8000:
        return None

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate contract field")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("Invalid contract number")

    try:
        payload = json.loads(content, object_pairs_hook=unique, parse_constant=reject_constant)
        if (not isinstance(payload, dict) or payload.get("source") != "launcher-assistant"
            or payload.get("untrustedContent") is not True or type(payload.get("contractVersion")) is not int
            or payload["contractVersion"] != 1 or not isinstance(payload.get("action"), str)):
            return None
        canonical = _canonical(payload)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        # Every byte of the decoded schema must match a contract emitted by
        # this host's registered describe producer. Markers alone never grant
        # an exemption, and rebinding/unbinding clears this finite epoch cache.
        with _LOCK:
            if digest not in _EMITTED:
                return None
        return canonical
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError):
        return None
