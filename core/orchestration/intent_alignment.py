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
T1 范围不含：规则预筛 / 回执解析 / packet 组装（T2）、工具 handler（T4）、
markdown 渲染（章节读 ctx packet，不读本 store）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
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
