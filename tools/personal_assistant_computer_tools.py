"""Assistant-only bridge; operator consent cannot be changed by model tools."""
import json

from core.web.services import personal_assistant_computer_service as service
from tools.personal_assistant_tools import _identity


def _invoke(action, observation_id="", element_id="", text="", _cancel_checker=None):
    from core.infrastructure.tool_result_budget import ToolResultBudget, register_tool_result_budget
    for name in ("personal_assistant_computer_observe_tool", "personal_assistant_computer_action_tool"):
        register_tool_result_budget(name, ToolResultBudget(max_model_chars=24000))
    try:
        runtime = _identity()
        owner = tuple(str(runtime.get(key) or "") for key in ("agentId", "sessionId", "turnId"))
        result = service.execute(owner, action=action, observation_id=observation_id,
                                 element_id=element_id, text=text, cancel_checker=_cancel_checker)
    except ValueError:
        result = {"ok": False, "status": "blocked", "message": "需要已就绪的个人助理原生会话与窗口授权。"}
    return json.dumps(result, ensure_ascii=False)


def personal_assistant_computer_observe_tool(_cancel_checker=None) -> str:
    """Read the operator-selected window's screenshot and UIA; no window selection."""
    return _invoke("observe", _cancel_checker=_cancel_checker)


def personal_assistant_computer_action_tool(action: str, observation_id: str, element_id: str = "", text: str = "",
                                           _cancel_checker=None) -> str:
    """One fresh observation, one operator-confirmed background action; never retry."""
    return _invoke(action, observation_id, element_id, text, _cancel_checker)
