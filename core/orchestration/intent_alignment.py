#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""意图对齐工件存储与服务核心（T1：store / 状态机 / 存储并发 / 快照投影）。

设计文档：docs/plans/2026-10-18-intent-alignment-module.md §3（工件契约与服务核心）。

模型要点（§3.2 / §3.6 / §3.7）：

- 「版本链 + 当前指针」：每个版本是一次内容不可变快照（contentHash 只覆盖
  内容字段 goal/boundaries/constraints/acceptance/assumptions/changes）；
  ``status`` 是当前版本自身的生命周期属性。
- 内容修订（record_structured 重写、record_answer 带 merge）= 追加新版本，
  新版本 ``supersedes`` 指向前一版本（supersededBy 由索引侧表达，旧版本冻结，
  其 status 原样保留）；状态机转换（发卡 / approved / rejected / take_confirmed /
  revision_requested 的旧版本标记）只发生在当前版本的 status 与 confirmation
  台账字段上，不改内容字段、不动 contentHash。
- 文件级只有 ``currentVersion`` 指针与 ``consumedBy`` 登记可变，其余只追加。
- 澄清台账（openQuestions）随版本快照化：问题增删只作用于当前版本的台账，
  不参与 contentHash（§3.4「台账并入版本」的落地形态）。

本模块是被动数据服务：不进单轮调用链、不写回任何 Session/Journal 字段；
owner 表登记归 T9（docs/plans/2026-10-18-intent-alignment-module.md §8.2）。
T2 在 store 段之后追加「判定段」（§4.1-§4.3 / §5.2 / §3.9）：规则预筛信号、
IntentAlignmentReply 回执解析与落账、IntentAlignmentPacket 组装，纯函数为主；
T4 在判定段之后追加「agent 工具 handler 段」（§3.5.2）：intent_alignment_card /
intent_alignment_merge 的确定性 handler（store 转调 + packet 刷新），供
tools/Key_Tools.py 的同名 @tool 注册面调用；markdown 渲染不存在（章节读
ctx packet，不读本 store）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, ClassVar, Iterator, Mapping, Optional

from core.infrastructure.atomic_io import atomic_write_json

__all__ = [
    "IntentAlignmentStore",
    "IntentAlignmentError",
    "IntentAlignmentVersionConflictError",
    "IntentAlignmentInvalidTransitionError",
    "IntentAlignmentArtifactNotFoundError",
    "HUMAN_GATE_DECISIONS",
    "get_intent_alignment_store",
    "reset_intent_alignment_store",
    "intent_storage_override",
    # ── T2 判定段 ──
    "GATE_DECIDED_BY",
    "MAX_QUESTIONS_PER_TURN",
    "REPLY_SCHEMA_VERSION",
    "detect_clear_imperative_signal",
    "detect_fork_signals",
    "run_rule_prefilter",
    "parse_intent_alignment_reply",
    "apply_reply",
    "assemble_packet",
    # ── T4 agent 工具 handler 段 ──
    "CARD_TOOL_NAME",
    "MERGE_TOOL_NAME",
    "intent_alignment_card_handler",
    "intent_alignment_merge_handler",
]


# 决策词表继承 problem_understanding 的 HUMAN_GATE_DECISIONS
# （core/web/services/team_workflow/research_runtime/problem_understanding_artifact_writer.py:21-23），
# 不新增第五个状态（设计文档 §3.2）。
HUMAN_GATE_DECISIONS = frozenset(
    {"pending", "approved", "revision_requested", "rejected"}
)
# 用户可提交的决策（pending 只是发卡后的初始态，不可作为提交值）。
_SUBMITTABLE_DECISIONS = frozenset({"approved", "revision_requested", "rejected"})

# 版本状态（§3.2 状态机）。
_STATUS_DRAFT = "draft"
_STATUS_PENDING_CONFIRMATION = "pending_confirmation"
_STATUS_CONFIRMED = "confirmed"
_STATUS_CONSUMED = "consumed"
_STATUS_SUPERSEDED = "superseded"

# 内容修订（追加新版本）允许的当前版本状态：任意非终态版本都可被新版本
# supersede（§3.2）；superseded 是终态，链终止后只读。
_CONTENT_REVISION_ALLOWED = frozenset(
    {_STATUS_DRAFT, _STATUS_PENDING_CONFIRMATION, _STATUS_CONFIRMED, _STATUS_CONSUMED}
)

# 内容字段集合：contentHash 的规范化输入（§3.6「contentHash 为该版本内容字段的
# 规范化 sha256」；openQuestions 是台账、status/confirmation 是状态台账，均不入 hash）。
_CONTENT_HASH_FIELDS = ("goal", "boundaries", "constraints", "acceptance", "assumptions", "changes")

SCHEMA_VERSION = 1

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# 测试会 monkeypatch `_intent_alignment_store_path`（对齐 task_planner.py:258-259
# 的注释意图）；`intent_storage_override` 供集成测试整目录隔离（对齐 task_planner.py:21、:235-241）。
_INTENT_STORAGE_OVERRIDE: ContextVar[str] = ContextVar(
    "vibelution_intent_storage_override", default=""
)


class IntentAlignmentError(Exception):
    """意图对齐工件错误基类。"""


class IntentAlignmentVersionConflictError(IntentAlignmentError, ValueError):
    """版本冲突：磁盘 currentVersion 与本实例 baseVersion 不匹配（§3.7 显式失败，绝不静默覆盖）。"""


class IntentAlignmentInvalidTransitionError(IntentAlignmentError, ValueError):
    """非法状态机转换（§3.2 转换表之外的操作）。"""


class IntentAlignmentArtifactNotFoundError(IntentAlignmentError, ValueError):
    """工件不存在：需先 open_or_load 创建骨架。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_sha256(value: object) -> str:
    """规范化 sha256，语义对齐 core/web/services/team_workflow/research_runtime/
    human_gate_artifacts.py:13 的 canonical_sha256（ensure_ascii=False + sort_keys +
    紧凑分隔符）。不跨包 import：core/orchestration 不得反向依赖 core/web 层。"""
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _content_hash(version: Mapping[str, Any]) -> str:
    payload = {field: version.get(field) for field in _CONTENT_HASH_FIELDS}
    return f"sha256:{_canonical_sha256(payload)}"


@contextmanager
def intent_storage_override(workspace_root: str | os.PathLike[str]) -> Iterator[None]:
    """集成测试整目录隔离：override 生效期间所有路径落到 workspace_root 之下。"""
    token = _INTENT_STORAGE_OVERRIDE.set(str(Path(workspace_root).resolve()))
    try:
        yield
    finally:
        _INTENT_STORAGE_OVERRIDE.reset(token)


def _resolve_root() -> Path:
    """解析项目根目录（供单例初始化用），模式对齐 task_planner._resolve_root。"""
    import sys

    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, "__file__", None):
            return Path(mod.__file__).parent.resolve()
    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()
    return Path(__file__).parent.parent.parent.resolve()


def _intent_alignment_store_path(session_id: str) -> str:
    """返回会话工件持久化路径。测试会 monkeypatch 这个函数。"""
    workspace_override = _INTENT_STORAGE_OVERRIDE.get("").strip()
    if workspace_override:
        return str(
            Path(workspace_override) / "memory" / "intent_alignment" / f"{session_id}.json"
        )
    from core.infrastructure import developer_sandbox

    return str(
        developer_sandbox.formal_workspace_path(
            _resolve_root(), "memory", "intent_alignment", f"{session_id}.json"
        )
    )


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"intentAlignment.{field} 必须是非空字符串")
    return value


def _normalize_goal(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"text": value}
    if isinstance(value, Mapping):
        return {"text": _require_text(str(value.get("text") or ""), "goal.text")}
    raise ValueError("intentAlignment.goal 必须是字符串或 {text} 映射")


def _normalize_str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ValueError(f"intentAlignment.{field} 必须是字符串列表")


def _normalize_acceptance(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError("intentAlignment.acceptance 必须是列表")
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            result.append({"criterion": item, "verifiable": False})
        elif isinstance(item, Mapping):
            result.append(
                {
                    "criterion": str(item.get("criterion") or ""),
                    "verifiable": bool(item.get("verifiable", False)),
                }
            )
        else:
            result.append({"criterion": str(item), "verifiable": False})
    return result


def _normalize_assumptions(value: Any, *, start_index: int = 1) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError("intentAlignment.assumptions 必须是列表")
    result: list[dict[str, Any]] = []
    index = start_index
    for item in value:
        if isinstance(item, str):
            entry = {"text": item}
        elif isinstance(item, Mapping):
            entry = dict(item)
        else:
            entry = {"text": str(item)}
        entry.setdefault("id", f"a{index}")
        entry.setdefault("source", "user_statement")
        entry.setdefault("status", "open")
        result.append(
            {
                "id": str(entry["id"]),
                "text": str(entry["text"]),
                "source": str(entry["source"]),
                "status": str(entry["status"]),
            }
        )
        index += 1
    return result


def _normalize_turn_ref(turn_ref: Any, field: str = "turn_ref") -> dict[str, str]:
    if not isinstance(turn_ref, Mapping):
        raise ValueError(f"intentAlignment.{field} 必须是 {{sessionId, turnId, messageId?}} 映射")
    return {
        "sessionId": str(turn_ref.get("sessionId") or ""),
        "turnId": str(turn_ref.get("turnId") or ""),
        "messageId": str(turn_ref.get("messageId") or ""),
    }


def _normalize_origin(origin: Any) -> dict[str, Any]:
    if not isinstance(origin, Mapping):
        raise ValueError("intentAlignment.origin 必须是 {mode, roomId, sourceTextDigest} 映射")
    mode = _require_text(str(origin.get("mode") or ""), "origin.mode")
    return {
        "mode": mode,
        "roomId": str(origin.get("roomId") or ""),
        "sourceTextDigest": str(origin.get("sourceTextDigest") or ""),
        "createdAt": str(origin.get("createdAt") or "") or _now_iso(),
    }


def _next_question_id(versions: list[dict[str, Any]]) -> str:
    max_index = 0
    for version in versions:
        for question in version.get("openQuestions") or []:
            match = re.fullmatch(r"q(\d+)", str(question.get("id") or ""))
            if match:
                max_index = max(max_index, int(match.group(1)))
    return f"q{max_index + 1}"


def _find_question(version: Mapping[str, Any], question_id: str) -> Optional[dict[str, Any]]:
    for question in version.get("openQuestions") or []:
        if str(question.get("id")) == question_id:
            return question
    return None


def _superseded_by(versions: list[Mapping[str, Any]], version_number: int) -> Optional[int]:
    for version in versions:
        if version.get("supersedes") == version_number:
            return int(version["version"])
    return None


class IntentAlignmentStore:
    """每会话一文件 + 文件内版本链的意图对齐工件存储（§3.3 方案 B）。

    - 磁盘文件是唯一权威；本实例持有工作副本（working copy），每次变更都在
      进程内锁区间完成「读盘对账 → 校验 baseVersion → 变更 → 原子替换 → 写回」。
    - 写入走 ``atomic_write_json(..., strict_replace=True)``（内部自带
      cross_process_file_lock，按 ``<target>.lock`` sidecar 串行化跨线程/跨进程写）；
      版本链文件绝不允许截断态。
    - 损坏容错（§3.7）：加载解析失败/结构非法 → 原文件改名 ``<name>.corrupt-<ts>``
      隔离后按空库处理，不静默重建覆盖——本文件含用户确认记录，属审计证据。
    """

    _instance: ClassVar[Optional["IntentAlignmentStore"]] = None

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = Path(project_root).resolve() if project_root else _resolve_root()
        self._lock = threading.RLock()
        # session_id -> 文件 payload 工作副本；磁盘为权威，工作副本即本实例的 baseVersion 视图。
        self._sessions: dict[str, dict[str, Any]] = {}

    # ── 存储层 ──────────────────────────────────────────────────────────

    def _store_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return Path(_intent_alignment_store_path(session_id))

    def _read_payload(self, path: Path) -> Optional[dict[str, Any]]:
        """读取并校验文件 payload；文件不存在或暂不可读返回 None；损坏则隔离后按不存在处理。"""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            _validate_payload(data, expect_session=path.stem)
        except OSError:
            # 读不到（Windows 下被并发原子替换/杀软短暂占用）：按不可读处理，
            # 不动原文件——隔离只针对解析/结构损坏，避免误隔离健康文件。
            return None
        except (_CorruptArtifactError, ValueError, TypeError):
            # 解析失败或结构非法（含 JSONDecodeError/UnicodeDecodeError）：
            # 原文件改名隔离供人工恢复，本实例按空库继续（§3.7）。
            self._quarantine_corrupt_file(path)
            return None
        return data

    def _quarantine_corrupt_file(self, path: Path) -> None:
        """把损坏文件改名隔离（§3.7：``<name>.corrupt-<ts>``），不覆盖、不重建。"""
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        suffix = 0
        while target.exists():
            suffix += 1
            target = path.with_name(f"{path.name}.corrupt-{stamp}-{suffix}")
        try:
            os.replace(path, target)
        except OSError:
            # 隔离失败不抛出：读取路径按「无文件」继续，显式失败留给写入对账。
            return

    def _working_copy(self, session_id: str) -> Optional[dict[str, Any]]:
        """取会话工作副本；未加载则从磁盘懒加载。不落盘、不创建。"""
        cached = self._sessions.get(session_id)
        if cached is not None:
            return cached
        data = self._read_payload(self._store_path(session_id))
        if data is not None:
            self._sessions[session_id] = data
        return data

    def _mutate(self, session_id: str, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        """锁内「读盘对账 → 校验 baseVersion → 变更 → 原子替换」（§3.7）。

        baseVersion（本实例工作副本的 currentVersion）与磁盘 currentVersion 不匹配
        时抛 IntentAlignmentVersionConflictError——冲突显式失败，绝不静默覆盖。
        """
        with self._lock:
            path = self._store_path(session_id)
            base = self._sessions.get(session_id)
            on_disk = self._read_payload(path)
            disk_current = int((on_disk or {}).get("currentVersion") or 0)
            base_current = int((base or {}).get("currentVersion") or 0)
            if disk_current != base_current:
                raise IntentAlignmentVersionConflictError(
                    f"intent_alignment 版本冲突: session={session_id} "
                    f"baseVersion={base_current} 但磁盘 currentVersion={disk_current}；"
                    "请重新加载工件后基于最新版本操作"
                )
            if base is None:
                raise IntentAlignmentArtifactNotFoundError(
                    f"intent_alignment 工件不存在: session={session_id}；先调用 open_or_load"
                )
            result = mutator(base)
            base["updatedAt"] = _now_iso()
            atomic_write_json(path, base, strict_replace=True)
            self._sessions[session_id] = base
            return result

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(f"非法 session_id: {session_id!r}")

    @staticmethod
    def _current_version(data: Mapping[str, Any]) -> dict[str, Any]:
        versions = data.get("versions") or []
        if not versions:
            raise IntentAlignmentArtifactNotFoundError(
                f"intent_alignment 工件尚无版本: session={data.get('sessionId')}"
            )
        return versions[-1]

    # ── 工件生命周期（§3.5.1） ─────────────────────────────────────────

    def open_or_load(self, session_id: str, *, origin: Mapping[str, Any]) -> dict[str, Any]:
        """打开已有工件或创建空骨架（currentVersion=0）；返回 ArtifactRef 投影。

        首次写入（record_structured）即产生 v1(draft)（§3.5.2「首次写入时
        open_or_load 创建 v1(draft)」的 store 侧落点）。已存在工件时 origin 不回写
        （文件级 origin 随骨架冻结，origin.createdAt 区分同会话先后工件链）。
        """
        self._validate_session_id(session_id)
        normalized_origin = _normalize_origin(origin)
        with self._lock:
            existing = self._working_copy(session_id)
            if existing is not None:
                return self._artifact_ref(existing)
            skeleton = {
                "schemaVersion": SCHEMA_VERSION,
                "sessionId": session_id,
                "origin": normalized_origin,
                "currentVersion": 0,
                "versions": [],
                "consumedBy": [],
                "updatedAt": _now_iso(),
            }
            path = self._store_path(session_id)
            on_disk = self._read_payload(path)
            if on_disk is not None:
                self._sessions[session_id] = on_disk
                return self._artifact_ref(on_disk)
            atomic_write_json(path, skeleton, strict_replace=True)
            self._sessions[session_id] = skeleton
            return self._artifact_ref(skeleton)

    def record_structured(
        self,
        artifact_id: str,
        *,
        goal: Any,
        boundaries: Any,
        constraints: Any,
        acceptance: Any,
        assumptions: Any,
    ) -> dict[str, Any]:
        """落当前最佳理解的四要素 + assumptions。

        无版本时创建 v1(draft)；已有版本时追加新 draft 版本（supersedes 当前版本，
        旧版本 status 冻结，supersededBy 由索引侧表达，§3.6）。结构化重写允许从
        任意非终态版本发起；链已终止（superseded 终态）时拒绝。
        """

        def mutator(data: dict[str, Any]) -> dict[str, Any]:
            versions = data["versions"]
            if versions:
                current = versions[-1]
                if current["status"] not in _CONTENT_REVISION_ALLOWED:
                    raise IntentAlignmentInvalidTransitionError(
                        f"版本 {current['version']} 状态为 {current['status']}，链已终止，"
                        "不允许结构化重写"
                    )
            new_content = {
                "goal": _normalize_goal(goal),
                "boundaries": _normalize_str_list(boundaries, "boundaries"),
                "constraints": _normalize_str_list(constraints, "constraints"),
                "acceptance": _normalize_acceptance(acceptance),
                "assumptions": _normalize_assumptions(assumptions),
            }
            ledger = list(versions[-1].get("openQuestions") or []) if versions else []
            changes: list[dict[str, Any]] = []
            if versions:
                old = versions[-1]
                for field in ("goal", "boundaries", "constraints", "acceptance", "assumptions"):
                    changes.append(
                        {
                            "field": field,
                            "from": old.get(field),
                            "to": new_content[field],
                            "reason": "structured rewrite",
                        }
                    )
            version = self._append_version(data, new_content, ledger, changes, status=_STATUS_DRAFT)
            return self._version_snapshot(data, version)

        return self._mutate(artifact_id, mutator)

    def request_confirmation(
        self, artifact_id: str, *, card_id: str, turn_ref: Mapping[str, Any]
    ) -> dict[str, Any]:
        """draft → pending_confirmation（发确认卡，§3.2）。

        四要素（goal/boundaries/constraints/acceptance）非空才允许；绑定 cardId
        与发卡 turnId；decision 置 pending，等用户裁决。
        """
        normalized_turn = _normalize_turn_ref(turn_ref)
        card = _require_text(card_id, "card_id")

        def mutator(data: dict[str, Any]) -> dict[str, Any]:
            current = self._current_version(data)
            if current["status"] != _STATUS_DRAFT:
                raise IntentAlignmentInvalidTransitionError(
                    f"request_confirmation 只允许 draft → pending_confirmation，"
                    f"当前版本 {current['version']} 状态为 {current['status']}"
                )
            _require_four_elements(current)
            current["status"] = _STATUS_PENDING_CONFIRMATION
            current["confirmation"] = {
                "cardId": card,
                "issuedAtTurn": normalized_turn["turnId"],
                "decision": "pending",
                "decidedAtTurn": "",
                "decidedAt": "",
                "confirmedDigest": "",
            }
            return self._version_snapshot(data, current)

        return self._mutate(artifact_id, mutator)

    def submit_confirmation_decision(
        self,
        artifact_id: str,
        *,
        decision: str,
        turn_ref: Mapping[str, Any],
        note: str = "",
    ) -> dict[str, Any]:
        """提交确认裁决（decision 词表继承 HUMAN_GATE_DECISIONS，§3.2）。

        - approved → confirmed（记录 decision turnId 与确认摘要 confirmedDigest）
        - revision_requested → 当前版本 superseded + 自动创建新 draft 继承已答内容
        - rejected → 当前版本 superseded 终止，不自动开新版本
        """
        if decision not in _SUBMITTABLE_DECISIONS:
            raise ValueError(
                f"decision 必须是 {sorted(_SUBMITTABLE_DECISIONS)} 之一，收到 {decision!r}"
            )
        normalized_turn = _normalize_turn_ref(turn_ref)

        def mutator(data: dict[str, Any]) -> dict[str, Any]:
            current = self._current_version(data)
            if current["status"] != _STATUS_PENDING_CONFIRMATION:
                raise IntentAlignmentInvalidTransitionError(
                    f"submit_confirmation_decision 只允许从 pending_confirmation 发起，"
                    f"当前版本 {current['version']} 状态为 {current['status']}"
                    f"（confirmed 的修订走 record_structured / record_answer 的版本链路径）"
                )
            current["confirmation"]["decision"] = decision
            current["confirmation"]["decidedAtTurn"] = normalized_turn["turnId"]
            current["confirmation"]["decidedAt"] = _now_iso()
            if note:
                current["confirmation"]["note"] = str(note)
            if decision == "approved":
                current["status"] = _STATUS_CONFIRMED
                current["confirmation"]["confirmedDigest"] = current["contentHash"]
                return self._version_snapshot(data, current)
            # revision_requested / rejected：当前版本冻结为 superseded。
            current["status"] = _STATUS_SUPERSEDED
            if decision == "rejected":
                # 用户明确放弃：链终止，不自动开新版本（§3.2）。
                return self._version_snapshot(data, current)
            # revision_requested：自动创建新 draft 继承已答内容（§3.2）。
            inherited_content = {
                field: _deepcopy(current.get(field))
                for field in ("goal", "boundaries", "constraints", "acceptance", "assumptions")
            }
            ledger = _deepcopy(current.get("openQuestions") or [])
            successor = self._append_version(
                data, inherited_content, ledger, changes=[], status=_STATUS_DRAFT
            )
            return self._version_snapshot(data, successor)

        return self._mutate(artifact_id, mutator)

    # ── 澄清台账（§3.4） ───────────────────────────────────────────────

    def record_question_asked(
        self,
        artifact_id: str,
        *,
        question: str,
        why_it_matters: str,
        applies_to: str,
        turn_ref: Optional[Mapping[str, Any]] = None,
        question_id: str = "",
        asked_in_card: str = "",
    ) -> str:
        """登记问题并分配台账稳定 questionId（跨卡稳定，§3.9）；返回 questionId。

        台账只落在当前版本的 openQuestions（不入 contentHash，不产生新版本）；
        调用方可携带已有 id 重问（工具面入参透传，§3.9「同一问题在新卡中重问时
        沿用原 id」）。
        """
        normalized_turn = _normalize_turn_ref(turn_ref) if turn_ref else {
            "sessionId": "",
            "turnId": "",
            "messageId": "",
        }
        question_text = _require_text(question, "question")

        def mutator(data: dict[str, Any]) -> str:
            current = self._current_version(data)
            if current["status"] not in _CONTENT_REVISION_ALLOWED:
                raise IntentAlignmentInvalidTransitionError(
                    f"当前版本 {current['version']} 状态为 {current['status']}，链已终止，"
                    "不允许登记新问题"
                )
            qid = str(question_id or "").strip() or _next_question_id(data["versions"])
            existing = _find_question(current, qid)
            if existing is not None:
                # 同 id 重问：刷新台账状态为 asked（保留原 id 跨卡稳定，§3.9）。
                existing["status"] = "asked"
                existing["question"] = question_text
                existing["whyItMatters"] = str(why_it_matters or "")
                existing["appliesTo"] = str(applies_to or "")
                existing["askedAtTurn"] = normalized_turn["turnId"]
                existing["askedInCard"] = str(asked_in_card or "")
                existing.pop("withdrawnReason", None)
                return qid
            current["openQuestions"].append(
                {
                    "id": qid,
                    "question": question_text,
                    "whyItMatters": str(why_it_matters or ""),
                    "appliesTo": str(applies_to or ""),
                    "status": "asked",
                    "askedAtTurn": normalized_turn["turnId"],
                    "askedInCard": str(asked_in_card or ""),
                }
            )
            return qid

        return self._mutate(artifact_id, mutator)

    def record_answer(
        self,
        artifact_id: str,
        question_id: str,
        *,
        answer_text: str,
        turn_ref: Mapping[str, Any],
        merge: Optional[list[Mapping[str, Any]]] = None,
    ) -> Optional[dict[str, Any]]:
        """记录答案并按 merge 指令决定是否产生新版本（§3.4-2）。

        - merge 为空：只落台账（问题标 answered、存答案原文），不产生新版本，
          返回 None——这是 gate 回执路径与 agent 语义归并路径的分界。
        - merge 非空：把答案折算进四要素/assumptions，生成新版本；changes 逐条
          记录 {field, from, to, reason}（附 questionId）。
        - 幂等重放（对齐 workflow_artifact_store 的同 identity 同 hash 幂等语义）：
          相同 questionId + 相同答案原文 + 相同 merge 指纹 → 不产生新版本。
        """
        normalized_turn = _normalize_turn_ref(turn_ref)
        answer = _require_text(answer_text, "answer_text")
        merge_updates = [dict(item) for item in (merge or [])]
        merge_digest = _canonical_sha256(merge_updates) if merge_updates else ""

        def mutator(data: dict[str, Any]) -> Optional[dict[str, Any]]:
            current = self._current_version(data)
            if current["status"] not in _CONTENT_REVISION_ALLOWED:
                raise IntentAlignmentInvalidTransitionError(
                    f"当前版本 {current['version']} 状态为 {current['status']}（superseded 终态），"
                    "不允许 record_answer"
                )
            question = _find_question(current, str(question_id))
            if question is None:
                raise IntentAlignmentArtifactNotFoundError(
                    f"问题 {question_id!r} 不在当前版本 {current['version']} 的台账中"
                )
            already_answered = question.get("status") == "answered"
            same_text = bool(
                already_answered
                and (question.get("answer") or {}).get("text") == answer
            )
            same_merge = bool(
                already_answered
                and (question.get("answer") or {}).get("mergeDigest", "") == merge_digest
            )
            if already_answered and same_text and (not merge_updates or same_merge):
                # 精确重放：幂等，不产生新版本、不重复落台账。
                return None

            answer_entry = {
                "text": answer,
                "turnId": normalized_turn["turnId"],
                "answeredAt": _now_iso(),
            }
            if not merge_updates:
                # 只落台账：gate 回执路径；回答永不静默改写结构化四要素。
                question["status"] = "answered"
                question["answer"] = answer_entry
                return None

            answer_entry["mergeDigest"] = merge_digest
            question["status"] = "answered"
            question["answer"] = answer_entry

            new_content = {
                field: _deepcopy(current.get(field))
                for field in ("goal", "boundaries", "constraints", "acceptance", "assumptions")
            }
            changes: list[dict[str, Any]] = []
            for update in merge_updates:
                changes.append(
                    _apply_field_update(new_content, update, question_id=str(question_id))
                )
            ledger = _deepcopy(current.get("openQuestions") or [])
            new_version = self._append_version(
                data, new_content, ledger, changes, status=_STATUS_DRAFT
            )
            return self._version_snapshot(data, new_version)

        return self._mutate(artifact_id, mutator)

    def withdraw_question(
        self, artifact_id: str, question_id: str, *, reason: str
    ) -> None:
        """撤销问题：台账保留并记录撤销原因（§3.4-4 撤销留痕）。"""
        _require_text(reason, "reason")

        def mutator(data: dict[str, Any]) -> None:
            current = self._current_version(data)
            question = _find_question(current, str(question_id))
            if question is None:
                raise IntentAlignmentArtifactNotFoundError(
                    f"问题 {question_id!r} 不在当前版本 {current['version']} 的台账中"
                )
            question["status"] = "withdrawn"
            question["withdrawnReason"] = str(reason)

        self._mutate(artifact_id, mutator)

    # ── 读取与交接（§3.5.1 / §3.8） ────────────────────────────────────

    def get_current(self, session_id: str) -> Optional[dict[str, Any]]:
        """当前版本快照（深拷贝只读投影）；无工件或无版本返回 None。"""
        with self._lock:
            data = self._working_copy(session_id)
        if not data or not data.get("versions"):
            return None
        return self._version_snapshot(data, data["versions"][-1])

    def get_version(self, session_id: str, version: int) -> Optional[dict[str, Any]]:
        """按版本号取快照（深拷贝只读投影）；不存在返回 None。"""
        with self._lock:
            data = self._working_copy(session_id)
        if not data:
            return None
        for entry in data.get("versions") or []:
            if entry.get("version") == version:
                return self._version_snapshot(data, entry)
        return None

    def take_confirmed(
        self, session_id: str, *, consumer: str, ref: str = ""
    ) -> Optional[dict[str, Any]]:
        """规划入口采纳 confirmed 工件（§3.2 / §3.8）。

        首个消费者 confirmed → consumed；后续消费者只登记 consumedBy 不改状态；
        无 confirmed 当前版本返回 None 不抛错。消费不删除、不回写工件内容。
        """
        consumer_name = _require_text(consumer, "consumer")

        def mutator(data: dict[str, Any]) -> Optional[dict[str, Any]]:
            current = self._current_version(data)
            if current["status"] == _STATUS_CONFIRMED:
                current["status"] = _STATUS_CONSUMED
            elif current["status"] != _STATUS_CONSUMED:
                return None
            data["consumedBy"].append(
                {
                    "consumer": consumer_name,
                    "consumedAt": _now_iso(),
                    "ref": str(ref or ""),
                }
            )
            return self._version_snapshot(data, current)

        with self._lock:
            # 消费方可能持全新 store 句柄：先懒加载建立 base 视图再进入变更对账。
            if self._working_copy(session_id) is None:
                return None
        try:
            return self._mutate(session_id, mutator)
        except IntentAlignmentArtifactNotFoundError:
            return None

    def open_questions(self, session_id: str) -> list[dict[str, Any]]:
        """累积待问集合 = asked ∧ 未 answered ∧ 未 withdrawn（§3.4-3 不变式）。"""
        with self._lock:
            data = self._working_copy(session_id)
        if not data or not data.get("versions"):
            return []
        current = data["versions"][-1]
        views: list[dict[str, Any]] = []
        for question in current.get("openQuestions") or []:
            if question.get("status") == "asked":
                views.append(_deepcopy(question))
        return views

    # ── 版本与快照内部件 ───────────────────────────────────────────────

    def _append_version(
        self,
        data: dict[str, Any],
        content: Mapping[str, Any],
        ledger: list[Mapping[str, Any]],
        changes: list[Mapping[str, Any]],
        *,
        status: str,
    ) -> dict[str, Any]:
        versions = data["versions"]
        previous = versions[-1] if versions else None
        entry: dict[str, Any] = {
            "version": (int(previous["version"]) if previous else 0) + 1,
            "status": status,
            "contentHash": "",
            "supersedes": int(previous["version"]) if previous else None,
            "goal": _deepcopy(content["goal"]),
            "boundaries": _deepcopy(content["boundaries"]),
            "constraints": _deepcopy(content["constraints"]),
            "acceptance": _deepcopy(content["acceptance"]),
            "assumptions": _deepcopy(content["assumptions"]),
            "openQuestions": _deepcopy(ledger),
            "changes": _deepcopy(changes),
            "confirmation": {},
            "createdAt": _now_iso(),
        }
        entry["contentHash"] = _content_hash(entry)
        versions.append(entry)
        data["currentVersion"] = int(entry["version"])
        return entry

    def _artifact_ref(self, data: Mapping[str, Any]) -> dict[str, Any]:
        versions = data.get("versions") or []
        current = versions[-1] if versions else None
        return {
            "artifactId": data["sessionId"],
            "sessionId": data["sessionId"],
            "version": int(current["version"]) if current else 0,
            "status": str(current["status"]) if current else "empty",
            "contentHash": str(current["contentHash"]) if current else "",
        }

    def _version_snapshot(
        self, data: Mapping[str, Any], version: Mapping[str, Any]
    ) -> dict[str, Any]:
        """版本快照投影：单存储源、投影非第二存储；一律深拷贝只读。"""
        versions = list(data.get("versions") or [])
        snapshot = {
            "artifactId": data["sessionId"],
            "sessionId": data["sessionId"],
            "version": int(version["version"]),
            "status": str(version["status"]),
            "contentHash": str(version.get("contentHash") or ""),
            "supersedes": version.get("supersedes"),
            "supersededBy": _superseded_by(versions, int(version["version"])),
            "goal": _deepcopy(version.get("goal")),
            "boundaries": _deepcopy(version.get("boundaries")),
            "constraints": _deepcopy(version.get("constraints")),
            "acceptance": _deepcopy(version.get("acceptance")),
            "assumptions": _deepcopy(version.get("assumptions")),
            "openQuestions": _deepcopy(version.get("openQuestions")),
            "changes": _deepcopy(version.get("changes")),
            "confirmation": _deepcopy(version.get("confirmation")),
            "createdAt": str(version.get("createdAt") or ""),
        }
        return _deepcopy(snapshot)


def _require_four_elements(version: Mapping[str, Any]) -> None:
    """发卡前置：四要素非空（§3.2 转换表约束）。"""
    goal_text = str((version.get("goal") or {}).get("text") or "").strip()
    if not goal_text:
        raise ValueError("intentAlignment 发卡前置不满足: goal 为空")
    for field in ("boundaries", "constraints", "acceptance"):
        if not (version.get(field) or []):
            raise ValueError(f"intentAlignment 发卡前置不满足: {field} 为空")


def _apply_field_update(
    content: dict[str, Any], update: Mapping[str, Any], *, question_id: str
) -> dict[str, Any]:
    """把单条 merge 指令折算进内容副本，返回 changes 条目 {field, from, to, reason}。

    支持字段：goal / goal.text、boundaries[+]|boundaries、constraints[+]|constraints、
    acceptance[+]|acceptance、assumptions[+]|assumptions|assumptions.<id>|
    assumptions.<id>.status（§3.6 changes 示例使用 ``constraints[+]`` 形态）。
    """
    field = str(update.get("field") or "").strip()
    if not field:
        raise ValueError("merge 指令缺少 field")
    target = update.get("to")
    reason = str(update.get("reason") or f"answer to {question_id}")

    def entry(from_value: Any, to_value: Any) -> dict[str, Any]:
        return {
            "field": field,
            "from": _deepcopy(from_value),
            "to": _deepcopy(to_value),
            "reason": reason,
            "questionId": str(question_id),
        }

    if field == "goal":
        previous = content["goal"]
        content["goal"] = _normalize_goal(target)
        return entry(previous, content["goal"])
    if field == "goal.text":
        previous = content["goal"].get("text")
        content["goal"]["text"] = _require_text(target, "merge.goal.text")
        return entry(previous, content["goal"]["text"])
    if field in ("boundaries", "constraints"):
        previous = list(content[field])
        content[field] = _normalize_str_list(target, field)
        return entry(previous, content[field])
    if field in ("boundaries[+]", "constraints[+]"):
        base_field = field[:-3]
        item = str(target)
        previous = list(content[base_field])
        content[base_field] = previous + [item]
        return entry(None, item)
    if field == "acceptance":
        previous = list(content["acceptance"])
        content["acceptance"] = _normalize_acceptance(target)
        return entry(previous, content["acceptance"])
    if field == "acceptance[+]":
        item = _normalize_acceptance([target])[0]
        previous = list(content["acceptance"])
        content["acceptance"] = previous + [item]
        return entry(None, item)
    if field == "assumptions":
        previous = list(content["assumptions"])
        start = len(previous) + 1
        content["assumptions"] = _normalize_assumptions(target, start_index=start)
        return entry(previous, content["assumptions"])
    if field == "assumptions[+]":
        item = _normalize_assumptions(
            [target], start_index=len(content["assumptions"]) + 1
        )[0]
        previous = list(content["assumptions"])
        content["assumptions"] = previous + [item]
        return entry(None, item)
    if field.startswith("assumptions."):
        remainder = field[len("assumptions.") :]
        assumption = next(
            (item for item in content["assumptions"] if item.get("id") == remainder), None
        )
        if assumption is None:
            raise ValueError(f"merge 指令目标假设不存在: {field}")
        previous = dict(assumption)
        if remainder.endswith(".status"):
            status_value = str(target)
            if status_value not in {"open", "validated", "invalidated"}:
                raise ValueError(f"非法 assumption status: {status_value!r}")
            assumption["status"] = status_value
        elif isinstance(target, Mapping):
            for key in ("text", "source", "status"):
                if key in target:
                    assumption[key] = str(target[key])
        else:
            assumption["text"] = str(target)
        return entry(previous, dict(assumption))
    raise ValueError(f"不支持的 merge 字段: {field}（仅四要素与 assumptions 字段可折算）")


def _deepcopy(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_deepcopy(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _deepcopy(item) for key, item in value.items()}
    return value


class _CorruptArtifactError(ValueError):
    """payload 结构非法（区别于读盘 IO 异常，处理路径同为隔离）。"""


def _validate_payload(data: Any, *, expect_session: str) -> None:
    """结构校验（§3.6 数据契约的最小形状）；非法按损坏处理（§3.7）。"""
    if not isinstance(data, dict):
        raise _CorruptArtifactError("payload 不是 JSON 对象")
    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise _CorruptArtifactError(f"schemaVersion 非法: {data.get('schemaVersion')!r}")
    if not isinstance(data.get("sessionId"), str) or not data.get("sessionId"):
        raise _CorruptArtifactError("sessionId 缺失")
    if not isinstance(data.get("origin"), dict):
        raise _CorruptArtifactError("origin 缺失或非法")
    if not isinstance(data.get("versions"), list):
        raise _CorruptArtifactError("versions 缺失或非法")
    if not isinstance(data.get("consumedBy"), list):
        raise _CorruptArtifactError("consumedBy 缺失或非法")
    current = data.get("currentVersion")
    if not isinstance(current, int) or current < 0:
        raise _CorruptArtifactError(f"currentVersion 非法: {current!r}")
    versions = data["versions"]
    if versions:
        last = versions[-1]
        if not isinstance(last, dict) or last.get("version") != current:
            raise _CorruptArtifactError("currentVersion 与 versions 不一致")
    if expect_session not in {"", data["sessionId"]}:
        # 文件名与内容 sessionId 错位：按损坏隔离，避免跨会话串数据。
        raise _CorruptArtifactError("sessionId 与文件名不一致")


_intent_alignment_store_instance: Optional[IntentAlignmentStore] = None
_intent_alignment_store_root: Optional[Path] = None


def get_intent_alignment_store(project_root: Optional[str] = None) -> IntentAlignmentStore:
    """获取意图对齐 store 单例，支持 project_root 校验。

    模式对齐 get_task_manager（task_planner.py:855-891）：storage override 生效且
    未显式传 project_root 时返回绑定 override 目录的独立实例（非单例），供集成
    测试整目录隔离。
    """
    global _intent_alignment_store_instance, _intent_alignment_store_root
    workspace_override = _INTENT_STORAGE_OVERRIDE.get("").strip()
    if workspace_override and project_root is None:
        store = IntentAlignmentStore.__new__(IntentAlignmentStore)
        store.project_root = Path(workspace_override).resolve()
        store._lock = threading.RLock()
        store._sessions = {}
        return store
    if (
        IntentAlignmentStore._instance is not None
        and _intent_alignment_store_instance is None
    ):
        _intent_alignment_store_instance = IntentAlignmentStore._instance

    if _intent_alignment_store_instance is None:
        root = Path(project_root).resolve() if project_root else _resolve_root()
        _intent_alignment_store_root = root
        _intent_alignment_store_instance = IntentAlignmentStore(root)
        IntentAlignmentStore._instance = _intent_alignment_store_instance
    elif project_root is not None:
        incoming = Path(project_root).resolve()
        if incoming != _intent_alignment_store_root:
            import warnings

            warnings.warn(
                f"IntentAlignmentStore 已在 {_intent_alignment_store_root} 初始化，"
                f"忽略传入路径 {incoming}"
            )
    return _intent_alignment_store_instance


def reset_intent_alignment_store() -> None:
    """重置 store 单例（测试复位，对齐 reset_task_manager，task_planner.py:894-899）。"""
    global _intent_alignment_store_instance, _intent_alignment_store_root
    _intent_alignment_store_instance = None
    _intent_alignment_store_root = None
    IntentAlignmentStore._instance = None


# ═══════════════════════════════════════════════════════════════════════════
# T2 判定段：规则预筛 / IntentAlignmentReply 回执解析与落账 / packet 组装
# （设计文档 §4.1-§4.3 / §5.2 / §3.9）。
#
# 分层纪律（§2.2）：本段以纯函数为主（唯一例外是 apply_reply 转调
# store.record_answer），无 LLM、无 IO；规则层只产「提示与审计」信号，不裁决、
# 不短路 turn、不代替模型产出 assistant 内容；规则不确定时保守给出 ask 倾向或
# 中性输出，绝不误标已答/已对齐。
# ═══════════════════════════════════════════════════════════════════════════

# ── 规则预筛信号（§4.1 / §4.3 判据 5） ─────────────────────────────────────

GATE_DECIDED_BY = "rules"
"""§4.2 gate.decidedBy 固定取值：规则预筛；主 agent 的最终决策体现为其行为。"""

MAX_QUESTIONS_PER_TURN = 3
"""§4.2 budget.maxQuestionsPerTurn：对齐 BRT 现规则「一组简短问题」语义
（prompt_template_service.py:77）。"""

REPLY_SCHEMA_VERSION = 1
"""§5.2 IntentAlignmentReply / IntentAlignmentCardPayload 的 schemaVersion。"""

_GATE_CONFIDENCE_CLEAR = 0.7
_GATE_CONFIDENCE_FORK = 0.8
_GATE_CONFIDENCE_UNCERTAIN = 0.3

# clear 快路径信号：明确祈使句 + 明确对象（中文祈使动词白名单，可枚举、从简）。
_CLEAR_POLITE_LEAD = r"^(?:\s*(?:请|帮我|麻烦|帮忙|劳驾|能否|可以|你|您)\s*[，,、。]?)*"
_CLEAR_IMPERATIVE_VERBS = (
    "写一个",
    "搭建", "创建", "新建", "生成", "添加", "增加", "删除", "移除", "修改",
    "更新", "实现", "编写", "开发", "修复", "重构", "部署", "发布", "导出", "导入",
    "运行", "执行", "构建", "设计", "翻译", "总结", "列出", "安装", "配置", "清洗",
)
_CLEAR_PATTERN = re.compile(
    _CLEAR_POLITE_LEAD
    + "("
    + "|".join(sorted(_CLEAR_IMPERATIVE_VERBS, key=len, reverse=True))
    + r")(.+)",
    re.DOTALL,
)

# 分叉信号一：多义指代。近似边界：初版以保守代词表正则近似，规则层无法解析真实
# 先行词；命中（含「这个文件」这类带显式宾语的短语）只提示 ask 不裁决，保守方向安全。
_AMBIGUOUS_PRONOUN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(它们|这些|那些|这个|那个|上述|它)(?![A-Za-z0-9])"
)

# 分叉信号二：缺失量纲。近似边界：模糊改进动词 + 全文无任何量纲提示才命中；
# 「把响应时间优化到 200ms 以内」这类带量纲的说法不命中。
_VAGUE_IMPROVEMENT_PATTERN = re.compile(
    r"(优化|改进|改善|完善|提升|增强|美化|加速|加快|调整一下|改一下)"
)
_METRIC_HINT_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:ms|s|秒|毫秒|分钟|小时|天|倍|%|％|mb|gb|kb|条|个|行|次)"
    r"|[一二两三四五六七八九十百千万]+\s*(?:秒|毫秒|倍|条|个|行|次)"
    r"|性能|速度|内存|指标|响应时间|吞吐|占用|准确率|命中率|耗时|延迟)",
    re.IGNORECASE,
)

# 分叉信号三：互斥约束并存。近似边界：初版从简——枚举互斥关键词对 + 「既要…又要…」
# 句式；语义级互斥判定归主 agent。
_EXCLUSIVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("全量", "增量"),
    ("同步", "异步"),
    ("离线", "在线"),
    ("只读", "可写"),
    ("本地", "云端"),
    ("单机", "多人"),
)
_EXCLUSIVE_BOTH_PATTERN = re.compile(r"既要.{1,16}又(?:要|得|能|想)|既要.{1,16}也要")


def detect_clear_imperative_signal(message_text: str) -> dict[str, Any]:
    """识别「明确祈使句 + 明确对象」clear 快路径信号（§4.3 判据 1 的规则侧近似）。

    确定性正则：礼貌前缀（请/帮我/麻烦…）+ 中文祈使动词白名单 + 非空宾语。
    返回 ``{"hit": bool, "verb": str, "object": str}``。纯函数，无 LLM、无 IO。
    近似边界：不解析句法；英文、白名单外动词、礼貌前缀组合过复杂的表达会漏检——
    漏检只是不给 proceed 倾向（保守方向安全），不会误标已对齐。
    """
    text = str(message_text or "").strip()
    if not text:
        return {"hit": False, "verb": "", "object": ""}
    match = _CLEAR_PATTERN.match(text)
    if match is None:
        return {"hit": False, "verb": "", "object": ""}
    verb = match.group(1)
    obj = match.group(2).strip("。，,、；;：:！!？? \t\n")
    if len(obj) < 2:
        return {"hit": False, "verb": "", "object": ""}
    return {"hit": True, "verb": verb, "object": obj}


def detect_fork_signals(message_text: str) -> list[dict[str, str]]:
    """检测 §4.3 判据 5 的分叉信号清单（确定性正则近似，初版从简）。

    返回 ``[{"signal": "多义指代"|"缺失量纲"|"互斥约束", "evidence": str}, ...]``
    （每类信号至多一条）。纯函数。近似边界见各模式处注释；规则层不做裁决，
    命中只意味着「不得给出 proceed 倾向」，判定权始终在主 agent。
    """
    text = str(message_text or "").strip()
    hits: list[dict[str, str]] = []
    if not text:
        return hits

    def add(signal: str, evidence: str) -> None:
        if all(hit["signal"] != signal for hit in hits):
            hits.append({"signal": signal, "evidence": evidence})

    pronouns = _AMBIGUOUS_PRONOUN_PATTERN.findall(text)
    if pronouns:
        add("多义指代", "、".join(dict.fromkeys(pronouns)))

    vague = _VAGUE_IMPROVEMENT_PATTERN.search(text)
    if vague is not None and _METRIC_HINT_PATTERN.search(text) is None:
        add("缺失量纲", vague.group(1))

    for left, right in _EXCLUSIVE_PAIRS:
        if left in text and right in text:
            add("互斥约束", f"{left}+{right}")
            break
    both = _EXCLUSIVE_BOTH_PATTERN.search(text)
    if both is not None:
        add("互斥约束", both.group(0))
    return hits


def run_rule_prefilter(message_text: str) -> dict[str, Any]:
    """规则预筛（§4.1/§4.3）：输出 §4.2 gate 段信号——提示与审计，非裁决。

    - 分叉信号命中 → action="ask"（规则层不得给出 proceed 倾向）；
    - 无分叉且命中 clear 快路径信号 → action="proceed"（仅直通倾向提示）；
    - 无任何确定性信号 → 保守 ask 倾向（低置信度；绝不误标已答/已对齐）。

    纯函数：无 LLM、无 IO、不读 store。输出固定四字段
    ``{action, confidence, decidedBy, reason}``，不携带任何对齐状态结论。
    """
    fork_hits = detect_fork_signals(message_text)
    if fork_hits:
        evidence = "、".join(f"{hit['signal']}({hit['evidence']})" for hit in fork_hits)
        return {
            "action": "ask",
            "confidence": _GATE_CONFIDENCE_FORK,
            "decidedBy": GATE_DECIDED_BY,
            "reason": f"命中分叉信号，交由本轮自判: {evidence}",
        }
    clear = detect_clear_imperative_signal(message_text)
    if clear["hit"]:
        return {
            "action": "proceed",
            "confidence": _GATE_CONFIDENCE_CLEAR,
            "decidedBy": GATE_DECIDED_BY,
            "reason": (
                f"命中明确祈使句+明确对象信号（动词「{clear['verb']}」），"
                "仅作直通倾向提示，判定权在主 agent"
            ),
        }
    return {
        "action": "ask",
        "confidence": _GATE_CONFIDENCE_UNCERTAIN,
        "decidedBy": GATE_DECIDED_BY,
        "reason": "未命中确定性信号，保守交由本轮自判（不作 proceed 倾向）",
    }


# ── IntentAlignmentReply 回执解析与落账（§5.2 / §3.9） ────────────────────

_REPLY_KIND = "intent_alignment_reply"
_CARD_KIND = "intent_alignment_card"
_REPLY_ACTIONS = frozenset({"confirm", "dismiss"})


def _parse_reply_entry(
    entry: Mapping[str, Any], questions_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """单题答案规范化：选中项 label（"；"连接）或 freeText；skipped/无内容 → 空串。"""
    question_id = str(entry.get("questionId") or "")
    question = questions_by_id.get(question_id)
    selected = entry.get("selectedOptionIds")
    selected_ids = [str(item) for item in selected] if isinstance(selected, list) else []
    free_text = str(entry.get("freeText") or "").strip()
    skipped = bool(entry.get("skipped"))

    labels: list[str] = []
    if question is not None:
        options = {
            str(option.get("optionId")): str(
                option.get("label") or option.get("optionId") or ""
            )
            for option in (question.get("options") or [])
            if isinstance(option, Mapping)
        }
        labels = [options.get(option_id, option_id) for option_id in selected_ids]
    else:
        # 无卡上下文（调用方未提供 card_payload）：退化用 optionId 原文。
        labels = list(selected_ids)

    parts = [label for label in labels if label]
    if free_text:
        parts.append(free_text)
    answer_text = "；".join(parts).strip()
    if not answer_text:
        skipped = True
        answer_text = ""
    return {
        "questionId": question_id,
        "answerText": answer_text,
        "skipped": skipped,
        "selectedOptionIds": selected_ids,
        "selectedLabels": labels,
        "freeText": free_text,
        "raw": dict(entry),
    }


def parse_intent_alignment_reply(reply: Any, card_payload: Any = None) -> dict[str, Any]:
    """解析 IntentAlignmentReply（§5.2 schema）。纯函数，不写 store。

    - 校验 schemaVersion==1、kind=="intent_alignment_reply"、action∈{confirm,dismiss}、
      cardId 非空、revision 为正整数；任一不满足 → ok=False，errors 收集原因。
    - card_payload（IntentAlignmentCardPayload）提供时按 cardId+revision 对卡匹配：
      匹配成功再按 questionId 映射题目并解析选中项 label；cardId/revision 不匹配
      （三元组不成立）→ 整卡条目全部原样进 unmapped；卡匹配但 questionId 不在卡内
      → 该条目原样进 unmapped（§3.9 三元组映射失败留档）。未提供 card_payload 时
      只做 schema 级解析（label 退化用 optionId 原文）。
    - 每题答案文本规范化拼接：选中项 label（"；"连接）或 freeText（自由输入/自定义
      答案保留原文），两者并存时拼接；skipped 或无任何答案内容 → answerText=""。
    - action="dismiss"：解析照常返回；其 store 处置为设计开放点（设计文档 §5.3 /
      §7.2-9），apply_reply 对 dismiss 保守不动 store。
    """
    result: dict[str, Any] = {
        "ok": True,
        "errors": [],
        "cardId": "",
        "revision": None,
        "action": "",
        "cardMatched": False,
        "answers": [],
        "unmapped": [],
    }
    if not isinstance(reply, Mapping):
        result["ok"] = False
        result["errors"].append("reply 不是 JSON 对象")
        return result

    card_id = str(reply.get("cardId") or "")
    revision = reply.get("revision")
    action = str(reply.get("action") or "")
    result["cardId"] = card_id
    result["revision"] = (
        revision if isinstance(revision, int) and not isinstance(revision, bool) else None
    )
    result["action"] = action

    if reply.get("schemaVersion") != REPLY_SCHEMA_VERSION:
        result["ok"] = False
        result["errors"].append(f"schemaVersion 非法: {reply.get('schemaVersion')!r}")
    if str(reply.get("kind") or "") != _REPLY_KIND:
        result["ok"] = False
        result["errors"].append(f"kind 非法: {reply.get('kind')!r}")
    if action not in _REPLY_ACTIONS:
        result["ok"] = False
        result["errors"].append(f"action 非法: {action!r}")
    if not card_id:
        result["ok"] = False
        result["errors"].append("cardId 缺失")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        result["ok"] = False
        result["errors"].append(f"revision 非法: {revision!r}")

    questions_by_id: dict[str, Mapping[str, Any]] = {}
    card_provided = card_payload is not None
    if card_provided:
        card_matched = (
            isinstance(card_payload, Mapping)
            and str(card_payload.get("kind") or "") == _CARD_KIND
            and str(card_payload.get("cardId") or "") == card_id
            and card_payload.get("revision") == revision
        )
        result["cardMatched"] = card_matched
        if card_matched:
            for question in card_payload.get("questions") or []:
                if isinstance(question, Mapping):
                    questions_by_id[str(question.get("questionId") or "")] = question

    answers = reply.get("answers")
    if answers is not None and not isinstance(answers, list):
        result["ok"] = False
        result["errors"].append("answers 必须是列表")
        answers = []
    for entry in list(answers or []):
        if not isinstance(entry, Mapping):
            result["unmapped"].append(entry)
            continue
        if card_provided and not result["cardMatched"]:
            # cardId/revision 三元组不成立：整卡条目全部留档，不解析不落账。
            result["unmapped"].append(entry)
            continue
        parsed_entry = _parse_reply_entry(entry, questions_by_id)
        if questions_by_id and parsed_entry["questionId"] not in questions_by_id:
            # 卡已匹配但 questionId 不在卡内：映射失败，原样留档。
            result["unmapped"].append(entry)
            continue
        result["answers"].append(parsed_entry)
    return result


def apply_reply(
    store: "IntentAlignmentStore",
    session_id: str,
    reply: Any,
    turn_ref: Mapping[str, Any],
    card_payload: Any = None,
) -> dict[str, Any]:
    """回执落账辅助（§2.1 gate P1 / §4.4）：映射成功的每题转调 store.record_answer。

    - 一律 merge=None（§3.4-2 gate 回执路径）：只落台账、标 answered、存答案原文，
      不产生结构化变更与新版本；语义归并仍归主 agent 的 intent_alignment_merge。
    - 映射不到（schema 非法 / 卡不匹配 / questionId 不在当前台账——含未问过、
      已答、已撤销——）的条目原样留档进 unmapped 返回，由调用方（worker gate /
      agent）处置；台账 askedInCard 非空且与回执 cardId 不一致同样留档。
    - 任何单题失败不阻断其余题：逐题 try，错误收集进 failed。
    - action="dismiss"：store 处置为设计开放点（§5.3 / §7.2-9），保守不动 store，
      解析结果经 parsed 原样返回。

    返回 ``{action, ok, errors, dismissed, applied, skipped, failed, unmapped,
    storeTouched, parsed}``。
    """
    parsed = parse_intent_alignment_reply(reply, card_payload)
    outcome: dict[str, Any] = {
        "action": parsed["action"],
        "ok": parsed["ok"],
        "errors": list(parsed["errors"]),
        "dismissed": parsed["action"] == "dismiss",
        "applied": [],
        "skipped": [],
        "failed": [],
        "unmapped": list(parsed["unmapped"]),
        "storeTouched": False,
        "parsed": parsed,
    }
    if not parsed["ok"] or outcome["dismissed"]:
        # schema 非法或 dismiss：不写 store；已解析条目并入 unmapped 留档。
        outcome["unmapped"].extend(entry["raw"] for entry in parsed["answers"])
        return outcome

    normalized_turn = _normalize_turn_ref(turn_ref)
    open_by_id = {
        str(question.get("id") or ""): question
        for question in store.open_questions(session_id)
    }
    for answer in parsed["answers"]:
        question_id = answer["questionId"]
        raw_entry = answer["raw"]
        ledger_question = open_by_id.get(question_id)
        if ledger_question is None:
            # 台账无此问题（未问过/已答/已撤销）：原样留档，由调用方处置。
            outcome["unmapped"].append(raw_entry)
            continue
        asked_in_card = str(ledger_question.get("askedInCard") or "")
        if asked_in_card and asked_in_card != parsed["cardId"]:
            outcome["unmapped"].append(raw_entry)
            continue
        if answer["skipped"]:
            # skipped（required=False）：无可落账答案原文，保守保留 asked 交自判。
            outcome["skipped"].append({"questionId": question_id, "raw": raw_entry})
            continue
        try:
            store.record_answer(
                session_id,
                question_id,
                answer_text=answer["answerText"],
                turn_ref=normalized_turn,
                merge=None,
            )
        except Exception as exc:  # 逐题 try：单题失败不阻断其余题
            outcome["failed"].append(
                {"questionId": question_id, "raw": raw_entry, "error": str(exc)}
            )
            continue
        outcome["applied"].append(
            {"questionId": question_id, "answerText": answer["answerText"]}
        )
        outcome["storeTouched"] = True
    return outcome


# ── IntentAlignmentPacket 组装（§4.2） ────────────────────────────────────

_PACKET_SCHEMA_VERSION = 1
_CONFIRMED_REQUIREMENTS_LIMIT = 5
_SETTLED_AS_LIMIT = 80


def _point_text(value: Any) -> str:
    """一句话化：取文本（Mapping 取 text/criterion）并折叠全部空白。"""
    if isinstance(value, Mapping):
        value = value.get("text") or value.get("criterion") or ""
    return " ".join(str(value or "").split()).strip()


def _confirmed_requirement_points(snapshot: Mapping[str, Any]) -> list[str]:
    """四要素要点（≤5 条、一句话化）：goal 在首位，随后 boundaries/constraints/acceptance。"""
    points: list[str] = []
    goal_text = _point_text(snapshot.get("goal") or {})
    if goal_text:
        points.append(goal_text)
    for field in ("boundaries", "constraints"):
        for item in snapshot.get(field) or []:
            text = _point_text(item)
            if text:
                points.append(text)
    for item in snapshot.get("acceptance") or []:
        text = _point_text(item.get("criterion") if isinstance(item, Mapping) else item)
        if text:
            points.append(text)
    return points[:_CONFIRMED_REQUIREMENTS_LIMIT]


def assemble_packet(snapshot: Any, gate: Any) -> Optional[dict[str, Any]]:
    """组装 IntentAlignmentPacket（§4.2）。派生投影：纯函数，绝不回写 store。

    snapshot 为 store.get_current 的版本快照投影；None/空 → 返回 None（章节空态）。
    gate 为 run_rule_prefilter 的信号输出；None/非法时填充保守中性段。

    映射（§4.2）：
    - confirmedRequirements ← 当前版本四要素要点（≤5 条、一句话化；settledAt 记
      版本号；evidence（用户原话短引用）由归并路径回填，此处为空串）；
    - openQuestions ← 台账 asked ∧ 未 answered ∧ 未 withdrawn（impactFork←
      whyItMatters；options 台账不承载，由发卡侧 packet 刷新回填，此处为空表；
      askedAt←askedAtTurn，未记为 None）；
    - clarifyHistory ← 已答条目（settledAs 优先取 changes 中引用该 questionId 的
      折算结果并截断 80 字符；无折算记录为空串）；
    - budget.questionsAskedThisSession ← 台账全部条目计数（每条均经
      record_question_asked 进入台账，按累计提问量计以防追问循环）。
    """
    if not isinstance(snapshot, Mapping) or not snapshot.get("version"):
        return None
    try:
        version = int(snapshot["version"])
    except (TypeError, ValueError):
        return None
    ledger = list(snapshot.get("openQuestions") or [])

    change_notes: dict[str, list[str]] = {}
    for change in snapshot.get("changes") or []:
        if not isinstance(change, Mapping):
            continue
        question_id = str(change.get("questionId") or "")
        folded = _point_text(change.get("to"))
        if question_id and folded:
            change_notes.setdefault(question_id, []).append(folded)

    open_items: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for question in ledger:
        if not isinstance(question, Mapping):
            continue
        question_id = str(question.get("id") or "")
        status = str(question.get("status") or "")
        if status == "asked":
            open_items.append(
                {
                    "id": question_id,
                    "question": str(question.get("question") or ""),
                    "impactFork": str(question.get("whyItMatters") or ""),
                    "options": [],
                    "askedAt": str(question.get("askedAtTurn") or "") or None,
                }
            )
        elif status == "answered":
            settled = "；".join(change_notes.get(question_id, []))
            history.append(
                {
                    "questionId": question_id,
                    "question": str(question.get("question") or ""),
                    "answer": str((question.get("answer") or {}).get("text") or ""),
                    "settledAs": settled[:_SETTLED_AS_LIMIT],
                }
            )

    if isinstance(gate, Mapping):
        gate_segment: dict[str, Any] = dict(gate)
    else:
        gate_segment = {
            "action": "ask",
            "confidence": _GATE_CONFIDENCE_UNCERTAIN,
            "decidedBy": GATE_DECIDED_BY,
            "reason": "无预筛信号输入，保守交由本轮自判",
        }
    return {
        "schemaVersion": _PACKET_SCHEMA_VERSION,
        "status": "clarifying" if open_items else "aligned",
        "confirmedRequirements": [
            {"point": point, "settledAt": f"v{version}", "evidence": ""}
            for point in _confirmed_requirement_points(snapshot)
        ],
        "openQuestions": open_items,
        "clarifyHistory": history,
        "gate": gate_segment,
        "budget": {
            "questionsAskedThisSession": len(ledger),
            "maxQuestionsPerTurn": MAX_QUESTIONS_PER_TURN,
        },
    }


# ── agent 工具 handler（§3.5.2，T4） ─────────────────────────────────────
#
# 两个 handler 是 store 写路径的 agent 面（确定性：语义判断全部由主 agent 在
# 入参中给出，handler 只落账与刷新投影）。注册面与 todo_write 同族：
# tools/Key_Tools.py 的同名 @tool wrapper → tool_executor 从 create_key_tools
# 自动推导执行映射；工具调用参数与结果由 turn 机制统一 journal 成 tool_call
# turnItem（handler 不自行写 journal——落账机制唯一，禁止第二套执行机制）。
# 写后 packet 刷新经 PromptManager.set_intent_alignment_packet（§4.4 时点 2）；
# packet 只是投影，刷新失败不回滚 store 写入（fail-open，§8.2 D2）。

CARD_TOOL_NAME = "intent_alignment_card"
MERGE_TOOL_NAME = "intent_alignment_merge"

_MAX_CARD_QUESTIONS = 5
_MAX_CARD_OPTIONS = 6
_CARD_PAYLOAD_CHAR_LIMIT = 8 * 1024
_SHORT_QUOTE_LIMIT = 80

_INPUT_MODES = frozenset({"single_choice", "multi_choice", "free_text", "choice_or_text"})
_CHOICE_MODES = frozenset({"single_choice", "multi_choice", "choice_or_text"})


def _tool_error(code: str, message: str) -> dict[str, Any]:
    """结构化错误返回（agent 可读、可据此先补 merge 再重试），不抛异常打断 turn。"""
    return {"status": "error", "code": code, "message": message}


def _tool_error_from_exc(exc: Exception, fallback_code: str) -> dict[str, Any]:
    if isinstance(exc, IntentAlignmentVersionConflictError):
        return _tool_error("VERSION_CONFLICT", str(exc))
    if isinstance(exc, IntentAlignmentInvalidTransitionError):
        return _tool_error("INVALID_TRANSITION", str(exc))
    if isinstance(exc, IntentAlignmentArtifactNotFoundError):
        return _tool_error("NO_ARTIFACT", str(exc))
    return _tool_error(fallback_code, str(exc))


def _runtime_session_context() -> tuple[str, dict[str, str]]:
    """从当前 agent runtime 上下文解析 (sessionId, turn_ref)（plan_tools 同源）。

    上下文缺失（测试直调 / 非会话执行环境）返回空串，由调用方决定拒绝方式。
    """
    from core.web.services.agent_directory_service import current_agent_runtime

    runtime = current_agent_runtime() or {}
    session_id = str(runtime.get("sessionId") or "").strip()
    turn_ref = {
        "sessionId": session_id,
        "turnId": str(runtime.get("turnId") or "").strip(),
        "messageId": "",
    }
    return session_id, turn_ref


def _normalize_card_question(index: int, raw: Any) -> tuple[dict[str, Any], str]:
    """规范化单题（§3.5.2 入参 → 台账写入 + §5.2 payload 双形态）；返回 (题, 错误)。"""
    if not isinstance(raw, Mapping):
        return {}, f"questions 第 {index} 项不是对象"
    question = str(raw.get("question") or raw.get("prompt") or "").strip()
    if not question:
        return {}, f"questions 第 {index} 项缺少 question"
    input_mode = str(raw.get("input_mode") or raw.get("inputMode") or "").strip()
    if input_mode not in _INPUT_MODES:
        return {}, (
            f"questions 第 {index} 项 input_mode 无效：{input_mode or '空'}。"
            "可用：single_choice / multi_choice / free_text / choice_or_text"
        )
    options: list[dict[str, Any]] = []
    if input_mode in _CHOICE_MODES:
        raw_options = raw.get("options")
        if not isinstance(raw_options, (list, tuple)) or not raw_options:
            return {}, f"questions 第 {index} 项为选择题，必须提供 options"
        if len(raw_options) > _MAX_CARD_OPTIONS:
            return {}, f"questions 第 {index} 项选项数超过 {_MAX_CARD_OPTIONS}"
        seen_option_ids: set[str] = set()
        for option_index, option in enumerate(raw_options, 1):
            if not isinstance(option, Mapping):
                return {}, f"questions 第 {index} 项第 {option_index} 个选项不是对象"
            option_id = str(option.get("option_id") or option.get("optionId") or "").strip()
            label = str(option.get("label") or "").strip()
            if not option_id or not label:
                return {}, f"questions 第 {index} 项第 {option_index} 个选项缺少 option_id/label"
            if option_id in seen_option_ids:
                return {}, f"questions 第 {index} 项选项 option_id 重复：{option_id}"
            seen_option_ids.add(option_id)
            entry: dict[str, Any] = {"optionId": option_id, "label": label}
            hint = str(option.get("hint") or "").strip()
            if hint:
                entry["hint"] = hint
            options.append(entry)
    required_raw = raw.get("required", True)
    required = bool(required_raw) if isinstance(required_raw, bool) else True
    normalized: dict[str, Any] = {
        "question_id": str(raw.get("question_id") or raw.get("questionId") or "").strip(),
        "question": question,
        "why_it_matters": str(raw.get("why_it_matters") or raw.get("whyItMatters") or "").strip(),
        "applies_to": str(raw.get("applies_to") or raw.get("appliesTo") or "").strip(),
        "input_mode": input_mode,
        "options": options,
        "required": required,
        "placeholder": str(raw.get("placeholder") or "").strip(),
    }
    return normalized, ""


def _normalize_card_artifacts(raw: Any) -> tuple[list[dict[str, Any]], str]:
    """规范化 artifacts 只读引用（§5.2 artifacts 形态）；返回 (列表, 错误)。"""
    if raw is None:
        return [], ""
    if not isinstance(raw, (list, tuple)):
        return [], "artifacts 需要是列表"
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, Mapping):
            return [], f"artifacts 第 {index} 项不是对象"
        artifact_id = str(item.get("artifact_id") or item.get("artifactId") or "").strip()
        title = str(item.get("title") or "").strip()
        if not artifact_id or not title:
            return [], f"artifacts 第 {index} 项缺少 artifact_id/title"
        try:
            version = int(item.get("version"))
        except (TypeError, ValueError):
            return [], f"artifacts 第 {index} 项 version 必须是整数"
        result.append({"artifactId": artifact_id, "version": version, "title": title})
    return result, ""


def _known_card_ids(store: "IntentAlignmentStore", session_id: str, up_to_version: int) -> set[str]:
    """收集台账已出现过的 cardId（各版本 confirmation.cardId + askedInCard），供唯一性检查。"""
    known: set[str] = set()
    for number in range(1, int(up_to_version) + 1):
        snapshot = store.get_version(session_id, number)
        if not snapshot:
            continue
        card_id = str((snapshot.get("confirmation") or {}).get("cardId") or "")
        if card_id:
            known.add(card_id)
        for question in snapshot.get("openQuestions") or []:
            card_ref = str((question or {}).get("askedInCard") or "")
            if card_ref:
                known.add(card_ref)
    return known


def _generate_card_id(store: "IntentAlignmentStore", session_id: str, revision: int) -> str:
    """发卡时生成同会话唯一 cardId（§3.9：handler 生成；ia_ 前缀 + 随机 hex）。"""
    known = _known_card_ids(store, session_id, revision)
    for _ in range(16):
        candidate = f"ia_{uuid.uuid4().hex[:10]}"
        if candidate not in known:
            return candidate
    # 16 次连撞（概率 ~0）时退化为完整 hex，仍保持同会话唯一。
    return f"ia_{uuid.uuid4().hex}"


def _card_payload_size_estimate(questions: list[dict[str, Any]]) -> int:
    """payload 尺寸预估（写台账前守 8KB 建议上限；questionId 用占位估长）。"""
    payload = _build_card_payload(
        card_id="ia_estimate",
        revision=0,
        intent_summary="",
        questions=questions,
        question_ids=[entry["question_id"] or "q0" for entry in questions],
        artifacts=None,
    )
    return len(json.dumps(payload, ensure_ascii=False))


def _build_card_payload(
    *,
    card_id: str,
    revision: int,
    intent_summary: str,
    questions: list[dict[str, Any]],
    question_ids: list[str],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    """组装 IntentAlignmentCardPayload（§5.2 schema）。"""
    payload_questions: list[dict[str, Any]] = []
    for entry, question_id in zip(questions, question_ids):
        item: dict[str, Any] = {
            "questionId": question_id,
            "prompt": entry["question"],
            "inputMode": entry["input_mode"],
        }
        if entry["options"]:
            item["options"] = entry["options"]
        if entry["input_mode"] == "choice_or_text":
            item["allowCustomAnswer"] = True
        if not entry["required"]:
            item["required"] = False
        if entry["placeholder"]:
            item["placeholder"] = entry["placeholder"]
        payload_questions.append(item)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "kind": _CARD_KIND,
        "cardId": card_id,
        "revision": int(revision),
        "intentSummary": intent_summary,
    }
    if artifacts:
        payload["artifacts"] = artifacts
    payload["questions"] = payload_questions
    payload["status"] = "open"
    return payload


def _resolve_prompt_manager(prompt_manager: Any) -> Any:
    if prompt_manager is not None:
        return prompt_manager
    from core.prompt_manager.prompt_manager import get_prompt_manager

    return get_prompt_manager()


def _refresh_intent_packet(
    store: "IntentAlignmentStore",
    session_id: str,
    prompt_manager: Any,
    *,
    options_by_question_id: Optional[Mapping[str, list[str]]] = None,
    evidence_by_question_id: Optional[Mapping[str, str]] = None,
) -> None:
    """写后刷新 PromptManager 内 packet（§4.4 时点 2）。

    store 快照 → assemble_packet（gate 段缺省保守中性）→ 回填 T2 契约委托给
    handler 的两个空位（openQuestions[].options ← 发卡 questions 入参；
    confirmedRequirements[].evidence ← 归并答案原文短引用）→ set 注入。
    packet 只是投影：无工件不注入；刷新异常静默直通（fail-open，权威在 store）。
    """
    try:
        snapshot = store.get_current(session_id)
        if snapshot is None:
            return
        packet = assemble_packet(snapshot, None)
        if packet is None:
            return
        if options_by_question_id:
            for item in packet.get("openQuestions") or []:
                labels = options_by_question_id.get(str(item.get("id") or ""))
                if labels:
                    item["options"] = list(labels)
        if evidence_by_question_id:
            evidence_map: dict[str, str] = {}
            for change in snapshot.get("changes") or []:
                if not isinstance(change, Mapping):
                    continue
                quote = evidence_by_question_id.get(str(change.get("questionId") or ""))
                if not quote:
                    continue
                folded = change.get("to")
                if isinstance(folded, (list, tuple)):
                    points = [_point_text(item) for item in folded]
                else:
                    points = [_point_text(folded)]
                for point in points:
                    if point:
                        evidence_map.setdefault(point, quote[:_SHORT_QUOTE_LIMIT])
            for item in packet.get("confirmedRequirements") or []:
                quote = evidence_map.get(str(item.get("point") or ""))
                if quote and not str(item.get("evidence") or ""):
                    item["evidence"] = quote
        _resolve_prompt_manager(prompt_manager).set_intent_alignment_packet(packet)
    except Exception:
        # 投影刷新绝不阻断权威写入（§8.2 D2 fail-open；packet 层无语义归并）。
        return


def intent_alignment_card_handler(
    session_id: str,
    *,
    intent_summary: str,
    questions: Any,
    artifacts: Any = None,
    turn_ref: Optional[Mapping[str, Any]] = None,
    store: Optional["IntentAlignmentStore"] = None,
    prompt_manager: Any = None,
) -> dict[str, Any]:
    """intent_alignment_card 确定性 handler（§3.5.2）。

    前置：工件已有四要素初稿（agent 先 merge 再发卡）；不满足返回结构化错误
    （status=error + code），不落卡、不动台账、不 journal。
    步骤：cardId 生成（§3.9）→ record_question_asked ×N（question_id 有值沿用、
    缺省台账分配；记 asked_in_card）→ request_confirmation（draft →
    pending_confirmation，绑定 cardId 与发卡 turn）→ 组装 §5.2 payload（含台账
    分配的最终 questionId）随工具结果返回（turn 机制把它与调用参数一起落成
    tool_call turnItem）→ 刷新 packet 并回填 options。
    """
    summary = str(intent_summary or "").strip()
    if not summary:
        return _tool_error("INVALID_QUESTIONS", "intent_summary 不能为空（卡片头部一句话）")
    if not isinstance(questions, (list, tuple)) or not questions:
        return _tool_error("INVALID_QUESTIONS", "questions 需要是非空列表（一次问完，不拆多轮）")
    if len(questions) > _MAX_CARD_QUESTIONS:
        return _tool_error(
            "INVALID_QUESTIONS", f"questions 一次最多 {_MAX_CARD_QUESTIONS} 个，请挑最影响走向的"
        )
    normalized_questions: list[dict[str, Any]] = []
    for index, raw in enumerate(questions, 1):
        entry, error = _normalize_card_question(index, raw)
        if error:
            return _tool_error("INVALID_QUESTIONS", error)
        normalized_questions.append(entry)
    normalized_artifacts, error = _normalize_card_artifacts(artifacts)
    if error:
        return _tool_error("INVALID_QUESTIONS", error)
    if _card_payload_size_estimate(normalized_questions) > _CARD_PAYLOAD_CHAR_LIMIT:
        return _tool_error(
            "CARD_TOO_LARGE",
            f"卡片 payload 超过 {_CARD_PAYLOAD_CHAR_LIMIT} 字符建议上限，请压缩问题/选项文本",
        )

    store = store or get_intent_alignment_store()
    try:
        snapshot = store.get_current(session_id)
        if snapshot is None:
            return _tool_error(
                "NO_ARTIFACT",
                "当前会话还没有意图对齐工件：先用 intent_alignment_merge 落四要素初稿再发卡",
            )
        try:
            _require_four_elements(snapshot)
        except ValueError as exc:
            return _tool_error(
                "NO_FOUR_ELEMENTS", f"{exc}；先用 intent_alignment_merge 补齐初稿再发卡"
            )
        if str(snapshot.get("status") or "") != _STATUS_DRAFT:
            return _tool_error(
                "INVALID_TRANSITION",
                f"当前版本 {snapshot.get('version')} 状态为 {snapshot.get('status')}，"
                "发卡只允许 draft；如需改问先用 intent_alignment_merge 归并出新 draft 再发新卡",
            )
        revision = int(snapshot["version"])
        card_id = _generate_card_id(store, session_id, revision)
        asked_ids: list[str] = []
        for entry in normalized_questions:
            asked_ids.append(
                store.record_question_asked(
                    session_id,
                    question=entry["question"],
                    why_it_matters=entry["why_it_matters"],
                    applies_to=entry["applies_to"],
                    turn_ref=turn_ref,
                    question_id=entry["question_id"],
                    asked_in_card=card_id,
                )
            )
        store.request_confirmation(session_id, card_id=card_id, turn_ref=turn_ref or {})
    except (IntentAlignmentError, ValueError) as exc:
        return _tool_error_from_exc(exc, "CARD_FAILED")

    payload = _build_card_payload(
        card_id=card_id,
        revision=revision,
        intent_summary=summary,
        questions=normalized_questions,
        question_ids=asked_ids,
        artifacts=normalized_artifacts,
    )
    _refresh_intent_packet(
        store,
        session_id,
        prompt_manager,
        options_by_question_id={
            str(entry.get("questionId") or ""): [
                str(option.get("label") or "") for option in (entry.get("options") or [])
            ]
            for entry in payload["questions"]
        },
    )
    return {
        "status": "ok",
        "cardId": card_id,
        "revision": revision,
        "questionIds": asked_ids,
        "artifactStatus": _STATUS_PENDING_CONFIRMATION,
        "payload": payload,
        "message": "已发卡并登记台账，工件转入 pending_confirmation；请以正文文本提出同样的问题（正文是用户可见的提问本体）。",
    }


def _overlay_structured(
    store: "IntentAlignmentStore", session_id: str, structured: Mapping[str, Any]
) -> dict[str, Any]:
    """把 merge 的 partial structured 叠加到当前版本内容上（未提供字段保持原值）。

    record_structured 是全量重写语义（五个内容字段必填）；agent 的 merge 入参
    允许只带部分字段——直接透传会把未提供字段清空。 assumptions 按 id 叠加：
    已有 id 覆盖对应条目，新条目显式分配下一个序号（避免 record_structured 的
    start_index=1 重排与既有 id 冲突）。
    """
    current = store.get_current(session_id)
    goal = current.get("goal") if current else None
    merged_goal = structured.get("goal")
    if merged_goal is None:
        goal_value: Any = (goal or {}).get("text") if isinstance(goal, Mapping) else goal
    else:
        goal_value = merged_goal

    def merged_list(field: str) -> Any:
        provided = structured.get(field)
        if provided is not None:
            return provided
        return list(current.get(field) or []) if current else []

    assumptions_current = list((current or {}).get("assumptions") or [])
    next_index = 1
    for item in assumptions_current:
        suffix = re.fullmatch(r"a(\d+)", str(item.get("id") or "")) if isinstance(item, Mapping) else None
        if suffix:
            next_index = max(next_index, int(suffix.group(1)) + 1)
    if "assumptions" not in structured:
        # 未提及 assumptions：原样保留（record_structured 全量重写语义下防误清空）。
        merged_assumptions: list[Any] = assumptions_current
    else:
        # 显式提供的 assumptions 即本轮全量声明：按 id 覆盖对应条目，新条目
        # 显式分配下一个序号（避免 record_structured 的 start_index=1 重排冲突）。
        merged_assumptions = []
        for item in structured.get("assumptions") or []:
            if isinstance(item, Mapping) and not item.get("id"):
                item = {**item, "id": f"a{next_index}"}
                next_index += 1
            merged_assumptions.append(item)
    return {
        "goal": goal_value,
        "boundaries": merged_list("boundaries"),
        "constraints": merged_list("constraints"),
        "acceptance": merged_list("acceptance"),
        "assumptions": merged_assumptions,
    }


def intent_alignment_merge_handler(
    session_id: str,
    *,
    answers: Any = None,
    structured: Any = None,
    confirmation: Any = None,
    turn_ref: Optional[Mapping[str, Any]] = None,
    store: Optional["IntentAlignmentStore"] = None,
    prompt_manager: Any = None,
) -> dict[str, Any]:
    """intent_alignment_merge 确定性 handler（§3.5.2）。

    answers / structured / confirmation 三段转调 store：record_answer（逐题，
    merge 指令透传）/ record_structured（partial 叠加当前版本，首次写入经
    open_or_load 创建 v1(draft)，origin.mode="chat"）/ submit_confirmation_decision。
    写后刷新 packet 并回填 evidence；返回 {artifactId, version, artifactStatus}。
    """
    if answers is None and structured is None and confirmation is None:
        return _tool_error("EMPTY_MERGE", "至少提供 answers / structured / confirmation 之一")

    store = store or get_intent_alignment_store()
    try:
        if structured is not None:
            if not isinstance(structured, Mapping):
                return _tool_error("INVALID_STRUCTURED", "structured 需要是对象")
            overlay = _overlay_structured(store, session_id, structured)
            if store.get_current(session_id) is None:
                store.open_or_load(
                    session_id,
                    origin={"mode": "chat", "roomId": "", "sourceTextDigest": ""},
                )
            latest = store.record_structured(
                session_id,
                goal=overlay["goal"],
                boundaries=overlay["boundaries"],
                constraints=overlay["constraints"],
                acceptance=overlay["acceptance"],
                assumptions=overlay["assumptions"],
            )
        else:
            latest = None

        answered_ids: list[str] = []
        evidence_by_question_id: dict[str, str] = {}
        for index, entry in enumerate(answers or [], 1):
            if not isinstance(entry, Mapping):
                return _tool_error("INVALID_ANSWERS", f"answers 第 {index} 项不是对象")
            question_id = str(entry.get("question_id") or entry.get("questionId") or "").strip()
            answer_text = str(entry.get("answer_text") or entry.get("answerText") or "").strip()
            if not question_id:
                return _tool_error("INVALID_ANSWERS", f"answers 第 {index} 项缺少 question_id")
            if not answer_text:
                return _tool_error(
                    "INVALID_ANSWERS", f"answers 第 {index} 项（{question_id}）缺少 answer_text；跳过的问题不必提交"
                )
            merge_updates = entry.get("merge")
            version_snapshot = store.record_answer(
                session_id,
                question_id,
                answer_text=answer_text,
                turn_ref=turn_ref or {},
                merge=[dict(item) for item in merge_updates] if isinstance(merge_updates, (list, tuple)) else None,
            )
            answered_ids.append(question_id)
            evidence_by_question_id[question_id] = answer_text
            if version_snapshot is not None:
                latest = version_snapshot

        if confirmation is not None:
            if not isinstance(confirmation, Mapping):
                return _tool_error("INVALID_CONFIRMATION", "confirmation 需要是对象")
            decision = str(confirmation.get("decision") or "").strip()
            note = str(confirmation.get("note") or "").strip()
            latest = store.submit_confirmation_decision(
                session_id, decision=decision, turn_ref=turn_ref or {}, note=note
            )
    except (IntentAlignmentError, ValueError) as exc:
        return _tool_error_from_exc(exc, "MERGE_FAILED")

    _refresh_intent_packet(
        store, session_id, prompt_manager, evidence_by_question_id=evidence_by_question_id
    )
    latest = latest or store.get_current(session_id) or {}
    return {
        "status": "ok",
        "artifactId": session_id,
        "version": int(latest.get("version") or 0),
        "artifactStatus": str(latest.get("status") or ""),
        "answeredQuestionIds": answered_ids,
        "message": "归并已落账；收到用户回答后先归并再继续推进。",
    }
