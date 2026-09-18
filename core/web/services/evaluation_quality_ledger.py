# -*- coding: utf-8 -*-
"""Evaluation-quality snapshot ledgers (append-only accumulation).

两条「评估器的评估」数据管道的快照台账：监督链评审质量面板在每轮监督
run 终态后追加一条紧凑快照；假说链评审者诊断奖励报告在每次构建且内容
变化时追加一条。台账用于跨时间积累与防丢失（run 存储被清理后仍可复算
趋势），不替代按需全量报告。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _ledger_path(name: str) -> Path:
    return developer_sandbox.sandboxed_workspace_path(
        _PROJECT_ROOT, "evaluation", name, "ledger.jsonl"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_quality_ledger(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Append one snapshot record to ``evaluation/<name>/ledger.jsonl``.

    记录自动加盖 ``capturedAt`` 与内容指纹 ``contentSha256``（指纹只对
    payload 本身计算，不含时间戳），失败抛错由调用方决定吞或报。
    """
    path = _ledger_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        **payload,
        "capturedAt": _now_iso(),
        "contentSha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest(),
    }
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return {"path": str(path), "contentSha256": record["contentSha256"]}


def read_quality_ledger(name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Read the most recent ledger records (oldest-first within the window)."""
    path = _ledger_path(name)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def latest_quality_ledger_fingerprint(name: str) -> str:
    """Return the newest record's content fingerprint ("" when empty)."""
    records = read_quality_ledger(name, limit=1)
    return str(records[-1].get("contentSha256") or "") if records else ""


def append_quality_ledger_if_changed(
    name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Append only when the payload fingerprint differs from the newest record."""
    fingerprint = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    if fingerprint == latest_quality_ledger_fingerprint(name):
        return {"skipped": True, "reason": "unchanged", "contentSha256": fingerprint}
    return append_quality_ledger(name, payload)


__all__ = [
    "append_quality_ledger",
    "append_quality_ledger_if_changed",
    "latest_quality_ledger_fingerprint",
    "read_quality_ledger",
]
