"""One owned, lifecycle-bound reconciliation loop; no request-side dispatch."""
from __future__ import annotations

import threading

from core.infrastructure.owned_executor import OwnedThreadPoolExecutor
from core.logging import debug as logger
from core.web.services.team import team_store

from . import service, store

_EXECUTOR = OwnedThreadPoolExecutor(max_workers=1, thread_name_prefix="generic-team-workflow")
_LOCK = threading.RLock()
_STOP = threading.Event()
_WAKE = threading.Event()
_FUTURE = None
# Lifecycle opens this only after the canonical Session startup sweep settles.
_ADMITTING = False


def reconcile_all() -> None:
    index = team_store._load_index()
    for team in index.get("teams", []):
        if _STOP.is_set():
            return
        team_id = str(team.get("teamId") or "")
        try:
            folder = store.root(team_id) / "runs"
            for path in folder.glob("*.json"):
                if _STOP.is_set():
                    return
                try:
                    target = store.path(team_id, "runs", path.stem)
                    if store.read(target).get("status") == "running":
                        service.reconcile_run(team_id, path.stem)
                except Exception as exc:
                    logger.warning(f"Generic workflow recovery skipped a run ({type(exc).__name__})")
        except Exception as exc:
            logger.warning(f"Generic workflow recovery skipped a team ({type(exc).__name__})")


def _loop() -> None:
    while not _STOP.is_set():
        try:
            reconcile_all()
        except Exception as exc:
            logger.warning(f"Generic workflow reconciliation failed ({type(exc).__name__})")
        _WAKE.wait(0.5)
        _WAKE.clear()


def ensure_admission() -> None:
    with _LOCK:
        if not _ADMITTING:
            raise store.Conflict("流程执行器尚未就绪，请稍后重试。")


def stopping() -> bool:
    return _STOP.is_set()


def wake() -> None:
    global _FUTURE
    with _LOCK:
        if not _ADMITTING:
            return  # Already accepted records resume after the next lifespan.
        if _FUTURE is None or _FUTURE.done():
            _FUTURE = _EXECUTOR.submit(_loop)
        _WAKE.set()


def begin_generic_workflow_lifecycle(*, should_stop=None) -> dict:
    global _ADMITTING
    with _LOCK:
        # The lifespan may have retired while its startup callback was waiting
        # to run. Share the admission lock with shutdown to fence that callback.
        if should_stop is not None and should_stop():
            return {"opened": False, "skipped": "lifespan_stopping"}
        result = _EXECUTOR.begin()
        if result.get("opened"):
            _ADMITTING = True
            _STOP.clear()
            wake()
        return result


def shutdown_generic_workflow_executor(*, deadline: float) -> dict:
    global _ADMITTING
    with _LOCK:
        _ADMITTING = False
        _STOP.set()
        _WAKE.set()
    return _EXECUTOR.shutdown_until(deadline)
