"""Select an existing native source; the repair coordinator stays shared."""
from __future__ import annotations

from . import research_source, store


def reference(record: dict) -> dict:
    steps = (record.get("flow") or {}).get("steps") or []
    if len(steps) != 1:
        raise store.WorkflowError("监督来源必须是单个原生任务引用。")
    step = steps[0]
    kind = step.get("kind")
    field = {"research": "researchSource", "session": "sessionSource"}.get(kind)
    if field is None or not isinstance(step.get(field), dict):
        raise store.WorkflowError("未知的原生监督来源。")
    return {"kind": kind, field: step[field]}


def adapter(record: dict):
    if reference(record)["kind"] == "research":
        return research_source
    from . import session_source
    return session_source


def identity(record: dict) -> dict:
    ref = reference(record)
    return ref if ref["kind"] == "research" else adapter(record).identity(record)


def observe(record: dict) -> dict:
    return adapter(record).observe(record)


def fence(record: dict) -> str:
    return adapter(record).fence(record)


def replay(record: dict) -> str:
    return adapter(record).replay(record)
