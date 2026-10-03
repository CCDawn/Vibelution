"""Lifecycle hooks for the Web workbench FastAPI app."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from .server_shutdown import mark_server_shutdown_clean
from .startup_jobs import StartupJobGroup, remaining_seconds, run_sync_bounded

logger = logging.getLogger(__name__)
LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS = 25.0


def _record_backend_ready_scene_event(
    *,
    pre_yield_ms: int,
    routes_ready: bool,
    background_tasks: list[str],
) -> None:
    """Record startup diagnostics after health readiness is no longer blocked."""

    try:
        from .services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "backend",
            "startup",
            "backend.lifespan.ready_to_serve",
            message="Workbench lifespan yielded; health is up while routes mount in background.",
            outcome="started",
            fields={
                "preYieldMs": max(0, int(pre_yield_ms)),
                "routesReady": bool(routes_ready),
                "backgroundTasks": list(background_tasks),
            },
            lifecycle=True,
        )
    except Exception as exc:  # noqa: BLE001 - startup diagnostics are best effort
        logger.debug("Backend ready runtime-scene event failed: %s", type(exc).__name__)


def initialize_session_catalog_on_startup() -> object:
    """Start the optional catalog candidate without changing the legacy read path."""

    from config.settings import get_config

    from .services.session.catalog_runtime import initialize_session_catalog_runtime

    return initialize_session_catalog_runtime(
        project_root=Path(__file__).resolve().parents[2],
        catalog_config=get_config().session_catalog,
    )


def initialize_session_directory_on_startup(generation: int | None = None) -> object:
    """Open the live session directory store and discard unmigrated JSON sessions."""

    from .services.session.directory_runtime import (
        SessionDirectoryRuntimeStatus,
        initialize_session_directory_runtime,
        should_skip_directory_runtime_for_pytest,
    )

    if should_skip_directory_runtime_for_pytest():
        return SessionDirectoryRuntimeStatus(status="skipped_pytest")
    return initialize_session_directory_runtime(
        project_root=Path(__file__).resolve().parents[2],
        generation=generation,
    )


def _reconcile_cli_agent_terminal_states_on_startup() -> object:
    from .services.cli_agent_terminal_service import (
        reconcile_cli_agent_terminal_states_on_startup,
    )

    return reconcile_cli_agent_terminal_states_on_startup(reason="backend_startup")


def _recover_wakeable_agent_inbox_messages_on_startup() -> object:
    from .services.session_service import (
        recover_wakeable_agent_inbox_messages_on_startup,
    )

    return recover_wakeable_agent_inbox_messages_on_startup()


def _recover_challenge_meeting_drivers_on_startup() -> object:
    from .services.team_workflow.meeting_driver_work import (
        recover_challenge_meeting_drivers,
    )

    return recover_challenge_meeting_drivers()


def _recover_orphaned_chat_room_rounds_on_startup() -> object:
    from .services.chat_room_startup_recovery import recover_chat_room_rounds_on_startup

    return recover_chat_room_rounds_on_startup()


def _recover_hypothesis_command_attempts_on_startup() -> object:
    """Fence long hypothesis commands interrupted by a restart (SCI-049).

    The async command window leaves ``accepted`` attempts behind when the
    backend dies mid-execution; this sweep marks those orphans ``failed`` so
    the UI shows a retryable failure instead of a zombie accepted state.
    """

    from .services.team_workflow.research_runtime.hypothesis_command_attempts import (
        recover_interrupted_command_attempts,
    )

    return recover_interrupted_command_attempts()


def _recover_interrupted_session_turns_on_startup(
    *, should_stop: Callable[[], bool] | None = None
) -> object:
    """Resume interrupted session turns and queue drains after a restart.

    Operator-gated by ``session_recovery``; best-effort (never blocks
    startup). Companion sessions are skipped by the sweep itself.
    """

    from .services.session.startup_recovery import (
        recover_interrupted_session_turns_on_startup,
    )

    return recover_interrupted_session_turns_on_startup(should_stop=should_stop)


def _validate_challenge_fence_config_on_startup() -> int | None:
    """Validate the operator per-call fence pin once at backend boot.

    The request-time derivation rejects an out-of-domain
    ``[research] challenge_meeting_per_call_budget_ms`` too, but only when a
    meeting is already being scheduled (2026-09-03 incident); this self-check
    surfaces the misconfiguration — with the actual and expected values —
    before any meeting can derive a clock.
    """

    from .services.team_workflow.challenge_deadline_policy import (
        validate_live_operator_per_call_config,
    )

    return validate_live_operator_per_call_config()


def shutdown_session_catalog_on_shutdown(*, deadline: float | None = None) -> dict[str, Any]:
    """Flush the directory writer and close catalog work under one deadline."""

    if deadline is None:
        deadline = time.monotonic() + LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS
    failed_owners: list[str] = []
    try:
        from .services.session.directory_runtime import shutdown_session_directory_runtime

        shutdown_session_directory_runtime(
            timeout=remaining_seconds(deadline),
        )
    except Exception as exc:  # noqa: BLE001 - catalog teardown still has to run
        failed_owners.append("session_directory")
        logger.error("Session directory writer shutdown failed (%s).", type(exc).__name__)
    try:
        from .services.session.catalog_runtime import shutdown_session_catalog_runtime

        shutdown_session_catalog_runtime()
    except Exception as exc:  # noqa: BLE001 - isolate the catalog owner
        failed_owners.append("session_catalog")
        logger.error("Session catalog shutdown failed (%s).", type(exc).__name__)
    return {"closed": not failed_owners, "failedOwners": failed_owners}


def reconcile_external_agent_tasks_once() -> list[dict[str, Any]]:
    """Recover and reconcile durable external task projections once."""

    from .services.external_agent.service import get_default_service

    project_root = Path(__file__).resolve().parents[2]
    return list(get_default_service(project_root).reconcile())


async def reconcile_external_agent_tasks_forever(
    *, interval_seconds: float = 5.0, startup_jobs: StartupJobGroup | None = None
) -> None:
    """Keep lease expiry and stop acknowledgement live without a child process."""

    interval = max(0.01, float(interval_seconds))
    iteration = 0
    while True:
        try:
            if startup_jobs is None:
                await asyncio.to_thread(reconcile_external_agent_tasks_once)
            else:
                iteration += 1
                await startup_jobs.run_sync(
                    f"external-agent-reconcile-{iteration}",
                    reconcile_external_agent_tasks_once,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad pass must not disable leases
            logger.warning(
                "External Agent task reconciliation iteration failed (%s); retrying.",
                type(exc).__name__,
            )
        await asyncio.sleep(interval)


def _enforce_runtime_scene_retention_after_routes_ready(
    *, should_stop: Callable[[], bool] | None = None
) -> dict[str, Any]:
    """Run the existing guarded retention sweep after route readiness."""

    try:
        # Keep the scene/query import graph off the startup path until routes
        # have mounted and health can be served.
        from .services.runtime_scene.query import _enforce_runtime_scene_retention

        if should_stop is None:
            return dict(_enforce_runtime_scene_retention() or {})
        return dict(_enforce_runtime_scene_retention(should_stop=should_stop) or {})
    except Exception as exc:  # noqa: BLE001 - cleanup must not affect readiness
        logger.warning("Runtime scene retention failed after startup (%s).", type(exc).__name__)
        return {}


async def _run_runtime_scene_retention_after_routes_ready(
    app: FastAPI,
    *,
    startup_jobs: StartupJobGroup | None = None,
) -> None:
    """Wait for successful route registration, then run one tracked cleanup."""

    ready_event = getattr(app.state, "web_routes_ready_event", None)
    if ready_event is None:
        return
    await ready_event.wait()
    if not bool(getattr(app.state, "web_routes_registered", False)):
        return

    stop_requested = threading.Event()
    if startup_jobs is not None:
        await startup_jobs.run_sync(
            "runtime-scene-retention-worker",
            _enforce_runtime_scene_retention_after_routes_ready,
            stop_keyword="should_stop",
        )
        return
    # Shield the worker so cancellation reaches this owner first; it can then
    # stop the next scan/delete and join any filesystem operation in progress.
    retention_worker = asyncio.create_task(
        asyncio.to_thread(
            _enforce_runtime_scene_retention_after_routes_ready,
            should_stop=stop_requested.is_set,
        ),
        name="runtime-scene-retention-worker",
    )
    try:
        await asyncio.shield(retention_worker)
    except asyncio.CancelledError:
        stop_requested.set()
        with suppress(Exception):
            await asyncio.shield(retention_worker)
        raise


# ---------------------------------------------------------------------------
# Startup cache prewarm gating.
#
# The heavy boot prewarms (config workspace alias scan ≈12s of pure-Python
# rglob+read, agent registry repair/summary) used to start as to_thread workers
# alongside the background route mount.  With ~15 workers pulled up at once the
# scans held the GIL for seconds at a time and multiplied every concurrent
# request's latency by 10-800x during the 2026-10-02 16:26 window.  The
# frontend's startup volley does not read these caches, so deferring them past
# route readiness plus a settle window is free.
# ---------------------------------------------------------------------------

# Aligns with wait_for_web_routes / WaitForWebRoutesMiddleware (route_bootstrap).
_ROUTES_READY_WAIT_TIMEOUT_SECONDS = 120.0
_DEFAULT_STARTUP_PREWARM_STAGGER_SECONDS = 12.0


def _startup_cache_prewarm_gate_enabled() -> bool:
    """Operator switch for the routes-ready prewarm gate (default: enabled).

    Set ``VIBELUTION_DEFER_STARTUP_CACHE_PREWARM=0`` (or false/no/off) to
    restore the legacy behavior of starting the scans immediately at boot.
    """

    raw = str(os.environ.get("VIBELUTION_DEFER_STARTUP_CACHE_PREWARM") or "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no", "off"}


def _startup_prewarm_stagger_seconds() -> float:
    """Settle window between route readiness and the heavy prewarm scans.

    ``VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS`` (float, default 12.0, 0 =
    only wait for route readiness) bounds how long the scans wait for the
    frontend's first request volley to drain before grabbing the GIL.
    """

    raw = str(os.environ.get("VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_STARTUP_PREWARM_STAGGER_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Invalid VIBELUTION_STARTUP_PREWARM_STAGGER_SECONDS=%r; using default %s.",
            raw,
            _DEFAULT_STARTUP_PREWARM_STAGGER_SECONDS,
        )
        return _DEFAULT_STARTUP_PREWARM_STAGGER_SECONDS
    return max(0.0, value)


async def _await_web_routes_ready_for_prewarm(app: FastAPI | None) -> int:
    """Bounded wait for the background route mount before heavy prewarm work.

    Same event and 120s semantics as the routes middleware; a timeout (or a
    mount failure that sets the event early) never fails the prewarm — it only
    bounds how long startup defers it.  Returns the elapsed wait in ms.
    """

    ready_event = getattr(getattr(app, "state", None), "web_routes_ready_event", None)
    if ready_event is None:
        return 0
    started = time.perf_counter()
    try:
        await asyncio.wait_for(ready_event.wait(), timeout=_ROUTES_READY_WAIT_TIMEOUT_SECONDS)
    except TimeoutError:
        # Routes never became ready within the serving contract's own window;
        # run the prewarm anyway instead of failing startup work over it.
        pass
    return max(0, int((time.perf_counter() - started) * 1000))


async def _run_prewarm_heavy_after_routes_ready(
    app: FastAPI | None,
    heavy: Callable[[dict[str, Any]], Any],
    *,
    worker_name: str,
    startup_jobs: StartupJobGroup | None = None,
) -> Any:
    """Shared ready→settle→to_thread gate for the CPU-heavy startup prewarms."""

    waited_ms = await _await_web_routes_ready_for_prewarm(app)
    stagger_seconds = _startup_prewarm_stagger_seconds()
    if stagger_seconds > 0:
        await asyncio.sleep(stagger_seconds)
    gate_timings = {
        "waitedForRoutesMs": waited_ms,
        "staggerMs": max(0, int(round(stagger_seconds * 1000))),
    }
    if startup_jobs is not None:
        return await startup_jobs.run_sync(worker_name, heavy, gate_timings)
    worker = asyncio.create_task(asyncio.to_thread(heavy, gate_timings), name=worker_name)
    try:
        # Shield the scan so cancellation reaches this owner first; shutdown
        # then joins the read-only executor work instead of orphaning it.
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with suppress(asyncio.CancelledError):
            await asyncio.shield(worker)
        raise


async def _run_config_workspace_prewarm_after_routes_ready(
    app: FastAPI | None, *, startup_jobs: StartupJobGroup | None = None
) -> dict[str, Any]:
    from .services.session.directory_runtime import should_skip_directory_runtime_for_pytest

    if should_skip_directory_runtime_for_pytest():
        return {"skipped": "pytest"}
    return await _run_prewarm_heavy_after_routes_ready(
        app,
        _prewarm_config_workspace_on_startup,
        worker_name="config-workspace-prewarm-worker",
        startup_jobs=startup_jobs,
    )


async def _run_agent_registry_prewarm_after_routes_ready(
    app: FastAPI | None, *, startup_jobs: StartupJobGroup | None = None
) -> dict[str, Any]:
    from .services.session.directory_runtime import should_skip_directory_runtime_for_pytest

    if should_skip_directory_runtime_for_pytest():
        return {"skipped": "pytest"}
    return await _run_prewarm_heavy_after_routes_ready(
        app,
        _prewarm_agent_registry_on_startup,
        worker_name="agent-registry-prewarm-worker",
        startup_jobs=startup_jobs,
    )


def is_windows_proactor_disconnect_noise(context: dict[str, Any]) -> bool:
    if os.name != "nt":
        return False
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError):
        return False
    fragments = [
        str(context.get("message") or ""),
        repr(context.get("handle")),
        repr(context.get("transport")),
        repr(context.get("protocol")),
    ]
    haystack = " ".join(fragment for fragment in fragments if fragment).lower()
    return "proactorbasepipetransport._call_connection_lost" in haystack


@asynccontextmanager
async def web_workbench_lifespan(app: FastAPI | None):
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    lifespan_started = time.perf_counter()

    def handle_loop_exception(current_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if is_windows_proactor_disconnect_noise(context):
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    _begin_owned_runtime_lifecycle()
    loop.set_exception_handler(handle_loop_exception)
    startup_jobs = StartupJobGroup()
    from .route_bootstrap import warm_web_routes_in_background

    startup_routes_task: asyncio.Task[Any] | None = None
    startup_scene_retention_task: asyncio.Task[Any] | None = None
    if app is not None:
        # Enable async waiters for non-health requests while routes mount in background.
        app.state.web_routes_ready_event = asyncio.Event()
        # Route import/mount is the cold-start bulk cost — do not await before yield so
        # /api/health can pass and Launcher can open the window early.
        startup_routes_task = startup_jobs.start_async(
            "web-routes-bootstrap",
            warm_web_routes_in_background(app, run_sync=startup_jobs.run_sync),
        )
        if os.environ.get("VIBELUTION_DEFER_RUNTIME_SCENE_RETENTION") == "1":
            startup_scene_retention_task = startup_jobs.start_async(
                "runtime-scene-retention",
                _run_runtime_scene_retention_after_routes_ready(app, startup_jobs=startup_jobs),
            )
    # Snapshot the git commit this backend was started from (best effort, never
    # blocks health). The UI compares it with disk HEAD to flag stale instances.
    startup_code_fingerprint_task = startup_jobs.start_thread(
        "startup-code-fingerprint", _write_running_code_fingerprint_on_startup, app
    )
    # Do not await terminal reconcile before yield — it blocked /api/health readiness
    # and stretched launcher open_launcher_action by the full reconcile cost.
    startup_cli_reconcile_task = startup_jobs.start_thread(
        "startup-cli-terminal-reconcile", _reconcile_cli_agent_terminal_states_on_startup
    )
    startup_cache_prewarm_task = startup_jobs.start_async(
        "startup-ui-cache-prewarm", prewarm_ui_caches_on_startup(startup_jobs=startup_jobs)
    )
    from .services.session.directory_runtime import (
        begin_directory_startup,
        should_skip_directory_runtime_for_pytest,
    )

    if should_skip_directory_runtime_for_pytest():
        startup_directory_task = startup_jobs.start_thread(
            "startup-session-directory", initialize_session_directory_on_startup
        )
    else:
        directory_generation = begin_directory_startup()
        startup_directory_task = startup_jobs.start_thread(
            "startup-session-directory", initialize_session_directory_on_startup, directory_generation
        )
    startup_catalog_task = startup_jobs.start_thread(
        "startup-session-catalog", initialize_session_catalog_on_startup
    )
    # The alias scans are multi-second pure-Python CPU and would hold the GIL
    # against the route mount and the frontend's first request volley; defer
    # them behind route readiness + a settle window unless the operator
    # disables the gate.
    if _startup_cache_prewarm_gate_enabled():
        # Registry prewarm must trail the directory startup task (see the
        # worker): the wait itself happens inside the thread, never blocking
        # startup.
        startup_agent_registry_prewarm_task = startup_jobs.start_async(
            "startup-agent-registry-prewarm",
            _run_agent_registry_prewarm_after_routes_ready(app, startup_jobs=startup_jobs),
        )
        # Config workspace prewarm trails the directory startup task for the
        # same reason (the alias scan reads sessions under the serving root).
        startup_config_workspace_prewarm_task = startup_jobs.start_async(
            "startup-config-workspace-prewarm",
            _run_config_workspace_prewarm_after_routes_ready(app, startup_jobs=startup_jobs),
        )
    else:
        startup_agent_registry_prewarm_task = startup_jobs.start_thread(
            "startup-agent-registry-prewarm", _prewarm_agent_registry_on_startup
        )
        startup_config_workspace_prewarm_task = startup_jobs.start_thread(
            "startup-config-workspace-prewarm", _prewarm_config_workspace_on_startup
        )
    startup_agent_inbox_recovery_task = startup_jobs.start_thread(
        "startup-agent-inbox-recovery", _recover_wakeable_agent_inbox_messages_on_startup
    )
    startup_meeting_driver_recovery_task = startup_jobs.start_thread(
        "startup-meeting-driver-recovery", _recover_challenge_meeting_drivers_on_startup
    )
    startup_chat_room_round_recovery_task = startup_jobs.start_thread(
        "startup-chat-room-round-recovery", _recover_orphaned_chat_room_rounds_on_startup
    )
    startup_command_attempt_recovery_task = startup_jobs.start_thread(
        "startup-command-attempt-recovery", _recover_hypothesis_command_attempts_on_startup
    )
    # Session startup recovery sweep (interrupted turns + queue drain). Kept
    # adjacent to the other *_recovery_* hooks; later recovery hooks append
    # below this block.
    startup_session_recovery_task = startup_jobs.start_thread(
        "startup-session-recovery",
        _recover_interrupted_session_turns_on_startup,
        stop_keyword="should_stop",
    )
    startup_challenge_fence_validation_task = startup_jobs.start_thread(
        "startup-challenge-fence-validation", _validate_challenge_fence_config_on_startup
    )
    startup_external_agent_reconcile_task = startup_jobs.start_async(
        "startup-external-agent-reconcile",
        reconcile_external_agent_tasks_forever(startup_jobs=startup_jobs),
    )
    startup_workflow_runtime_task = startup_jobs.start_thread(
        "startup-workflow-runtime", _start_research_workflow_runtime
    )
    from .services.virtual_human_life_service import run_virtual_human_life_runtime

    startup_virtual_human_life_task = startup_jobs.start_async(
        "startup-virtual-human-life",
        run_virtual_human_life_runtime(run_sync=startup_jobs.run_sync),
    )

    def consume_startup_task_result(task: asyncio.Task[Any], *, message: str) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - route task failures use the loop handler
            loop.call_exception_handler(
                {
                    "message": message,
                    "exception": exc,
                }
            )

    if startup_routes_task is not None:
        startup_routes_task.add_done_callback(
            lambda task: consume_startup_task_result(task, message="Web route bootstrap failed during startup.")
        )
    if startup_scene_retention_task is not None:
        startup_scene_retention_task.add_done_callback(
            lambda task: consume_startup_task_result(
                task, message="Runtime scene retention task failed during startup."
            )
        )
    startup_cli_reconcile_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="CLI agent terminal reconcile failed during startup."
        )
    )
    startup_cache_prewarm_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="UI cache prewarm failed during startup.")
    )
    startup_directory_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Session directory store startup failed."
        )
    )
    startup_catalog_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Session catalog startup failed.")
    )
    startup_agent_registry_prewarm_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Agent registry prewarm failed during startup."
        )
    )
    startup_config_workspace_prewarm_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Config workspace prewarm failed during startup."
        )
    )
    startup_agent_inbox_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(task, message="Agent inbox recovery failed during startup.")
    )
    startup_meeting_driver_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Challenge meeting driver recovery failed during startup."
        )
    )
    startup_chat_room_round_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Chat room round startup recovery failed during startup."
        )
    )
    startup_command_attempt_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Hypothesis command attempt recovery failed during startup."
        )
    )
    startup_session_recovery_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Session startup recovery sweep failed during startup."
        )
    )
    startup_challenge_fence_validation_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task,
            message=(
                "research.challenge_meeting_per_call_budget_ms is out of the "
                "governed domain; fix the operator config before scheduling "
                "Challenge meetings."
            ),
        )
    )
    startup_external_agent_reconcile_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="External Agent task reconciliation stopped unexpectedly."
        )
    )
    startup_code_fingerprint_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Running-code fingerprint snapshot failed during startup."
        )
    )
    startup_workflow_runtime_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Research workflow Ledger runtime failed during startup."
        )
    )
    startup_virtual_human_life_task.add_done_callback(
        lambda task: consume_startup_task_result(
            task, message="Virtual human life runtime stopped unexpectedly."
        )
    )
    startup_scene_event_task: asyncio.Task[Any] | None = None
    try:
        # Schedule the informational event immediately before yield, but do not
        # import the runtime-scene/LLM graph until health is already available.
        try:
            startup_scene_event_task = startup_jobs.start_thread(
                "startup-ready-scene-event",
                _record_backend_ready_scene_event,
                pre_yield_ms=max(0, int((time.perf_counter() - lifespan_started) * 1000)),
                routes_ready=bool(
                    app is not None and getattr(app.state, "web_routes_registered", False)
                ),
                background_tasks=[
                    *(["web_routes_bootstrap"] if startup_routes_task is not None else []),
                    "cli_terminal_reconcile",
                    "ui_cache_prewarm",
                    "session_directory",
                    "session_catalog",
                    "agent_registry_prewarm",
                    "config_workspace_prewarm",
                    "agent_inbox_recovery",
                    "meeting_driver_recovery",
                    "chat_room_round_recovery",
                    "command_attempt_recovery",
                    "session_recovery_sweep",
                    "challenge_fence_config_validation",
                    "external_agent_task_reconcile",
                    "virtual_human_life",
                ],
            )
        except Exception as exc:  # noqa: BLE001 - health must not depend on diagnostics
            logger.debug("Backend ready runtime-scene task scheduling failed: %s", type(exc).__name__)
        yield
    finally:
        deadline = time.monotonic() + LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS
        shutdown_clean = True
        startup_jobs.request_stop()

        human_stop_ok = await _run_shutdown_step(
            "virtual-human-stop",
            lambda: run_sync_bounded(
                _stop_virtual_human_life_runtime,
                deadline_at=deadline,
                name="shutdown-virtual-human",
            ),
            deadline=deadline,
        )
        shutdown_clean &= _sync_owner_result_is_clean(human_stop_ok)

        startup_result = await _run_shutdown_step(
            "startup-jobs",
            startup_jobs.shutdown(deadline=deadline),
            deadline=deadline,
        )
        shutdown_clean &= bool(
            isinstance(startup_result, dict) and startup_result.get("closed") is True
        )

        workflow_stop_ok = await _run_shutdown_step(
            "research-workflow-stop",
            lambda: run_sync_bounded(
                _stop_research_workflow_runtime,
                deadline_at=deadline,
                name="shutdown-research-workflow",
            ),
            deadline=deadline,
        )
        shutdown_clean &= _sync_owner_result_is_clean(workflow_stop_ok)

        owned_result = await _run_shutdown_step(
            "owned-runtime-resources",
            _shutdown_owned_runtime_resources(deadline=deadline),
            deadline=deadline,
        )
        shutdown_clean &= bool(
            isinstance(owned_result, dict) and owned_result.get("closed") is True
        )

        stores_ok = await _run_shutdown_step(
            "session-stores",
            lambda: run_sync_bounded(
                shutdown_session_catalog_on_shutdown,
                deadline_at=deadline,
                name="shutdown-session-stores",
                deadline=deadline,
            ),
            deadline=deadline,
        )
        shutdown_clean &= _sync_owner_result_is_clean(stores_ok)
        if shutdown_clean:
            mark_server_shutdown_clean()
        else:
            logger.error("Workbench shutdown left one or more owned resources unverified.")
        loop.set_exception_handler(previous_handler)


def _stop_virtual_human_life_runtime() -> None:
    from .services.virtual_human_life_service import stop_virtual_human_life_runtime

    stop_virtual_human_life_runtime()


def _sync_owner_result_is_clean(result: Any) -> bool:
    return bool(
        isinstance(result, tuple)
        and len(result) == 2
        and result[0] is True
        and not (isinstance(result[1], dict) and result[1].get("closed") is False)
    )


async def _run_shutdown_step(name: str, awaitable: Any, *, deadline: float) -> Any:
    """Isolate one owner failure/cancellation and still run later cleanup."""

    try:
        if callable(awaitable):
            awaitable = awaitable()
        task = asyncio.create_task(awaitable, name=f"shutdown-{name}")
    except asyncio.CancelledError:
        logger.error("Workbench shutdown step could not start because it was cancelled: %s", name)
        return None
    except Exception as exc:  # noqa: BLE001 - setup/import failure must not skip later owners
        logger.error("Workbench shutdown step could not start: %s (%s)", name, type(exc).__name__)
        return None
    while not task.done():
        remaining = remaining_seconds(deadline)
        if remaining <= 0:
            task.cancel()
            logger.error("Workbench shutdown step exceeded the shared deadline: %s", name)
            return None
        try:
            await asyncio.wait({task}, timeout=min(0.05, remaining))
        except asyncio.CancelledError:
            logger.warning("Workbench shutdown step was cancelled; continuing cleanup: %s", name)
    if task.cancelled():
        logger.error("Workbench shutdown step ended cancelled: %s", name)
        return None
    try:
        return task.result()
    except asyncio.CancelledError:
        logger.error("Workbench shutdown owner raised CancelledError: %s", name)
    except Exception as exc:  # noqa: BLE001 - one owner must not skip later cleanup
        logger.error("Workbench shutdown owner failed: %s (%s)", name, type(exc).__name__)
    return None


def _begin_owned_runtime_lifecycle() -> None:
    # Fresh processes already have open admission gates. Only reopen owners
    # from a previous lifespan; importing them here would delay cold health.
    failures: list[str] = []
    for module_name, begin_name in (
        ("core.infrastructure.background_tasks", "begin_background_task_lifecycle"),
        ("core.web.services.cli_agent_terminal_service", "begin_cli_agent_terminal_lifecycle"),
        ("core.web.services.session_service", "begin_session_service_lifecycle"),
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            try:
                result = getattr(module, begin_name)()
                if isinstance(result, dict) and result.get("opened") is False:
                    failures.append(module_name)
                    logger.error("Owned runtime lifecycle could not reopen: %s", module_name)
            except Exception as exc:  # noqa: BLE001 - assess every loaded owner
                failures.append(module_name)
                logger.error(
                    "Owned runtime lifecycle reopen failed: %s (%s)",
                    module_name,
                    type(exc).__name__,
                )
    if failures:
        raise RuntimeError("Owned runtime lifecycle could not reopen: " + ", ".join(failures))


async def _shutdown_owned_runtime_resources(*, deadline: float | None = None) -> dict[str, Any]:
    if deadline is None:
        deadline = time.monotonic() + LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS

    def _stop_background_tasks() -> Any:
        from core.infrastructure.background_tasks import shutdown_background_tasks

        return shutdown_background_tasks()

    def _stop_cli_terminals() -> Any:
        from .services.cli_agent_terminal_service import shutdown_cli_agent_terminal_sessions

        return shutdown_cli_agent_terminal_sessions()

    def _stop_session_executors() -> Any:
        from .services.session_service import shutdown_session_service

        return shutdown_session_service(deadline=deadline)

    owners = (
        ("background-tasks", _stop_background_tasks, {}),
        ("cli-terminals", _stop_cli_terminals, {}),
        ("session-executors", _stop_session_executors, {}),
    )

    async def _shutdown_owner(name: str, callback: Callable[..., Any], kwargs: dict[str, Any]) -> bool:
        try:
            completed, result = await run_sync_bounded(
                callback,
                deadline_at=deadline,
                name=f"shutdown-{name}",
                **kwargs,
            )
        except asyncio.CancelledError:
            logger.error("Owned runtime shutdown cancelled: %s", name)
            return False
        except Exception as exc:  # noqa: BLE001 - isolate each runtime owner
            logger.error("Owned runtime shutdown failed: %s (%s)", name, type(exc).__name__)
            return False
        if not completed or (isinstance(result, dict) and result.get("closed") is False):
            logger.error("Owned runtime shutdown incomplete: %s", name)
            return False
        return True

    results = await asyncio.gather(
        *(_shutdown_owner(name, callback, kwargs) for name, callback, kwargs in owners),
        return_exceptions=True,
    )
    return {
        "closed": all(result is True for result in results),
        "owners": [name for name, _, _ in owners],
    }



def _start_research_workflow_runtime() -> str:
    from .services.team_workflow.research_runtime.runtime_factory import (
        start_production_workflow_runtime,
    )

    return start_production_workflow_runtime()


def _stop_research_workflow_runtime() -> None:
    from .services.team_workflow.research_runtime.runtime_factory import (
        stop_production_workflow_runtime,
    )

    stop_production_workflow_runtime()


def _write_running_code_fingerprint_on_startup(app: Any | None = None) -> None:
    from .services.code_freshness import write_running_code_fingerprint

    project_root = Path(str(os.environ.get("VIBELUTION_WORKSPACE_ROOT") or Path(__file__).resolve().parents[2])).resolve()
    serving = getattr(getattr(app, "state", None), "serving_metadata", None)
    write_running_code_fingerprint(
        project_root=project_root,
        source="web_workbench_lifespan",
        serving_metadata=serving if isinstance(serving, dict) else None,
    )


def _prewarm_git_memory_on_startup() -> tuple[Any, int]:
    from core.infrastructure import git_memory

    # Warm the code-freshness verdict cache FIRST (45s fast-path TTL): the
    # frontend polls freshness ~20s after boot while refresh_git_memory's
    # subprocess-heavy pass runs for tens of seconds, and resolving freshness
    # after the refresh made that first poll miss the cache, pay the full
    # git-backed resolution itself, and then have the prewarm repeat the same
    # walk (double compute).  Resolving before the refresh fills the cache in
    # time for the first poll and removes the duplicate scan.  Best effort — a
    # freshness failure never fails git prewarm.
    try:
        from .routes.runtime import PROJECT_ROOT
        from .services.code_freshness import resolve_code_freshness

        resolve_code_freshness(project_root=PROJECT_ROOT)
    except Exception:  # noqa: BLE001 - freshness prewarm is best effort
        pass
    started = time.perf_counter()
    state = git_memory.refresh_git_memory(force=True)
    # durationMs stays scoped to the git memory refresh itself.
    return state, max(0, int((time.perf_counter() - started) * 1000))


def _prewarm_config_workspace_on_startup(gate_timings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Warm the config workspace payload cache before the first request.

    ``GET /api/config/workspace`` pays a multi-second full rebuild on a cold
    cache (the model-alias usage scan walks six sources per alias, including
    two full rglob traversals). config_service's per-key single-flight shares
    one build across this prewarm thread and any early request volley, so
    boot-time requests wait for this build instead of each paying the slow
    path. The session directory startup task aligns the serving root the
    alias scan reads, so wait for it (bounded) first — same reason as the
    registry prewarm. Pytest skips like the directory runtime itself.
    ``gate_timings`` (routes-ready wait + settle stagger, from the gated async
    wrapper) is merged into the reported timings when present.
    """

    from .services.session.directory_runtime import (
        should_skip_directory_runtime_for_pytest,
        wait_for_directory_startup,
    )

    if should_skip_directory_runtime_for_pytest():
        return {"skipped": "pytest"}
    wait_for_directory_startup()
    from .services import config_service

    started = time.perf_counter()
    config_service.prewarm_config_workspace()
    timings = {"totalMs": max(0, int((time.perf_counter() - started) * 1000))}
    if isinstance(gate_timings, dict) and gate_timings:
        timings.update(gate_timings)
    try:
        from .services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "config",
            "startup_prewarm",
            "config.workspace_prewarmed",
            message="Config workspace payload cache was prewarmed at startup.",
            outcome="completed",
            fields=dict(timings),
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - prewarm diagnostics are best effort
        pass
    return timings


def _prewarm_agent_registry_on_startup(gate_timings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Warm the Agent registry repair + summary caches before the first request.

    The session directory startup task is what aligns
    ``agent_directory_service.PROJECT_ROOT`` with the serving root, so wait for
    it (bounded, same pattern as directory_bridge readers) before warming;
    otherwise the repair cache would be built against the wrong registry.
    Pytest skips like the directory runtime itself: boot-time heavy work has no
    value under TestClient lifespans and must never touch the real checkout.
    ``gate_timings`` (routes-ready wait + settle stagger, from the gated async
    wrapper) is merged into the reported timings when present.
    """

    from .services.session.directory_runtime import (
        should_skip_directory_runtime_for_pytest,
        wait_for_directory_startup,
    )

    if should_skip_directory_runtime_for_pytest():
        return {"skipped": "pytest"}
    wait_for_directory_startup()
    from .services import agent_directory_service

    started = time.perf_counter()
    timings = agent_directory_service.prewarm_registry_caches()
    timings["totalMs"] = max(0, int((time.perf_counter() - started) * 1000))
    if isinstance(gate_timings, dict) and gate_timings:
        timings.update(gate_timings)
    try:
        from .services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "agent_directory",
            "startup_prewarm",
            "agent_directory.registry_prewarmed",
            message="Agent registry repair and summary caches were prewarmed at startup.",
            outcome="completed",
            fields=dict(timings),
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - prewarm diagnostics are best effort
        pass
    return timings


async def prewarm_ui_caches_on_startup(
    *, startup_jobs: StartupJobGroup | None = None
) -> None:
    from tools import Key_Tools, web_search_tool

    started = time.perf_counter()
    if startup_jobs is None:
        jobs = (
            asyncio.to_thread(Key_Tools.prewarm_key_tool_definitions),
            asyncio.to_thread(web_search_tool.autoglm_search_tool_availability, force=True),
            asyncio.to_thread(_prewarm_git_memory_on_startup),
        )
    else:
        jobs = (
            startup_jobs.run_sync("startup-key-tools-prewarm", Key_Tools.prewarm_key_tool_definitions),
            startup_jobs.run_sync(
                "startup-web-search-prewarm",
                web_search_tool.autoglm_search_tool_availability,
                force=True,
            ),
            startup_jobs.run_sync("startup-git-memory-prewarm", _prewarm_git_memory_on_startup),
        )
    results = await asyncio.gather(*jobs)
    git_state, git_duration_ms = results[2]
    from .services.runtime_scene_service import record_runtime_scene_event

    record_runtime_scene_event(
        "runtime_manager",
        "startup_prewarm",
        "runtime.startup.git_memory_prewarmed",
        message="Git memory was prewarmed before the first chat turn.",
        outcome="completed",
        fields={
            "durationMs": git_duration_ms,
            "totalPrewarmMs": max(0, int((time.perf_counter() - started) * 1000)),
            "available": bool(getattr(git_state, "available", False)),
            "dirty": bool(getattr(git_state, "dirty", False)),
            "headPresent": bool(getattr(git_state, "head_rev", None)),
            "indexedHeadPresent": bool(getattr(git_state, "indexed_head_rev", None)),
        },
        lifecycle=True,
    )
