"""Read proposals solely from an owned native Turn's committed final answer."""

import json
import re

from pydantic import TypeAdapter, ValidationError

from core.chat.turn_journal import (
    EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED,
    fold_active_events, session_turn_items_from_events,
)
from core.web.services import financial_report_service as reports
from core.web.services.financial_preferences_service import FinancialPreferenceError
from .advisor_contract import Proposal
from .investment import InvestmentProfile

_ADAPTER = TypeAdapter(Proposal)
_FENCE = re.compile(r"^```investment-proposal[ \t]*\r?\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
_MAX_ANSWER = 250_000
_MAX_PROPOSAL = 24_000


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def parse_proposal(answer: str) -> dict | None:
    if not isinstance(answer, str) or len(answer) > _MAX_ANSWER:
        return None
    matches = list(_FENCE.finditer(answer))
    if len(matches) != 1 or answer.count("```investment-proposal") != 1:
        return None
    raw = matches[0].group(1)
    if len(raw) > _MAX_PROPOSAL:
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        if isinstance(value, dict) and value.get("kind") == "profile":
            if not isinstance(value.get("profile"), dict) or set(value["profile"]) != set(InvestmentProfile.model_fields):
                return None
        result = _ADAPTER.validate_python(value).model_dump()
        if result["kind"] == "plan":
            from .workspace import _text
            from core.web.services import financial_market_service as market

            plan = result["plan"]
            plan["title"] = _text(plan["title"], 120)
            plan["rationale"] = _text(plan["rationale"], 2000)
            for order in plan["orders"]:
                order["symbol"] = market.normalize_a_share_symbol(order["symbol"])
            if len({order["symbol"] for order in plan["orders"]}) != len(plan["orders"]):
                return None
        return result
    except (ValueError, TypeError, ValidationError, RecursionError):
        return None


def get_proposal(agent_id: str, session_id: str, turn_id: str) -> dict:
    from .workspace import _agent, _identifier

    _agent(agent_id)
    session_id, turn_id = _identifier(session_id), _identifier(turn_id)
    if not reports._owned_session(agent_id, session_id):
        raise FinancialPreferenceError("未找到此助手拥有的会话", 404)
    try:
        events = reports.session_service.load_session_conversation_events_snapshot(session_id)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise FinancialPreferenceError("会话暂不可读取", 409) from exc
    # Branch markers belong to other Turns too. Fold the complete native
    # snapshot before selecting a Turn, or an edited-away answer can reappear.
    active_events = fold_active_events(events)
    selected = [event for event in active_events if event.session_id == session_id and event.turn_id == turn_id]
    terminals = [event for event in selected if event.event_type in {EVENT_TURN_COMPLETED, EVENT_TURN_FAILED, EVENT_TURN_INTERRUPTED}]
    successful = {"completed", "success", "succeeded", "done"}
    if len(terminals) != 1 or terminals[0].event_type != EVENT_TURN_COMPLETED or terminals[0].status.lower() not in successful:
        return {"proposal": None}
    terminal = terminals[0]
    payload = terminal.payload if isinstance(terminal.payload, dict) else {}
    if any(payload.get(key) for key in ("marker", "errorType", "error_type")) or any(
        payload.get(key) and str(payload[key]).lower() not in successful
        for key in ("terminalReason", "terminal_reason", "finalStatus", "final_status", "resultStatus", "result_status")
    ):
        return {"proposal": None}
    # Project revisions through the native journal; never parse user/tool text.
    items = session_turn_items_from_events(selected, turn_id=turn_id)
    finals = {}
    for item in items:
        if item.get("type") != "assistant_message":
            continue
        identity = (
            str(item.get("invocationId") or ""),
            int(item.get("iteration") or 0),
            str(item.get("itemId") or item.get("id") or ""),
        )
        previous = finals.get(identity)
        revision = (int(item.get("revision") or 0), int(item.get("sequence") or 0))
        if previous is None or revision >= (int(previous.get("revision") or 0), int(previous.get("sequence") or 0)):
            finals[identity] = item
    ordered = sorted(
        (item for item in finals.values() if item.get("channel") == "answer" and item.get("phase") == "final_answer" and item.get("status") == "completed"),
        key=lambda item: int(item.get("sequence") or 0),
    )
    answer = "\n\n".join(str(item.get("text") or "") for item in ordered)
    if re.search(r"(?:本轮已按请求停止[。，]|This turn was stopped (?:as requested|before it started)\.)", answer, re.I):
        return {"proposal": None}
    from .analysis_checks import assess_budget
    from .workspace import get_workspace

    proposal = parse_proposal(answer)
    state = get_workspace(agent_id)
    assessment = assess_budget(answer, active_events, turn_id, state["investmentProfile"], proposal)
    result = {"proposal": None if assessment["issues"] else proposal}
    if assessment["budgetCny"] is not None or assessment["issues"]:
        result["assessment"] = assessment
    return result
