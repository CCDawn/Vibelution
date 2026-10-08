"""Bounded proposal artifacts in the existing paper account's private territory."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.financial_paper import ledger

from .risk import RebalanceConflict, RebalanceError, RebalanceNotFound


def identifier(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RebalanceError("调仓请求标识必须是UUID") from exc


def root(agent_id: str) -> Path:
    return ledger._ledger_path(ledger._financial_agent(agent_id)).parent / "proposals"


def path_for(agent_id: str, proposal_id: str) -> Path:
    return root(agent_id) / f"{identifier(proposal_id)}.json"


@contextmanager
def lock(agent_id: str, proposal_id: str):
    path = path_for(agent_id, proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with cross_process_file_lock(path, lock_path=path.with_suffix(".lock"), timeout=20):
        yield


def read(agent_id: str, proposal_id: str) -> dict:
    path = path_for(agent_id, proposal_id)
    if not path.exists():
        raise RebalanceNotFound("组合建议不存在")
    if path.stat().st_size > 512_000:
        raise RebalanceConflict("组合建议文件超过大小限制")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RebalanceConflict("组合建议文件无法读取") from exc
    if not isinstance(payload, dict) or payload.get("agentId") != agent_id or payload.get("proposalId") != identifier(proposal_id):
        raise RebalanceConflict("组合建议归属不匹配")
    return payload


def write(agent_id: str, payload: dict) -> None:
    path = path_for(agent_id, payload["proposalId"])
    if payload.get("agentId") != agent_id:
        raise RebalanceConflict("组合建议归属不匹配")
    if not path.exists() and sum(1 for _ in path.parent.glob("*.json")) >= 200:
        raise RebalanceConflict("该模拟账户已保存200份建议，请使用已有建议")
    atomic_write_json(path, payload, ensure_ascii=False, sort_keys=True, strict_replace=True)


def list_items(agent_id: str) -> list[dict]:
    folder = root(agent_id)
    if not folder.exists():
        return []
    paths = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:50]
    return [read(agent_id, path.stem) for path in paths]
