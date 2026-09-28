"""JSONL ledger, scope lock and errors for the hypothesis-first chain.

Owning surface for durable chain records. Command, meeting and auto-advance
orchestration stay in ``hypothesis_first_chain``. Public imports remain on
that facade.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

_LOCK = threading.RLock()

def _record_scene_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any] | None = None,
    level: str = "info",
) -> None:
    """Best-effort observability event; diagnostics never break the chain."""
    from core.web.services.runtime_scene_service import (
        record_runtime_scene_event_quietly,
    )

    record_runtime_scene_event_quietly(
        "team_workflow_orchestration",
        "hypothesis_first_chain",
        event_code,
        level=level,
        outcome=outcome,
        fields=fields or {},
    )

class HypothesisFirstChainError(RuntimeError):
    """Base error for hypothesis-first chain orchestration."""

class StageOneCandidateScreeningError(HypothesisFirstChainError):
    """Formal R1 screening cannot produce two mechanism-distinct finalists."""

    code = "diversity_collapse"

    def __init__(self, message: str = "diversity_collapse", *, artifact_ref: str = ""):
        self.artifact_ref = str(artifact_ref or "")
        super().__init__(message)

class HypothesisFirstChainNotFoundError(HypothesisFirstChainError):
    """Raised when a chain record (collection request / link) does not exist."""

class StaleDigestError(HypothesisFirstChainError):
    """Raised when approve-digest receives a stale digest content hash."""

    def __init__(self, message: str, *, expected: str = "", actual: str = ""):
        super().__init__(message)
        self.code = "stale_digest"
        self.expected = expected
        self.actual = actual

class StateVersionConflictError(HypothesisFirstChainError):
    """Raised when a V2 command was issued against an obsolete snapshot."""

    code = "state_version_conflict"
    status_code = 409

    def __init__(self, *, expected: str, actual: str, snapshot_path: str = "") -> None:
        super().__init__(
            "流程状态已更新，请刷新当前题目后重新确认。"
        )
        self.expected = expected
        self.actual = actual
        self.snapshot_path = snapshot_path

class IdempotencyConflictError(HypothesisFirstChainError):
    """Raised when one V2 selection key is reused for different input."""

    code = "idempotency_conflict"
    status_code = 409

    def __init__(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        expected_input_digest: str,
        actual_input_digest: str,
    ) -> None:
        super().__init__(
            "idempotencyKey 已绑定到不同的选择输入，不能复用。"
        )
        self.action_id = action_id
        self.idempotency_key = idempotency_key
        self.expected_input_digest = expected_input_digest
        self.actual_input_digest = actual_input_digest
        self.expected = expected_input_digest
        self.actual = actual_input_digest

class CommandAttemptInProgressError(HypothesisFirstChainError):
    """Another long command is still executing in the background.

    With the async command window, a second distinct command for the same
    question can no longer queue behind a 60-150s mutation on the HTTP
    thread; it is rejected immediately with a stable 409 code so the client
    can wait for the running attempt (or its own poll) instead of hanging.
    """

    code = "command_attempt_in_progress"
    status_code = 409

    def __init__(self, *, question_id: str, command: str, action_id: str) -> None:
        super().__init__(
            "上一条命令仍在后台执行，请等待其完成后再提交新命令。"
        )
        self.question_id = str(question_id or "")
        self.command = str(command or "")
        self.action_id = str(action_id or "")

class FormalCommandRejectedError(HypothesisFirstChainError):
    """A formal runtime command was rejected with a stable client-facing reason.

    Preserves the structured error contract already exposed by the formal
    runtime command route (``code`` plus optional readiness ``blockers``) so
    UI surfaces can render an actionable rejection instead of a flattened
    message string.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.blockers = [dict(item) for item in blockers or []]

class StageOneContextBlockedError(FormalCommandRejectedError):
    """A stage-one R1 launch was rejected because its grounded context is blocked.

    Opening the meeting with a FORMAL authority and an empty evidence
    whitelist would strand every speaker turn on the REFS rules, so the
    launch fails before any meeting opens.  The blocker names the exact
    blocked context code (for example ``knowledge_package_has_no_evidence_claims``)
    so the UI can explain what is still missing.
    """

    def __init__(self, context: Mapping[str, Any]) -> None:
        blocked_code = str(context.get("code") or "stage_one_context_blocked")
        message = _STAGE_ONE_BLOCKED_MESSAGES.get(
            blocked_code, "第一阶段接地生成上下文未就绪"
        )
        super().__init__(
            message,
            code="stage_one_context_blocked",
            status_code=409,
            blockers=[
                {
                    "code": blocked_code,
                    "message": message,
                }
            ],
        )
        self.blockedContextCode = blocked_code

_STAGE_ONE_BLOCKED_MESSAGES = {
    "workflow_run_not_found": "第一阶段运行不存在或已不可读，无法开启接地生成",
    "workflow_snapshot_invalid": "第一阶段运行的冻结输入不可读，无法开启接地生成",
    "stage_one_policy_invalid": "第一阶段完成策略不是当前跟踪版本，无法开启接地生成",
    "workflow_scope_mismatch": "运行不属于当前团队或赛题，无法开启接地生成",
    "knowledge_package_has_no_evidence_claims": (
        "知识包没有可引用的证据主张；请先补齐并批准证据后再开启接地生成"
    ),
}

class ClaimBeliefGateBlockedError(FormalCommandRejectedError):
    """A formal selection authority was blocked by the claim belief hard gate.

    R2.2 fail-closed semantics: a hypothesis whose core claims are
    ``contradicted``/``disputed`` — or whose claim data is missing or
    unreadable, so the five-state belief table cannot be evaluated — must
    never be advanced onto the formal path.  The structured ``blockers`` carry
    ``claimId`` and ``beliefState`` so the operator can repair the claim
    ledger (supersede/retract, evidence re-review) and retry the same
    decision; nothing is silently waived.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        question_id: str,
        candidate_id: str = "",
        blockers: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="claim_belief_gate_blocked",
            status_code=422,
            blockers=blockers,
        )
        self.stage = stage
        self.question_id = question_id
        self.candidate_id = candidate_id

def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")

def _storage_path(team_id: str) -> Path:
    from . import hypothesis_first_chain as chain

    root = developer_sandbox.seeded_sandbox_workspace_path(
        chain._project_root(),
        "teams",
        _safe_team_id(team_id),
    )
    return root / "research_workflow" / "hypothesis_first_chain.jsonl"

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_cached

    # The shared stat-validated cache replaces this module's private
    # mtime/size records cache; the write primitives invalidate it eagerly.
    return read_jsonl_cached(path)

def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)

def _latest_by_id(
    records: list[dict[str, Any]], field: str, record_id: str
) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None

def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]

def _rewrite_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Replace one JSONL ledger atomically after a scoped reset has been checked."""
    from .atomic_fs import atomic_write_text

    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    atomic_write_text(path, payload)
    from core.web.services.team_workflow.storage_durability import (
        _invalidate_read_cache,
    )

    _invalidate_read_cache(path)

def _latest_records(records: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = str(record.get(field) or "").strip()
        if record_id:
            latest[record_id] = record
    return latest

def _records(team_id: str) -> list[dict[str, Any]]:
    """Parsed chain ledger for one team (memoized on file mtime + size)."""
    from . import hypothesis_first_chain as chain

    with _LOCK:
        return _read_jsonl(chain._storage_path(team_id))

@contextmanager
def hypothesis_first_scope_lock(team_id: str, question_id: str):
    """Serialize one question command across all V2 command workers.

    The V2 state is a coarse cross-surface CAS.  The JSONL services already
    serialize their individual appends across processes, but that is not wide
    enough for the command's read/re-authorize/side-effect sequence: two
    backend workers could both validate the same state version before either
    owning mutation became visible.  The separate scope lock closes that
    window for every V2 command, including the delivery retry whose expensive
    orchestration must happen after the claim and before the terminal event.

    This intentionally uses a lock file distinct from the chain JSONL lock.
    Command handlers may append to that JSONL while this scope is held, and a
    nested acquisition of the same OS file lock is not portable on Windows.
    Late workflow/runtime completions still carry their own meeting/request
    identity and are validated by the owning service.

    The in-process service locks below freeze the chain/selection/rounds
    ledgers for the command window; ``meeting_rounds._LOCK`` is deliberately
    NOT held here (SCI-049): commands run 60-150s of orchestration while
    holding it, which starved every bounded ``list_meeting_rounds`` reader
    into structured 10s timeouts.  Meeting rounds keep their own per-operation
    short bounded critical sections — the same discipline cross-process
    writers were already subject to, where each append is validated by the
    owning service instead of relying on a whole-command mutex.
    """

    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
    )
    from core.web.services.team_workflow.storage_durability import (
        inter_process_lock,
    )
    from . import hypothesis_first_chain as chain

    # Keep this separate from ``hypothesis_first_chain.jsonl.lock``: command
    # handlers append through ``append_jsonl_locked`` while the scope is held.
    scope_key = _stable_hash({"questionId": str(question_id or "").strip().upper()})[:24]
    scope_lock = chain._storage_path(team_id).with_name(
        f"hypothesis_first_v2_scope_{scope_key}"
    )
    with (
        inter_process_lock(scope_lock, timeout_s=120.0),
        _LOCK,
        hypothesis_selection._LOCK,
        hypothesis_rounds._LOCK,
    ):
        yield
