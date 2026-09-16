"""Session fork: seed a new session from one node of an existing journal.

Fork is the branch feature's exit: the version arrows move a head inside one
journal, while fork copies the active path (optionally with its sibling
branches) into a brand-new session journal. The source journal is never
modified; the new journal is a one-time seed write of an otherwise append-only
session, replayed through the same fold/branch/model pipeline as any other
session.

Copy strategy (see ``_select_fork_events``): journal replay derives parent
links from stream order, so a prefix of a journal replays into exactly the
tree state at that point. ``with_branches`` copies the original stream prefix
verbatim (edit/regenerate/head_select markers keep sibling branches replayable);
``visible_path`` copies the folded active path as a clean linear stream. Event
ids and turn ids are preserved (markers, aliases, tool correlations and UI
node lineage stay valid), ``sessionId`` is remapped and sequences are
renumbered. Volatile partial events are dropped except when the fork target
itself is one; any turn whose terminal event did not make the copy is seeded
without its ``turn_started``/``turn_context`` scaffolding so the new journal
never carries a dangling open turn.
"""

from __future__ import annotations

from typing import Any

from core.chat.conversation_ledger import rewrite_conversation_events
from core.chat.turn_journal import (
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_BRANCH_REBASE,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_CONTEXT,
    EVENT_TURN_FAILED,
    EVENT_TURN_STARTED,
    SCHEMA_VERSION,
    TERMINAL_EVENTS,
    TurnJournalEvent,
    fold_active_events,
    latest_open_turn_id,
)

FORK_SCOPE_VISIBLE_PATH = "visible_path"
FORK_SCOPE_WITH_BRANCHES = "with_branches"
FORK_SCOPES = (FORK_SCOPE_VISIBLE_PATH, FORK_SCOPE_WITH_BRANCHES)

# Turn scaffolding that closes a copied tail turn cleanly. ``branch_rebase`` is
# deliberately absent: a marker after the target changes the replayed chain and
# must never be pulled into the copy by tail extension.
_TAIL_CLOSE_EVENT_TYPES = frozenset({EVENT_TURN_COMPLETED, EVENT_TURN_FAILED})
_TAIL_SCAFFOLD_EVENT_TYPES = frozenset({EVENT_TURN_STARTED, EVENT_TURN_CONTEXT})
_VOLATILE_EVENT_TYPES = frozenset({EVENT_ASSISTANT_PARTIAL, EVENT_ASSISTANT_DELTA_COMMITTED})

_SESSION_SOURCE = "session_fork"

__all__ = [
    "FORK_SCOPE_VISIBLE_PATH",
    "FORK_SCOPE_WITH_BRANCHES",
    "FORK_SCOPES",
    "fork_session_from_node",
]


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


def _index_of_event(events: list[TurnJournalEvent], event_id: str) -> int:
    for index, event in enumerate(events):
        if str(event.event_id or "").strip() == event_id:
            return index
    return -1


def _extend_tail_to_terminal(
    source_events: list[TurnJournalEvent],
    end_index: int,
    tail_turn_id: str,
) -> int:
    """Extend ``end_index`` through trailing same-turn audit scaffolding.

    When the fork target is the last message of a completed turn, the copied
    prefix should also carry that turn's terminal event so the seeded journal
    ends with a closed turn. Extension stops at any message-bearing event, any
    marker, or the turn boundary; an interrupted turn is never extended (the
    interrupt marker belongs to the source lineage, not the fork).
    """

    cursor = end_index + 1
    terminal_index = -1
    while cursor < len(source_events):
        event = source_events[cursor]
        if str(event.turn_id or "").strip() != tail_turn_id:
            break
        event_type = str(event.event_type or "").strip()
        if event_type in _TAIL_CLOSE_EVENT_TYPES:
            terminal_index = cursor
            break
        if event_type in _TAIL_SCAFFOLD_EVENT_TYPES:
            cursor += 1
            continue
        break
    return terminal_index if terminal_index >= 0 else end_index


def _drop_unclosed_turn_scaffolding(selected: list[TurnJournalEvent]) -> None:
    """Remove ``turn_started``/``turn_context`` of turns without a terminal.

    A prefix cut can separate a turn's scaffolding from its terminal event
    (markers cut completed terminals out of the folded chain; the fork cuts
    mid-turn at the target). Copying the scaffolding anyway would leave the
    seeded journal with a permanently open turn that reconcile keeps flagging;
    replay derives visible messages from the message events themselves, so the
    scaffolding is not needed for a turn whose terminal did not make the copy.
    """

    terminal_turn_ids = {
        str(event.turn_id or "").strip()
        for event in selected
        if str(event.event_type or "").strip() in TERMINAL_EVENTS
    }
    selected[:] = [
        event
        for event in selected
        if not (
            str(event.event_type or "").strip() in _TAIL_SCAFFOLD_EVENT_TYPES
            and str(event.turn_id or "").strip() not in terminal_turn_ids
        )
    ]


def _select_fork_events(
    source_events: list[TurnJournalEvent],
    *,
    target_event_id: str,
    tail_turn_id: str,
    scope: str,
) -> list[TurnJournalEvent]:
    """Return the copy set for one scope, ending at the fork target."""

    if scope == FORK_SCOPE_VISIBLE_PATH:
        sequence = fold_active_events(source_events)
    else:
        sequence = source_events
    end_index = _index_of_event(sequence, target_event_id)
    if end_index < 0:
        return []
    extended_index = _extend_tail_to_terminal(sequence, end_index, tail_turn_id)
    selected = list(sequence[: extended_index + 1])
    # Volatile partials are transient streaming state; dropping them cannot
    # lose committed content. The fork target itself is always kept, even when
    # it is an interrupted partial: it is the node the user forked from, and
    # replay re-attaches its interrupted presentation automatically.
    selected = [
        event
        for event in selected
        if not (
            str(event.event_type or "").strip() in _VOLATILE_EVENT_TYPES
            and str(event.event_id or "").strip() != target_event_id
        )
    ]
    _drop_unclosed_turn_scaffolding(selected)
    return selected


def _remap_copied_event(
    event: TurnJournalEvent,
    *,
    new_session_id: str,
    sequence: int,
) -> TurnJournalEvent:
    """Re-own one source event to the forked session without breaking lineage."""

    payload = dict(event.payload or {})
    if "sessionId" in payload:
        payload["sessionId"] = new_session_id
    return TurnJournalEvent(
        schema_version=SCHEMA_VERSION,
        event_id=event.event_id,
        session_id=new_session_id,
        turn_id=event.turn_id,
        sequence=sequence,
        event_type=event.event_type,
        status=event.status,
        timestamp=event.timestamp,
        source=event.source,
        payload=payload,
        parent_event_id=event.parent_event_id,
        visible_in_model=event.visible_in_model,
        projection_kind=event.projection_kind,
        provider_role=event.provider_role,
        tool_call_id=event.tool_call_id,
        correlation_id=event.correlation_id,
        source_kind=event.source_kind,
    )


def fork_session_from_node(
    source_session_id: str,
    node_id: str,
    *,
    scope: str = FORK_SCOPE_VISIBLE_PATH,
) -> dict[str, Any]:
    """Create a new chat session seeded with the path ending at ``node_id``.

    The fork is a plain direct session created through the normal
    ``create_chat_session`` admission path (no run state is inherited), and the
    source session is only read, never written.
    """

    s = _service()
    lang = s.get_web_language()
    conversation_id = str(source_session_id or "").strip()
    if not conversation_id:
        raise s.SessionNotFoundError(
            s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
        )
    normalized_node_id = str(node_id or "").strip()
    if not normalized_node_id:
        raise s.SessionValidationError(
            s.text_for(lang, zh="请选择要分叉的对话消息。", en="Choose a conversation message to fork from.")
        )
    normalized_scope = str(scope or "").strip() or FORK_SCOPE_VISIBLE_PATH
    if normalized_scope not in FORK_SCOPES:
        raise s.SessionValidationError(
            s.text_for(
                lang,
                zh=f"未知的分叉范围：{normalized_scope}",
                en=f"Unknown fork scope: {normalized_scope}",
            )
        )

    admit_lock = s._session_submit_admit_lock(conversation_id)
    admit_lock.acquire()
    new_session_id = ""
    try:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, conversation_id)
        if conversation is None:
            raise s.SessionNotFoundError(
                s.text_for(lang, zh="未找到当前会话。", en="Session not found.")
            )
        s._ensure_session_mutable(conversation_id, conversation=conversation)
        if s._is_session_running(conversation_id):
            raise s.SessionBusyError(
                s.text_for(
                    lang,
                    zh="当前会话仍有进行中的回答，请等待其结束后再分叉。",
                    en="This session still has a running turn; wait for it to finish before forking.",
                )
            )
        events = s._load_session_conversation_events_cached(conversation_id)
        if not events:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="当前会话还没有可分叉的对话历史。",
                    en="This session has no conversation history to fork from.",
                )
            )
        open_turn_id = latest_open_turn_id(events)
        if open_turn_id:
            raise s.SessionBusyError(
                s.text_for(
                    lang,
                    zh="当前会话有未收口的轮次，请等待收口后再分叉。",
                    en="This session has an unsettled turn; wait for it to settle before forking.",
                )
            )
        view = s.analyze_conversation_branches(events)
        logical_node_id = view.node_id_by_event.get(normalized_node_id, normalized_node_id)
        node = view.nodes.get(logical_node_id)
        if node is None or not node.active:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="找不到要分叉的对话版本，请刷新后重试。",
                    en="The conversation version to fork from was not found; refresh and try again.",
                )
            )
        selected = _select_fork_events(
            list(events),
            target_event_id=node.event_id,
            tail_turn_id=str(node.turn_id or "").strip(),
            scope=normalized_scope,
        )
        if not selected:
            raise s.SessionValidationError(
                s.text_for(
                    lang,
                    zh="该消息没有可复制的对话历史。",
                    en="This message has no conversation history to copy.",
                )
            )
        source_title = s.trim_lines(
            str(conversation.get("title") or "").strip(),
            max_lines=1,
        ).strip()
        if not source_title:
            source_title = s.text_for(lang, zh="新会话", en="New session")
        fork_title = s.text_for(lang, zh="{title}（分叉）", en="{title} (fork)").format(
            title=source_title
        )[:120]
        created = s.create_chat_session(
            title=fork_title,
            title_source="manual",
            agent_id=str(conversation.get("agentId") or conversation.get("agent_id") or "").strip(),
            created_by="user",
            forked_from={
                "sessionId": conversation_id,
                "nodeId": logical_node_id,
                "scope": normalized_scope,
                "forkedAt": s._now_timestamp(),
            },
        )
        new_session_id = str(created.get("id") or "").strip() if isinstance(created, dict) else ""
        if not new_session_id:
            raise s.SessionValidationError(
                s.text_for(lang, zh="分叉会话创建失败，请重试。", en="Failed to create the forked session; try again.")
            )
        rewrite_conversation_events(
            s.PROJECT_ROOT,
            new_session_id,
            [
                _remap_copied_event(event, new_session_id=new_session_id, sequence=sequence)
                for sequence, event in enumerate(selected, start=1)
            ],
        )
        s._invalidate_session_conversation_events_cache(new_session_id)
    finally:
        admit_lock.release()

    from core.chat.session_catalog import notify_session_catalog_dirty

    try:
        notify_session_catalog_dirty(
            s.PROJECT_ROOT,
            new_session_id,
            f"journal:{len(selected)}",
        )
    except Exception:
        pass
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_fork",
            "conversation.session.forked",
            level="info",
            outcome="succeeded",
            message="Session forked from a conversation node.",
            fields={
                "sessionId": new_session_id,
                "sourceSessionId": conversation_id,
                "nodeId": logical_node_id,
                "scope": normalized_scope,
                "copiedEventCount": len(selected),
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return s.get_session_detail(new_session_id) or {}
