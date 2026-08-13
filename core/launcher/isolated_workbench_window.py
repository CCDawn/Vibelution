"""Open and close named Workbench windows for isolated branch instances.

Isolated worktrees keep their own backend. The product desktop shell stays
singular: Electron opens an extra titled window, or Edge --app is used when
no Electron session is alive. Tests inject openers so this module never
touches the operator desktop during pytest.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.infrastructure.instance_display_name import workbench_window_title
from core.launcher import desktop_session_store, lifecycle_intent_store
from core.launcher.slot_identity import slot_id_for_project
from core.runtime_manager import instances_registry as registry
from core.runtime_manager.constants import PROJECT_ROOT

OPEN_INSTANCE_WORKBENCH = "open_instance_workbench"
CLOSE_INSTANCE_WORKBENCH = "close_instance_workbench"
_WINDOW_OPEN_WAIT_SECONDS = 8.0
_WINDOW_OPEN_POLL_SECONDS = 0.2

WindowOpener = Callable[[dict[str, Any]], dict[str, Any]]
WindowCloser = Callable[[dict[str, Any]], dict[str, Any]]


def instance_workbench_title(item: dict[str, Any]) -> str:
    explicit = str(item.get("workbenchTitle") or "").strip()
    if explicit:
        return explicit
    return workbench_window_title(str(item.get("shortName") or item.get("branch") or "detached"))


def overlay_instance_window_pid(item: dict[str, Any], entry: dict[str, Any] | None) -> None:
    """Copy a live registry window pid onto a non-current instance row."""

    if not isinstance(item, dict) or item.get("current"):
        return
    pid = _live_pid((entry or {}).get("windowPid"))
    if pid <= 0:
        return
    pids = item.get("pids")
    if not isinstance(pids, dict):
        pids = {}
        item["pids"] = pids
    pids["window"] = pid


def persist_instance_window_from_desktop_action(action: dict[str, Any]) -> None:
    """Write Electron ack renderer pid back to the instance registry."""

    if not isinstance(action, dict):
        return
    name = str(action.get("action") or "").strip()
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    instance_id = str(payload.get("instanceId") or "").strip()
    if not instance_id:
        return
    if name == OPEN_INSTANCE_WORKBENCH:
        result = action.get("result") if isinstance(action.get("result"), dict) else {}
        window_state = result.get("windowState") if isinstance(result.get("windowState"), dict) else {}
        pid = _positive_int(window_state.get("rendererProcessId"))
        title = str(payload.get("windowTitle") or window_state.get("title") or "").strip()
        _persist_window_fields(instance_id, window_pid=pid, window_title=title)
        return
    if name == CLOSE_INSTANCE_WORKBENCH:
        _persist_window_fields(instance_id, window_pid=0)


def open_isolated_workbench_window(
    item: dict[str, Any],
    *,
    opener: WindowOpener | None = None,
) -> dict[str, Any]:
    """Present a named workbench window for one isolated instance."""

    if _running_under_pytest() and opener is None:
        return {"provider": "test", "windowPid": 0, "title": instance_workbench_title(item)}
    runner = opener or _default_open
    result = runner(item) or {}
    instance_id = str(item.get("id") or "").strip()
    title = str(result.get("title") or instance_workbench_title(item))
    pid = _positive_int(result.get("windowPid"))
    if instance_id:
        _persist_window_fields(instance_id, window_pid=pid, window_title=title)
    return {
        "provider": str(result.get("provider") or ""),
        "windowPid": pid,
        "title": title,
        "intentId": str(result.get("intentId") or ""),
    }


def close_isolated_workbench_window(
    item: dict[str, Any],
    *,
    closer: WindowCloser | None = None,
) -> dict[str, Any]:
    """Close the named window without stopping the current main workbench."""

    instance_id = str(item.get("id") or "").strip()
    if _running_under_pytest() and closer is None:
        if instance_id:
            _persist_window_fields(instance_id, window_pid=0)
        return {"provider": "test", "windowPid": 0}
    runner = closer or _default_close
    result = runner(item) or {}
    if instance_id:
        _persist_window_fields(instance_id, window_pid=0)
    return result


def _default_open(item: dict[str, Any]) -> dict[str, Any]:
    title = instance_workbench_title(item)
    url = _instance_workbench_url(item)
    if not url:
        return {"provider": "", "windowPid": 0, "title": title}
    if _electron_desktop_shell_available():
        return _open_via_electron(item, url=url, title=title)
    return _open_via_named_edge(item, url=url, title=title)


def _default_close(item: dict[str, Any]) -> dict[str, Any]:
    if _electron_desktop_shell_available():
        intent = _submit_instance_window_action(
            CLOSE_INSTANCE_WORKBENCH,
            item,
            reason="isolated_branch_instance_window_close",
        )
        return {"provider": "electron", "windowPid": 0, "intentId": str(intent.get("intentId") or "")}
    _terminate_edge_window_pid(item)
    return {"provider": "edge_app", "windowPid": 0}


def _open_via_electron(item: dict[str, Any], *, url: str, title: str) -> dict[str, Any]:
    intent = _submit_instance_window_action(
        OPEN_INSTANCE_WORKBENCH,
        item,
        reason="isolated_branch_instance_window",
        extra_payload={"workbenchUrl": url, "windowTitle": title},
    )
    intent_id = str(intent.get("intentId") or "")
    finished = _wait_for_intent(intent_id) if intent_id else intent
    result = finished.get("result") if isinstance(finished.get("result"), dict) else {}
    window_state = result.get("windowState") if isinstance(result.get("windowState"), dict) else {}
    pid = _positive_int(window_state.get("rendererProcessId"))
    status = str(finished.get("status") or intent.get("status") or "")
    if pid > 0 or status in {"accepted", "executing", ""}:
        return {
            "provider": "electron",
            "windowPid": pid,
            "title": title,
            "intentId": intent_id,
            "status": status,
        }
    edge = _open_via_named_edge(item, url=url, title=title)
    edge["intentId"] = intent_id
    edge["electronStatus"] = status
    return edge


def _open_via_named_edge(item: dict[str, Any], *, url: str, title: str) -> dict[str, Any]:
    if os.name != "nt":
        return {"provider": "none", "windowPid": 0, "title": title}
    worktree = Path(str(item.get("path") or "")).expanduser()
    profile_dir = worktree / ".runtime" / "launcher" / "workbench-app-profile"
    slot_id = str(item.get("slotId") or "")
    if not slot_id and worktree.exists():
        try:
            slot_id = slot_id_for_project(worktree)
        except (OSError, TypeError, ValueError):
            slot_id = "isolated"
    app_id = f"Vibelution.Workbench.{slot_id or 'isolated'}"
    from scripts.vibelution_launcher import start_named_workbench_browser

    started = start_named_workbench_browser(
        url,
        profile_dir=profile_dir,
        app_id=app_id,
        display_name=title,
    )
    return {
        "provider": "edge_app",
        "windowPid": _positive_int(started.get("browserWindowPid") or started.get("browserLaunchPid")),
        "title": title,
        "appUserModelId": app_id,
    }


def _submit_instance_window_action(
    action: str,
    item: dict[str, Any],
    *,
    reason: str,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instance_id = str(item.get("id") or "").strip()
    payload = {"instanceId": instance_id}
    if extra_payload:
        payload.update(extra_payload)
    return lifecycle_intent_store.submit_lifecycle_intent(
        {
            "action": action,
            "reason": reason,
            "idempotencyKey": f"{action}:{instance_id}:{uuid4().hex}",
        },
        actor_context={
            "actorType": "launcher_api",
            "actorId": "isolated-instance-window",
            "sourceRunId": "",
            "sourceTaskId": "",
            "sourceWorktree": str(item.get("path") or ""),
        },
        active_work_runs=[],
        desktop_action_payload=payload,
    )


def _wait_for_intent(intent_id: str, timeout_seconds: float = _WINDOW_OPEN_WAIT_SECONDS) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = lifecycle_intent_store.get_lifecycle_intent(intent_id)
        if str(latest.get("status") or "") in {"succeeded", "failed"}:
            return latest
        time.sleep(_WINDOW_OPEN_POLL_SECONDS)
    return latest


def _electron_desktop_shell_available() -> bool:
    try:
        session = desktop_session_store.latest_active_desktop_session(
            provider="electron",
            workspace_root=str(PROJECT_ROOT),
        )
    except (OSError, TypeError, ValueError):
        return False
    return bool(session)


def _instance_workbench_url(item: dict[str, Any]) -> str:
    url = str(item.get("url") or "").strip()
    if url:
        return url if url.endswith("/") else f"{url}/"
    port = _positive_int(item.get("port"))
    if port <= 0:
        return ""
    return f"http://127.0.0.1:{port}/"


def _persist_window_fields(instance_id: str, *, window_pid: int, window_title: str = "") -> None:
    fields: dict[str, Any] = {"windowPid": int(window_pid)}
    if window_title:
        fields["windowTitle"] = window_title
    registry.upsert_instance(instance_id, **fields)
    entry = registry.get_instance(instance_id)
    root = str(entry.get("projectRoot") or "").strip()
    if root:
        _write_worktree_window_pid(Path(root), int(window_pid))


def _write_worktree_window_pid(worktree: Path, pid: int) -> None:
    path = worktree / ".runtime" / "launcher" / "state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["browserWindowPid"] = int(pid)
    payload["windowPid"] = int(pid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _terminate_edge_window_pid(item: dict[str, Any]) -> None:
    instance_id = str(item.get("id") or "").strip()
    entry = registry.get_instance(instance_id) if instance_id else {}
    pid = _positive_int(entry.get("windowPid"))
    if pid <= 0:
        return
    try:
        from scripts.vibelution_launcher import _terminate_pid

        _terminate_pid(pid)
    except Exception:
        return


def _running_under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _live_pid(value: Any) -> int:
    pid = _positive_int(value)
    if pid <= 0:
        return 0
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return 0
        return pid
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid) or kernel32.OpenProcess(0x0400, False, pid)
    if not handle:
        return 0
    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return 0
        return pid if int(exit_code.value) == 259 else 0
    finally:
        kernel32.CloseHandle(handle)


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
