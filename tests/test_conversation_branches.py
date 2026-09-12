from core.chat.conversation_branches import (
    analyze_conversation_branches,
    resolve_active_user_node_id,
    resolve_head_target,
    sibling_node_ids,
    visible_messages_with_branch_info,
)
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_BRANCH_REBASE,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    fold_active_events,
)


def _event(
    event_id: str,
    turn_id: str,
    sequence: int,
    event_type: str,
    *,
    payload: dict | None = None,
    parent_event_id: str = "",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=1,
        event_id=event_id,
        session_id="session-branches",
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status="recorded" if event_type == EVENT_USER_MESSAGE else "completed",
        timestamp="",
        source="test",
        payload=dict(payload or {}),
        parent_event_id=parent_event_id,
    )


def _rebase(
    event_id: str,
    sequence: int,
    from_event_id: str,
    *,
    operation: str = "edit",
    branch_id: str = "branch-1",
    turn_id: str = "turn-3",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=1,
        event_id=event_id,
        session_id="session-branches",
        turn_id=turn_id,
        sequence=sequence,
        event_type=EVENT_BRANCH_REBASE,
        status="recorded",
        timestamp="",
        source="test",
        payload={
            "operation": operation,
            "branchId": branch_id,
            "fromEventId": from_event_id,
            "replacedTurnIds": [],
        },
        parent_event_id=from_event_id,
        visible_in_model=False,
        projection_kind="session_branch_rebase",
    )


def _main_fixture() -> list[TurnJournalEvent]:
    return [
        _event("event-u1", "turn-1", 1, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _event("event-a1", "turn-1", 2, EVENT_ASSISTANT_MESSAGE, payload={"content": "原始回答"}),
        _event("event-u2", "turn-2", 3, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _event("event-a2", "turn-2", 4, EVENT_ASSISTANT_MESSAGE, payload={"content": "后续回答"}),
    ]


def _edit_branch_fixture() -> list[TurnJournalEvent]:
    return [
        *_main_fixture(),
        _rebase("event-rebase-1", 5, "event-a1", operation="edit"),
        _event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
    ]


def _regenerate_branch_fixture() -> list[TurnJournalEvent]:
    return [
        *_main_fixture(),
        _rebase("event-rebase-1", 5, "event-a1", operation="regenerate", branch_id="branch-regen"),
        _event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "重答"}),
    ]


def test_branch_view_marks_active_path_and_leaf():
    events = _main_fixture()

    view = analyze_conversation_branches(events)

    assert view.active_node_ids == ("event-u1", "event-a1", "event-u2", "event-a2")
    assert view.active_leaf_id == "event-a2"
    assert view.active_branch_id == "main"
    assert view.nodes["event-a2"].parent_node_id == "event-u2"
    assert view.nodes["event-u1"].parent_node_id == ""
    assert view.root_node_ids == ("event-u1",)
    assert all(node.active for node in view.nodes.values())


def test_edit_branch_creates_user_message_siblings():
    events = _edit_branch_fixture()

    view = analyze_conversation_branches(events)

    assert view.active_leaf_id == "event-a2b"
    assert view.active_branch_id == "branch-1"
    assert view.nodes["event-u2"].active is False
    assert view.nodes["event-u2b"].active is True
    assert sibling_node_ids(view, "event-u2b") == ("event-u2", "event-u2b")
    assert view.nodes["event-u2"].child_node_ids == ("event-a2",)
    assert view.nodes["event-u2b"].child_node_ids == ("event-a2b",)
    assert sibling_node_ids(view, "event-a2") == ("event-a2",)
    assert sibling_node_ids(view, "event-a2b") == ("event-a2b",)
    assert view.nodes["event-a2b"].parent_node_id == "event-u2b"


def test_regenerate_alias_groups_assistant_siblings_under_one_user_node():
    events = _regenerate_branch_fixture()

    view = analyze_conversation_branches(events)

    assert view.node_id_by_event["event-u2b"] == "event-u2"
    assert view.active_node_ids == ("event-u1", "event-a1", "event-u2", "event-a2b")
    assert view.active_leaf_id == "event-a2b"
    assert view.active_branch_id == "branch-regen"
    assert sibling_node_ids(view, "event-a2b") == ("event-a2", "event-a2b")
    assert sibling_node_ids(view, "event-a2") == ("event-a2", "event-a2b")
    assert view.nodes["event-a2"].active is False
    assert view.nodes["event-a2b"].active is True
    assert view.default_leaf_ids["event-u2"] == "event-a2b"
    assert view.default_leaf_ids["event-a2"] == "event-a2"


def test_head_select_switches_active_path_back_to_superseded_branch():
    events = [
        *_regenerate_branch_fixture(),
        _rebase("event-head-1", 8, "event-a2", operation="head_select", turn_id="turn-2"),
    ]

    view = analyze_conversation_branches(events)

    assert view.active_node_ids == ("event-u1", "event-a1", "event-u2", "event-a2")
    assert view.active_leaf_id == "event-a2"
    assert view.active_branch_id == "main"
    assert view.nodes["event-a2b"].active is False
    assert [event.event_id for event in fold_active_events(events)] == [
        "event-u1",
        "event-a1",
        "event-u2",
        "event-a2",
    ]


def test_resolve_head_target_prefers_branch_default_leaf_and_reports_active():
    events = _regenerate_branch_fixture()
    view = analyze_conversation_branches(events)

    event_id, already_active = resolve_head_target(view, "event-u2")
    assert event_id == "event-a2b"
    assert already_active is True

    back_events = [
        *events,
        _rebase("event-head-1", 8, "event-a2", operation="head_select", turn_id="turn-2"),
    ]
    back_view = analyze_conversation_branches(back_events)
    assert resolve_head_target(back_view, "event-u2") == ("event-a2b", False)
    assert resolve_head_target(back_view, "event-a2") == ("event-a2", True)
    assert resolve_head_target(back_view, "event-missing") == ("", False)


def test_resolve_active_user_node_maps_assistant_and_rejects_off_path():
    events = _regenerate_branch_fixture()
    view = analyze_conversation_branches(events)

    assert resolve_active_user_node_id(view, "event-a2b") == "event-u2"
    assert resolve_active_user_node_id(view, "event-u2b") == "event-u2"
    assert resolve_active_user_node_id(view, "event-a2") == ""
    assert resolve_active_user_node_id(view, "event-missing") == ""


def test_visible_messages_carry_branch_metadata():
    events = _regenerate_branch_fixture()

    messages, active_leaf_id, active_branch_id = visible_messages_with_branch_info(events)

    assert active_leaf_id == "event-a2b"
    assert active_branch_id == "branch-regen"
    by_node = {message.get("nodeId"): message for message in messages}
    assert set(by_node) == {"event-u1", "event-a1", "event-u2", "event-a2b"}
    user_branch = by_node["event-u2"]["branch"]
    assert user_branch["siblingCount"] == 1
    assert user_branch["siblingIndex"] == 1
    assistant_branch = by_node["event-a2b"]["branch"]
    assert assistant_branch["branchId"] == "branch-regen"
    assert assistant_branch["parentNodeId"] == "event-u2"
    assert assistant_branch["siblingCount"] == 2
    assert assistant_branch["siblingIndex"] == 2
    assert assistant_branch["siblingNodeIds"] == ["event-a2", "event-a2b"]
    assert assistant_branch["active"] is True


def test_visible_messages_without_rebase_keep_single_siblings():
    events = _main_fixture()

    messages, active_leaf_id, _branch_id = visible_messages_with_branch_info(events)

    assert active_leaf_id == "event-a2"
    assert [message.get("nodeId") for message in messages] == [
        "event-u1",
        "event-a1",
        "event-u2",
        "event-a2",
    ]
    assert all(message["branch"]["siblingCount"] == 1 for message in messages)


def test_branch_view_tolerates_empty_and_unknown_events():
    assert analyze_conversation_branches([]).active_leaf_id == ""

    events = [*_main_fixture(), _rebase("event-head-1", 5, "event-missing", operation="head_select")]

    view = analyze_conversation_branches(events)

    assert view.active_leaf_id == "event-a2"
