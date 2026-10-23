"""Personal affairs domain: ledger CRUD, projection and tool surface."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from core.agent_plugins.personal_affairs.service import (
    AFFAIR_KINDS,
    PersonalAffairsError,
    PersonalAffairsNotFoundError,
    PersonalAffairsService,
    project_affairs,
)
from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore

UTC = timezone.utc


def _make_service(tmp_path, now: datetime, *, with_agent: bool = True) -> PersonalAffairsService:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}

    def loader(agent_id, include_archived=False):
        return agent if (with_agent and agent_id == "agent-a") else None

    return PersonalAffairsService(
        tmp_path,
        agent_loader=loader,
        now_provider=lambda: now,
    )


class TestAffairLedgerCrud:
    def test_add_validate_and_persist(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        item = service.add_item(
            "agent-a",
            kind="todo",
            title="  帮 用户  买牛奶  ",
            note="脱脂",
            due_at="2026-10-20T09:00",
            source_turn_id="turn-1",
        )
        assert item["kind"] == "todo"
        assert item["title"] == "帮 用户 买牛奶"
        assert item["status"] == "open"
        assert item["dueAt"].startswith("2026-10-20T09:00")
        assert item["itemId"].startswith("affair-")
        rows = service.store.read_jsonl("agent-a", "affairs/items.jsonl")
        assert len(rows) == 1 and rows[0]["itemId"] == item["itemId"]

    def test_kind_and_title_validation(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        for bad_kind in ("meeting", "", None):
            try:
                service.add_item("agent-a", kind=bad_kind, title="x")
                raise AssertionError("kind validation missing")
            except PersonalAffairsError:
                pass
        try:
            service.add_item("agent-a", kind="todo", title="   ")
            raise AssertionError("title validation missing")
        except PersonalAffairsError:
            pass
        assert set(AFFAIR_KINDS) == {"todo", "schedule", "goal"}

    def test_due_at_accepts_date_only_and_rejects_garbage(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        assert service.add_item("agent-a", kind="schedule", title="体检", due_at="2026-11-01")[
            "dueAt"
        ].startswith("2026-11-01")
        try:
            service.add_item("agent-a", kind="schedule", title="坏时间", due_at="明天")
            raise AssertionError("dueAt validation missing")
        except PersonalAffairsError:
            pass

    def test_complete_cancel_reopen_and_idempotent_transition(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        item = service.add_item("agent-a", kind="goal", title="读完一本书")
        done = service.complete_item("agent-a", item_id=item["itemId"])
        assert done["status"] == "done" and done["completedAt"]
        again = service.complete_item("agent-a", item_id=item["itemId"])
        assert again["status"] == "done"
        rows = service.store.read_jsonl("agent-a", "affairs/items.jsonl")
        assert len(rows) == 1
        reopened = service.reopen_item("agent-a", item_id=item["itemId"])
        assert reopened["status"] == "open" and reopened["completedAt"] == ""
        cancelled = service.cancel_item("agent-a", item_id=item["itemId"])
        assert cancelled["status"] == "cancelled"

    def test_set_due_updates_item(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        item = service.add_item("agent-a", kind="todo", title="缴费")
        updated = service.set_due(
            "agent-a", item_id=item["itemId"], due_at="2026-10-21T08:30:00Z"
        )
        assert updated["dueAt"].startswith("2026-10-21T08:30")

    def test_unknown_item_raises_not_found(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        try:
            service.complete_item("agent-a", item_id="affair-missing")
            raise AssertionError("missing item should raise")
        except PersonalAffairsNotFoundError:
            pass

    def test_unknown_agent_is_rejected(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        try:
            service.add_item("agent-ghost", kind="todo", title="x")
            raise AssertionError("unknown agent should raise")
        except Exception as exc:
            assert "not available" in str(exc) or "Agent" in str(exc)

    def test_storage_is_agent_scoped_and_atomic(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        service.add_item("agent-a", kind="todo", title="A 的待办")
        root = service.store.plugin_root("agent-a")
        assert root.name == "personal-affairs"
        assert (root / "affairs" / "items.jsonl").is_file()
        assert list((root / "affairs").glob(".vhl-*")) == []


class TestAffairConcurrentWrites:
    @pytest.mark.parametrize("first_action,second_action", [
        ("complete", "due"), ("due", "add"), ("add", "complete"),
    ])
    def test_service_instances_preserve_concurrent_mutations(
        self, tmp_path, monkeypatch, first_action, second_action,
    ) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        first = _make_service(tmp_path, now)
        second = _make_service(tmp_path, now)
        item_a = first.add_item("agent-a", kind="todo", title="A")
        item_b = first.add_item("agent-a", kind="todo", title="B")
        first_read, release_first, second_read, second_started = (Event() for _ in range(4))
        read_first, read_second = first._rows, second._rows

        def pause_first(agent_id):
            rows = read_first(agent_id)
            first_read.set()
            assert release_first.wait(3)
            return rows

        def observe_second(agent_id):
            rows = read_second(agent_id)
            second_read.set()
            return rows

        def mutate(service, action):
            if action == "add":
                return service.add_item("agent-a", kind="goal", title="new")
            if action == "due":
                return service.set_due("agent-a", item_id=item_b["itemId"], due_at="2026-10-21")
            return service.complete_item("agent-a", item_id=item_a["itemId"])

        def run_second():
            second_started.set()
            return mutate(second, second_action)

        monkeypatch.setattr(first, "_rows", pause_first)
        monkeypatch.setattr(second, "_rows", observe_second)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_result = pool.submit(mutate, first, first_action)
            try:
                assert first_read.wait(2)
                second_result = pool.submit(run_second)
                assert second_started.wait(2)
                # Without a transaction the second writer reads the same snapshot
                # and commits before the first writer, deterministically losing it.
                if second_read.wait(0.2):
                    second_result.result(timeout=2)
            finally:
                release_first.set()
            first_result.result(timeout=2)
            second_result.result(timeout=2)
        rows = {row["itemId"]: row for row in read_first("agent-a")}
        if "complete" in (first_action, second_action):
            assert rows[item_a["itemId"]]["status"] == "done"
        if "due" in (first_action, second_action):
            assert rows[item_b["itemId"]]["dueAt"].startswith("2026-10-21")
        if "add" in (first_action, second_action):
            assert {row["title"] for row in rows.values()} == {"A", "B", "new"}

    def test_unrelated_agent_can_write_while_another_ledger_is_busy(self, tmp_path, monkeypatch) -> None:
        service = PersonalAffairsService(tmp_path)
        other = PersonalAffairsService(tmp_path)
        item = service.add_item("agent-a", kind="todo", title="A")
        entered, release = Event(), Event()
        read_rows = service._rows

        def pause(agent_id):
            rows = read_rows(agent_id)
            entered.set()
            assert release.wait(3)
            return rows

        monkeypatch.setattr(service, "_rows", pause)
        with ThreadPoolExecutor(max_workers=2) as pool:
            busy = pool.submit(service.complete_item, "agent-a", item_id=item["itemId"])
            try:
                assert entered.wait(2)
                independent = pool.submit(other.add_item, "agent-b", kind="todo", title="B")
                assert independent.result(timeout=2)["title"] == "B"
            finally:
                release.set()
            busy.result(timeout=2)

    @pytest.mark.parametrize("action", ["add", "complete", "due"])
    def test_lock_timeout_leaves_ledger_unchanged(self, tmp_path, monkeypatch, action) -> None:
        from core.agent_plugins.personal_affairs import service as module
        from core.infrastructure.file_lock import cross_process_file_lock

        service = PersonalAffairsService(tmp_path)
        item = service.add_item("agent-a", kind="todo", title="A")
        path = service.store._path("agent-a", "affairs/items.jsonl")
        before = path.read_bytes()
        entered, release = Event(), Event()

        def hold():
            with cross_process_file_lock(path):
                entered.set()
                assert release.wait(3)

        monkeypatch.setattr(module, "cross_process_file_lock", lambda path: cross_process_file_lock(path, timeout=0.03))
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold)
            try:
                assert entered.wait(2)
                with pytest.raises(TimeoutError):
                    if action == "add":
                        service.add_item("agent-a", kind="goal", title="new")
                    elif action == "due":
                        service.set_due("agent-a", item_id=item["itemId"], due_at="2026-10-21")
                    else:
                        service.complete_item("agent-a", item_id=item["itemId"])
                assert path.read_bytes() == before
            finally:
                release.set()
            holder.result(timeout=2)


class TestAffairProjection:
    def test_filters_due_state_and_counts(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        overdue = service.add_item(
            "agent-a", kind="todo", title="过期", due_at="2026-10-18T09:00"
        )
        today = service.add_item(
            "agent-a", kind="schedule", title="今天", due_at="2026-10-19T18:00"
        )
        upcoming = service.add_item(
            "agent-a", kind="todo", title="将来", due_at="2026-10-25T09:00"
        )
        undated = service.add_item("agent-a", kind="goal", title="无期限")
        done = service.add_item("agent-a", kind="todo", title="已完成")
        service.complete_item("agent-a", item_id=done["itemId"])

        projection = service.list_items("agent-a")
        assert projection["counts"] == {"open": 4, "overdue": 1, "done": 1}
        states = {item["title"]: item["dueState"] for item in projection["items"]}
        assert states["过期"] == "overdue"
        assert states["今天"] == "today"
        assert states["将来"] == "upcoming"
        assert states["无期限"] == "none"
        # Overdue open items sort first; closed items sort last.
        assert projection["items"][0]["itemId"] == overdue["itemId"]
        assert projection["items"][-1]["itemId"] == done["itemId"]

        todos = service.list_items("agent-a", kind="todo")
        assert {item["itemId"] for item in todos["items"]} == {
            overdue["itemId"], upcoming["itemId"], done["itemId"], undated["itemId"]
        } - {undated["itemId"]}
        open_only = service.list_items("agent-a", status="open")
        assert all(item["status"] == "open" for item in open_only["items"])
        assert {item["itemId"] for item in open_only["items"]} == {
            overdue["itemId"], today["itemId"], upcoming["itemId"], undated["itemId"]
        }

    def test_project_affairs_is_pure_over_rows(self) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        rows = [
            {
                "itemId": "affair-1",
                "kind": "todo",
                "title": "过期",
                "status": "open",
                "dueAt": "2026-10-18T09:00:00+00:00",
                "createdAt": "2026-10-17T09:00:00+00:00",
                "updatedAt": "2026-10-17T09:00:00+00:00",
            }
        ]
        first = project_affairs(rows, agent_id="agent-a", now=now)
        second = project_affairs(rows, agent_id="agent-a", now=now)
        assert first == second
        assert first["items"][0]["dueState"] == "overdue"


class TestPersonalAffairsTool:
    def test_runtime_without_agent_is_blocked(self, monkeypatch) -> None:
        from tools import personal_affairs_tools as module

        monkeypatch.setattr(
            module, "_runtime_context", lambda: {"agentId": "", "sessionId": "s"}
        )
        payload = json.loads(module.personal_affairs_tool(action="list"))
        assert payload["status"] == "blocked"
        assert payload["error"] == "agent_runtime_missing"

    def test_full_tool_flow_against_service(self, tmp_path, monkeypatch) -> None:
        from tools import personal_affairs_tools as module

        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        monkeypatch.setattr(module, "_service", lambda: service)
        monkeypatch.setattr(
            module, "_runtime_context", lambda: {"agentId": "agent-a", "sessionId": "s"}
        )
        added = json.loads(
            module.personal_affairs_tool(
                action="add",
                kind="todo",
                title="提醒我买牛奶",
                due_at="2026-10-20T09:00",
                source_turn_id="turn-tool",
            )
        )
        assert added["ok"] and added["item"]["kind"] == "todo"
        item_id = added["item"]["itemId"]
        listed = json.loads(module.personal_affairs_tool(action="list", kind="todo"))
        assert listed["ok"] and listed["affairs"]["counts"]["open"] == 1
        completed = json.loads(
            module.personal_affairs_tool(action="complete", item_id=item_id)
        )
        assert completed["ok"] and completed["item"]["status"] == "done"
        rejected = json.loads(module.personal_affairs_tool(action="complete"))
        assert rejected["status"] == "blocked" and rejected["error"] == "item_id_required"
        unknown = json.loads(
            module.personal_affairs_tool(action="explode", title="x")
        )
        assert unknown["status"] == "blocked" and unknown["error"] == "unknown_action"
        contract = json.loads(
            module.personal_affairs_tool(action="add", kind="meeting", title="x")
        )
        assert contract["status"] == "rejected"


class TestCatalogRegistration:
    def test_tool_and_bundle_are_registered(self) -> None:
        from core.web.services.tool_catalog import (
            CATEGORY_LABELS,
            TOOL_BUNDLE_DEFINITIONS,
            TOOL_CATALOG,
            _CATEGORY_SCOPES,
        )

        entry = TOOL_CATALOG.get("personal_affairs_tool")
        assert entry and entry["category"] == "personal_affairs"
        assert _CATEGORY_SCOPES.get("personal_affairs") == ("agent",)
        assert CATEGORY_LABELS.get("personal_affairs")
        bundle = next(
            (
                item
                for item in TOOL_BUNDLE_DEFINITIONS
                if item.get("bundleId") == "personal_affairs"
            ),
            None,
        )
        assert bundle and "personal_affairs_tool" in bundle["toolNames"]

    def test_key_tools_returns_the_affairs_tool(self) -> None:
        from tools.Key_Tools import create_key_tools

        names = {getattr(tool, "name", "") for tool in create_key_tools()}
        assert "personal_affairs_tool" in names


class TestRoutes:
    def test_affair_routes_are_mounted_and_shaped(self) -> None:
        from core.web.routes.personal_assistant_affairs import router

        paths = {route.path for route in router.routes}
        assert "/agents/{agent_id}/plugins/personal-affairs/affairs" in paths
        assert (
            "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/complete"
            in paths
        )
        assert "/agents/{agent_id}/plugins/personal-affairs/affairs/{item_id}/due" in paths
