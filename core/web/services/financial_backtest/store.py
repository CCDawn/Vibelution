"""Owner-scoped durable storage for frozen AI backtest previews and runs."""

from __future__ import annotations

import copy
import json
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.financial_backtest.contract import (
    MAX_RESULT_CHARS,
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    FinancialBacktestStoreError,
)
from core.web.services.financial_team import runs as financial_runs

_SCHEMA_VERSION = 1


class FinancialBacktestStore:
    """Per-Agent storage with atomic writes and cross-process RMW locks.

    Snapshots are content addressed, previews are short-lived references, and
    each run has its own JSON file. No model prompt or raw model response is
    stored; the run file contains only structured decision evidence.
    """

    def __init__(self, *, path_resolver: Callable[[str], str | Path] | None = None) -> None:
        self._path_resolver = path_resolver
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def root_for(self, agent_id: str, *, create: bool = False) -> Path:
        owner_id = str(agent_id or "").strip()
        if not owner_id:
            raise FinancialBacktestNotFound("炒股智能体不存在")
        if self._path_resolver is not None:
            root = Path(self._path_resolver(owner_id)).resolve()
        else:
            # financial_team owns the private workspace resolution and path
            # escape checks. This sibling directory stores no team transcript.
            run_root = financial_runs._run_root(owner_id, create=create)
            owner_root = run_root.parent.resolve()
            root = (owner_root / "ai-backtests").resolve()
            try:
                root.relative_to(owner_root)
            except ValueError as exc:
                raise FinancialBacktestStoreError("回测存储路径超出智能体私有工作区") from exc
        # Instance/Agent territory plus a content hash exceeds MAX_PATH on
        # Windows. Extend filesystem paths after the ordinary containment check;
        # this also protects transaction sidecars and atomic-write temp files.
        if os.name == "nt" and not str(root).startswith("\\\\?\\"):
            raw = str(root)
            root = Path("\\\\?\\UNC\\" + raw[2:] if raw.startswith("\\\\") else "\\\\?\\" + raw)
        if create:
            for name in ("snapshots", "previews", "runs"):
                (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def save_snapshot(self, agent_id: str, snapshot: Mapping[str, Any]) -> str:
        data_hash = str(snapshot.get("dataHash") or "").strip()
        if len(data_hash) != 64 or any(char not in "0123456789abcdef" for char in data_hash):
            raise FinancialBacktestStoreError("历史行情快照摘要无效")
        path = self.root_for(agent_id, create=True) / "snapshots" / f"{data_hash}.json"
        lock = self._lock_for(path)
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            if path.exists():
                current = self._read(path, "行情快照")
                if str(current.get("dataHash") or "") != data_hash:
                    raise FinancialBacktestStoreError("已冻结行情快照与摘要不匹配")
                return data_hash
            self._write(path, dict(snapshot), "行情快照")
        return data_hash

    def load_snapshot(self, agent_id: str, data_hash: str) -> dict[str, Any]:
        canonical = str(data_hash or "").strip()
        if len(canonical) != 64 or any(char not in "0123456789abcdef" for char in canonical):
            raise FinancialBacktestNotFound("回测历史行情不存在")
        path = self.root_for(agent_id) / "snapshots" / f"{canonical}.json"
        snapshot = self._read(path, "回测历史行情")
        if str(snapshot.get("dataHash") or "") != canonical:
            raise FinancialBacktestStoreError("回测历史行情摘要校验失败")
        try:
            from core.web.services.financial_backtest.runtime import _restore_snapshot

            _restore_snapshot(snapshot)
        except FinancialBacktestNotFound:
            raise
        except Exception as exc:
            raise FinancialBacktestStoreError("回测历史行情内容校验失败") from exc
        return snapshot

    def save_preview(self, agent_id: str, preview: Mapping[str, Any]) -> dict[str, Any]:
        owner_id = str(agent_id or "").strip()
        preview_id = _uuid(str(preview.get("previewId") or ""), "预览标识")
        if str(preview.get("agentId") or "") != owner_id:
            raise FinancialBacktestStoreError("预览归属与智能体不匹配")
        path = self.root_for(owner_id, create=True) / "previews" / f"{preview_id}.json"
        lock = self._lock_for(path)
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            if path.exists():
                raise FinancialBacktestConflict("回测预览标识已存在")
            self._write(path, dict(preview), "回测预览")
        return copy.deepcopy(dict(preview))

    def load_preview(self, agent_id: str, preview_id: str) -> dict[str, Any]:
        owner_id = str(agent_id or "").strip()
        normalized = _uuid(preview_id, "预览标识")
        path = self.root_for(owner_id) / "previews" / f"{normalized}.json"
        payload = self._read(path, "回测预览")
        if str(payload.get("previewId") or "") != normalized or str(payload.get("agentId") or "") != owner_id:
            raise FinancialBacktestNotFound("回测预览不存在")
        return payload

    def create_run_if_absent(
        self,
        agent_id: str,
        run: Mapping[str, Any],
        *,
        max_runs: int,
    ) -> tuple[dict[str, Any], bool]:
        owner_id = str(agent_id or "").strip()
        run_id = _uuid(str(run.get("runId") or ""), "回测标识")
        if str(run.get("agentId") or "") != owner_id:
            raise FinancialBacktestStoreError("回测任务归属与智能体不匹配")
        path = self.root_for(owner_id, create=True) / "runs" / f"{run_id}.json"
        lock = self._lock_for(path)
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            if path.exists():
                current = self._read(path, "回测任务")
                if (
                    str(current.get("clientRequestId") or "") != str(run.get("clientRequestId") or "")
                    or str(current.get("requestHash") or "") != str(run.get("requestHash") or "")
                ):
                    raise FinancialBacktestConflict("clientRequestId已用于不同的回测请求")
                return current, False
            count = sum(1 for _ in (path.parent).glob("*.json"))
            if count >= max_runs:
                raise FinancialBacktestConflict(f"该智能体已保存{max_runs}次回测，请先导出并清理历史记录")
            self._write(path, dict(run), "回测任务")
            return copy.deepcopy(dict(run)), True

    def load_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        owner_id = str(agent_id or "").strip()
        normalized = _uuid(run_id, "回测标识")
        path = self.root_for(owner_id) / "runs" / f"{normalized}.json"
        payload = self._read(path, "回测任务")
        if str(payload.get("runId") or "") != normalized or str(payload.get("agentId") or "") != owner_id:
            raise FinancialBacktestNotFound("回测任务不存在")
        return payload

    def update_run(
        self,
        agent_id: str,
        run_id: str,
        mutator: Callable[[dict[str, Any]], Any],
    ) -> tuple[dict[str, Any], Any]:
        owner_id = str(agent_id or "").strip()
        normalized = _uuid(run_id, "回测标识")
        path = self.root_for(owner_id) / "runs" / f"{normalized}.json"
        lock = self._lock_for(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            state = self._read(path, "回测任务")
            if str(state.get("runId") or "") != normalized or str(state.get("agentId") or "") != owner_id:
                raise FinancialBacktestNotFound("回测任务不存在")
            result = mutator(state)
            state["updatedAt"] = _now_iso()
            self._write(path, state, "回测任务")
            return copy.deepcopy(state), result

    def list_runs(self, agent_id: str) -> list[dict[str, Any]]:
        root = self.root_for(agent_id)
        directory = root / "runs"
        if not directory.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            paths = list(directory.glob("*.json"))
        except OSError as exc:
            raise FinancialBacktestStoreError("回测历史目录无法读取") from exc
        for path in paths:
            if path.name.endswith(".transaction.lock"):
                continue
            try:
                payload = self._read(path, "回测任务")
                if str(payload.get("agentId") or "") == str(agent_id or ""):
                    rows.append(payload)
            except FinancialBacktestNotFound:
                continue
        rows.sort(key=lambda item: (str(item.get("createdAt") or ""), str(item.get("runId") or "")), reverse=True)
        return rows

    def acquire_runner_lease(
        self,
        agent_id: str,
        *,
        run_id: str,
        worker_id: str,
        now_epoch: float,
        lease_seconds: float,
    ) -> bool:
        path = self.root_for(agent_id, create=True) / "runner-lease.json"
        lock = self._lock_for(path)
        acquired = False
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            current = self._read_optional(path)
            if isinstance(current, dict):
                try:
                    expires = float(current.get("expiresAtEpoch") or 0)
                except (TypeError, ValueError):
                    expires = 0.0
                same_owner = str(current.get("workerId") or "") == worker_id and str(current.get("runId") or "") == run_id
                if expires > now_epoch and not same_owner:
                    return False
            self._write(
                path,
                {
                    "schemaVersion": _SCHEMA_VERSION,
                    "agentId": str(agent_id),
                    "runId": run_id,
                    "workerId": worker_id,
                    "expiresAtEpoch": now_epoch + max(30.0, float(lease_seconds)),
                },
                "运行租约",
            )
            acquired = True
        return acquired

    def release_runner_lease(self, agent_id: str, *, run_id: str, worker_id: str) -> None:
        path = self.root_for(agent_id, create=True) / "runner-lease.json"
        lock = self._lock_for(path)
        with lock, cross_process_file_lock(path, lock_path=self._lock_path(path), timeout=30.0):
            current = self._read_optional(path)
            if (
                isinstance(current, dict)
                and str(current.get("agentId") or "") == str(agent_id)
                and str(current.get("runId") or "") == run_id
                and str(current.get("workerId") or "") == worker_id
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    raise FinancialBacktestStoreError("回测运行租约无法释放") from exc

    def _read(self, path: Path, label: str) -> dict[str, Any]:
        if not path.exists():
            raise FinancialBacktestNotFound(f"{label}不存在")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FinancialBacktestStoreError(f"{label}无法安全读取，未覆盖现有数据") from exc
        if not isinstance(payload, dict):
            raise FinancialBacktestStoreError(f"{label}格式无效，未覆盖现有数据")
        if int(payload.get("schemaVersion") or 0) != _SCHEMA_VERSION:
            raise FinancialBacktestStoreError(f"{label}版本不受支持，未覆盖现有数据")
        return payload

    def _read_optional(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return self._read(path, "运行租约")

    def _write(self, path: Path, payload: Mapping[str, Any], label: str) -> None:
        output = dict(payload)
        output["schemaVersion"] = _SCHEMA_VERSION
        try:
            encoded = json.dumps(output, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise FinancialBacktestStoreError(f"{label}含有无法保存的字段") from exc
        if len(encoded) > MAX_RESULT_CHARS:
            raise FinancialBacktestStoreError(f"{label}超过安全存储大小限制")
        try:
            atomic_write_json(
                path,
                output,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                strict_replace=True,
                retry_timeout_seconds=5.0,
            )
        except OSError as exc:
            raise FinancialBacktestStoreError(f"{label}无法安全保存") from exc

    def _lock_for(self, path: Path) -> threading.RLock:
        key = str(path)
        with self._guard:
            return self._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _lock_path(path: Path) -> Path:
        return path.with_name(path.name + ".transaction.lock")


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialBacktestNotFound(f"{label}不存在") from exc


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


_DEFAULT_STORE = FinancialBacktestStore()


def default_store() -> FinancialBacktestStore:
    return _DEFAULT_STORE


__all__ = ["FinancialBacktestStore", "default_store"]
