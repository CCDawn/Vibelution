"""Server-owned one-shot execution evidence for user-approved shell commands.

「审批即证据」（Windows 审批死路修复 Phase 1）：当操作者在审批卡片上显式批准
一条沙箱受控 shell 命令时，审批服务在本进程内的证据登记表签发一条一次性执行
证据；Codex CLI 沙箱门（Windows 原生离线隔离未验证场景）在放行前必须核对并
消费这条证据。

安全性质：
- 证据只存在于服务端内存，从不进入模型可见的工具参数或返回文本。模型与工具层
  没有任何可构造、可重放的凭据字符串——验证是登记表查询，不是字符串比对。
- 一次性：验证成功即消费；同一条证据不能放行第二次执行。
- 绑定：session + turn + 命令哈希三元组必须全部一致，且短 TTL 内有效。
- 命令哈希覆盖规范化（strip）后的完整命令文本（sha256），与沙箱入口的归一化
  完全一致；命令被内容门（危险命令 / 路由拦截）先拦下时证据不被消费。
- 登记失败从不升级授权：查无证据、过期、身份不一致一律维持 fail-closed。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
import time
from typing import Any
from uuid import uuid4

# 批准后命令在同一个 turn 内立即执行；TTL 只需覆盖「批准落账 → 沙箱门核对」
# 的短暂窗口，同时限制凭证被旁路调用方延后重放的窗口。
EXECUTION_EVIDENCE_TTL_SECONDS = 120.0
_MAX_EVIDENCE_RECORDS = 512
# 过期记录的诚实报告宽限期：超过后才物理清理。
_EXPIRED_RETENTION_SECONDS = 300.0


def command_execution_hash(command_text: str) -> str:
    """Hash the exact normalized command text the sandbox gate will see."""

    return sha256(str(command_text or "").strip().encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _ExecutionEvidence:
    evidence_id: str
    session_id: str
    turn_id: str
    call_id: str
    command_hash: str
    recorded_at: float
    expires_at: float


_LOCK = RLock()
_EVIDENCE: dict[str, _ExecutionEvidence] = {}


def _required_identity(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _prune_expired_locked(now: float) -> None:
    # 刚过期的记录保留一个宽限期再清理，让核对方能拿到诚实的 ``expired``
    # 原因（而不是笼统的 ``no_evidence``）；宽限期外的过期记录即时清理。
    stale_ids = [
        evidence_id
        for evidence_id, record in _EVIDENCE.items()
        if record.expires_at + _EXPIRED_RETENTION_SECONDS <= now
    ]
    for evidence_id in stale_ids:
        _EVIDENCE.pop(evidence_id, None)
    if len(_EVIDENCE) <= _MAX_EVIDENCE_RECORDS:
        return
    # 上限兜底：先丢过期记录，再丢最早的记录，保证登记表有界。
    expired_ids = [
        evidence_id
        for evidence_id, record in _EVIDENCE.items()
        if record.expires_at <= now
    ]
    for evidence_id in expired_ids:
        _EVIDENCE.pop(evidence_id, None)
    if len(_EVIDENCE) <= _MAX_EVIDENCE_RECORDS:
        return
    ordered = sorted(_EVIDENCE.values(), key=lambda item: (item.recorded_at, item.evidence_id))
    for record in ordered[: len(_EVIDENCE) - _MAX_EVIDENCE_RECORDS]:
        _EVIDENCE.pop(record.evidence_id, None)


def record_execution_evidence(
    *,
    session_id: str,
    turn_id: str,
    call_id: str = "",
    command_hash: str,
    ttl_seconds: float = EXECUTION_EVIDENCE_TTL_SECONDS,
) -> str:
    """Mint one one-shot execution evidence; returns its evidence id."""

    normalized_session = _required_identity(session_id, "sessionId")
    normalized_turn = _required_identity(turn_id, "turnId")
    normalized_hash = _required_identity(command_hash, "commandHash")
    try:
        ttl = max(0.05, float(ttl_seconds))
    except (TypeError, ValueError):
        ttl = EXECUTION_EVIDENCE_TTL_SECONDS
    evidence_id = f"exec-evidence-{uuid4().hex}"
    now = time.monotonic()
    with _LOCK:
        _prune_expired_locked(now)
        _EVIDENCE[evidence_id] = _ExecutionEvidence(
            evidence_id=evidence_id,
            session_id=normalized_session,
            turn_id=normalized_turn,
            call_id=str(call_id or "").strip(),
            command_hash=normalized_hash,
            recorded_at=now,
            expires_at=now + ttl,
        )
    return evidence_id


def verify_and_consume_execution_evidence(
    *,
    session_id: str,
    turn_id: str,
    command_hash: str,
) -> tuple[bool, str]:
    """Consume the matching evidence; ``(False, reason)`` keeps the gate closed.

    Reasons: ``no_evidence`` / ``expired`` / ``session_mismatch`` /
    ``turn_mismatch``. Only a full session + turn + command-hash match inside
    TTL consumes the record and allows exactly one execution.
    """

    normalized_session = _required_identity(session_id, "sessionId")
    normalized_turn = _required_identity(turn_id, "turnId")
    normalized_hash = _required_identity(command_hash, "commandHash")
    now = time.monotonic()
    with _LOCK:
        _prune_expired_locked(now)
        session_matched: _ExecutionEvidence | None = None
        full_matched: _ExecutionEvidence | None = None
        for record in _EVIDENCE.values():
            if record.session_id != normalized_session or record.command_hash != normalized_hash:
                continue
            session_matched = record
            if record.turn_id == normalized_turn:
                full_matched = record
                break
        if full_matched is not None:
            if full_matched.expires_at <= now:
                _EVIDENCE.pop(full_matched.evidence_id, None)
                return False, "expired"
            _EVIDENCE.pop(full_matched.evidence_id, None)
            return True, "consumed"
        if session_matched is not None:
            if session_matched.expires_at <= now:
                _EVIDENCE.pop(session_matched.evidence_id, None)
                return False, "expired"
            return False, "turn_mismatch"
        return False, "no_evidence"


def peek_execution_evidence(
    *,
    session_id: str,
    turn_id: str,
    command_hash: str,
) -> dict[str, Any]:
    """Diagnostics-only projection; never consumes or affects authorization."""

    normalized_session = str(session_id or "").strip()
    normalized_turn = str(turn_id or "").strip()
    normalized_hash = str(command_hash or "").strip()
    now = time.monotonic()
    with _LOCK:
        for record in _EVIDENCE.values():
            if (
                record.session_id == normalized_session
                and record.turn_id == normalized_turn
                and record.command_hash == normalized_hash
            ):
                return {
                    "evidenceId": record.evidence_id,
                    "sessionId": record.session_id,
                    "turnId": record.turn_id,
                    "callId": record.call_id,
                    "commandHash": record.command_hash,
                    "expired": record.expires_at <= now,
                    "remainingSeconds": max(0.0, record.expires_at - now),
                }
    return {}


def reset_execution_evidence_state() -> None:
    """Clear the in-memory evidence registry (tests and state resets)."""

    with _LOCK:
        _EVIDENCE.clear()
