# -*- coding: utf-8 -*-
"""Branch/head analysis for the append-only conversation journal.

The journal stores every branch; this module derives the user-visible branch
graph from the shared event tree (parent chain + head pointer) in
``core.chat.turn_journal`` and stamps ``nodeId``/``branch`` metadata onto the
active-path messages that the session detail contract exposes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from core.chat.turn_journal import (
    TurnJournalEvent,
    build_journal_event_tree,
    model_visible_messages_from_events,
    replay_visible_messages,
)

MAIN_BRANCH_ID = "main"

__all__ = [
    "BranchNode",
    "ConversationBranchView",
    "MAIN_BRANCH_ID",
    "analyze_conversation_branches",
    "resolve_active_user_node_id",
    "resolve_head_leaf",
    "resolve_head_target",
    "stamp_branch_metadata",
    "visible_messages_with_branch_info",
]


@dataclass(frozen=True)
class BranchNode:
    node_id: str
    event_id: str
    parent_node_id: str
    child_node_ids: tuple[str, ...]
    branch_id: str
    turn_id: str
    role: str
    sequence: int
    active: bool


@dataclass(frozen=True)
class ConversationBranchView:
    nodes: dict[str, BranchNode]
    node_id_by_event: dict[str, str]
    root_node_ids: tuple[str, ...]
    active_node_ids: tuple[str, ...]
    active_leaf_id: str
    active_branch_id: str
    default_leaf_ids: dict[str, str]


def _event_id(event: TurnJournalEvent) -> str:
    return str(getattr(event, "event_id", "") or "").strip()


def _message_event_id(message: dict[str, Any]) -> str:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str(metadata.get("eventId") or "").strip()


def analyze_conversation_branches(events: Iterable[TurnJournalEvent]) -> ConversationBranchView:
    """Derive the branch graph for every message the journal has ever stored.

    Nodes are logical messages keyed by their stable node id (a user message
    keeps the id of the message it replaces after ``regenerate``). Children are
    ordered by first appearance so ``siblingIndex`` is stable.
    """

    event_list = list(events or [])
    if not event_list:
        return ConversationBranchView(
            nodes={},
            node_id_by_event={},
            root_node_ids=(),
            active_node_ids=(),
            active_leaf_id="",
            active_branch_id="",
            default_leaf_ids={},
        )
    tree = build_journal_event_tree(event_list)
    messages = replay_visible_messages(event_list)
    order_by_event_id = {_event_id(event): index for index, event in enumerate(event_list)}
    message_by_event: dict[str, dict[str, Any]] = {}
    message_event_ids: list[str] = []
    for message in messages:
        event_id = _message_event_id(message)
        if not event_id or event_id not in tree.events_by_id or event_id in message_by_event:
            continue
        message_by_event[event_id] = message
        message_event_ids.append(event_id)
    message_event_id_set = set(message_event_ids)
    chain_event_id_set = set(tree.chain_ids)

    logical_aliases: dict[str, list[str]] = {}
    logical_order: list[str] = []
    for event_id in message_event_ids:
        logical_id = tree.alias_by_id.get(event_id, event_id)
        if logical_id not in logical_aliases:
            logical_aliases[logical_id] = []
            logical_order.append(logical_id)
        logical_aliases[logical_id].append(event_id)

    def canonical_event_id(node_aliases: list[str]) -> str:
        for event_id in node_aliases:
            if event_id in chain_event_id_set:
                return event_id
        return node_aliases[-1]

    def parent_message_event_id(event_id: str) -> str:
        cursor = tree.parent_by_id.get(event_id, "")
        seen: set[str] = set()
        while cursor and cursor not in seen:
            if cursor in message_event_id_set:
                return cursor
            seen.add(cursor)
            cursor = tree.parent_by_id.get(cursor, "")
        return ""

    provisional: dict[str, BranchNode] = {}
    child_ids_by_parent: dict[str, list[str]] = {}
    for logical_id in logical_order:
        aliases = logical_aliases[logical_id]
        event_id = canonical_event_id(aliases)
        message = message_by_event[event_id]
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        parent_event_id = parent_message_event_id(event_id)
        parent_node_id = (
            tree.alias_by_id.get(parent_event_id, parent_event_id) if parent_event_id else ""
        )
        node = BranchNode(
            node_id=logical_id,
            event_id=event_id,
            parent_node_id=parent_node_id,
            child_node_ids=(),
            branch_id=tree.branch_by_id.get(event_id, MAIN_BRANCH_ID),
            turn_id=str(metadata.get("turnId") or "").strip(),
            role=str(message.get("role") or "").strip().lower(),
            sequence=order_by_event_id.get(aliases[0], 0),
            active=False,
        )
        provisional[logical_id] = node
        child_ids_by_parent.setdefault(parent_node_id, []).append(logical_id)

    active_node_ids: list[str] = []
    active_leaf_id = ""
    active_leaf_event_id = ""
    for event_id in tree.chain_ids:
        if event_id not in message_event_id_set:
            continue
        logical_id = tree.alias_by_id.get(event_id, event_id)
        if logical_id in provisional and logical_id not in active_node_ids:
            active_node_ids.append(logical_id)
            active_leaf_id = logical_id
            active_leaf_event_id = event_id
    active_node_id_set = set(active_node_ids)

    nodes: dict[str, BranchNode] = {}
    for logical_id, node in provisional.items():
        nodes[logical_id] = replace(
            node,
            child_node_ids=tuple(child_ids_by_parent.get(logical_id, ())),
            active=logical_id in active_node_id_set,
        )

    default_leaf_ids: dict[str, str] = {}

    def default_leaf(node_id: str) -> str:
        cached = default_leaf_ids.get(node_id)
        if cached:
            return cached
        node = nodes.get(node_id)
        if node is None or not node.child_node_ids:
            default_leaf_ids[node_id] = node_id
            return node_id
        child = max(node.child_node_ids, key=lambda child_id: nodes[child_id].sequence)
        leaf = default_leaf(child)
        default_leaf_ids[node_id] = leaf
        return leaf

    for logical_id in logical_order:
        default_leaf(logical_id)

    return ConversationBranchView(
        nodes=nodes,
        node_id_by_event={
            event_id: logical_id
            for logical_id, aliases in logical_aliases.items()
            for event_id in aliases
        },
        root_node_ids=tuple(child_ids_by_parent.get("", ())),
        active_node_ids=tuple(active_node_ids),
        active_leaf_id=active_leaf_id,
        active_branch_id=(
            tree.branch_by_id.get(active_leaf_event_id, "") if active_leaf_event_id else ""
        ),
        default_leaf_ids=default_leaf_ids,
    )


def resolve_head_leaf(view: ConversationBranchView, node_id: str) -> BranchNode | None:
    """Return the branch leaf a head-select request should land on."""

    normalized = str(node_id or "").strip()
    normalized = view.node_id_by_event.get(normalized, normalized)
    leaf_id = view.default_leaf_ids.get(normalized, normalized)
    return view.nodes.get(leaf_id)


def resolve_head_target(view: ConversationBranchView, node_id: str) -> tuple[str, bool]:
    """Resolve a head-select target to ``(leaf event id, already active)``.

    Clicking a version chip may reference any message on a branch; the head
    always moves to that branch's default leaf so later turns on the branch
    stay visible.
    """

    leaf = resolve_head_leaf(view, node_id)
    if leaf is None:
        return "", False
    return leaf.event_id, leaf.node_id == view.active_leaf_id


def resolve_active_user_node_id(view: ConversationBranchView, node_id: str) -> str:
    """Return the user-message node that owns an active-path target, else ``""``."""

    normalized = str(node_id or "").strip()
    normalized = view.node_id_by_event.get(normalized, normalized)
    cursor = view.nodes.get(normalized)
    if cursor is None or not cursor.active:
        return ""
    seen: set[str] = set()
    while cursor is not None and cursor.node_id not in seen:
        seen.add(cursor.node_id)
        if cursor.role == "user":
            return cursor.node_id
        cursor = view.nodes.get(cursor.parent_node_id)
    return ""


def sibling_node_ids(view: ConversationBranchView, node_id: str) -> tuple[str, ...]:
    normalized = str(node_id or "").strip()
    normalized = view.node_id_by_event.get(normalized, normalized)
    node = view.nodes.get(normalized)
    if node is None:
        return ()
    if node.parent_node_id:
        parent = view.nodes.get(node.parent_node_id)
        return parent.child_node_ids if parent is not None else ()
    return view.root_node_ids


def stamp_branch_metadata(
    messages: Iterable[dict[str, Any]],
    view: ConversationBranchView,
) -> list[dict[str, Any]]:
    """Attach ``nodeId``/``branch`` metadata to active-path messages in place."""

    stamped: list[dict[str, Any]] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            continue
        event_id = _message_event_id(message)
        node_id = view.node_id_by_event.get(event_id, "")
        node = view.nodes.get(node_id)
        if node is None:
            stamped.append(message)
            continue
        siblings = sibling_node_ids(view, node_id)
        index = siblings.index(node_id) + 1 if node_id in siblings else 0
        message["nodeId"] = node_id
        message["branch"] = {
            "branchId": node.branch_id,
            "parentNodeId": node.parent_node_id,
            "siblingCount": len(siblings),
            "siblingIndex": index,
            "siblingNodeIds": list(siblings),
            "active": True,
        }
        stamped.append(message)
    return stamped


def visible_messages_with_branch_info(
    events: Iterable[TurnJournalEvent],
) -> tuple[list[dict[str, Any]], str, str]:
    """Return ``(active messages, activeLeafId, activeBranchId)`` for a session."""

    event_list = list(events or [])
    view = analyze_conversation_branches(event_list)
    messages = model_visible_messages_from_events(event_list)
    stamp_branch_metadata(messages, view)
    return messages, view.active_leaf_id, view.active_branch_id
