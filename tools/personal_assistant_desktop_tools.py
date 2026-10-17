"""Canonical personal-assistant identity boundary for the opt-in CUA profile."""
from __future__ import annotations

import json

from core.web.services import personal_assistant_desktop_service as service
from tools.personal_assistant_tools import _identity


def _invoke(action, observation_id="", text="", _cancel_checker=None):
    try:
        runtime = _identity()
        owner = tuple(str(runtime.get(key) or "").strip() for key in ("agentId", "sessionId", "turnId"))
        result = service.execute(owner, action=action, observation_id=observation_id,
                                 text=text, cancel_checker=_cancel_checker)
    except ValueError:
        result = {"ok": False, "status": "blocked", "message": "仅允许已绑定且就绪的个人助理原生轮次。"}
    return json.dumps(result, ensure_ascii=False)


def personal_assistant_desktop_observe_tool(_cancel_checker=None) -> str:
    """Read only the operator-authorized Notepad test document, using UIA."""
    return _invoke("observe", _cancel_checker=_cancel_checker)


def personal_assistant_desktop_action_tool(action: str, observation_id: str = "", text: str = "",
                                         _cancel_checker=None) -> str:
    """launch/type_text/save/save_foreground/end; native authorization owns approval."""
    return _invoke(action, observation_id, text, _cancel_checker)
