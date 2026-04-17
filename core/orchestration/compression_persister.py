#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
压缩上下文持久化器

将 LLM Context 压缩快照保存到磁盘，实现跨会话恢复。

功能：
- 压缩快照保存/加载
- 关键决策记录
- 工具使用统计持久化
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime


@dataclass
class CompressedSnapshot:
    """压缩快照"""
    id: str = ""
    generation: int = 1
    timestamp: str = ""
    reason: str = ""
    before_tokens: int = 0
    after_tokens: int = 0
    compression_ratio: float = 0.0
    level: str = "standard"  # light, standard, deep, emergency
    summary: str = ""
    key_decisions: List[Dict[str, Any]] = field(default_factory=list)
    preserved_messages: List[Dict[str, Any]] = field(default_factory=list)
    tool_stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompressedSnapshot":
        return cls(**data)


@dataclass
class DecisionRecord:
    """关键决策记录"""
    timestamp: str = ""
    decision: str = ""
    context: str = ""
    outcome: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CompressionPersister:
    """
    压缩上下文持久化器

    将压缩快照保存到 archives/ 目录，支持跨会话恢复。

    目录结构：
        workspace/memory/archives/
        ├── snapshots/
        │   ├── compressed_{gen}_{timestamp}.json
        │   └── ...
        ├── decisions/
        │   └── decisions_{gen}.jsonl
        └── tool_stats/
            └── tool_stats_{gen}.json
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化压缩持久化器

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)
        self.archives_dir = self.project_root / "workspace" / "memory" / "archives"
        self.snapshots_dir = self.archives_dir / "snapshots"
        self.decisions_dir = self.archives_dir / "decisions"
        self.tool_stats_dir = self.archives_dir / "tool_stats"

        # 确保目录存在
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """确保必要目录存在"""
        for dir_path in [self.snapshots_dir, self.decisions_dir, self.tool_stats_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def _generate_snapshot_id(self, generation: int) -> str:
        """生成快照 ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"compressed_{generation}_{timestamp}"

    def _generate_decision_id(self, generation: int) -> str:
        """生成决策记录 ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"decision_{generation}_{timestamp}"

    # =========================================================================
    # 快照操作
    # =========================================================================

    def save_snapshot(
        self,
        generation: int,
        messages: List[Any],
        summary: str,
        before_tokens: int,
        after_tokens: int,
        level: str = "standard",
        reason: str = "",
        key_decisions: Optional[List[Dict[str, Any]]] = None,
        tool_stats: Optional[Dict[str, int]] = None,
    ) -> CompressedSnapshot:
        """
        保存压缩快照

        Args:
            generation: 当前世代
            messages: 压缩后的消息列表
            summary: 压缩摘要
            before_tokens: 压缩前 token 数
            after_tokens: 压缩后 token 数
            level: 压缩级别
            reason: 压缩原因
            key_decisions: 关键决策列表
            tool_stats: 工具统计

        Returns:
            压缩快照对象
        """
        snapshot_id = self._generate_snapshot_id(generation)
        timestamp = datetime.now().isoformat()

        # 序列化消息（提取关键字段）
        serialized_messages = []
        for msg in messages[-20:]:  # 只保存最近 20 条消息
            serialized_messages.append({
                "type": getattr(msg, 'type', 'unknown'),
                "content": str(getattr(msg, 'content', ''))[:500],  # 截断
                "tool_calls": [
                    {"name": tc.get('name', ''), "args": str(tc.get('args', {}))[:200]}
                    for tc in getattr(msg, 'tool_calls', []) or []
                ],
            })

        snapshot = CompressedSnapshot(
            id=snapshot_id,
            generation=generation,
            timestamp=timestamp,
            reason=reason or f"compression_{level}",
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            compression_ratio=before_tokens / after_tokens if after_tokens > 0 else 0,
            level=level,
            summary=summary,
            key_decisions=key_decisions or [],
            preserved_messages=serialized_messages,
            tool_stats=tool_stats or {},
        )

        # 保存到文件
        snapshot_file = self.snapshots_dir / f"{snapshot_id}.json"
        with open(snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)

        return snapshot

    def load_snapshot(self, snapshot_id: str) -> Optional[CompressedSnapshot]:
        """
        加载压缩快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            压缩快照对象，不存在返回 None
        """
        snapshot_file = self.snapshots_dir / f"{snapshot_id}.json"
        if not snapshot_file.exists():
            return None

        try:
            with open(snapshot_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return CompressedSnapshot.from_dict(data)
        except Exception:
            return None

    def load_latest_snapshot(self, generation: int) -> Optional[CompressedSnapshot]:
        """
        加载指定世代的最新快照

        Args:
            generation: 世代号

        Returns:
            最新压缩快照
        """
        pattern = f"compressed_{generation}_*.json"
        matches = list(self.snapshots_dir.glob(pattern))

        if not matches:
            return None

        # 按修改时间排序，返回最新的
        latest = sorted(matches, key=lambda p: p.stat().st_mtime)[-1]
        snapshot_id = latest.stem

        return self.load_snapshot(snapshot_id)

    def list_snapshots(self, generation: Optional[int] = None) -> List[CompressedSnapshot]:
        """
        列出压缩快照

        Args:
            generation: 世代号，None 表示所有

        Returns:
            压缩快照列表
        """
        if generation is not None:
            pattern = f"compressed_{generation}_*.json"
        else:
            pattern = "compressed_*.json"

        snapshots = []
        for file in self.snapshots_dir.glob(pattern):
            snapshot_id = file.stem
            snapshot = self.load_snapshot(snapshot_id)
            if snapshot:
                snapshots.append(snapshot)

        # 按时间排序
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots

    # =========================================================================
    # 决策记录操作
    # =========================================================================

    def save_decision(
        self,
        generation: int,
        decision: str,
        context: str = "",
        outcome: str = "",
    ) -> DecisionRecord:
        """
        保存关键决策

        Args:
            generation: 世代号
            decision: 决策内容
            context: 决策上下文
            outcome: 决策结果

        Returns:
            决策记录对象
        """
        record = DecisionRecord(
            timestamp=datetime.now().isoformat(),
            decision=decision,
            context=context,
            outcome=outcome,
        )

        # 保存到 JSONL 文件
        decision_file = self.decisions_dir / f"decisions_{generation}.jsonl"
        with open(decision_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + '\n')

        return record

    def load_decisions(self, generation: int) -> List[DecisionRecord]:
        """
        加载指定世代的所有决策

        Args:
            generation: 世代号

        Returns:
            决策记录列表
        """
        decision_file = self.decisions_dir / f"decisions_{generation}.jsonl"
        if not decision_file.exists():
            return []

        decisions = []
        with open(decision_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    decisions.append(DecisionRecord(**data))

        return decisions

    # =========================================================================
    # 工具统计操作
    # =========================================================================

    def save_tool_stats(self, generation: int, tool_stats: Dict[str, int]) -> None:
        """
        保存工具使用统计

        Args:
            generation: 世代号
            tool_stats: 工具统计 {tool_name: count}
        """
        stats_file = self.tool_stats_dir / f"tool_stats_{generation}.json"
        data = {
            "generation": generation,
            "timestamp": datetime.now().isoformat(),
            "stats": tool_stats,
            "total_calls": sum(tool_stats.values()),
        }
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_tool_stats(self, generation: int) -> Optional[Dict[str, Any]]:
        """
        加载工具使用统计

        Args:
            generation: 世代号

        Returns:
            工具统计数据
        """
        stats_file = self.tool_stats_dir / f"tool_stats_{generation}.json"
        if not stats_file.exists():
            return None

        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    # =========================================================================
    # 统计信息
    # =========================================================================

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        获取存储统计

        Returns:
            存储统计信息
        """
        snapshot_files = list(self.snapshots_dir.glob("compressed_*.json"))
        decision_files = list(self.decisions_dir.glob("decisions_*.jsonl"))
        tool_stats_files = list(self.tool_stats_dir.glob("tool_stats_*.json"))

        total_size = 0
        for f in snapshot_files:
            total_size += f.stat().st_size

        return {
            "snapshot_count": len(snapshot_files),
            "decision_file_count": len(decision_files),
            "tool_stats_file_count": len(tool_stats_files),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }

    def cleanup_old_snapshots(self, keep_count: int = 10) -> int:
        """
        清理旧快照，保留最近的

        Args:
            keep_count: 保留数量

        Returns:
            清理的快照数量
        """
        snapshots = self.list_snapshots()
        if len(snapshots) <= keep_count:
            return 0

        removed = 0
        for snapshot in snapshots[keep_count:]:
            snapshot_file = self.snapshots_dir / f"{snapshot.id}.json"
            if snapshot_file.exists():
                snapshot_file.unlink()
                removed += 1

        return removed


# ============================================================================
# 全局单例
# ============================================================================

_persister: Optional[CompressionPersister] = None


def get_compression_persister(project_root: Optional[str] = None) -> CompressionPersister:
    """
    获取压缩持久化器单例

    Args:
        project_root: 项目根目录

    Returns:
        CompressionPersister 实例
    """
    global _persister
    if _persister is None:
        _persister = CompressionPersister(project_root)
    return _persister


def reset_compression_persister() -> None:
    """重置压缩持久化器单例"""
    global _persister
    _persister = None
