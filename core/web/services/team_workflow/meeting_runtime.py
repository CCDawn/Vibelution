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

Only hypothesis-first discussion rounds are auto-opened here; stage
coordination elsewhere stays ``manual_only``. The discussion driver remains
synchronous for DEV/fixture callers, while production's default chat runner
queues its post-opening rounds on a bounded in-process executor.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any

from core.research.competition.resources import (
    CompetitionResourceError,
    load_science_question_catalog,
)
from core.research.workflow.contracts import (
    CURRENT_RESEARCH_TEAM_ROLE_CONTRACT,
    ContractValidationError,
    sha256_hex,
)
from core.research.workflow.contracts.discussion_scope import (
    CANDIDATE_REVIEW_SCOPE_KIND,
    PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
    QUESTION_GENERATION_SCOPE_KIND,
    PreformalCandidateReviewScopeV1,
    WorkflowDiscussionScopeV1,
    parse_discussion_scope,
    session_scope_key,
)
from core.web.services.team_workflow import meeting_driver_work, meeting_rounds
from core.web.services.team_workflow.research_runtime.challenge_cup_maintenance_fence import (
    assert_writes_allowed,
)
from core.web.services.team_workflow.research_runtime.meeting_receipt_authority import (
    workflow_run_stop_reason,
)
from core.web.services.team_workflow.source_collection import (
    facade as collection_facade,
)

DEFAULT_MAX_MESSAGES = 40
MAX_SELECTED_CANDIDATES = 16
MEETING_SOURCE = "hypothesis_first_meeting"
# The opening topic embeds one line per selected candidate (plus header/footer
# lines), so meeting rounds need a line budget beyond the generic chat-room
# topic cap: 3 framing lines + rules + host line + one line per candidate.
MEETING_TOPIC_MAX_LINES = MAX_SELECTED_CANDIDATES + 8
_MEETING_RECEIPT_AUTHORITY_SCHEMA_VERSION = 1

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
    "证据请求必须使用唯一合法词表：sourceTypes 只允许 "
    + "、".join(sorted(collection_facade.SEARCH_ENVELOPE_SOURCE_TYPES))
    + "；evidenceLevels 只允许 "
    + "、".join(sorted(collection_facade.SEARCH_ENVELOPE_EVIDENCE_LEVELS))
    + '。预印本使用 sourceTypes=["paper"]、evidenceLevels=["preprint"]；'
    + '官方网页或声明使用 sourceTypes=["url"]、evidenceLevels=["primary"]；'
    + '代码仓库使用 sourceTypes=["repo"]。candidateRefs 只能填写本会议已绑定的'
    + "候选 ID，不得新造候选 ID",
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
_FORMAL_GROUNDED_GENERATION_AGENDA_RULES = (
    "本轮只生成正式证据接地候选；R0 探索草案只能作为待修订输入，不能沿用其 candidateId",
    "每个候选写入 protocol.proposedCandidates，必须包含新的 candidateId、statement、rationale、proposedBy、lineageRefs、testablePrediction、falsifier 和完整 axisProfile",
    "lineageRefs 必须来自本轮 allowedEvidenceRefs 白名单，且每个候选至少一条；testablePrediction 不得为空",
    "axisProfile 必须恰好描述 mechanism、intervention、observable、population、boundary 五轴；falsifier 必须能够否定或显著削弱核心机制",
    "必须说明相对 R0 草案的具体机制变化，不得只改写措辞",
    "没有新内容时回复 pass；分歧必须显式记录",
)

_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
_PARTICIPANT_CONTRACT_FIELDS = (
    "participantRoleIds",
    "teamRoleContractVersion",
    "participantPolicyVersion",
    "roleContractFingerprint",
    "participantRoleSnapshot",
    "resolutionHash",
)
_ROLE_METADATA_FIELDS = (
    "teamRoleKey",
    "teamRole",
    "roleKey",
    "role",
    "researchTeamRoleKey",
    "researchTeamRole",
    "challengeCupTeamRoleKey",
    "challengeCupTeamRole",
)
_DISCUSSION_DRIVER = threading.local()
_MEETING_DISCUSSION_EXECUTOR_MAX_WORKERS = 4
_MEETING_DISCUSSION_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MEETING_DISCUSSION_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="hypothesis-meeting",
)
_MEETING_DISCUSSION_JOBS_LOCK = threading.Lock()
_MEETING_DISCUSSION_JOBS: set[tuple[str, str]] = set()
_SUMMARY_DRAFT_LOCKS_GUARD = threading.Lock()
_SUMMARY_DRAFT_LOCKS: dict[tuple[str, str], tuple[Any, int]] = {}
_SCOPED_DISCUSSION_SCOPE_AUTHORITY = "workflow_discussion_scope.v1"
_PREFORMAL_CANDIDATE_ROOM_SOURCE = "hypothesis_first_candidate_review.v1"
_PREFORMAL_DISCUSSION_SCOPE_AUTHORITY = "preformal_candidate_review_scope.v1"


@contextmanager
def _summary_draft_lock(team_id: str, meeting_round_id: str):
    """Serialize one summary draft per meeting without retaining idle locks."""

    key = (team_id, meeting_round_id)
    with _SUMMARY_DRAFT_LOCKS_GUARD:
        entry = _SUMMARY_DRAFT_LOCKS.get(key)
        if entry is None:
            lock = threading.RLock()
            references = 0
        else:
            lock, references = entry
        _SUMMARY_DRAFT_LOCKS[key] = (lock, references + 1)

    acquired = False
    try:
        lock.acquire()
        acquired = True
        yield
    finally:
        try:
            if acquired:
                lock.release()
        finally:
            with _SUMMARY_DRAFT_LOCKS_GUARD:
                current = _SUMMARY_DRAFT_LOCKS.get(key)
                if current is not None and current[0] is lock:
                    if current[1] <= 1:
                        _SUMMARY_DRAFT_LOCKS.pop(key, None)
                    else:
                        _SUMMARY_DRAFT_LOCKS[key] = (lock, current[1] - 1)


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


def _discussion_scope_candidate(request: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return an explicitly supplied v1 discussion scope, if present.

    The legacy hypothesis-first payload has a ``scope`` made of the six
    meeting fields (program/theme/...).  It must not be mistaken for the v1
    room identity.  Formal workflow callers instead send the canonical scope
    directly or under a checkpoint ``scopeBinding`` envelope.
    """

    for key in ("discussionScope", "activeDiscussionScope", "workflowScope"):
        value = request.get(key)
        if isinstance(value, Mapping):
            return value
    binding = request.get("scopeBinding")
    if isinstance(binding, Mapping):
        for key in ("discussionScope", "scope"):
            value = binding.get(key)
            if isinstance(value, Mapping):
                return value
    value = request.get("discussion_scope")
    return value if isinstance(value, Mapping) else None


def _discussion_scope_for_request(
    team_id: str,
    request: Mapping[str, Any],
    *,
    question_id: str,
    meeting_type: str,
    selection: Mapping[str, Any] | None = None,
) -> WorkflowDiscussionScopeV1 | None:
    """Resolve the formal room scope without changing the legacy DEV path.

    A scope is enabled only by an explicit v1 envelope or by the complete
    workflowRunId/workflowNodeId/researchProjectId tuple.  A receipt alone is
    deliberately insufficient: it identifies a model invocation, not the
    discussion node that owns a room.
    """

    request_scope = _discussion_scope_candidate(request)
    raw_kind = str(request_scope.get("kind") or "").strip() if request_scope else ""
    raw_version = request_scope.get("version") if request_scope else None
    # ``researchProjectId`` may already be present on a legacy payload for
    # project routing. It becomes a formal-room signal only together with the
    # workflow node/run identity (or an explicit v1 envelope).
    has_scope_signal = bool(request_scope) or any(
        str(request.get(key) or "").strip()
        for key in ("workflowRunId", "workflowNodeId")
    )
    if not has_scope_signal:
        return None

    selection_payload = selection or {}
    selected_candidate_ids = _normalized_str_list(
        selection_payload.get("selectedCandidateIds")
    )
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_team_id = str(team_id or "").strip()

    if request_scope is not None and (
        raw_kind in {QUESTION_GENERATION_SCOPE_KIND, CANDIDATE_REVIEW_SCOPE_KIND}
        or raw_version == 1
    ):
        try:
            scope = parse_discussion_scope(request_scope)
        except ContractValidationError as exc:
            raise ResearchMeetingRuntimeError(
                f"formal discussion scope is invalid: {exc}"
            ) from exc
    else:
        workflow_run_id = str(
            request.get("workflowRunId") or request.get("workflow_run_id") or ""
        ).strip()
        workflow_node_id = str(
            request.get("workflowNodeId") or request.get("workflow_node_id") or ""
        ).strip()
        research_project_id = str(
            request.get("researchProjectId")
            or request.get("research_project_id")
            or ""
        ).strip()
        if workflow_run_id and workflow_node_id and not research_project_id:
            from core.web.services.team_workflow.research_project_agent_sessions import (
                resolve_research_project_identity,
            )

            try:
                project = resolve_research_project_identity(normalized_team_id)
            except Exception as exc:  # noqa: BLE001 - retain fail-closed domain error
                raise ResearchMeetingRuntimeError(
                    "formal discussion scope requires a resolvable research project"
                ) from exc
            research_project_id = str(project.get("projectId") or "").strip()
        if not (workflow_run_id and workflow_node_id and research_project_id):
            raise ResearchMeetingRuntimeError(
                "formal discussion scope requires workflowRunId, workflowNodeId and researchProjectId"
            )
        selection_id = str(selection_payload.get("selectionId") or "").strip()
        candidate_id = str(
            request.get("candidateId")
            or request.get("candidate_id")
            or ""
        ).strip()
        if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
            scope = WorkflowDiscussionScopeV1.generation(
                teamId=normalized_team_id,
                researchProjectId=research_project_id,
                workflowRunId=workflow_run_id,
                workflowNodeId=workflow_node_id,
                questionId=normalized_question_id,
            )
        else:
            if not candidate_id and len(selected_candidate_ids) == 1:
                candidate_id = selected_candidate_ids[0]
            if not selection_id or not candidate_id:
                raise ResearchMeetingRuntimeError(
                    "formal hypothesis review scope requires selectionId and one candidateId"
                )
            scope = WorkflowDiscussionScopeV1.review(
                teamId=normalized_team_id,
                researchProjectId=research_project_id,
                workflowRunId=workflow_run_id,
                workflowNodeId=workflow_node_id,
                questionId=normalized_question_id,
                selectionId=selection_id,
                candidateId=candidate_id,
            )

    if scope.teamId != normalized_team_id or scope.questionId.upper() != normalized_question_id:
        raise ResearchMeetingRuntimeError(
            "formal discussion scope does not match the meeting team or question"
        )
    if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
        if scope.kind != QUESTION_GENERATION_SCOPE_KIND:
            raise ResearchMeetingRuntimeError(
                "candidate generation requires a question_generation discussion scope"
            )
    elif scope.kind != CANDIDATE_REVIEW_SCOPE_KIND:
        raise ResearchMeetingRuntimeError(
            "hypothesis review requires a candidate_review discussion scope"
        )
    try:
        scope.validate_candidate_membership(
            selected_candidate_ids if scope.is_candidate_review else None
        )
    except ContractValidationError as exc:
        raise ResearchMeetingRuntimeError(str(exc)) from exc
    return scope


def _resolve_scoped_meeting_room(
    team_id: str,
    request: Mapping[str, Any],
    *,
    base_room_id: str,
    scope: WorkflowDiscussionScopeV1 | None,
    participant_resolution: Mapping[str, Any],
    meeting_type: str,
    selected_candidate_ids: Sequence[str] = (),
) -> tuple[str, WorkflowDiscussionScopeV1 | PreformalCandidateReviewScopeV1 | None]:
    """Bind role-resolved Agents to hidden Child Sessions and one room."""

    if scope is None:
        return _resolve_preformal_candidate_review_room(
            team_id,
            request,
            base_room_id=base_room_id,
            participant_resolution=participant_resolution,
            meeting_type=meeting_type,
            selected_candidate_ids=selected_candidate_ids,
        )

    from core.web.services import chat_room_service
    from core.web.services.team_workflow.discussion_room_runtime import (
        resolve_scoped_discussion_room,
    )
    from core.web.services.team_workflow.research_project_agent_sessions import (
        resolve_research_project_agent_session,
    )

    role_snapshot = [
        dict(item)
        for item in list(participant_resolution.get("participantRoleSnapshot") or [])
        if isinstance(item, Mapping)
    ]
    role_by_agent_id = {
        str(item.get("agentId") or "").strip(): item
        for item in role_snapshot
        if str(item.get("agentId") or "").strip()
    }
    if set(role_by_agent_id) != set(
        str(item or "").strip()
        for item in list(participant_resolution.get("participants") or [])
        if str(item or "").strip()
    ):
        raise ResearchMeetingRuntimeError(
            "formal discussion participant role snapshot is incomplete"
        )

    created_from_task_id = str(
        request.get("createdFromTaskId")
        or request.get("taskId")
        or request.get("workflowTaskId")
        or ""
    ).strip()
    selected = list(selected_candidate_ids or [])
    bindings: list[dict[str, Any]] = []
    for agent_id in participant_resolution.get("participants") or []:
        normalized_agent_id = str(agent_id or "").strip()
        role = role_by_agent_id[normalized_agent_id]
        resolved = resolve_research_project_agent_session(
            team_id,
            research_project_id=scope.researchProjectId,
            agent_id=normalized_agent_id,
            role_key=str(role.get("roleId") or "").strip(),
            role_label=str(role.get("observedRole") or "").strip(),
            created_from_task_id=created_from_task_id,
            workflow_run_id=scope.workflowRunId,
            workflow_node_id=scope.workflowNodeId,
            discussion_scope=scope,
            selected_candidate_ids=selected if scope.is_candidate_review else None,
            question_id=scope.questionId,
        )
        session_id = str(resolved.get("sessionId") or "").strip()
        if not session_id or str(resolved.get("sessionKind") or "").lower() != "child":
            raise ResearchMeetingRuntimeError(
                "formal discussion participant did not resolve to a hidden Child Session"
            )
        bindings.append(
            {
                "agentId": normalized_agent_id,
                "sessionId": session_id,
                "discussionScope": scope.to_dict(),
                "discussionScopeHash": scope.scope_hash,
                "discussionSessionScopeKey": session_scope_key(scope, normalized_agent_id),
            }
        )

    title_suffix = (
        f" | {scope.candidateId}" if scope.is_candidate_review else " | 候选生成"
    )
    room = resolve_scoped_discussion_room(
        scope,
        bindings,
        title=f"{scope.questionId}{title_suffix}",
        participant_contexts_by_agent_id=_derived_room_participant_contexts(
            chat_room_service.get_chat_room_detail(base_room_id),
            participant_resolution,
            list(participant_resolution.get("participants") or []),
        ),
    )
    room_id = str(room.get("roomId") or "").strip()
    if not room_id:
        raise ResearchMeetingRuntimeError("formal discussion room resolver returned no roomId")
    return room_id, scope


def _resolve_preformal_candidate_review_room(
    team_id: str,
    request: Mapping[str, Any],
    *,
    base_room_id: str,
    participant_resolution: Mapping[str, Any],
    meeting_type: str,
    selected_candidate_ids: Sequence[str],
) -> tuple[str, PreformalCandidateReviewScopeV1 | None]:
    """Allocate one deterministic room for an unscoped candidate review.

    Candidate selection normally precedes creation of the formal research
    runtime, so it intentionally has no ``WorkflowDiscussionScopeV1`` yet.
    It must nevertheless not reuse the team room: a background round makes
    that room busy and prevents sibling candidate reviews from ever opening.
    These rooms retain the exact server-resolved roster and carry a compact
    preformal binding, while formal flows continue to use child-session rooms
    through ``_resolve_scoped_meeting_room`` above.
    """

    selected = _normalized_str_list(selected_candidate_ids)
    if (
        str(meeting_type or "").strip().lower() != "hypothesis_review"
        or len(selected) != 1
    ):
        return base_room_id, None

    from core.web.services import chat_room_service

    selection_id = str(request.get("selectionId") or "").strip()
    question_id = str(request.get("questionId") or "").strip().upper()
    meeting_round_id = str(request.get("meetingRoundId") or "").strip()
    candidate_id = selected[0]
    if not selection_id or not question_id or not meeting_round_id:
        raise ResearchMeetingRuntimeError(
            "preformal candidate review room requires selection, question and meeting ids"
        )

    room_id = "room-hf-review-" + sha256_hex(
        {
            "teamId": str(team_id or "").strip(),
            "meetingRoundId": meeting_round_id,
            "selectionId": selection_id,
            "candidateId": candidate_id,
        }
    )[:24]
    expected_config = {
        "source": _PREFORMAL_CANDIDATE_ROOM_SOURCE,
        "teamId": str(team_id or "").strip(),
        "meetingRoundId": meeting_round_id,
        "selectionId": selection_id,
        "questionId": question_id,
        "candidateId": candidate_id,
    }
    discussion_scope = PreformalCandidateReviewScopeV1.review(
        teamId=str(team_id or "").strip(),
        questionId=question_id,
        selectionId=selection_id,
        candidateId=candidate_id,
        meetingRoundId=meeting_round_id,
        roomId=room_id,
    )
    existing = chat_room_service.get_chat_room_detail(room_id)
    if isinstance(existing, Mapping):
        config = existing.get("config") if isinstance(existing.get("config"), Mapping) else {}
        if any(str(config.get(key) or "") != value for key, value in expected_config.items()):
            raise ResearchMeetingRuntimeError(
                "preformal candidate review room is already bound to different content"
            )
        stored_scope = config.get("discussionScope")
        if stored_scope is not None:
            try:
                stored = PreformalCandidateReviewScopeV1.from_mapping(stored_scope)
            except (ContractValidationError, TypeError, ValueError) as exc:
                raise ResearchMeetingRuntimeError(
                    "preformal candidate review room has an invalid discussion scope"
                ) from exc
            if stored.to_dict() != discussion_scope.to_dict() or str(
                config.get("discussionScopeHash") or config.get("scopeHash") or ""
            ).lower() != discussion_scope.scope_hash:
                raise ResearchMeetingRuntimeError(
                    "preformal candidate review room is already bound to different content"
                )
        return room_id, discussion_scope

    participant_agent_ids = _normalized_str_list(participant_resolution.get("participants"))
    if not participant_agent_ids:
        raise ResearchMeetingRuntimeError(
            "preformal candidate review room requires a resolved participant roster"
        )
    participant_contexts = _derived_room_participant_contexts(
        chat_room_service.get_chat_room_detail(base_room_id),
        participant_resolution,
        participant_agent_ids,
    )
    created = chat_room_service.create_chat_room(
        room_id=room_id,
        title=f"{question_id} | 候选评审 | {candidate_id}",
        participant_agent_ids=participant_agent_ids,
        participant_contexts_by_agent_id=participant_contexts,
        mode="round_robin",
        purpose="meeting",
        config={
            **expected_config,
            "scopeAuthority": _PREFORMAL_DISCUSSION_SCOPE_AUTHORITY,
            "discussionScope": discussion_scope.to_dict(),
            "discussionScopeHash": discussion_scope.scope_hash,
            "scopeHash": discussion_scope.scope_hash,
        },
    )
    created_room_id = str(created.get("roomId") or "").strip()
    if created_room_id != room_id:
        raise ResearchMeetingRuntimeError("preformal candidate room resolver returned no roomId")
    return room_id, discussion_scope


def _derived_room_participant_contexts(
    base_room: Mapping[str, Any] | None,
    participant_resolution: Mapping[str, Any],
    participant_agent_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Copy the fixed roster's team context into a derived discussion room."""

    allowed_agent_ids = set(_normalized_str_list(participant_agent_ids))
    role_by_agent_id = {
        str(item.get("agentId") or "").strip(): str(item.get("observedRole") or "").strip()
        for item in list(participant_resolution.get("participantRoleSnapshot") or [])
        if isinstance(item, Mapping) and str(item.get("agentId") or "").strip()
    }
    context_fields = (
        "teamId",
        "teamName",
        "teamPurpose",
        "teamRole",
        "teamMemberPurpose",
        "teamResponsibilities",
    )
    contexts: dict[str, dict[str, Any]] = {}
    for participant in list((base_room or {}).get("participants") or []):
        if not isinstance(participant, Mapping):
            continue
        agent_id = str(participant.get("agentId") or "").strip()
        if agent_id not in allowed_agent_ids:
            continue
        context = {
            field: participant.get(field)
            for field in context_fields
            if participant.get(field) not in (None, "")
        }
        if not context.get("teamRole") and role_by_agent_id.get(agent_id):
            context["teamRole"] = role_by_agent_id[agent_id]
        contexts[agent_id] = context
    return contexts


def _persist_discussion_scope_projection(
    team_id: str,
    meeting_round: Mapping[str, Any],
    scope: WorkflowDiscussionScopeV1 | PreformalCandidateReviewScopeV1 | None,
) -> dict[str, Any]:
    """Persist a formal or preformal scope beside the legacy MeetingRound contract.

    ``MeetingRound`` predates the v1 discussion identity and intentionally
    ignores unknown projection fields.  Append the validated projection using
    its owning append helper so reads of ``meeting_rounds.jsonl`` retain the
    exact room scope without altering the public DTO.
    """

    record = dict(meeting_round)
    if scope is None:
        return record
    existing_scope = record.get("discussionScope")
    if existing_scope is not None:
        try:
            if isinstance(scope, PreformalCandidateReviewScopeV1):
                existing = PreformalCandidateReviewScopeV1.from_mapping(existing_scope)
            else:
                existing = parse_discussion_scope(existing_scope)
        except ContractValidationError as exc:
            raise ResearchMeetingRuntimeError(
                "existing meeting has an invalid discussion scope"
            ) from exc
        if existing.key != scope.key or str(record.get("discussionScopeHash") or "").lower() != scope.scope_hash:
            raise ResearchMeetingRuntimeError(
                "existing meeting is bound to a different discussion scope"
            )
        return record
    if isinstance(scope, PreformalCandidateReviewScopeV1):
        return meeting_rounds.persist_preformal_meeting_discussion_scope(
            str(team_id or "").strip(),
            str(record.get("meetingRoundId") or "").strip(),
            discussion_scope=scope.to_dict(),
            discussion_scope_hash=scope.scope_hash,
            scope_authority=_PREFORMAL_DISCUSSION_SCOPE_AUTHORITY,
        )
    record.update(
        {
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
            "scopeAuthority": _SCOPED_DISCUSSION_SCOPE_AUTHORITY,
            "researchProjectId": scope.researchProjectId,
            "workflowRunId": scope.workflowRunId,
            "workflowNodeId": scope.workflowNodeId,
        }
    )
    return meeting_rounds.persist_meeting_discussion_scope(
        str(team_id or "").strip(),
        str(record.get("meetingRoundId") or "").strip(),
        discussion_scope=scope.to_dict(),
        discussion_scope_hash=scope.scope_hash,
        scope_authority=_SCOPED_DISCUSSION_SCOPE_AUTHORITY,
    )


def _role_owner_index() -> dict[str, str]:
    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    index: dict[str, str] = {}
    for role in contract.product_agents:
        for value in (role.product_role_id, *role.legacy_role_aliases):
            index[str(value).strip().lower()] = role.product_role_id
    for capability in contract.system_capabilities:
        for value in (capability.capability_id, *capability.legacy_role_aliases):
            index[str(value).strip().lower()] = capability.capability_id
    return index


def _role_values(item: Mapping[str, Any], *, source: str) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    owner_index = _role_owner_index()
    for field in _ROLE_METADATA_FIELDS:
        raw = str(item.get(field) or "").strip()
        owner_id = owner_index.get(raw.lower()) if raw else None
        if owner_id:
            values.append(
                {
                    "ownerId": owner_id,
                    "observedRole": raw,
                    "source": f"{source}.{field}",
                }
            )
    return values


def resolve_hypothesis_meeting_participants(
    team_id: str,
    room_id: str,
    meeting_type: str,
) -> dict[str, Any]:
    """Resolve and freeze the exact contract-owned roster for a hypothesis meeting."""

    from core.web.services import (
        agent_directory_service,
        chat_room_service,
        team_service,
    )

    normalized_team_id = str(team_id or "").strip()
    normalized_room_id = str(room_id or "").strip()
    if not normalized_room_id:
        raise ContractValidationError("linked chat room id is required for participant resolution")
    room_detail = chat_room_service.get_chat_room_detail(normalized_room_id)
    if room_detail is None:
        raise ResearchMeetingRuntimeError("Team linked chat room not found.")

    contract = CURRENT_RESEARCH_TEAM_ROLE_CONTRACT
    normalized_meeting_type = str(meeting_type or "").strip().lower()
    policy = contract.participant_policy(normalized_meeting_type)
    required_role_ids = list(policy.required_product_role_ids)
    team = team_service.get_team(normalized_team_id) or {}
    team_members = {
        str(member.get("agentId") or "").strip(): dict(member)
        for member in list(team.get("members") or [])
        if isinstance(member, Mapping) and str(member.get("agentId") or "").strip()
    }
    candidates_by_role: dict[str, list[dict[str, str]]] = {
        role_id: [] for role_id in required_role_ids
    }
    seen_agent_ids: set[str] = set()
    for room_participant in list(room_detail.get("participants") or []):
        if not isinstance(room_participant, Mapping):
            continue
        agent_id = str(room_participant.get("agentId") or "").strip()
        if not agent_id:
            continue
        if agent_id in seen_agent_ids:
            raise ContractValidationError(
                f"duplicate participant agent binding in linked chat room: {agent_id}"
            )
        seen_agent_ids.add(agent_id)
        merged: dict[str, Any] = dict(team_members.get(agent_id) or {})
        merged.update(dict(room_participant))
        try:
            agent = agent_directory_service.get_agent(agent_id, include_archived=False) or {}
        except Exception:
            agent = {}
        metadata = agent.get("metadata") if isinstance(agent, Mapping) else {}
        if isinstance(metadata, Mapping):
            for field in _ROLE_METADATA_FIELDS:
                if field not in merged and metadata.get(field) is not None:
                    merged[field] = metadata.get(field)

        resolved_values = _role_values(merged, source="participant")
        resolved_role_ids = {
            item["ownerId"]
            for item in resolved_values
            if item["ownerId"] in candidates_by_role
        }
        if len(resolved_role_ids) > 1:
            raise ContractValidationError(
                f"ambiguous participant role binding for agent {agent_id}"
            )
        if not resolved_role_ids:
            continue
        role_id = next(iter(resolved_role_ids))
        observed = next(item for item in resolved_values if item["ownerId"] == role_id)
        candidates_by_role[role_id].append(
            {
                "roleId": role_id,
                "agentId": agent_id,
                "observedRole": observed["observedRole"],
                "resolvedFrom": observed["source"],
            }
        )

    missing = [role_id for role_id in required_role_ids if not candidates_by_role[role_id]]
    if missing:
        raise ContractValidationError(
            "missing required participant role(s): " + ", ".join(missing)
        )
    duplicate = [
        role_id for role_id in required_role_ids if len(candidates_by_role[role_id]) > 1
    ]
    if duplicate:
        raise ContractValidationError(
            "multiple agents are bound to required participant role(s): "
            + ", ".join(duplicate)
        )

    snapshot = [candidates_by_role[role_id][0] for role_id in required_role_ids]
    resolution_seed = {
        "teamId": normalized_team_id,
        "roomId": normalized_room_id,
        "meetingType": normalized_meeting_type,
        "teamRoleContractVersion": contract.team_role_contract_version,
        "participantPolicyVersion": contract.participant_policy_version,
        "roleContractFingerprint": contract.fingerprint(),
        "participantRoleSnapshot": snapshot,
    }
    return {
        "participants": [item["agentId"] for item in snapshot],
        "participantRoleIds": required_role_ids,
        "participantRoleSnapshot": snapshot,
        "teamRoleContractVersion": contract.team_role_contract_version,
        "participantPolicyVersion": contract.participant_policy_version,
        "roleContractFingerprint": contract.fingerprint(),
        "resolutionHash": sha256_hex(resolution_seed),
    }


def _validated_participant_resolution(
    team_id: str,
    room_id: str,
    meeting_type: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    resolved = resolve_hypothesis_meeting_participants(team_id, room_id, meeting_type)
    if "participants" in request:
        raw_participants = request.get("participants")
        provided_participants = (
            [str(item or "").strip() for item in raw_participants]
            if isinstance(raw_participants, (list, tuple))
            else []
        )
        if provided_participants != resolved["participants"]:
            raise ContractValidationError(
                "participants must match the server-resolved participant roster"
            )

    provided_contract_fields = [
        field for field in _PARTICIPANT_CONTRACT_FIELDS if field in request
    ]
    if provided_contract_fields and len(provided_contract_fields) != len(
        _PARTICIPANT_CONTRACT_FIELDS
    ):
        raise ContractValidationError(
            "callers must provide the complete participant contract snapshot or omit it"
        )
    for field in provided_contract_fields:
        provided: Any = request.get(field)
        if field == "participantRoleIds":
            provided = (
                [str(item or "").strip() for item in provided]
                if isinstance(provided, (list, tuple))
                else []
            )
        elif field == "participantRoleSnapshot":
            provided = (
                [dict(item) for item in provided]
                if isinstance(provided, (list, tuple))
                and all(isinstance(item, Mapping) for item in provided)
                else []
            )
        elif field in {"roleContractFingerprint", "resolutionHash"}:
            provided = str(provided or "").strip().lower()
        if provided != resolved[field]:
            raise ContractValidationError(
                f"{field} must match the server-resolved participant contract"
            )
    return resolved


def _frozen_participant_agent_ids(meeting_round: Mapping[str, Any]) -> list[str]:
    participants = _normalized_str_list(meeting_round.get("participants"))
    snapshot = [
        dict(item)
        for item in list(meeting_round.get("participantRoleSnapshot") or [])
        if isinstance(item, Mapping)
    ]
    snapshot_agent_ids = [str(item.get("agentId") or "").strip() for item in snapshot]
    if (
        not participants
        or not snapshot
        or snapshot_agent_ids != participants
        or not _normalized_str_list(meeting_round.get("participantRoleIds"))
        or not int(meeting_round.get("teamRoleContractVersion") or 0)
        or not int(meeting_round.get("participantPolicyVersion") or 0)
        or not str(meeting_round.get("roleContractFingerprint") or "").strip()
        or not str(meeting_round.get("resolutionHash") or "").strip()
    ):
        raise ResearchMeetingRuntimeError(
            "legacy meeting round has no complete participant snapshot and cannot continue discussion"
        )
    return participants


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
    generation_context: Mapping[str, Any] | None = None,
) -> str:
    context = question_context or {}
    grounded = generation_context or {}
    lines = [
        f"候选假说生成讨论开幕（{meeting_round_id}）：{question_id or '未命名赛题'}",
    ]
    question_text = str(context.get("questionText") or "").strip()
    domain = str(context.get("domain") or "").strip()
    if question_text:
        lines.append("赛题正文：" + question_text)
    if domain:
        lines.append("赛题领域：" + domain)
    evidence_claims = [
        dict(item)
        for item in list(grounded.get("evidenceClaims") or [])[:8]
        if isinstance(item, Mapping)
    ]
    if evidence_claims:
        lines.append("受控证据摘要（引用键必须原样用于 REFS）：")
        lines.extend(
            f"- {str(item.get('sourceRef') or '').strip()} | {str(item.get('claim') or '').strip()[:300]}"
            for item in evidence_claims
            if str(item.get("sourceRef") or "").strip()
        )
    exploratory_drafts = [
        dict(item)
        for item in list(grounded.get("exploratoryDrafts") or [])[:8]
        if isinstance(item, Mapping)
    ]
    if exploratory_drafts:
        lines.append("R0 探索草案（仅供修订，不得沿用 candidateId）：")
        lines.extend(
            f"- {str(item.get('draftId') or item.get('candidateId') or '').strip()} | {str(item.get('statement') or '').strip()[:300]}"
            for item in exploratory_drafts
        )
    formal_grounded = (
        str(grounded.get("candidateAuthority") or "").strip().lower()
        == "formal_grounded_candidate"
    )
    lines.extend(
        [
            "议程：" + "；".join(str(item) for item in agenda),
            "规则："
            + "；".join(
                _FORMAL_GROUNDED_GENERATION_AGENDA_RULES
                if formal_grounded
                else _GENERATION_AGENDA_RULES
            ),
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
    auto_drive_discussion: bool = False,
) -> dict[str, Any]:
    discussion_scope = meeting_round.get("discussionScope")
    discussion_scope_hash = str(
        meeting_round.get("discussionScopeHash") or ""
    ).strip().lower()
    scope_authority = (
        _PREFORMAL_DISCUSSION_SCOPE_AUTHORITY
        if isinstance(discussion_scope, Mapping)
        and str(discussion_scope.get("kind") or "").strip()
        == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
        else _SCOPED_DISCUSSION_SCOPE_AUTHORITY
    )
    challenge_deadline_at_ms = meeting_round.get("challengeDeadlineAtMs")
    return {
        "source": MEETING_SOURCE,
        "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
        "meetingType": str(meeting_round.get("meetingType") or "hypothesis_review"),
        "meetingStage": str(meeting_round.get("stage") or ""),
        "meetingRoundType": str(meeting_round.get("roundType") or ""),
        "candidateAuthority": str(meeting_round.get("candidateAuthority") or ""),
        "selectionId": str(selection.get("selectionId") or ""),
        # The legacy MeetingRound scopeHash is retained for compatibility. A
        # formal room has its own canonical v1 hash and must not be overwritten
        # by the legacy six-field meeting hash when the round config is merged.
        "scopeHash": discussion_scope_hash
        or str(meeting_round.get("scopeHash") or ""),
        **(
            {
                "scopeAuthority": scope_authority,
                "discussionScope": dict(discussion_scope),
                "discussionScopeHash": discussion_scope_hash,
            }
            if isinstance(discussion_scope, Mapping)
            else {}
        ),
        **{field: str(meeting_round.get(field) or "") for field in _SCOPE_FIELDS},
        "agentId": str(meeting_round.get("agentId") or ""),
        "mode": str(meeting_round.get("mode") or ""),
        "teamId": str(team_id or meeting_round.get("teamId") or "").strip(),
        "discussionRoundIndex": discussion_round_index,
        # Only production's default runner opts into the background driver.
        # Fixture/custom runners deliberately keep the synchronous contract so
        # callers can inspect and control every discussion round themselves.
        "autoDriveDiscussion": bool(auto_drive_discussion),
        "agenda": list(meeting_round.get("agenda") or []),
        "agendaQuestions": list(meeting_round.get("agendaQuestions") or []),
        "agendaRules": list(meeting_round.get("agendaRules") or []),
        "selectedCandidateIds": list(selection.get("selectedCandidateIds") or []),
        "participantAgentIds": _frozen_participant_agent_ids(meeting_round),
        **(
            {"challengeDeadlineAtMs": int(challenge_deadline_at_ms)}
            if isinstance(challenge_deadline_at_ms, int)
            and not isinstance(challenge_deadline_at_ms, bool)
            and challenge_deadline_at_ms > 0
            else {}
        ),
        **{
            field: meeting_round[field]
            for field in (
                "deadlinePolicyVersion",
                "deadlinePolicyHash",
                "plannedSerialCallCount",
                "perCallBudgetMs",
                "meetingBudgetMs",
                "meetingDeadlineAtMs",
                "sampleSource",
                "sampleCount",
                "latencyP95Ms",
            )
            if meeting_round.get(field) not in (None, "")
        },
    }


def _normalized_model_invocation_receipt_authority(
    authority: Mapping[str, Any] | None,
    *,
    team_id: str,
    question_id: str,
) -> dict[str, Any] | None:
    """Validate the private server-owned run binding before it reaches chat."""

    if authority is None:
        return None
    if not isinstance(authority, Mapping):
        raise ResearchMeetingRuntimeError("meeting receipt authority must be an object")
    normalized = {
        "schemaVersion": authority.get("schemaVersion"),
        "authorityKind": str(authority.get("authorityKind") or "").strip(),
        "teamId": str(authority.get("teamId") or "").strip(),
        "questionId": str(authority.get("questionId") or "").strip().upper(),
        "workflowRunId": str(authority.get("workflowRunId") or "").strip(),
        "workflowId": str(authority.get("workflowId") or "").strip(),
        "workflowVersionId": str(authority.get("workflowVersionId") or "").strip(),
        "modelPolicySha256": str(authority.get("modelPolicySha256") or "")
        .strip()
        .lower(),
    }
    expected_team = str(team_id or "").strip()
    expected_question = str(question_id or "").strip().upper()
    if (
        normalized["schemaVersion"] != _MEETING_RECEIPT_AUTHORITY_SCHEMA_VERSION
        or normalized["authorityKind"] != "workflow_run"
        or normalized["teamId"] != expected_team
        or normalized["questionId"] != expected_question
        or any(
            not normalized[key]
            for key in ("workflowRunId", "workflowId", "workflowVersionId")
        )
    ):
        raise ResearchMeetingRuntimeError("meeting receipt authority scope is invalid")
    policy_sha256 = normalized["modelPolicySha256"]
    if len(policy_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in policy_sha256
    ):
        raise ResearchMeetingRuntimeError("meeting receipt authority policy hash is invalid")
    return normalized


def _require_matching_model_invocation_receipt_authority(
    meeting_round: Mapping[str, Any],
    authority: Mapping[str, Any] | None,
    *,
    team_id: str,
    question_id: str,
) -> dict[str, Any] | None:
    """Refuse to rebind a deterministic meeting id to another formal run."""

    if authority is None:
        return None
    normalized = _normalized_model_invocation_receipt_authority(
        authority,
        team_id=team_id,
        question_id=question_id,
    )
    stored = meeting_round.get("modelInvocationReceiptAuthority")
    if not isinstance(stored, Mapping) or dict(stored) != normalized:
        raise ResearchMeetingRuntimeError(
            "existing meeting is not bound to this formal workflow run"
        )
    return normalized


def _require_reused_formal_meeting_authority(
    meeting_round: Mapping[str, Any],
    authority: Mapping[str, Any] | None,
    *,
    team_id: str,
    question_id: str,
) -> dict[str, Any]:
    """Fail closed when a formal meeting cannot prove its run authority.

    ``create_meeting_round`` is append-only and intentionally idempotent, so a
    legacy record with the same meeting id can otherwise be returned as
    ``reused``.  A formal run must never continue from that record unless both
    sides of its server-owned receipt binding are present and equal.
    """

    stored = meeting_round.get("modelInvocationReceiptAuthority")
    if not isinstance(stored, Mapping):
        raise ResearchMeetingRuntimeError(
            "existing formal meeting has no verifiable receipt authority"
        )
    if authority is None:
        raise ResearchMeetingRuntimeError(
            "existing formal meeting requires receipt authority"
        )
    return _require_matching_model_invocation_receipt_authority(
        meeting_round,
        authority,
        team_id=team_id,
        question_id=question_id,
    ) or {}


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
    _model_invocation_receipt_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Open a hypothesis-review meeting from a hypothesis selection payload.

    Creates the ``hypothesis_review`` MeetingRound (stage ``hypothesis``,
    roundType ``decision_gate`` by default) and starts the first discussion
    round in the team's linked chat room with the meeting binding in config.
    Reopening with an identical payload reuses the existing meeting and its
    bound discussion round instead of starting a duplicate.
    """
    # This must run before linked-room/session resolution: both can create
    # durable Challenge Cup objects when the reset fence is active.
    assert_writes_allowed(team_id, operation="meeting_open")
    from core.web.services import chat_room_service

    request = dict(payload) if isinstance(payload, Mapping) else {}
    selection = _validated_selection(request)
    team, base_room_id = _ensure_linked_room(str(team_id or "").strip())
    receipt_authority = _normalized_model_invocation_receipt_authority(
        _model_invocation_receipt_authority,
        team_id=team["teamId"],
        question_id=str(selection.get("questionId") or ""),
    )
    participant_resolution = _validated_participant_resolution(
        team["teamId"], base_room_id, "hypothesis_review", request
    )
    discussion_scope = _discussion_scope_for_request(
        team["teamId"],
        request,
        question_id=str(selection.get("questionId") or ""),
        meeting_type="hypothesis_review",
        selection=selection,
    )
    room_id, discussion_scope = _resolve_scoped_meeting_room(
        team["teamId"],
        request,
        base_room_id=base_room_id,
        scope=discussion_scope,
        participant_resolution=participant_resolution,
        meeting_type="hypothesis_review",
        selected_candidate_ids=selection["selectedCandidateIds"],
    )
    effective_selection = dict(selection)
    if discussion_scope is not None and discussion_scope.is_candidate_review:
        effective_selection["selectedCandidateIds"] = [discussion_scope.candidateId]

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
            **participant_resolution,
            "meetingType": "hypothesis_review",
            "stage": str(request.get("stage") or "hypothesis").strip().lower(),
            "roundType": str(request.get("roundType") or "decision_gate").strip().lower(),
            "discussionItemRefs": [
                f"hypothesis_candidate:{candidate_id}"
                for candidate_id in effective_selection["selectedCandidateIds"]
            ],
            "inputArtifactRefs": [
                f"hypothesis_selection:{selection['selectionId']}",
                *_normalized_str_list(request.get("inputArtifactRefs")),
            ],
            "agenda": agenda,
            "agendaQuestions": agenda_questions,
            "agendaRules": agenda_rules,
            "linkedChatRoomId": room_id,
            **(
                {"modelInvocationReceiptAuthority": receipt_authority}
                if receipt_authority is not None
                else {}
            ),
        },
    )
    if created["status"] == "reused" and (
        receipt_authority is not None
        or isinstance(discussion_scope, WorkflowDiscussionScopeV1)
    ):
        _require_reused_formal_meeting_authority(
            created["meetingRound"],
            receipt_authority,
            team_id=team["teamId"],
            question_id=str(selection.get("questionId") or ""),
        )
    meeting_round = _persist_discussion_scope_projection(
        team["teamId"], created["meetingRound"], discussion_scope
    )
    meeting_round = meeting_rounds.persist_challenge_meeting_deadline_policy(
        team["teamId"], str(meeting_round.get("meetingRoundId") or "")
    )
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
    if meeting_round.get("deadlineBudgetSufficient") is False:
        problem = meeting_round.get("deadlineProblem") or {}
        raise ResearchMeetingRuntimeError(
            "deadline_budget_insufficient: "
            f"availableMs={int(problem.get('availableMs') or 0)} "
            f"requiredMs={int(problem.get('requiredMs') or 0)}"
        )

    topic = str(request.get("topic") or "").strip() or _opening_topic(
        meeting_round_id, effective_selection, agenda, candidate_contexts
    )
    bound_result: dict[str, Any] = {}

    def bind_opening_round(_room: Mapping[str, Any], round_payload: Mapping[str, Any]) -> None:
        bound_result.update(
            meeting_rounds.bind_meeting_chat_room_round(
                team["teamId"],
                meeting_round_id,
                room_id,
                str(round_payload.get("roundId") or ""),
            )
        )

    result = chat_room_service.start_chat_room_round(
        room_id,
        topic,
        purpose="meeting",
        config=_round_config(
            meeting_round,
            effective_selection,
            discussion_round_index=1,
            team_id=str(team_id or ""),
            auto_drive_discussion=background and agent_runner is None,
        ),
        agent_runner=agent_runner,
        background=background,
        lightweight_response=background,
        max_topic_lines=MEETING_TOPIC_MAX_LINES,
        _model_invocation_receipt_authority=receipt_authority,
        _on_round_persisted=bind_opening_round if background else None,
    )
    round_id = _round_id_from_start_result(result, meeting_round_id)
    bound = bound_result or meeting_rounds.bind_meeting_chat_room_round(
        team["teamId"], meeting_round_id, room_id, round_id
    )
    if background and agent_runner is None:
        # The first room round can finish before its meeting binding is
        # persisted. Scheduling after the bind closes that race; the scheduler
        # remains a no-op until the opening round is terminal.
        schedule_meeting_discussion(team["teamId"], meeting_round_id)
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
    _model_invocation_receipt_authority: Mapping[str, Any] | None = None,
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
    assert_writes_allowed(team_id, operation="meeting_open")
    from core.web.services import chat_room_service

    request = dict(payload) if isinstance(payload, Mapping) else {}
    question_id = str(request.get("questionId") or "").strip().upper()
    if not question_id:
        raise ContractValidationError(
            "opening a candidate generation meeting requires a questionId"
        )
    team, base_room_id = _ensure_linked_room(str(team_id or "").strip())
    receipt_authority = _normalized_model_invocation_receipt_authority(
        _model_invocation_receipt_authority,
        team_id=team["teamId"],
        question_id=question_id,
    )
    participant_resolution = _validated_participant_resolution(
        team["teamId"], base_room_id, CANDIDATE_GENERATION_MEETING_TYPE, request
    )
    discussion_scope = _discussion_scope_for_request(
        team["teamId"],
        request,
        question_id=question_id,
        meeting_type=CANDIDATE_GENERATION_MEETING_TYPE,
    )
    room_id, discussion_scope = _resolve_scoped_meeting_room(
        team["teamId"],
        request,
        base_room_id=base_room_id,
        scope=discussion_scope,
        participant_resolution=participant_resolution,
        meeting_type=CANDIDATE_GENERATION_MEETING_TYPE,
    )

    agenda = _normalized_str_list(request.get("agenda")) or list(_GENERATION_AGENDA)
    agenda_questions = _normalized_str_list(request.get("agendaQuestions")) or list(
        _GENERATION_AGENDA_QUESTIONS
    )
    candidate_authority = str(request.get("candidateAuthority") or "").strip().lower()
    agenda_rules = _normalized_str_list(request.get("agendaRules")) or list(
        _FORMAL_GROUNDED_GENERATION_AGENDA_RULES
        if candidate_authority == "formal_grounded_candidate"
        else _GENERATION_AGENDA_RULES
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
            **participant_resolution,
            "meetingType": CANDIDATE_GENERATION_MEETING_TYPE,
            "stage": "hypothesis",
            "roundType": "generation",
            "discussionItemRefs": [],
            "inputArtifactRefs": _normalized_str_list(request.get("inputArtifactRefs")),
            "candidateAuthority": candidate_authority,
            "allowedEvidenceRefs": _normalized_str_list(
                request.get("allowedEvidenceRefs")
            ),
            "exploratoryDraftRefs": _normalized_str_list(
                request.get("exploratoryDraftRefs")
            ),
            "knowledgePackageRefs": _normalized_str_list(
                request.get("knowledgePackageRefs")
            ),
            "revisionOrdinal": request.get("revisionOrdinal") or 0,
            "agenda": agenda,
            "agendaQuestions": agenda_questions,
            "agendaRules": agenda_rules,
            "linkedChatRoomId": room_id,
            **(
                {"modelInvocationReceiptAuthority": receipt_authority}
                if receipt_authority is not None
                else {}
            ),
        },
    )
    if created["status"] == "reused" and (
        receipt_authority is not None
        or isinstance(discussion_scope, WorkflowDiscussionScopeV1)
    ):
        _require_reused_formal_meeting_authority(
            created["meetingRound"],
            receipt_authority,
            team_id=team["teamId"],
            question_id=question_id,
        )
    meeting_round = _persist_discussion_scope_projection(
        team["teamId"], created["meetingRound"], discussion_scope
    )
    meeting_round = meeting_rounds.persist_challenge_meeting_deadline_policy(
        team["teamId"], str(meeting_round.get("meetingRoundId") or "")
    )
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
    if meeting_round.get("deadlineBudgetSufficient") is False:
        problem = meeting_round.get("deadlineProblem") or {}
        raise ResearchMeetingRuntimeError(
            "deadline_budget_insufficient: "
            f"availableMs={int(problem.get('availableMs') or 0)} "
            f"requiredMs={int(problem.get('requiredMs') or 0)}"
        )

    topic = str(request.get("topic") or "").strip() or _generation_opening_topic(
        meeting_round_id,
        question_id,
        agenda,
        question_context=_catalog_question_context(question_id),
        generation_context=(
            dict(request.get("generationContext") or {})
            if isinstance(request.get("generationContext"), Mapping)
            else {"candidateAuthority": candidate_authority}
        ),
    )
    selection_shim = {
        "selectionId": "",
        "questionId": question_id,
        "selectedCandidateIds": [],
    }
    bound_result: dict[str, Any] = {}

    def bind_opening_round(_room: Mapping[str, Any], round_payload: Mapping[str, Any]) -> None:
        bound_result.update(
            meeting_rounds.bind_meeting_chat_room_round(
                team["teamId"],
                meeting_round_id,
                room_id,
                str(round_payload.get("roundId") or ""),
            )
        )

    result = chat_room_service.start_chat_room_round(
        room_id,
        topic,
        purpose="meeting",
        config=_round_config(
            meeting_round,
            selection_shim,
            discussion_round_index=1,
            team_id=str(team_id or ""),
            auto_drive_discussion=background and agent_runner is None,
        ),
        agent_runner=agent_runner,
        background=background,
        lightweight_response=background,
        max_topic_lines=MEETING_TOPIC_MAX_LINES,
        _model_invocation_receipt_authority=receipt_authority,
        _on_round_persisted=bind_opening_round if background else None,
    )
    round_id = _round_id_from_start_result(result, meeting_round_id)
    bound = bound_result or meeting_rounds.bind_meeting_chat_room_round(
        team["teamId"], meeting_round_id, room_id, round_id
    )
    if background and agent_runner is None:
        schedule_meeting_discussion(team["teamId"], meeting_round_id)
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


def _record_meeting_discussion_driver_event(
    team_id: str,
    meeting_round_id: str,
    event_code: str,
    *,
    outcome: str,
    error: Exception | None = None,
) -> None:
    """Emit bounded scheduler evidence without turning logs into authority."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_discussion",
            event_code,
            message=(
                "Hypothesis meeting discussion driver failed."
                if error is not None
                else "Hypothesis meeting discussion driver scheduled."
            ),
            level="error" if error is not None else "info",
            outcome=outcome,
            fields={
                "teamId": team_id,
                "meetingRoundId": meeting_round_id,
                "errorType": type(error).__name__ if error is not None else "",
                "error": str(error)[:240] if error is not None else "",
            },
            lifecycle=True,
        )
    except Exception:
        # A diagnostic outage must not alter the meeting lifecycle.
        return


def _record_driver_work_state(
    team_id: str,
    meeting_round_id: str,
    *,
    status: str,
    error: Exception | None = None,
) -> None:
    """Persist the durable driver intent; storage outages never alter the run."""

    try:
        meeting_driver_work.record_intent(
            team_id,
            meeting_round_id,
            status=status,
            last_problem=None if error is None else meeting_driver_work.format_problem(error),
        )
    except Exception:  # noqa: BLE001 - durable intent accelerates recovery only
        return


def _run_scheduled_meeting_discussion(team_id: str, meeting_round_id: str) -> None:
    key = (team_id, meeting_round_id)
    try:
        _record_driver_work_state(
            team_id, meeting_round_id, status=meeting_driver_work.STATUS_RUNNING
        )
        result = run_meeting_discussion(team_id, meeting_round_id)
        _record_driver_work_state(
            team_id, meeting_round_id, status=meeting_driver_work.STATUS_COMPLETED
        )
        _record_meeting_discussion_driver_event(
            team_id,
            meeting_round_id,
            "meeting_discussion.driver.completed",
            outcome=str(result.get("stopReason") or "completed"),
        )
    except Exception as exc:  # noqa: BLE001 - background failures need durable evidence
        _record_driver_work_state(
            team_id,
            meeting_round_id,
            status=meeting_driver_work.STATUS_FAILED,
            error=exc,
        )
        _record_meeting_discussion_driver_event(
            team_id,
            meeting_round_id,
            "meeting_discussion.driver.failed",
            outcome="failed",
            error=exc,
        )
    finally:
        with _MEETING_DISCUSSION_JOBS_LOCK:
            _MEETING_DISCUSSION_JOBS.discard(key)


def schedule_meeting_discussion(team_id: str, meeting_round_id: str) -> dict[str, Any]:
    """Queue the post-opening discussion driver exactly once when it is ready.

    Opening chat rounds run in the chat executor. A separate bounded meeting
    executor avoids blocking that worker while each candidate completes its
    own second/third round and reaches the human approval gate.
    """

    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRuntimeError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(
        normalized_team_id, normalized_round_id
    )["meetingRound"]
    if str(meeting_round.get("status") or "").strip().lower() != "open":
        return {
            "status": "not_open",
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
        }
    bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not bound_round_ids:
        return {
            "status": "waiting_for_binding",
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
        }
    if meeting_rounds.running_bound_round_ids(meeting_round):
        return {
            "status": "waiting_for_opening_round",
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
        }
    latest_messages = _latest_bound_round_messages(meeting_round)
    if not any(
        str(message.get("status") or "").strip().lower() == "completed"
        for message in latest_messages
    ):
        return {
            "status": "waiting_for_completed_speech",
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
        }
    key = (normalized_team_id, normalized_round_id)
    with _MEETING_DISCUSSION_JOBS_LOCK:
        if key in _MEETING_DISCUSSION_JOBS:
            return {
                "status": "already_scheduled",
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
            }
        _MEETING_DISCUSSION_JOBS.add(key)
    # Persist the intent before the executor accepts the job: a backend
    # restart between here and completion must leave a recoverable record.
    _record_driver_work_state(
        normalized_team_id,
        normalized_round_id,
        status=meeting_driver_work.STATUS_PENDING,
    )
    try:
        _MEETING_DISCUSSION_EXECUTOR.submit(
            _run_scheduled_meeting_discussion,
            normalized_team_id,
            normalized_round_id,
        )
    except Exception as exc:
        with _MEETING_DISCUSSION_JOBS_LOCK:
            _MEETING_DISCUSSION_JOBS.discard(key)
        _record_driver_work_state(
            normalized_team_id,
            normalized_round_id,
            status=meeting_driver_work.STATUS_FAILED,
            error=exc,
        )
        raise
    _record_meeting_discussion_driver_event(
        normalized_team_id,
        normalized_round_id,
        "meeting_discussion.driver.scheduled",
        outcome="scheduled",
    )
    return {
        "status": "scheduled",
        "teamId": normalized_team_id,
        "meetingRoundId": normalized_round_id,
    }


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
    _frozen_participant_agent_ids(meeting_round)
    selection = _selection_from_meeting(meeting_round)
    receipt_authority = (
        dict(meeting_round.get("modelInvocationReceiptAuthority"))
        if isinstance(meeting_round.get("modelInvocationReceiptAuthority"), Mapping)
        else None
    )
    if receipt_authority is not None:
        challenge_deadline_at_ms = meeting_round.get("challengeDeadlineAtMs")
        if not (
            isinstance(challenge_deadline_at_ms, int)
            and not isinstance(challenge_deadline_at_ms, bool)
            and challenge_deadline_at_ms > 0
        ):
            challenge_deadline_at_ms = _bound_room_challenge_deadline_at_ms(
                room_id,
                bound_round_ids,
            )
        if challenge_deadline_at_ms is not None:
            # The persisted MeetingRound deadline policy is the single source
            # for the per-call fence.  Legacy meetings that recovered their
            # clock from the bound room config must also recover the persisted
            # per-call budget fields, otherwise room rounds would silently
            # lose the per-call fence (or fall back to defaults).
            recovered_policy = {
                field: value
                for field in ("perCallBudgetMs", "meetingDeadlineAtMs")
                if meeting_round.get(field) in (None, "")
                and (value := _bound_room_deadline_policy_field(room_id, bound_round_ids, field))
                is not None
            }
            meeting_round = {
                **dict(meeting_round),
                "challengeDeadlineAtMs": challenge_deadline_at_ms,
                **recovered_policy,
            }
    budget = int(meeting_round.get("rounds") or 3)
    stop_reason = ""
    while len(bound_round_ids) < budget:
        parent_run_stop_reason = workflow_run_stop_reason(receipt_authority)
        if parent_run_stop_reason:
            stop_reason = parent_run_stop_reason
            break
        challenge_deadline_at_ms = meeting_round.get("challengeDeadlineAtMs")
        if (
            isinstance(challenge_deadline_at_ms, int)
            and not isinstance(challenge_deadline_at_ms, bool)
            and int(time.time() * 1000) >= challenge_deadline_at_ms
        ):
            stop_reason = "challenge_deadline"
            break
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
        # Existing meetings may drain, but they cannot create another room
        # round after maintenance starts.
        assert_writes_allowed(normalized_team_id, operation="meeting_round_start")
        bound_result: dict[str, Any] = {}

        def bind_follow_up_round(
            _room: Mapping[str, Any], round_payload: Mapping[str, Any]
        ) -> None:
            bound_result.update(
                meeting_rounds.bind_meeting_chat_room_round(
                    normalized_team_id,
                    normalized_round_id,
                    room_id,
                    str(round_payload.get("roundId") or ""),
                )
            )

        chat_room_service.start_chat_room_round(
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
            _model_invocation_receipt_authority=receipt_authority,
            _on_round_persisted=bind_follow_up_round,
        )
        bound = bound_result
        meeting_round = bound["meetingRound"]
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    else:
        stop_reason = "budget_exhausted"

    all_messages = meeting_rounds.meeting_source_messages(meeting_round)
    if stop_reason == "challenge_deadline" or stop_reason.startswith(
        "challenge_workflow_run_"
    ):
        # The room round is the source of truth for the stopped discussion.
        # Do not draft or approve a digest from a partial, deadline-expired
        # fan-out; a retry must remain a no-op against the same absolute clock.
        terminal = meeting_rounds.terminate_meeting_execution(
            normalized_team_id,
            normalized_round_id,
            reason=stop_reason,
        )
        meeting_round = terminal["meetingRound"]
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "stopped",
            "meetingRound": meeting_round,
            "roomId": room_id,
            "chatRoomRoundIds": bound_round_ids,
            "roundsRun": len(bound_round_ids),
            "roundBudget": budget,
            "maxMessages": normalized_max_messages,
            "messageCount": len(all_messages),
            "completedMessageCount": sum(
                1
                for message in all_messages
                if str(message.get("status") or "").strip().lower() == "completed"
            ),
            "stopReason": stop_reason,
            "summaryDraft": None,
        }
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
    if drafted is not None:
        # Active-policy hook (autoCloseMeetingRound): a digest draft just
        # landed (meeting is awaiting_approval).  Gated, audited, quiet —
        # with no active policy configured this is a no-op before any I/O,
        # and the executor never breaks the discussion completion result.
        try:
            from core.web.services.team_workflow.research_runtime import (
                automation_policy_executor,
            )

            automation_policy_executor.attempt_capability_quietly(
                decision_point="meeting_close",
                team_id=normalized_team_id,
                meeting_round_id=normalized_round_id,
            )
        except Exception:  # noqa: BLE001 - hooks never break the discussion flow
            pass
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


def _bound_room_challenge_deadline_at_ms(
    room_id: str,
    bound_round_ids: Sequence[str],
) -> int | None:
    """Read the first formal round's server-owned deadline for follow-ups."""

    from core.web.services import chat_room_service

    room = chat_room_service.get_chat_room_detail(room_id) or {}
    expected_round_ids = set(_normalized_str_list(bound_round_ids))
    for round_payload in reversed(list(room.get("rounds") or [])):
        if not isinstance(round_payload, Mapping):
            continue
        if str(round_payload.get("roundId") or "").strip() not in expected_round_ids:
            continue
        config = round_payload.get("config") if isinstance(round_payload.get("config"), Mapping) else {}
        value = config.get("challengeDeadlineAtMs")
        if isinstance(value, bool):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None
    return None


def _bound_room_deadline_policy_field(
    room_id: str,
    bound_round_ids: Sequence[str],
    field: str,
) -> int | None:
    """Recover one persisted deadline-policy field from a bound room round.

    The bound round config was server-derived from the MeetingRound record
    when that round started, so it is the faithful fallback source for legacy
    meetings whose own record predates the persisted policy fields.
    """

    from core.web.services import chat_room_service

    room = chat_room_service.get_chat_room_detail(room_id) or {}
    expected_round_ids = set(_normalized_str_list(bound_round_ids))
    for round_payload in reversed(list(room.get("rounds") or [])):
        if not isinstance(round_payload, Mapping):
            continue
        if str(round_payload.get("roundId") or "").strip() not in expected_round_ids:
            continue
        config = round_payload.get("config") if isinstance(round_payload.get("config"), Mapping) else {}
        value = config.get(field)
        if isinstance(value, bool):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None
    return None


def _record_meeting_digest_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: Mapping[str, Any],
    level: str = "info",
    lifecycle: bool = False,
) -> None:
    """Emit bounded digest lifecycle evidence without becoming state authority."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_digest",
            event_code,
            message="Meeting digest lifecycle observed.",
            level=level,
            outcome=outcome,
            fields=dict(fields),
            lifecycle=lifecycle,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never fail the meeting
        # Diagnostics are best-effort and must never alter meeting state.
        return


def _meeting_digest_source_metrics(
    meeting_round: Mapping[str, Any],
    source_messages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    completed = [
        item
        for item in source_messages
        if str(item.get("status") or "").strip().lower() == "completed"
    ]
    return {
        "teamId": str(meeting_round.get("teamId") or ""),
        "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
        "meetingType": str(meeting_round.get("meetingType") or ""),
        "meetingStatus": str(meeting_round.get("status") or ""),
        "sourceMessageCount": len(source_messages),
        "completedSourceMessageCount": len(completed),
        "transcriptChars": sum(
            len(str(item.get("content") or "")) for item in completed
        ),
        "participantCount": len(
            _normalized_str_list(meeting_round.get("participants"))
        ),
        "roundCount": len(_normalized_str_list(meeting_round.get("chatRoomRoundIds"))),
    }


def _meeting_digest_fact_counts(draft: Mapping[str, Any]) -> dict[str, int]:
    ledger = (
        draft.get("factLedger")
        if isinstance(draft.get("factLedger"), Mapping)
        else draft
    )
    return {
        "agreementCount": len(list(ledger.get("agreements") or [])),
        "disagreementCount": len(list(ledger.get("disagreements") or [])),
        "actionCount": len(list(ledger.get("actionItems") or [])),
        "riskCount": len(list(ledger.get("risks") or [])),
        "knowledgeCandidateCount": len(list(ledger.get("knowledgeCandidates") or [])),
        "proposedCandidateCount": len(list(ledger.get("proposedCandidates") or [])),
        "evidenceRequestCount": len(list(ledger.get("evidenceRequests") or [])),
        "validationErrorCount": len(list(ledger.get("validationErrors") or [])),
        "sourceMessageRefCount": len(list(ledger.get("sourceMessageRefs") or [])),
    }


def build_meeting_digest_draft(
    meeting_round: Mapping[str, Any],
    source_messages: Sequence[Mapping[str, Any]],
    *,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]]
    | None = None,
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
        return _merge_llm_digest_with_deterministic_markers(
            meeting_round, dict(drafted)
        )
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
    meeting_type = str(meeting_round.get("meetingType") or "").strip()
    is_candidate_generation = meeting_type == CANDIDATE_GENERATION_MEETING_TYPE
    meeting_label = "候选生成会议" if is_candidate_generation else "假说评审会议"
    discussion_focus = (
        f"{len(markers['proposedCandidates'])} 个候选"
        if is_candidate_generation
        else f"{len(discussion_item_refs)} 个入选候选"
    )
    if unstructured_agreements and not markers.get("disagreements"):
        summary = (
            f"{meeting_label} {str(meeting_round.get('meetingRoundId') or '')}："
            f"{len(participants)} 位参与者围绕 {discussion_focus}完成 "
            f"{rounds_run} 轮讨论，从 {len(unstructured_agreements)} 条自由格式发言生成摘要条目，"
            "未提取到标记化共识或分歧。"
        )
    else:
        summary = (
            f"{meeting_label} {str(meeting_round.get('meetingRoundId') or '')}："
            f"{len(participants)} 位参与者围绕 {discussion_focus}完成 "
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


_LLM_DIGEST_MARKER_BUCKETS = (
    "agreements",
    "disagreements",
    "actionItems",
    "risks",
    "knowledgeCandidates",
    "proposedCandidates",
)
_PROTOCOL_FACT_LEDGER_SCHEMA_VERSION = 1


def _merge_llm_digest_with_deterministic_markers(
    meeting_round: Mapping[str, Any],
    drafted: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the source-owned protocol ledger and legacy field projections.

    The LLM owns only the narrative document. Explicit marker facts already
    exist in completed room messages, so asking the model to reproduce them
    made the digest response large and then discarded that work. The ledger
    remains authoritative for those facts. ``factLedger`` is the approved
    source snapshot, and the existing top-level buckets are compatibility
    projections at draft time while current consumers migrate.
    """

    completed_messages = meeting_rounds.completed_meeting_source_messages(meeting_round)
    markers = meeting_rounds.extract_discussion_markers(completed_messages)
    merged = dict(drafted)
    for key in _LLM_DIGEST_MARKER_BUCKETS:
        merged[key] = list(markers.get(key) or [])
    source_refs = [
        meeting_rounds.message_source_ref(message)
        for message in completed_messages
    ]
    evidence_requests, validation_errors = _collect_evidence_requests(
        meeting_round, markers, source_refs
    )
    fact_ledger = {
        "schemaVersion": _PROTOCOL_FACT_LEDGER_SCHEMA_VERSION,
        "source": "completed_meeting_messages",
        **{
            key: list(markers.get(key) or [])
            for key in _LLM_DIGEST_MARKER_BUCKETS
        },
        "evidenceRequests": evidence_requests,
        "validationErrors": validation_errors,
        "sourceMessageRefs": source_refs,
    }
    merged["factLedger"] = fact_ledger
    merged["sourceMessageRefs"] = source_refs
    merged["evidenceRequests"] = evidence_requests
    merged["validationErrors"] = validation_errors
    _record_meeting_digest_scene_event(
        "meeting_digest.fact_ledger.projected",
        outcome="succeeded",
        fields={
            "teamId": str(meeting_round.get("teamId") or ""),
            "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
            **_meeting_digest_fact_counts(merged),
        },
    )
    return merged


def draft_meeting_digest(
    team_id: str,
    meeting_round_id: str,
    *,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate the Coordinator digest draft and move the meeting to ``awaiting_approval``.

    Without an injected ``drafter`` the operator-configured LLM is tried
    first; when no model is configured the deterministic DEV fixture
    drafter keeps the previous behaviour.
    """
    from core.web.services import team_service

    started_at = time.monotonic()
    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRuntimeError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    source_messages = meeting_rounds.meeting_source_messages(meeting_round)
    effective_drafter = drafter
    if effective_drafter is None:
        from core.web.services.team_workflow.llm_review_runners import (
            build_meeting_digest_drafter,
        )

        effective_drafter = build_meeting_digest_drafter()
    _record_meeting_digest_scene_event(
        "meeting_digest.draft.started",
        outcome="started",
        fields={
            **_meeting_digest_source_metrics(meeting_round, source_messages),
            "drafterMode": "llm" if effective_drafter is not None else "deterministic",
        },
        lifecycle=True,
    )
    draft = build_meeting_digest_draft(meeting_round, source_messages, drafter=effective_drafter)
    draft["sourceMessageContentHash"] = meeting_rounds.source_message_content_hash(
        source_messages
    )
    persisted = meeting_rounds.submit_meeting_digest_draft(
        normalized_team_id, normalized_round_id, draft
    )
    _record_meeting_digest_scene_event(
        "meeting_digest.draft.persisted",
        outcome="succeeded",
        fields={
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
            "meetingStatus": str(persisted.get("status") or ""),
            "drafterMode": "llm" if effective_drafter is not None else "deterministic",
            "documentChars": len(str(draft.get("documentMarkdown") or "")),
            "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            **_meeting_digest_fact_counts(draft),
        },
        lifecycle=True,
    )
    return persisted


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
    search_envelope = raw.get("searchEnvelope")
    try:
        envelope = facade._normalize_search_envelope(
            search_envelope, require_keywords=True
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
    deduplicated_errors: list[dict[str, str]] = []
    seen_errors: set[tuple[str, str]] = set()
    for item in validation_errors:
        key = (str(item.get("code") or ""), str(item.get("message") or ""))
        if key in seen_errors:
            continue
        seen_errors.add(key)
        deduplicated_errors.append(item)
    return collected, deduplicated_errors


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

    with _summary_draft_lock(normalized_team_id, normalized_round_id):
        return _prepare_meeting_summary_draft_locked(
            normalized_team_id,
            normalized_round_id,
            actor=actor,
            force=force,
            drafter=drafter,
        )


def _prepare_meeting_summary_draft_locked(
    normalized_team_id: str,
    normalized_round_id: str,
    *,
    actor: str = "",
    force: bool = False,
    drafter: Callable[[dict[str, Any], list[dict[str, Any]]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the summary-draft state machine while its meeting lock is held."""

    started_at = time.monotonic()
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
    _record_meeting_digest_scene_event(
        "meeting_digest.prepare.started",
        outcome="started",
        fields={
            **_meeting_digest_source_metrics(meeting_round, source_messages),
            "teamId": normalized_team_id,
            "meetingRoundId": normalized_round_id,
            "force": bool(force),
            "existingDraft": bool(existing_draft),
            "drafterInjected": drafter is not None,
        },
        lifecycle=True,
    )
    stale_generation_draft = (
        str(meeting_round.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
        and not [
            item
            for item in list(existing_draft.get("proposedCandidates") or [])
            if isinstance(item, Mapping)
        ]
        and bool(
            meeting_rounds.extract_discussion_markers(completed_source_messages).get(
                "proposedCandidates"
            )
        )
    )
    if status == "closed":
        _record_meeting_digest_scene_event(
            "meeting_digest.prepare.reused",
            outcome="closed",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "meetingStatus": status,
                "reuseReason": "meeting_closed",
                "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            lifecycle=True,
        )
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "closed",
            "meetingRound": meeting_round,
            "digestDraft": existing_draft or None,
            "storagePath": str(meeting_rounds._rounds_path(normalized_team_id)),
        }
    if status == "awaiting_approval" and stale_generation_draft:
        meeting_rounds.reject_meeting_digest_draft(
            normalized_team_id,
            normalized_round_id,
            actor=actor or "system:summary-repair",
            reason="recovered candidate markers missing from the stored draft",
        )
        meeting_round = meeting_rounds.get_meeting_round(
            normalized_team_id, normalized_round_id
        )["meetingRound"]
        status = "summarizing"
        existing_draft = {}
    elif status == "awaiting_approval":
        _record_meeting_digest_scene_event(
            "meeting_digest.prepare.reused",
            outcome="awaiting_approval",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "meetingStatus": status,
                "reuseReason": "draft_already_persisted",
                "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            lifecycle=True,
        )
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
            _record_meeting_digest_scene_event(
                "meeting_digest.prepare.blocked",
                outcome="blocked",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "meetingRoundId": normalized_round_id,
                    "blockerCode": "discussion_round_running",
                    "runningRoundCount": len(running),
                    "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
                },
                lifecycle=True,
            )
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
            _record_meeting_digest_scene_event(
                "meeting_digest.prepare.blocked",
                outcome="blocked",
                level="warning",
                fields={
                    "teamId": normalized_team_id,
                    "meetingRoundId": normalized_round_id,
                    "blockerCode": "discussion_has_no_completed_messages",
                    "runningRoundCount": 0,
                    "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
                },
                lifecycle=True,
            )
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
        _record_meeting_digest_scene_event(
            "meeting_digest.prepare.blocked",
            outcome="blocked",
            level="warning",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "blockerCode": "discussion_has_no_completed_messages",
                "runningRoundCount": len(
                    meeting_rounds.running_bound_round_ids(meeting_round)
                ),
                "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            lifecycle=True,
        )
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
        and not stale_generation_draft
    ):
        _record_meeting_digest_scene_event(
            "meeting_digest.prepare.reused",
            outcome="succeeded",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "meetingStatus": status,
                "reuseReason": "source_hash_unchanged",
                "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            lifecycle=True,
        )
        return meeting_rounds.submit_meeting_digest_draft(
            normalized_team_id, normalized_round_id, existing_draft
        )
    try:
        return draft_meeting_digest(
            normalized_team_id, normalized_round_id, drafter=drafter
        )
    except Exception as exc:
        # A review-profile LLM call that exceeds its wall-clock budget must
        # surface as a distinct recoverable failure (SCI-096): the meeting
        # stays in ``summarizing`` with a structured summaryDraftError, the
        # per-meeting lock is released by this return, and the retry path
        # (summary-draft / regenerate_summary) regenerates from the bound
        # source messages without reopening the discussion.
        from core.web.services.team_workflow.llm_review_runners import (
            ReviewLLMTimeoutError,
        )

        timed_out = isinstance(exc, ReviewLLMTimeoutError)
        error_category = (
            "timeout"
            if timed_out
            else "contract_validation"
            if isinstance(exc, ContractValidationError)
            else "runtime_error"
        )
        _record_meeting_digest_scene_event(
            "meeting_digest.draft.failed",
            outcome="failed",
            level="error",
            fields={
                "teamId": normalized_team_id,
                "meetingRoundId": normalized_round_id,
                "meetingStatus": status,
                "errorCategory": error_category,
                "errorType": type(exc).__name__,
                "elapsedMs": max(0, int((time.monotonic() - started_at) * 1000)),
            },
            lifecycle=True,
        )
        error = {
            "code": "summary_draft_timeout" if timed_out else "summary_draft_failed",
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
    if bool(config.get("autoDriveDiscussion")):
        return schedule_meeting_discussion(team_id, meeting_round_id)
    return maybe_auto_draft_meeting(
        team_id,
        meeting_round_id,
        required_round_id=str(round_payload.get("roundId") or "").strip(),
    )


def finalize_stopped_meeting_after_chat_round(
    room: Mapping[str, Any] | None,
    round_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Propagate one formal Chat Room stop into its bound workflow owners."""

    if not isinstance(room, Mapping) or not isinstance(round_payload, Mapping):
        return None
    config = (
        round_payload.get("config")
        if isinstance(round_payload.get("config"), Mapping)
        else {}
    )
    meeting_round_id = str(config.get("meetingRoundId") or "").strip()
    terminal_reason = str(round_payload.get("terminalReason") or "").strip()
    if not meeting_round_id or not terminal_reason:
        return None
    team_id = _team_id_for_auto_draft(room, round_payload)
    if not team_id:
        raise ResearchMeetingRuntimeError(
            "stopped formal meeting round has no owning team"
        )
    meeting_round = meeting_rounds.get_meeting_round(
        team_id, meeting_round_id
    )["meetingRound"]
    meeting_status = str(meeting_round.get("status") or "").strip().lower()
    if meeting_status not in {"open", "summarizing"}:
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": team_id,
            "status": "already_terminal",
            "meetingRound": meeting_round,
        }
    terminal = meeting_rounds.terminate_meeting_execution(
        team_id,
        meeting_round_id,
        reason=terminal_reason,
    )
    meeting_round = terminal.get("meetingRound") or {}
    if (
        str(meeting_round.get("meetingType") or "").strip().lower()
        == CANDIDATE_GENERATION_MEETING_TYPE
    ):
        from core.web.services.team_workflow.research_runtime import (
            hypothesis_first_chain,
        )

        hypothesis_first_chain.fail_generation_attempt_for_meeting(
            team_id,
            meeting_round_id,
            reason=terminal_reason,
        )
    return terminal
