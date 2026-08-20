"""Hypothesis-first meeting runtime: bind MeetingRound lifecycle to chat-room discussion.

This module is the meeting-service entry point for the hypothesis-first flow
(overall design §3.2/§4).  ``open_hypothesis_review_meeting`` turns a
hypothesis selection payload into a ``hypothesis_review`` MeetingRound and
opens the first real discussion round in the team's linked chat room; the room
round carries ``config.meetingRoundId``/scope and the meeting record carries
``linkedChatRoomId``/``chatRoomRoundIds`` (two-way binding).
``run_meeting_discussion`` drives the remaining discussion rounds with the
Virtual Lab / AutoGen termination trio: a maxMessages runaway cap, a
convergence signal (a round where every speaker passes), and a check after
every round.  ``draft_meeting_digest`` builds the Coordinator digest draft
from the bound room messages (deterministic DEV fixture drafter by default;
a real Coordinator model drafter can be injected through ``drafter``) and
moves the meeting to ``awaiting_approval`` for the human closure gate.

Only hypothesis-first ``hypothesis_review`` rounds are auto-opened here;
stage coordination elsewhere stays ``manual_only``.  The discussion driver is
synchronous (DEV/fixture path); asynchronous production wiring belongs to the
orchestration batch.  No real model is called unless the caller injects one.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from core.research.competition.resources import (
    CompetitionResourceError,
    load_science_question_catalog,
)
from core.research.workflow.contracts import ContractValidationError
from core.web.services.team_workflow import meeting_rounds

DEFAULT_MAX_MESSAGES = 40
MAX_SELECTED_CANDIDATES = 16
MEETING_SOURCE = "hypothesis_first_meeting"
# The opening topic embeds one line per selected candidate (plus header/footer
# lines), so meeting rounds need a line budget beyond the generic chat-room
# topic cap: 3 framing lines + rules + host line + one line per candidate.
MEETING_TOPIC_MAX_LINES = MAX_SELECTED_CANDIDATES + 8

_DEFAULT_AGENDA = (
    "回顾入选假说候选与赛题已有证据",
    "逐候选评审机制、证伪路径与可检验预测",
    "识别知识缺口并决定是否搜集更多证据",
)
_DEFAULT_AGENDA_QUESTIONS = (
    "每个候选的核心机制是什么？",
    "哪些证据支持或挑战该候选？",
    "还需要搜集哪些知识才能收敛？",
)
_DEFAULT_AGENDA_RULES = (
    "结论必须引用证据或消息来源",
    "没有新内容时回复 pass",
    "分歧必须显式记录，不得省略",
    # The closure digest extracts evidence requests by this marker; without
    # teaching the format the review can never emit a search envelope and the
    # first source-collection round stays blocked (observed live on SCI-001).
    "认为需要补充资料时，必须独占一行输出 "
    'EVIDENCE_REQUEST: {"rationale":"为何需要","candidateRefs":["候选ID"],'
    '"searchEnvelope":{"keywords":["检索关键词"],"sourceTypes":["paper"],'
    '"evidenceLevels":["peer_reviewed"]},'
    '"requirements":{"minEvidenceLevel":"medium","completeness":"stage-one"}} '
    "（JSON 字段可按需增删，candidateRefs 用本轮候选 ID）；本轮无资料缺口则不输出该标记",
    "共识与分歧必须独占一行，格式：AGREE: <一条共识> 或 DISAGREE: <一条分歧>",
)

CANDIDATE_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation"
_GENERATION_AGENDA = (
    "围绕赛题提出可证伪的候选假说",
    "逐一评估候选的机制合理性与检验路径",
    "收敛出供人工选择的候选清单",
)
_GENERATION_AGENDA_QUESTIONS = (
    "这个赛题最可能的机制解释有哪些？",
    "每个候选假说的可检验预测是什么？",
    "哪些候选应该进入人工选择清单？",
)
_GENERATION_AGENDA_RULES = (
    "本次会议中提出候选是假说生成临时职责，优先于日常岗位边界；每位参与者必须直接提出至少一个可证伪候选，不得等待其他角色代为提出",
    "每个候选假说独占一行，格式：CANDIDATE: <候选编号> | <假说陈述> | <提出理由>",
    "结论必须引用证据或消息来源",
    "没有新内容时回复 pass",
    "分歧必须显式记录，不得省略",
)

_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
_DISCUSSION_DRIVER = threading.local()


class ResearchMeetingRuntimeError(RuntimeError):
    """Base error for the hypothesis-first meeting runtime."""


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _selection_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    selection = request.get("selection") if isinstance(request.get("selection"), Mapping) else {}
    merged = dict(selection)
    for key in ("selectionId", "questionId", "selectedCandidateIds", "decidedBy"):
        if key in request and request.get(key) is not None:
            merged[key] = request.get(key)
    return merged


def _validated_selection(request: Mapping[str, Any]) -> dict[str, Any]:
    selection = _selection_payload(request)
    selection_id = str(selection.get("selectionId") or "").strip()
    if not selection_id:
        raise ContractValidationError(
            "opening a hypothesis review meeting requires a selectionId"
        )
    selected_candidate_ids = _normalized_str_list(selection.get("selectedCandidateIds"))
    if not selected_candidate_ids:
        raise ContractValidationError(
            "opening a hypothesis review meeting requires a non-empty selectedCandidateIds list"
        )
    if len(selected_candidate_ids) > MAX_SELECTED_CANDIDATES:
        raise ContractValidationError(
            f"selectedCandidateIds supports at most {MAX_SELECTED_CANDIDATES} candidates"
        )
    if len(set(selected_candidate_ids)) != len(selected_candidate_ids):
        raise ContractValidationError("selectedCandidateIds must not contain duplicates")
    scope_question = str(request.get("question") or "").strip()
    question_id = str(selection.get("questionId") or "").strip()
    if question_id and scope_question and question_id != scope_question:
        raise ContractValidationError(
            "selection questionId does not match the meeting scope question"
        )
    return {
        "selectionId": selection_id,
        "questionId": question_id or scope_question,
        "selectedCandidateIds": selected_candidate_ids,
        "decidedBy": str(selection.get("decidedBy") or "").strip(),
    }


def _ensure_linked_room(team_id: str) -> tuple[dict[str, Any], str]:
    from core.web.services import chat_room_service, team_service
    from core.web.services.team import chat_room_links

    team = team_service.get_team(team_id)
    room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not room_id:
        chat_room_links.sync_team_chat_room(team_id)
        team = team_service.get_team(team_id)
        room_id = str(team.get("linkedChatRoomId") or "").strip()
    if not room_id:
        raise ResearchMeetingRuntimeError(
            "Team has no linked chat room for the hypothesis review meeting."
        )
    if chat_room_service.get_chat_room_compact(room_id) is None:
        raise ResearchMeetingRuntimeError(
            "Team linked chat room is missing; sync the team chat room first."
        )
    return team, room_id


def _assert_participants_in_room(room_id: str, participants: Sequence[str]) -> None:
    from core.web.services import chat_room_service

    room_detail = chat_room_service.get_chat_room_detail(room_id)
    if room_detail is None:
        raise ResearchMeetingRuntimeError("Team linked chat room not found.")
    room_agent_ids = {
        str(item.get("agentId") or "").strip()
        for item in list(room_detail.get("participants") or [])
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    }
    missing = [agent_id for agent_id in participants if agent_id not in room_agent_ids]
    if missing:
        raise ContractValidationError(
            "meeting participants must be members of the team linked chat room: "
            + ", ".join(missing)
        )


def _opening_topic(
    meeting_round_id: str,
    selection: Mapping[str, Any],
    agenda: Sequence[str],
    candidate_contexts: Sequence[Mapping[str, Any]] = (),
) -> str:
    candidates = list(selection.get("selectedCandidateIds") or [])
    candidate_contexts = {
        str(item.get("candidateId") or "").strip(): item
        for item in candidate_contexts
        if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
    }
    lines = [
        f"假说评审会议开幕（{meeting_round_id}）：{str(selection.get('questionId') or '').strip() or '未命名赛题'}",
        "议程：" + "；".join(str(item) for item in agenda),
        "入选候选详情：",
        *[
            (
                f"- {candidate_id} | 陈述："
                f"{str((candidate_contexts.get(candidate_id) or {}).get('claim') or '').strip() or '[缺少候选正文]'}"
                " | 机制："
                f"{str((candidate_contexts.get(candidate_id) or {}).get('rationale') or '').strip() or '[缺少机制理由]'}"
            )
            for candidate_id in candidates
        ],
        "规则：" + "；".join(_DEFAULT_AGENDA_RULES),
        "Coordinator 主持开场，成员按轮回应，无新内容回复 pass。",
    ]
    return "\n".join(lines)


def _catalog_question_context(question_id: str) -> dict[str, str]:
    """Return the frozen catalog context needed by a generation discussion."""

    normalized_question_id = str(question_id or "").strip().upper()
    try:
        catalog = load_science_question_catalog()
    except CompetitionResourceError:
        return {}
    for item in catalog.get("questions") or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("id") or "").strip().upper() != normalized_question_id:
            continue
        return {
            "questionText": str(item.get("question_en") or "").strip(),
            "domain": str(item.get("domain") or "").strip(),
        }
    return {}


def _generation_opening_topic(
    meeting_round_id: str,
    question_id: str,
    agenda: Sequence[str],
    *,
    question_context: Mapping[str, str] | None = None,
) -> str:
    context = question_context or {}
    lines = [
        f"候选假说生成讨论开幕（{meeting_round_id}）：{question_id or '未命名赛题'}",
    ]
    question_text = str(context.get("questionText") or "").strip()
    domain = str(context.get("domain") or "").strip()
    if question_text:
        lines.append("赛题正文：" + question_text)
    if domain:
        lines.append("赛题领域：" + domain)
    lines.extend(
        [
            "议程：" + "；".join(str(item) for item in agenda),
            "规则：" + "；".join(_GENERATION_AGENDA_RULES),
            "Coordinator 主持开场，成员按轮回应，无新内容回复 pass。",
        ]
    )
    return "\n".join(lines)


def _follow_up_topic(discussion_round_index: int) -> str:
    return (
        f"假说评审第 {discussion_round_index} 轮（批评与修订）："
        "逐条批评上一轮观点、补充证据或新分歧；没有新内容请回复 pass。"
    )


def _round_config(
    meeting_round: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    discussion_round_index: int,
    team_id: str = "",
) -> dict[str, Any]:
    return {
        "source": MEETING_SOURCE,
        "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
        "meetingType": str(meeting_round.get("meetingType") or "hypothesis_review"),
        "meetingStage": str(meeting_round.get("stage") or ""),
        "meetingRoundType": str(meeting_round.get("roundType") or ""),
        "selectionId": str(selection.get("selectionId") or ""),
        "scopeHash": str(meeting_round.get("scopeHash") or ""),
        **{field: str(meeting_round.get(field) or "") for field in _SCOPE_FIELDS},
        "agentId": str(meeting_round.get("agentId") or ""),
        "mode": str(meeting_round.get("mode") or ""),
        "teamId": str(team_id or meeting_round.get("teamId") or "").strip(),
        "discussionRoundIndex": discussion_round_index,
        "agenda": list(meeting_round.get("agenda") or []),
        "agendaQuestions": list(meeting_round.get("agendaQuestions") or []),
        "agendaRules": list(meeting_round.get("agendaRules") or []),
        "selectedCandidateIds": list(selection.get("selectedCandidateIds") or []),
    }


def _round_id_from_start_result(result: Mapping[str, Any], meeting_round_id: str) -> str:
    round_id = str(result.get("roundId") or "").strip()
    if round_id:
        return round_id
    bound_rounds = [
        item
        for item in list(result.get("rounds") or [])
        if isinstance(item, dict)
        and str((item.get("config") or {}).get("meetingRoundId") or "").strip() == meeting_round_id
    ]
    if bound_rounds:
        return str(bound_rounds[-1].get("roundId") or "").strip()
    fallback = str(result.get("activeRoundId") or "").strip()
    if fallback:
        return fallback
    rounds = [item for item in list(result.get("rounds") or []) if isinstance(item, dict)]
    if rounds:
        return str(rounds[-1].get("roundId") or "").strip()
    raise ResearchMeetingRuntimeError("chat room round did not return a roundId")


def open_hypothesis_review_meeting(
    team_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    agent_runner: Callable[..., dict[str, Any]] | None = None,
    background: bool = True,
    candidate_contexts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Open a hypothesis-review meeting from a hypothesis selection payload.

    Creates the ``hypothesis_review`` MeetingRound (stage ``hypothesis``,
    roundType ``decision_gate`` by default) and starts the first discussion
    round in the team's linked chat room with the meeting binding in config.
    Reopening with an identical payload reuses the existing meeting and its
    bound discussion round instead of starting a duplicate.
    """
    from core.web.services import chat_room_service

    request = dict(payload) if isinstance(payload, Mapping) else {}
    selection = _validated_selection(request)
    participants = _normalized_str_list(request.get("participants"))
    if not participants:
        raise ContractValidationError(
            "opening a hypothesis review meeting requires at least one participant"
        )
    team, room_id = _ensure_linked_room(str(team_id or "").strip())
    _assert_participants_in_room(room_id, participants)

    agenda = _normalized_str_list(request.get("agenda")) or list(_DEFAULT_AGENDA)
    agenda_questions = _normalized_str_list(request.get("agendaQuestions")) or list(
        _DEFAULT_AGENDA_QUESTIONS
    )
    agenda_rules = _normalized_str_list(request.get("agendaRules")) or list(_DEFAULT_AGENDA_RULES)
    create_request = {
        key: request.get(key)
        for key in (
            *_SCOPE_FIELDS,
            "agentId",
            "mode",
            "meetingRoundId",
            "rounds",
            "startedAt",
        )
        if key in request and request.get(key) is not None
    }
    created = meeting_rounds.create_meeting_round(
        team["teamId"],
        {
            **create_request,
            "meetingType": "hypothesis_review",
            "stage": str(request.get("stage") or "hypothesis").strip().lower(),
            "roundType": str(request.get("roundType") or "decision_gate").strip().lower(),
            "participants": participants,
            "participantRoleIds": _normalized_str_list(request.get("participantRoleIds")),
            "discussionItemRefs": [
                f"hypothesis_candidate:{candidate_id}"
                for candidate_id in selection["selectedCandidateIds"]
            ],
            "inputArtifactRefs": [
                f"hypothesis_selection:{selection['selectionId']}",
                *_normalized_str_list(request.get("inputArtifactRefs")),
            ],
            "agenda": agenda,
            "agendaQuestions": agenda_questions,
            "agendaRules": agenda_rules,
            "linkedChatRoomId": room_id,
        },
    )
    meeting_round = created["meetingRound"]
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    if created["status"] == "reused":
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
        if bound_round_ids:
            return {
                "schemaVersion": meeting_rounds.SCHEMA_VERSION,
                "teamId": team["teamId"],
                "status": "reused",
                "meetingRound": meeting_round,
                "roomId": room_id,
                "roundId": bound_round_ids[-1],
                "chatRoomRoundIds": bound_round_ids,
                "storagePath": created["storagePath"],
            }

    topic = str(request.get("topic") or "").strip() or _opening_topic(
        meeting_round_id, selection, agenda, candidate_contexts
    )
    result = chat_room_service.start_chat_room_round(
        room_id,
        topic,
        purpose="meeting",
        config=_round_config(
            meeting_round, selection, discussion_round_index=1, team_id=str(team_id or "")
        ),
        agent_runner=agent_runner,
        background=background,
        lightweight_response=background,
        max_topic_lines=MEETING_TOPIC_MAX_LINES,
    )
    round_id = _round_id_from_start_result(result, meeting_round_id)
    bound = meeting_rounds.bind_meeting_chat_room_round(
        team["teamId"], meeting_round_id, room_id, round_id
    )
    return {
        "schemaVersion": meeting_rounds.SCHEMA_VERSION,
        "teamId": team["teamId"],
        "status": "opened",
        "meetingRound": bound["meetingRound"],
        "roomId": room_id,
        "roundId": round_id,
        "chatRoomRoundIds": _normalized_str_list(bound["meetingRound"].get("chatRoomRoundIds")),
        "discussion": {
            "background": bool(background),
            "roundStatus": str(result.get("status") or ""),
        },
        "storagePath": bound["storagePath"],
    }


def open_candidate_generation_meeting(
    team_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    agent_runner: Callable[..., dict[str, Any]] | None = None,
    background: bool = True,
) -> dict[str, Any]:
    """Open the round-0 candidate-generation discussion for a question.

    Cold-start counterpart to ``open_hypothesis_review_meeting``: catalog
    questions without an approved v2 artifact have no selectable candidates,
    so the team's first discussion proposes them.  Participants answer with
    ``CANDIDATE:`` marker lines; the closure digest carries the structured
    ``proposedCandidates`` that the selection UI then offers.  The meeting id
    is deterministic per scope/question so replays reuse instead of
    duplicating.
    """
    from core.web.services import chat_room_service

    request = dict(payload) if isinstance(payload, Mapping) else {}
    question_id = str(request.get("questionId") or "").strip().upper()
    if not question_id:
        raise ContractValidationError(
            "opening a candidate generation meeting requires a questionId"
        )
    participants = _normalized_str_list(request.get("participants"))
    if not participants:
        raise ContractValidationError(
            "opening a candidate generation meeting requires at least one participant"
        )
    team, room_id = _ensure_linked_room(str(team_id or "").strip())
    _assert_participants_in_room(room_id, participants)

    agenda = _normalized_str_list(request.get("agenda")) or list(_GENERATION_AGENDA)
    agenda_questions = _normalized_str_list(request.get("agendaQuestions")) or list(
        _GENERATION_AGENDA_QUESTIONS
    )
    agenda_rules = _normalized_str_list(request.get("agendaRules")) or list(
        _GENERATION_AGENDA_RULES
    )
    create_request = {
        key: request.get(key)
        for key in (
            *_SCOPE_FIELDS,
            "agentId",
            "mode",
            "meetingRoundId",
            "rounds",
            "startedAt",
        )
        if key in request and request.get(key) is not None
    }
    created = meeting_rounds.create_meeting_round(
        team["teamId"],
        {
            **create_request,
            "meetingType": CANDIDATE_GENERATION_MEETING_TYPE,
            "stage": "hypothesis",
            "roundType": "generation",
            "participants": participants,
            "participantRoleIds": _normalized_str_list(request.get("participantRoleIds")),
            "discussionItemRefs": [],
            "inputArtifactRefs": _normalized_str_list(request.get("inputArtifactRefs")),
            "agenda": agenda,
            "agendaQuestions": agenda_questions,
            "agendaRules": agenda_rules,
            "linkedChatRoomId": room_id,
        },
    )
    meeting_round = created["meetingRound"]
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    if created["status"] == "reused":
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
        if bound_round_ids:
            return {
                "schemaVersion": meeting_rounds.SCHEMA_VERSION,
                "teamId": team["teamId"],
                "status": "reused",
                "meetingRound": meeting_round,
                "roomId": room_id,
                "roundId": bound_round_ids[-1],
                "chatRoomRoundIds": bound_round_ids,
                "storagePath": created["storagePath"],
            }

    topic = str(request.get("topic") or "").strip() or _generation_opening_topic(
        meeting_round_id,
        question_id,
        agenda,
        question_context=_catalog_question_context(question_id),
    )
    selection_shim = {
        "selectionId": "",
        "questionId": question_id,
        "selectedCandidateIds": [],
    }
    result = chat_room_service.start_chat_room_round(
        room_id,
        topic,
        purpose="meeting",
        config=_round_config(
            meeting_round,
            selection_shim,
            discussion_round_index=1,
            team_id=str(team_id or ""),
        ),
        agent_runner=agent_runner,
        background=background,
        lightweight_response=background,
        max_topic_lines=MEETING_TOPIC_MAX_LINES,
    )
    round_id = _round_id_from_start_result(result, meeting_round_id)
    bound = meeting_rounds.bind_meeting_chat_room_round(
        team["teamId"], meeting_round_id, room_id, round_id
    )
    return {
        "schemaVersion": meeting_rounds.SCHEMA_VERSION,
        "teamId": team["teamId"],
        "status": "opened",
        "meetingRound": bound["meetingRound"],
        "roomId": room_id,
        "roundId": round_id,
        "chatRoomRoundIds": _normalized_str_list(bound["meetingRound"].get("chatRoomRoundIds")),
        "discussion": {
            "background": bool(background),
            "roundStatus": str(result.get("status") or ""),
        },
        "storagePath": bound["storagePath"],
    }


def _latest_bound_round_messages(meeting_round: Mapping[str, Any]) -> list[dict[str, Any]]:
    bound_rounds = meeting_rounds._load_bound_room_rounds(meeting_round)
    round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not round_ids:
        return []
    latest = bound_rounds.get(round_ids[-1]) or {}
    return [dict(item) for item in list(latest.get("messages") or []) if isinstance(item, dict)]


def _selection_from_meeting(meeting_round: Mapping[str, Any]) -> dict[str, Any]:
    selection_id = ""
    for ref in _normalized_str_list(meeting_round.get("inputArtifactRefs")):
        if ref.startswith("hypothesis_selection:"):
            selection_id = ref.split(":", 1)[-1]
            break
    return {
        "selectionId": selection_id,
        "questionId": str(meeting_round.get("question") or ""),
        "selectedCandidateIds": [
            ref.split(":", 1)[-1]
            for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
            if ref.startswith("hypothesis_candidate:")
        ],
    }


def run_meeting_discussion(
    team_id: str,
    meeting_round_id: str,
    *,
    agent_runner: Callable[..., dict[str, Any]] | None = None,
    max_messages: int | None = None,
) -> dict[str, Any]:
    """Drive the remaining discussion rounds for one open meeting.

    Synchronous DEV/fixture driver: each follow-up round runs to completion
    before the after-round checks.  Termination trio (per round): cumulative
    completed messages hitting ``max_messages`` (runaway cap), every speaker
    passing in the latest round (convergence signal), and the planned-round
    budget from the meeting contract (default 3).
    """
    from core.web.services import chat_room_service, team_service

    _DISCUSSION_DRIVER.active = True
    try:
        return _run_meeting_discussion_impl(
            team_id,
            meeting_round_id,
            agent_runner=agent_runner,
            max_messages=max_messages,
        )
    finally:
        _DISCUSSION_DRIVER.active = False


def _run_meeting_discussion_impl(
    team_id: str,
    meeting_round_id: str,
    *,
    agent_runner: Callable[..., dict[str, Any]] | None = None,
    max_messages: int | None = None,
) -> dict[str, Any]:
    from core.web.services import chat_room_service, team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRuntimeError("Meeting round id is required.")
    if max_messages is None:
        normalized_max_messages = DEFAULT_MAX_MESSAGES
    elif isinstance(max_messages, bool) or not isinstance(max_messages, int) or max_messages < 1:
        raise ContractValidationError("maxMessages must be an integer >= 1")
    else:
        normalized_max_messages = max_messages

    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    if str(meeting_round.get("status") or "").strip().lower() != "open":
        raise ResearchMeetingRuntimeError(
            "discussion rounds can only run while the meeting round is open"
        )
    room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
    bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not room_id or not bound_round_ids:
        raise ResearchMeetingRuntimeError(
            "meeting round has no bound chat room discussion round"
        )
    selection = _selection_from_meeting(meeting_round)
    budget = int(meeting_round.get("rounds") or 3)
    stop_reason = ""
    while len(bound_round_ids) < budget:
        all_messages = meeting_rounds.meeting_source_messages(meeting_round)
        completed = [
            message
            for message in all_messages
            if str(message.get("status") or "").strip().lower() == "completed"
        ]
        if len(completed) >= normalized_max_messages:
            stop_reason = "max_messages"
            break
        latest_completed = [
            message
            for message in _latest_bound_round_messages(meeting_round)
            if str(message.get("status") or "").strip().lower() == "completed"
        ]
        if not latest_completed:
            stop_reason = "no_progress"
            break
        if all(meeting_rounds.is_pass_message(message) for message in latest_completed):
            stop_reason = "converged"
            break
        discussion_round_index = len(bound_round_ids) + 1
        result = chat_room_service.start_chat_room_round(
            room_id,
            _follow_up_topic(discussion_round_index),
            purpose="meeting",
            config=_round_config(
                meeting_round,
                selection,
                discussion_round_index=discussion_round_index,
                team_id=normalized_team_id,
            ),
            agent_runner=agent_runner,
            background=False,
            max_topic_lines=MEETING_TOPIC_MAX_LINES,
        )
        round_id = _round_id_from_start_result(result, normalized_round_id)
        bound = meeting_rounds.bind_meeting_chat_room_round(
            normalized_team_id, normalized_round_id, room_id, round_id
        )
        meeting_round = bound["meetingRound"]
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    else:
        stop_reason = "budget_exhausted"

    all_messages = meeting_rounds.meeting_source_messages(meeting_round)
    completed_count = sum(
        1
        for message in all_messages
        if str(message.get("status") or "").strip().lower() == "completed"
    )
    try:
        drafted = prepare_meeting_summary_draft(
            normalized_team_id, normalized_round_id, actor="system", force=False
        )
        meeting_round = drafted.get("meetingRound") or meeting_round
    except Exception:
        drafted = None
    return {
        "schemaVersion": meeting_rounds.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "completed",
        "meetingRound": meeting_round,
        "roomId": room_id,
        "chatRoomRoundIds": bound_round_ids,
        "roundsRun": len(bound_round_ids),
        "roundBudget": budget,
        "maxMessages": normalized_max_messages,
        "messageCount": len(all_messages),
        "completedMessageCount": completed_count,
        "stopReason": stop_reason,
        "summaryDraft": drafted,
    }


def build_meeting_digest_draft(
    meeting_round: Mapping[str, Any],
    source_messages: Sequence[Mapping[str, Any]],
    *,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the Coordinator digest draft from bound room messages.

    The default drafter is the deterministic DEV fixture (marker extraction,
    no model call); inject ``drafter`` to delegate drafting to a real
    Coordinator role later.
    """
    if drafter is not None:
        drafted = drafter(dict(meeting_round), [dict(item) for item in source_messages])
        if not isinstance(drafted, Mapping):
            raise ContractValidationError("digest drafter must return a mapping")
        return dict(drafted)
    markers = meeting_rounds.apply_unstructured_digest_fallback(
        meeting_rounds.extract_discussion_markers(source_messages),
        source_messages,
    )
    agenda = _normalized_str_list(meeting_round.get("agenda"))
    discussion_item_refs = _normalized_str_list(meeting_round.get("discussionItemRefs"))
    participants = _normalized_str_list(meeting_round.get("participants"))
    rounds_run = len(_normalized_str_list(meeting_round.get("chatRoomRoundIds")))
    source_refs = [
        meeting_rounds.message_source_ref(message)
        for message in source_messages
        if str(message.get("status") or "").strip().lower() == "completed"
        and not meeting_rounds.is_pass_message(message)
    ]
    unstructured_agreements = [
        item
        for item in list(markers.get("agreements") or [])
        if isinstance(item, Mapping)
        and str(item.get("derivedFrom") or "") == meeting_rounds.UNSTRUCTURED_DERIVED_FROM
    ]
    if unstructured_agreements and not markers.get("disagreements"):
        summary = (
            f"假说评审会议 {str(meeting_round.get('meetingRoundId') or '')}："
            f"{len(participants)} 位参与者围绕 {len(discussion_item_refs)} 个入选候选完成 "
            f"{rounds_run} 轮讨论，从 {len(unstructured_agreements)} 条自由格式发言生成摘要条目，"
            "未提取到标记化共识或分歧。"
        )
    else:
        summary = (
            f"假说评审会议 {str(meeting_round.get('meetingRoundId') or '')}："
            f"{len(participants)} 位参与者围绕 {len(discussion_item_refs)} 个入选候选完成 "
            f"{rounds_run} 轮讨论，形成 {len(markers['agreements'])} 条共识、"
            f"{len(markers['disagreements'])} 条分歧、{len(markers['actionItems'])} 条行动项、"
            f"{len(markers['risks'])} 条未解决风险。"
        )
    evidence_requests, validation_errors = _collect_evidence_requests(
        meeting_round, markers, source_refs
    )
    return {
        "summary": summary,
        "agendaSummary": "；".join(agenda),
        "discussionTopics": [*agenda, *discussion_item_refs],
        "agreements": list(markers["agreements"]),
        "disagreements": list(markers["disagreements"]),
        "actionItems": list(markers["actionItems"]),
        "risks": list(markers["risks"]),
        "blockers": [],
        "knowledgeCandidates": list(markers["knowledgeCandidates"]),
        "proposedCandidates": list(markers["proposedCandidates"]),
        "evidenceRequests": evidence_requests,
        "validationErrors": validation_errors,
        "sourceMessageRefs": source_refs,
    }


def draft_meeting_digest(
    team_id: str,
    meeting_round_id: str,
    *,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate the Coordinator digest draft and move the meeting to ``awaiting_approval``."""
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRuntimeError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    source_messages = meeting_rounds.meeting_source_messages(meeting_round)
    draft = build_meeting_digest_draft(meeting_round, source_messages, drafter=drafter)
    draft["sourceMessageContentHash"] = meeting_rounds.source_message_content_hash(
        source_messages
    )
    return meeting_rounds.submit_meeting_digest_draft(
        normalized_team_id, normalized_round_id, draft
    )


def discussion_driver_active() -> bool:
    return bool(getattr(_DISCUSSION_DRIVER, "active", False))


def _allowed_candidate_ids(meeting_round: Mapping[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for ref in _normalized_str_list(meeting_round.get("discussionItemRefs")):
        allowed.add(ref)
        if ":" in ref:
            allowed.add(ref.split(":", 1)[-1].strip())
    for item in _normalized_str_list(meeting_round.get("selectedCandidateIds")):
        allowed.add(item)
    return {item for item in allowed if item}


def validate_evidence_request_draft(
    raw: Mapping[str, Any] | None,
    meeting_round: Mapping[str, Any],
    *,
    source_refs: Sequence[str] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Validate one untrusted evidence request. Invalid items never enter closure."""

    from core.web.services.team_workflow.source_collection import facade

    errors: list[dict[str, str]] = []
    if not isinstance(raw, Mapping):
        return None, [
            {
                "code": "evidence_request_invalid",
                "message": "evidence request must be an object",
            }
        ]
    rationale = str(raw.get("rationale") or "").strip()
    if len(rationale) > 10000:
        errors.append(
            {"code": "rationale_too_long", "message": "rationale exceeds 10000 characters"}
        )
    candidate_refs = _normalized_str_list(raw.get("candidateRefs"))
    allowed = _allowed_candidate_ids(meeting_round)
    if allowed:
        unknown = [
            item
            for item in candidate_refs
            if item not in allowed and item.split(":")[-1] not in allowed
        ]
        if unknown:
            errors.append(
                {
                    "code": "candidate_ref_unbound",
                    "message": "candidateRefs are not bound to this meeting: "
                    + ", ".join(unknown),
                }
            )
    evidence_refs = _normalized_str_list(raw.get("evidenceRefs"))
    allowed_refs = {str(item) for item in list(source_refs or []) if str(item)}
    for ref in evidence_refs:
        if ref.startswith("evidence:"):
            continue
        if allowed_refs and ref not in allowed_refs:
            errors.append(
                {
                    "code": "evidence_ref_unbound",
                    "message": f"evidenceRefs are not bound to source messages: {ref}",
                }
            )
            break
    try:
        envelope = facade._normalize_search_envelope(
            raw.get("searchEnvelope"), require_keywords=True
        )
    except Exception as exc:
        errors.append(
            {
                "code": str(getattr(exc, "code", "") or "search_envelope_invalid"),
                "message": str(exc),
            }
        )
        envelope = None
    try:
        requirements = facade._normalize_requirements(raw.get("requirements"))
        writeback_policy = facade._normalize_writeback_policy(raw.get("writebackPolicy"))
    except Exception as exc:
        errors.append(
            {
                "code": str(getattr(exc, "code", "") or "collection_payload_invalid"),
                "message": str(exc),
            }
        )
        requirements = {}
        writeback_policy = {}
    if errors or envelope is None:
        return None, errors
    return {
        "rationale": rationale,
        "candidateRefs": candidate_refs,
        "evidenceRefs": evidence_refs,
        "searchEnvelope": {
            "keywords": list(envelope.get("keywords") or []),
            "sourceTypes": list(envelope.get("sourceTypes") or []),
            "evidenceLevels": list(envelope.get("evidenceLevels") or []),
        },
        "requirements": requirements,
        "writebackPolicy": writeback_policy,
    }, []


def _collect_evidence_requests(
    meeting_round: Mapping[str, Any],
    markers: Mapping[str, Any],
    source_refs: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    validation_errors = [
        dict(item)
        for item in list(markers.get("evidenceRequestErrors") or [])
        if isinstance(item, Mapping)
    ]
    collected: list[dict[str, Any]] = []
    for raw in list(markers.get("evidenceRequests") or []):
        normalized, errors = validate_evidence_request_draft(
            raw if isinstance(raw, Mapping) else None,
            meeting_round,
            source_refs=source_refs,
        )
        validation_errors.extend(errors)
        if normalized is not None:
            collected.append(normalized)
        elif isinstance(raw, Mapping):
            collected.append(dict(raw))
    return collected, validation_errors


def prepare_meeting_summary_draft(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "",
    force: bool = False,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Idempotent open → summarizing → awaiting_approval summary-draft action."""

    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRuntimeError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    status = str(meeting_round.get("status") or "").strip().lower()
    source_messages = meeting_rounds.meeting_source_messages(meeting_round)
    completed_source_messages = meeting_rounds.completed_meeting_source_messages(
        meeting_round
    )
    source_hash = meeting_rounds.source_message_content_hash(source_messages)
    existing_draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    if status == "closed":
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "closed",
            "meetingRound": meeting_round,
            "digestDraft": existing_draft or None,
            "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
        }
    if status == "awaiting_approval":
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "awaiting_approval",
            "meetingRound": meeting_round,
            "digestDraft": existing_draft or None,
            "boundChatRoundsTerminal": not meeting_rounds.running_bound_round_ids(
                meeting_round
            ),
            "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
        }
    if status == "open":
        running = [] if force else meeting_rounds.running_bound_round_ids(meeting_round)
        if running:
            return {
                "schemaVersion": meeting_rounds.SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "blocked",
                "blocker": {
                    "code": "discussion_round_running",
                    "message": "讨论回合仍在进行，全部结束后才能生成纪要",
                    "runningRoundIds": running,
                },
                "meetingRound": meeting_round,
                "boundChatRoundsTerminal": False,
                "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
            }
        if not completed_source_messages:
            return {
                "schemaVersion": meeting_rounds.SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "blocked",
                "blocker": {
                    "code": "discussion_has_no_completed_messages",
                    "message": "讨论未产出可引用的成功发言，不能生成纪要",
                    "remediationLabel": "重新发起讨论",
                },
                "meetingRound": meeting_round,
                "boundChatRoundsTerminal": True,
                "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
            }
        meeting_rounds.begin_meeting_summary(
            normalized_team_id,
            normalized_round_id,
            actor=actor,
            human_triggered=bool(force),
        )
        meeting_round = meeting_rounds.get_meeting_round(
            normalized_team_id, normalized_round_id
        )["meetingRound"]
        status = "summarizing"
        existing_draft = (
            dict(meeting_round.get("digestDraft"))
            if isinstance(meeting_round.get("digestDraft"), Mapping)
            else {}
        )
    if status == "summarizing" and not completed_source_messages:
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "blocked",
            "blocker": {
                "code": "discussion_has_no_completed_messages",
                "message": "讨论未产出可引用的成功发言，不能生成纪要",
                "remediationLabel": "重新发起讨论",
            },
            "meetingRound": meeting_round,
            "boundChatRoundsTerminal": not meeting_rounds.running_bound_round_ids(
                meeting_round
            ),
            "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
        }
    if status != "summarizing":
        raise ResearchMeetingRuntimeError(
            f"meeting status {status or '<unknown>'} cannot generate a summary draft"
        )
    if (
        existing_draft
        and str(existing_draft.get("sourceMessageContentHash") or "") == source_hash
    ):
        return meeting_rounds.submit_meeting_digest_draft(
            normalized_team_id, normalized_round_id, existing_draft
        )
    try:
        return draft_meeting_digest(
            normalized_team_id, normalized_round_id, drafter=drafter
        )
    except Exception as exc:
        error = {
            "code": "summary_draft_failed",
            "message": str(exc),
            "remediationLabel": "重试生成纪要",
        }
        persisted = meeting_rounds.record_meeting_summary_draft_error(
            normalized_team_id, normalized_round_id, error
        )
        return {
            **persisted,
            "status": "summarizing",
            "summaryDraftError": error,
        }


def _team_id_for_auto_draft(
    room: Mapping[str, Any], round_payload: Mapping[str, Any]
) -> str:
    config = (
        round_payload.get("config")
        if isinstance(round_payload.get("config"), Mapping)
        else {}
    )
    team_id = str(config.get("teamId") or "").strip()
    if team_id:
        return team_id
    room_config = room.get("config") if isinstance(room.get("config"), Mapping) else {}
    team_id = str(room_config.get("teamId") or room.get("teamId") or "").strip()
    if team_id:
        return team_id
    for participant in list(room.get("participants") or []):
        if isinstance(participant, Mapping):
            team_id = str(participant.get("teamId") or "").strip()
            if team_id:
                return team_id
    room_id = str(room.get("roomId") or "").strip()
    if not room_id:
        return ""
    from core.web.services import team_service

    try:
        listed = team_service.list_teams()
    except Exception:
        return ""
    teams = listed.get("teams") if isinstance(listed, Mapping) else listed
    for team in list(teams or []):
        if isinstance(team, Mapping) and str(team.get("linkedChatRoomId") or "") == room_id:
            return str(team.get("teamId") or "").strip()
    return ""


def maybe_auto_draft_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    required_round_id: str = "",
) -> dict[str, Any] | None:
    """Draft only when every bound chat round is terminal and will not follow-up."""

    if discussion_driver_active():
        return None
    normalized_team_id = str(team_id or "").strip()
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_team_id or not normalized_round_id:
        return None
    try:
        meeting_round = meeting_rounds.get_meeting_round(
            normalized_team_id, normalized_round_id
        )["meetingRound"]
    except Exception:
        return None
    if str(meeting_round.get("status") or "").strip().lower() != "open":
        return None
    bound_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not bound_ids:
        return None
    required = str(required_round_id or "").strip()
    if required and required not in bound_ids:
        return None
    if meeting_rounds.running_bound_round_ids(meeting_round):
        return None
    try:
        return prepare_meeting_summary_draft(
            normalized_team_id, normalized_round_id, actor="system", force=False
        )
    except Exception:
        return None


def maybe_auto_draft_after_chat_round(
    room: Mapping[str, Any] | None,
    round_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """P1 hook: draft after a meeting-bound chat round reaches a terminal status."""

    if not isinstance(room, Mapping) or not isinstance(round_payload, Mapping):
        return None
    config = (
        round_payload.get("config")
        if isinstance(round_payload.get("config"), Mapping)
        else {}
    )
    meeting_round_id = str(config.get("meetingRoundId") or "").strip()
    if not meeting_round_id:
        return None
    team_id = _team_id_for_auto_draft(room, round_payload)
    if not team_id:
        return None
    return maybe_auto_draft_meeting(
        team_id,
        meeting_round_id,
        required_round_id=str(round_payload.get("roundId") or "").strip(),
    )
