"""Narrow native Session adapter. No model invocation or transcript persistence."""
from __future__ import annotations

from urllib.parse import urlencode

from .store import WorkflowError, team


class SessionUnavailable(WorkflowError):
    """A confirmed unavailable identity, distinguished from transient IO errors."""

    def __init__(self, message: str, *, safe_new_attempt: bool = False):
        super().__init__(message)
        self.safe_new_attempt = safe_new_attempt


def _inactive(attempt: dict, detail: dict | None) -> bool:
    from core.web.services.session_service import get_session_turn_completion_snapshot

    result = get_session_turn_completion_snapshot(attempt["sessionId"], attempt["turnId"])
    if (not detail and result.get("completionSource") == "missing_conversation"
            and result.get("isRunning") is False):
        return True
    try:
        chain = _chain(attempt)
    except SessionUnavailable:
        return False
    effective = chain[-1]
    result = get_session_turn_completion_snapshot(attempt["sessionId"], effective)
    return bool(effective and result.get("turnId") == effective
                and result.get("terminal") and result.get("completionSource") == "turn_journal")


def validate_owner(team_id: str, agent_id: str) -> None:
    roster = team(team_id)
    if roster.get("status") == "archived":
        raise WorkflowError("已归档团队不能执行流程。")
    if not agent_id or agent_id not in {
        str(member.get("agentId") or "") for member in roster.get("members", [])
        if isinstance(member, dict) and member.get("status") != "archived"
    }:
        raise WorkflowError("步骤负责人不是当前团队成员。")
    from core.web.services.agent_directory_service import get_agent

    if not get_agent(agent_id, include_archived=False):
        raise WorkflowError("步骤负责人当前不可用。")


def create(attempt: dict, run: dict, step: dict) -> str:
    from core.web.services import session_service as sessions
    from core.web.services.agent_directory_service import CONVERSATION_INDEX_KIND_HIDDEN

    result = sessions.create_chat_session(
        title=f"{run['flow']['name']} · {step['label']}",
        agent_id=attempt["agentId"],
        conversation_index_kind=CONVERSATION_INDEX_KIND_HIDDEN,
        created_by="generic_team_workflow", activate=False, lightweight=True,
        session_metadata={"source": "generic_team_workflow", "externalTaskId": attempt["key"]},
        idempotency_key=attempt["key"],
    )
    session_id = str(result.get("sessionId") or result.get("id") or "")
    if not session_id:
        raise WorkflowError("原生会话没有返回会话标识。")
    if str(result.get("agentId") or "") != attempt["agentId"]:
        raise WorkflowError("原生会话负责人不匹配。")
    return session_id


def _detail(attempt: dict) -> dict:
    from core.web.services.session_service import get_session_detail

    detail = get_session_detail(attempt["sessionId"], include_secondary=False, message_limit=1)
    if not detail:
        raise SessionUnavailable("原生会话已不存在；确认旧轮次结束后可重试。",
                                 safe_new_attempt=_inactive(attempt, None))
    if str(detail.get("id") or detail.get("sessionId") or "") != attempt["sessionId"]:
        raise SessionUnavailable("原生会话标识不匹配，请打开原会话核查。")
    if str(detail.get("agentId") or "") != attempt["agentId"]:
        raise SessionUnavailable("原生会话负责人已变化，请打开原会话确认旧轮次已结束后重试。",
                                 safe_new_attempt=_inactive(attempt, detail))
    return detail


def submit(attempt: dict, prompt: str) -> str:
    from core.web.services.session_service import submit_session_message

    _detail(attempt)
    result = submit_session_message(
        attempt["sessionId"], prompt, client_submission_id=attempt["key"],
        message_source="generic_team_workflow", lightweight_response=True,
        include_started_turn_id=True,
    )
    turn_id = str(result.get("turnId") or result.get("startedTurnId") or "")
    if not turn_id:
        raise WorkflowError("原生会话没有返回轮次标识。")
    return turn_id


def snapshot(attempt: dict) -> dict:
    from core.web.services.session_service import get_session_turn_completion_snapshot

    detail = _detail(attempt)
    chain = _chain(attempt)
    effective = chain[-1]
    result = get_session_turn_completion_snapshot(attempt["sessionId"], effective)
    anchored = (result.get("completionSource") == "turn_journal" or
                detail.get("lastTurnTerminalTurnId") == effective)
    if result.get("turnId") != effective or not anchored:
        result = {**result, "terminal": False}
    return {**result, "originTurnId": chain[0], "recoveryTurnIds": chain[1:]}


def recovery(attempt: dict) -> str:
    """Reassess a blocked identity without submitting or stopping any work."""
    try:
        _detail(attempt)
        if attempt["turnId"]:
            result = snapshot(attempt)
            succeeded = (result.get("terminalStatus") in {"ready", "completed", "done", "success", "succeeded"}
                         and result.get("assistantTurnId") == result.get("turnId") and result.get("assistantText"))
            if result.get("terminal") and (not succeeded or attempt.get("failureOrigin") == "result_contract"):
                return "safe_new_attempt"
        return "resume_same_identity"
    except SessionUnavailable as exc:
        return "safe_new_attempt" if exc.safe_new_attempt else "unknown_blocked"
    except Exception:
        return "unknown_blocked"


def lookup_turn(attempt: dict) -> str:
    """Recover an accepted dispatch without submitting new work while stopping."""
    from core.web.services import session_service as sessions
    from core.web.services.session import journal_bridge

    events = journal_bridge.load_session_conversation_events_by_correlation(
        attempt["sessionId"], event_type=sessions.EVENT_USER_MESSAGE,
        correlation_id=attempt["key"], project_root=sessions.PROJECT_ROOT,
    )
    return str(events[-1].turn_id or "") if events else ""


def _chain(attempt: dict) -> list[str]:
    """Follow only journal-verified startup-resume children of our own receipt."""
    from core.web.services import session_service as sessions
    from core.web.services.session import journal_bridge

    def events(key: str):
        return journal_bridge.load_session_conversation_events_by_correlation(
            attempt["sessionId"], event_type=sessions.EVENT_USER_MESSAGE,
            correlation_id=key, project_root=sessions.PROJECT_ROOT,
        )

    origin_events = events(attempt["key"])
    if not origin_events:
        raise SessionUnavailable("原生派发记录不存在，请打开原会话核查。")
    origin = origin_events[-1]
    if str((origin.payload or {}).get("source") or "") != "generic_team_workflow":
        raise SessionUnavailable("原生派发记录来源不匹配，请打开原会话核查。")
    chain = [str(origin.turn_id or "")]
    if not chain[0] or (attempt.get("originTurnId") and attempt["originTurnId"] != chain[0]):
        raise SessionUnavailable("原生派发起始轮次不匹配。")
    for _ in range(32):
        rows = events("resume:" + chain[-1])
        if not rows:
            if attempt["turnId"] and attempt["turnId"] not in chain:
                raise SessionUnavailable("流程轮次不属于原生恢复链。")
            return chain
        event = rows[-1]
        payload = event.payload or {}
        metadata = payload.get("metadata") or {}
        child = str(event.turn_id or "")
        if (payload.get("source") != "hot_restart_resume" or
                metadata.get("kind") != "hot_restart_resume" or
                metadata.get("recoverySource") != "startup_sweep" or
                metadata.get("recoveredTurnId") != chain[-1] or
                not child or child in chain or len({row.turn_id for row in rows}) != 1):
            raise SessionUnavailable("原生恢复链证据不匹配，请打开原会话核查。")
        chain.append(child)
    raise SessionUnavailable("原生恢复链超过32次上限。")


def stop(attempt: dict) -> None:
    from core.web.services.session_service import request_stop_session_turn

    _detail(attempt)
    effective = _chain(attempt)[-1]
    request_stop_session_turn(attempt["sessionId"], expected_turn_id=effective, fast_ack=True)


def chat_url(attempt: dict) -> str:
    return "/chat?" + urlencode({"session": attempt["sessionId"], "turn": attempt["turnId"]})
