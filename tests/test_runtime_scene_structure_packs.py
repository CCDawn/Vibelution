"""Focused tests for runtime_scene structure packs (record/query/diagnosis)."""

from __future__ import annotations

import pytest

from core.web.services import runtime_scene_service as facade
from core.web.services.runtime_scene import diagnosis, file_preview, package_index, query, record

# 2026-10-19 生产事故复盘：Electron 壳实际发射的事件码大量未登记进
# ELECTRON_SUPERVISOR_EVENT_CODES，record_electron_supervisor_event 抛
# ValueError → API 400，事件桥队列队头被拒后所有 supervisor 事件（含人工
# 关注通知）无声消失。下面两个清单锁定发射清单即契约的口径。
_ELECTRON_SHELL_EMITTED_EVENT_CODES = {
    # conversation_notification
    "electron.conversation_notification.notified",
    "electron.conversation_notification.suppressed",
    "electron.conversation_notification.failed",
    # deep_link
    "electron.deep_link.accepted",
    "electron.deep_link.rejected",
    # startup
    "electron.startup.summary",
    "electron.startup.control_plane_attached",
    "electron.startup.desktop_session_registered",
    "electron.startup.workbench_window_ready",
    # lifecycle
    "electron.lifecycle.force_authorized",
    "electron.lifecycle.os_session_end",
    # tray
    "electron.tray.created",
    "electron.tray.ready",
    "electron.tray.quit_all.force_interrupt",
    "electron.tray.restart_all.force_interrupt",
    "electron.tray.restart_all.post_refresh_stale",
    "electron.tray.restart_all.restore",
    "electron.tray.restart_all.restore_failed",
    "electron.tray.restart_launcher.force_interrupt",
    # runtime
    "electron.runtime.start_reap_requested",
    "electron.runtime.start_reap_failed",
    "electron.runtime.stop_requested",
    "electron.runtime.stop_failed",
    # launcher_service
    "electron.launcher_service.start_reap_requested",
    "electron.launcher_service.start_reap_failed",
    "electron.launcher_service.stop_requested",
    "electron.launcher_service.stop_failed",
    # desktop_session
    "electron.desktop_session.heartbeat_failed",
    "electron.desktop_session.heartbeat_recovery_failed",
    # desktop_control
    "electron.desktop_control.recovered",
    # desktop_shell
    "electron.desktop_shell.exit_blocked_stop_failed",
    # workbench_close
    "electron.workbench_close.window_authorized",
    "electron.workbench_close.active_work_checked",
    "electron.workbench_close.cancelled_active_work",
    "electron.workbench_close.backend_stopping",
    "electron.workbench_close.backend_stop_settled",
    "electron.workbench_close.fail_open_destroy",
    "electron.workbench_close.fail_open_user_declined",
    "electron.workbench_close.failed",
    "electron.workbench_close.untracked_window_closed",
    "electron.workbench_close.window_closed_after_failure",
    "electron.workbench_close.completed",
    # main_line
    "electron.main_line_command.settled",
    "electron.main_line_command.close_backoff_coalesced",
    # isolated
    "electron.isolated_instance.stopped",
    "electron.isolated_instance.stop_failed",
    "electron.isolated_instances.stop_all_requested",
    "electron.isolated_instances.stop_all_failed",
    # watchdog
    "electron.workbench_backend_watchdog.degraded",
    "electron.workbench_backend_watchdog.recovered",
}
_ELECTRON_LEGACY_EVENT_CODES = {
    "electron.launcher.supervisor.started",
    "electron.launcher.window.opened",
    "electron.workbench.window.opened",
    "electron.workbench.navigation.ready",
    "electron.workbench.navigation.failed",
    "electron.launcher_service.started",
    "electron.launcher_service.exited",
    "electron.desktop_action.claimed",
    "electron.desktop_action.succeeded",
    "electron.desktop_action.failed",
    "electron.human_attention_notification.delivered",
    "electron.human_attention_notification.suppressed",
    "electron.human_attention_notification.invalid",
}


def test_facade_reexports_record_pack() -> None:
    assert facade.record_runtime_scene_event is record.record_runtime_scene_event
    assert facade.record_runtime_scene_conversation_event is record.record_runtime_scene_conversation_event
    assert facade.record_backend_api_event is record.record_backend_api_event
    assert facade.record_browser_telemetry is record.record_browser_telemetry
    assert facade.record_research_scene_event is record.record_research_scene_event
    assert facade.record_electron_supervisor_event is record.record_electron_supervisor_event
    assert facade.delete_runtime_scenes is record.delete_runtime_scenes


def test_electron_supervisor_catalog_accepts_workbench_navigation_outcomes() -> None:
    assert {
        "electron.workbench.navigation.ready",
        "electron.workbench.navigation.failed",
    }.issubset(facade.ELECTRON_SUPERVISOR_EVENT_CODES)


def test_electron_supervisor_catalog_accepts_human_attention_notification_outcomes() -> None:
    # 壳侧双通道通知的投递/去重/拒绝事件必须能落场景；漏登记会让 launcher
    # 端点 ValueError，事件被静默丢弃（live 实弹踩过）。
    assert {
        "electron.human_attention_notification.delivered",
        "electron.human_attention_notification.suppressed",
        "electron.human_attention_notification.invalid",
    }.issubset(facade.ELECTRON_SUPERVISOR_EVENT_CODES)


def test_electron_supervisor_catalog_covers_all_shell_emitted_and_legacy_codes() -> None:
    # 发射清单即契约：壳侧每个 `eventCode: "electron.*"` 发射码（对照方法：
    # grep desktop/electron/src 的 "electron\.[a-z0-9_.]" 模式与本表做差集）
    # 加历史保留码（含未被发射的 electron.launcher.window.opened）必须全部在册。
    assert facade.ELECTRON_SUPERVISOR_EVENT_CODES.issuperset(_ELECTRON_SHELL_EMITTED_EVENT_CODES)
    assert facade.ELECTRON_SUPERVISOR_EVENT_CODES.issuperset(_ELECTRON_LEGACY_EVENT_CODES)


def test_record_electron_supervisor_event_accepts_every_catalogued_code(monkeypatch) -> None:
    monkeypatch.setattr(
        facade,
        "record_runtime_scene_event",
        lambda *args, **_kwargs: {"accepted": True, "runtimeSceneId": "scene-1"},
    )
    for event_code in sorted(facade.ELECTRON_SUPERVISOR_EVENT_CODES):
        result = facade.record_electron_supervisor_event(event_code, message=event_code)
        assert result["accepted"] is True


def test_record_electron_supervisor_event_still_rejects_unknown_codes(monkeypatch) -> None:
    monkeypatch.setattr(
        facade,
        "record_runtime_scene_event",
        lambda *args, **_kwargs: {"accepted": True, "runtimeSceneId": "scene-1"},
    )
    with pytest.raises(ValueError):
        facade.record_electron_supervisor_event("electron.fake.code", message="must be rejected")


def test_facade_reexports_query_pack() -> None:
    assert facade.list_runtime_scenes is query.list_runtime_scenes
    assert facade.get_runtime_scene_detail is query.get_runtime_scene_detail
    assert facade.read_runtime_scene_file is file_preview.read_runtime_scene_file
    assert facade.list_runtime_scene_evidence_for_agent is query.list_runtime_scene_evidence_for_agent
    assert facade.build_runtime_scene_prompt_index is query.build_runtime_scene_prompt_index


def test_facade_reexports_diagnosis_pack() -> None:
    assert facade._runtime_scene_package_diagnosis is diagnosis._runtime_scene_package_diagnosis
    assert facade._runtime_scene_agent_brief is diagnosis._runtime_scene_agent_brief
    assert facade._runtime_scene_issue_state is diagnosis._runtime_scene_issue_state
    assert facade._runtime_scene_key_entries is diagnosis._runtime_scene_key_entries
    assert facade._fold_repeated_work_run_snapshots is diagnosis._fold_repeated_work_run_snapshots
    assert facade._runtime_scene_diagnosis_next_step is diagnosis._runtime_scene_diagnosis_next_step


def test_facade_reexports_package_index_pack() -> None:
    assert (
        facade._sync_runtime_scene_package_index_if_stale
        is package_index._sync_runtime_scene_package_index_if_stale
    )
    assert (
        facade._runtime_scene_package_index_sidecar_is_stale
        is package_index._runtime_scene_package_index_sidecar_is_stale
    )
    assert (
        facade._update_runtime_scene_manifest_package_index_fields
        is package_index._update_runtime_scene_manifest_package_index_fields
    )
