"""Durable owner-scoped records for A-share walk-forward workflows."""

from __future__ import annotations

import copy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import UUID

from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.financial_backtest.contract import (
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    FinancialBacktestStoreError,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore, default_store

_DIRECTORY_NAME = "walk-forward"


class WalkForwardWorkflowCommitError(FinancialBacktestStoreError):
    """A workflow transition could not be durably committed and can be retried.

    Child runs are persisted independently, so callers must reconcile their
    deterministic request IDs before attempting to create another child.
    """


class WalkForwardStore:
    """A narrow workflow ledger backed by the existing per-Agent backtest store."""

    def __init__(self, backtest_store: FinancialBacktestStore | None = None) -> None:
        self._backtests = backtest_store or default_store()

    def create(self, agent_id: str, workflow: Mapping[str, Any]) -> dict[str, Any]:
        owner_id = str(agent_id or "").strip()
        workflow_id = _workflow_uuid(workflow.get("workflowId"))
        if not owner_id or str(workflow.get("agentId") or "") != owner_id:
            raise FinancialBacktestStoreError("滚动验证工作流归属与智能体不匹配")
        path = self._path(owner_id, workflow_id, create=True)
        lock = self._backtests._lock_for(path)
        with lock, cross_process_file_lock(
            path,
            lock_path=self._backtests._lock_path(path),
            timeout=30.0,
        ):
            if path.exists():
                raise FinancialBacktestConflict("滚动验证工作流标识已存在")
            self._backtests._write(path, dict(workflow), "滚动验证工作流")
        return copy.deepcopy(dict(workflow))

    def load(self, agent_id: str, workflow_id: str) -> dict[str, Any]:
        owner_id = str(agent_id or "").strip()
        normalized_id = _workflow_uuid(workflow_id)
        record = self._backtests._read(
            self._path(owner_id, normalized_id), "滚动验证工作流"
        )
        if (
            str(record.get("workflowId") or "") != normalized_id
            or str(record.get("agentId") or "") != owner_id
        ):
            raise FinancialBacktestNotFound("滚动验证工作流不存在")
        return record

    def list(self, agent_id: str) -> list[dict[str, Any]]:
        owner_id = str(agent_id or "").strip()
        directory = self._directory(owner_id)
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in directory.glob("*.json"):
            record = self._backtests._read(path, "滚动验证工作流")
            if str(record.get("agentId") or "") == owner_id:
                records.append(record)
        records.sort(
            key=lambda row: (str(row.get("createdAt") or ""), str(row.get("workflowId") or "")),
            reverse=True,
        )
        return records

    @contextmanager
    def locked(self, agent_id: str, workflow_id: str) -> Iterator[dict[str, Any]]:
        """Hold one workflow lock over read/transition/write and child creation.

        Callers may create an ordinary child run while holding this lock. A stop
        request then waits for that short local operation and sees the persisted
        child id, so it cannot race a child start and accidentally launch another.
        """
        owner_id = str(agent_id or "").strip()
        normalized_id = _workflow_uuid(workflow_id)
        path = self._path(owner_id, normalized_id)
        lock = self._backtests._lock_for(path)
        with lock, cross_process_file_lock(
            path,
            lock_path=self._backtests._lock_path(path),
            timeout=30.0,
        ):
            record = self._backtests._read(path, "滚动验证工作流")
            if (
                str(record.get("workflowId") or "") != normalized_id
                or str(record.get("agentId") or "") != owner_id
            ):
                raise FinancialBacktestNotFound("滚动验证工作流不存在")
            previous = copy.deepcopy(record)
            yield record
            if record != previous:
                try:
                    self._backtests._write(path, record, "滚动验证工作流")
                except Exception as exc:
                    raise WalkForwardWorkflowCommitError(
                        "滚动验证工作流暂时无法保存；后续推进会按冻结幂等标识恢复"
                    ) from exc

    def _path(self, agent_id: str, workflow_id: str, *, create: bool = False) -> Path:
        owner_id = str(agent_id or "").strip()
        if not owner_id:
            raise FinancialBacktestNotFound("炒股智能体不存在")
        directory = self._directory(owner_id, create=create)
        return directory / f"{_workflow_uuid(workflow_id)}.json"

    def _directory(self, agent_id: str, *, create: bool = False) -> Path:
        root = self._backtests.root_for(agent_id, create=create)
        directory = root / _DIRECTORY_NAME
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory


def _workflow_uuid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialBacktestNotFound("滚动验证工作流不存在") from exc


__all__ = ["WalkForwardStore", "WalkForwardWorkflowCommitError"]
