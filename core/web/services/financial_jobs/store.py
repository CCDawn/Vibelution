"""Cross-process-safe Agent-private schedule and occurrence storage."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.financial_team import runs as financial_runs

from .errors import FinancialJobNotFoundError, FinancialJobStoreError

SCHEMA_VERSION = 1
SCHEDULES_FILENAME = "financial-research-jobs.json"


def new_state(assistant_agent_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "assistantAgentId": str(assistant_agent_id or "").strip(),
        "schedules": {},
        "runnerLease": None,
    }


class FinancialResearchJobStore:
    """Persist plans in the financial assistant's private artifacts directory.

    Read-modify-write operations hold both a process lock and the shared
    sidecar lock for the entire transaction. A missing file is an in-memory
    empty projection until an explicit create/update operation writes it.
    """

    def __init__(
        self,
        *,
        path_resolver: Callable[[str], str | Path] | None = None,
    ) -> None:
        self._path_resolver = path_resolver
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def path_for(self, assistant_agent_id: str) -> Path:
        owner_id = str(assistant_agent_id or "").strip()
        if not owner_id:
            raise FinancialJobNotFoundError("金融助手不存在")
        if self._path_resolver is not None:
            return Path(self._path_resolver(owner_id)).resolve()
        # Reuse financial-team's owner and private-workspace boundary checks.
        # The sibling jobs file stays beside, not inside, the run transcript
        # registry and stores only schedules, occurrences, and native IDs.
        return (financial_runs._run_root(owner_id).parent / SCHEDULES_FILENAME).resolve()

    def load(self, assistant_agent_id: str) -> dict[str, Any]:
        owner_id = str(assistant_agent_id or "").strip()
        path = self.path_for(owner_id)
        if not path.exists():
            return new_state(owner_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinancialJobStoreError("研究计划无法安全读取，未覆盖现有数据") from exc
        return _normalize_state(payload, owner_id)

    def update(
        self,
        assistant_agent_id: str,
        mutator: Callable[[dict[str, Any]], Any],
    ) -> tuple[dict[str, Any], Any]:
        owner_id = str(assistant_agent_id or "").strip()
        path = self.path_for(owner_id)
        lock = self._lock_for(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock, cross_process_file_lock(
            path,
            lock_path=path.with_name(path.name + ".transaction.lock"),
            timeout=30.0,
        ):
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise FinancialJobStoreError(
                        "研究计划无法安全读取，未覆盖现有数据"
                    ) from exc
                state = _normalize_state(current, owner_id)
            else:
                state = new_state(owner_id)
            result = mutator(state)
            normalized = _normalize_state(state, owner_id)
            atomic_write_json(
                path,
                normalized,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                strict_replace=True,
                retry_timeout_seconds=5.0,
            )
            return _copy(normalized), result

    def acquire_runner_lease(
        self,
        assistant_agent_id: str,
        *,
        batch_id: str,
        worker_id: str,
        now_epoch: float,
        lease_seconds: float,
    ) -> bool:
        acquired = False

        def _mutate(state: dict[str, Any]) -> None:
            nonlocal acquired
            current = state.get("runnerLease")
            if isinstance(current, dict):
                current_worker = str(current.get("workerId") or "")
                current_batch = str(current.get("batchId") or "")
                try:
                    expires = float(current.get("expiresAtEpoch") or 0)
                except (TypeError, ValueError):
                    expires = 0
                if expires > now_epoch and (current_worker, current_batch) != (worker_id, batch_id):
                    return
            state["runnerLease"] = {
                "workerId": worker_id,
                "batchId": batch_id,
                "expiresAtEpoch": now_epoch + max(5.0, float(lease_seconds)),
            }
            acquired = True

        self.update(assistant_agent_id, _mutate)
        return acquired

    def release_runner_lease(
        self, assistant_agent_id: str, *, batch_id: str, worker_id: str
    ) -> None:
        def _mutate(state: dict[str, Any]) -> None:
            current = state.get("runnerLease")
            if (
                isinstance(current, dict)
                and str(current.get("batchId") or "") == batch_id
                and str(current.get("workerId") or "") == worker_id
            ):
                state["runnerLease"] = None

        self.update(assistant_agent_id, _mutate)

    def _lock_for(self, path: Path) -> threading.RLock:
        key = str(path)
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())


def _normalize_state(payload: Any, assistant_agent_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FinancialJobStoreError("研究计划格式无效，未覆盖现有数据")
    try:
        version = int(payload.get("schemaVersion") or 0)
    except (TypeError, ValueError) as exc:
        raise FinancialJobStoreError("研究计划版本无效，未覆盖现有数据") from exc
    if version != SCHEMA_VERSION:
        raise FinancialJobStoreError("研究计划版本不受支持，未覆盖现有数据")
    if str(payload.get("assistantAgentId") or "").strip() != assistant_agent_id:
        raise FinancialJobStoreError("研究计划归属不匹配，未覆盖现有数据")
    raw_schedules = payload.get("schedules")
    if not isinstance(raw_schedules, dict):
        raise FinancialJobStoreError("研究计划列表格式无效，未覆盖现有数据")
    schedules: dict[str, dict[str, Any]] = {}
    for schedule_id, raw in raw_schedules.items():
        if not isinstance(schedule_id, str) or not isinstance(raw, dict):
            raise FinancialJobStoreError("研究计划条目格式无效，未覆盖现有数据")
        if (
            str(raw.get("scheduleId") or "").strip() != schedule_id
            or str(raw.get("assistantAgentId") or "").strip() != assistant_agent_id
            or not isinstance(raw.get("execution"), dict)
            or not isinstance(raw.get("symbols"), list)
        ):
            raise FinancialJobStoreError("研究计划身份或字段无效，未覆盖现有数据")
        schedules[schedule_id] = _copy(raw)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "assistantAgentId": assistant_agent_id,
        "schedules": schedules,
        "runnerLease": _copy(payload.get("runnerLease"))
        if isinstance(payload.get("runnerLease"), dict)
        else None,
    }


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


_STORE = FinancialResearchJobStore()


def default_store() -> FinancialResearchJobStore:
    return _STORE


__all__ = [
    "SCHEDULES_FILENAME",
    "SCHEMA_VERSION",
    "FinancialResearchJobStore",
    "default_store",
    "new_state",
]
