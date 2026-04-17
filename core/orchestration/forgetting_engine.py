#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
遗忘引擎

实现选择性遗忘机制，自动清理低价值记忆。

功能：
- 记忆价值评估
- 自动遗忘低价值记忆
- 遗忘回收站
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ForgettingRecord:
    """遗忘记录"""
    memory_id: str = ""
    content: str = ""
    memory_type: str = "general"
    importance: float = 0.0
    access_count: int = 0
    created_at: str = ""
    forgotten_at: str = ""
    reason: str = ""  # low_value, old, contradictory, manual


class ForgettingEngine:
    """
    遗忘引擎

    负责判断哪些记忆应该被遗忘，并执行遗忘操作。
    """

    # 遗忘阈值配置
    FORGET_THRESHOLDS = {
        "min_importance": 0.2,      # 重要性低于此值
        "max_age_days": 90,          # 超过此天数无访问
        "min_access_afterCreation": 0,  # 创建后最少访问次数
        "max_access_count": 3,      # 访问次数低于此值且较老
    }

    # 记忆类型权重（某些类型不容易遗忘）
    TYPE_WEIGHTS = {
        "decision": 1.5,    # 决策不容易遗忘
        "insight": 1.3,     # 洞察不容易遗忘
        "code": 1.2,        # 代码不容易遗忘
        "tool": 0.8,       # 工具使用容易遗忘
        "general": 1.0,     # 一般记忆标准权重
    }

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化遗忘引擎

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)
        self.forgotten_dir = self.project_root / "workspace" / "memory" / "forgotten"
        self.forgotten_dir.mkdir(parents=True, exist_ok=True)

        # 加载遗忘记录
        self._forgetting_log = self.forgotten_dir / "forgetting_log.jsonl"

    def _load_forgetting_log(self) -> List[ForgettingRecord]:
        """加载遗忘日志"""
        if not self._forgetting_log.exists():
            return []

        records = []
        try:
            with open(self._forgetting_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        records.append(ForgettingRecord(**data))
        except Exception:
            pass
        return records

    def _save_forgetting_record(self, record: ForgettingRecord) -> None:
        """保存遗忘记录"""
        with open(self._forgetting_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record.__dict__, ensure_ascii=False) + '\n')

    def should_forget(
        self,
        entry: Any,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """
        判断记忆是否应该被遗忘

        Args:
            entry: 记忆条目（需要有空属性: id, content, memory_type, importance, access_count, timestamp）
            current_time: 当前时间

        Returns:
            (是否遗忘, 原因)
        """
        if current_time is None:
            current_time = datetime.now()

        # 解析创建时间
        created_at = entry.timestamp
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except Exception:
                created_at = None

        # 类型权重
        type_weight = self.TYPE_WEIGHTS.get(entry.memory_type, 1.0)

        # 加权重要性
        weighted_importance = entry.importance * type_weight

        # 1. 检查加权重要性是否过低
        if weighted_importance < self.FORGET_THRESHOLDS["min_importance"]:
            if entry.access_count == 0:
                return True, "low_value_unaccessed"
            if entry.access_count <= self.FORGET_THRESHOLDS["max_access_count"]:
                return True, "low_value_low_access"

        # 2. 检查是否过旧
        if created_at:
            age_days = (current_time - created_at).days
            if age_days > self.FORGET_THRESHOLDS["max_age_days"]:
                if entry.access_count == 0:
                    return True, "old_unaccessed"
                # 虽然旧但有访问，不容易遗忘
                if entry.access_count <= 2 and age_days > self.FORGET_THRESHOLDS["max_age_days"] * 2:
                    return True, "very_old_low_access"

        # 3. 长期未访问
        if hasattr(entry, 'last_access') and entry.last_access:
            try:
                last_access = datetime.fromisoformat(entry.last_access)
                days_since_access = (current_time - last_access).days
                if days_since_access > self.FORGET_THRESHOLDS["max_age_days"] * 0.8:
                    if entry.access_count == 0:
                        return True, "long_unaccessed"
            except Exception:
                pass

        return False, ""

    def forget(
        self,
        memory_id: str,
        entry: Any,
        reason: str,
    ) -> ForgettingRecord:
        """
        执行遗忘

        Args:
            memory_id: 记忆 ID
            entry: 记忆条目
            reason: 遗忘原因

        Returns:
            遗忘记录
        """
        record = ForgettingRecord(
            memory_id=memory_id,
            content=entry.content[:500] if hasattr(entry, 'content') else "",  # 只保存前500字符
            memory_type=entry.memory_type if hasattr(entry, 'memory_type') else "unknown",
            importance=entry.importance if hasattr(entry, 'importance') else 0.0,
            access_count=entry.access_count if hasattr(entry, 'access_count') else 0,
            created_at=entry.timestamp if hasattr(entry, 'timestamp') else "",
            forgotten_at=datetime.now().isoformat(),
            reason=reason,
        )

        # 保存到遗忘日志
        self._save_forgetting_record(record)

        # 保存到回收站
        trash_file = self.forgotten_dir / f"{memory_id}.json"
        with open(trash_file, 'w', encoding='utf-8') as f:
            json.dump(record.__dict__, f, ensure_ascii=False, indent=2)

        return record

    def recover(self, memory_id: str) -> Optional[ForgettingRecord]:
        """
        恢复记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            恢复的遗忘记录
        """
        trash_file = self.forgotten_dir / f"{memory_id}.json"
        if not trash_file.exists():
            return None

        try:
            with open(trash_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 删除回收站文件
            trash_file.unlink()

            return ForgettingRecord(**data)
        except Exception:
            return None

    def cleanup_trash(self, keep_days: int = 30) -> int:
        """
        清理回收站

        Args:
            keep_days: 保留天数

        Returns:
            清理数量
        """
        if not self._forgetting_log.exists():
            return 0

        current_time = datetime.now()
        removed = 0

        # 重新写入，跳过已过期的
        valid_records = []
        with open(self._forgetting_log, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    try:
                        forgotten_at = datetime.fromisoformat(data["forgotten_at"])
                        if (current_time - forgotten_at).days <= keep_days:
                            valid_records.append(line)
                        else:
                            removed += 1
                            # 删除回收站文件
                            trash_file = self.forgotten_dir / f"{data['memory_id']}.json"
                            if trash_file.exists():
                                trash_file.unlink()
                    except Exception:
                        valid_records.append(line)

        # 重写日志
        with open(self._forgetting_log, 'w', encoding='utf-8') as f:
            for line in valid_records:
                f.write(line)

        return removed

    def get_forgetting_stats(self) -> Dict[str, Any]:
        """
        获取遗忘统计

        Returns:
            统计信息
        """
        records = self._load_forgetting_log()

        by_reason: Dict[str, int] = {}
        by_type: Dict[str, int] = {}

        for record in records:
            by_reason[record.reason] = by_reason.get(record.reason, 0) + 1
            by_type[record.memory_type] = by_type.get(record.memory_type, 0) + 1

        # 回收站文件数
        trash_files = list(self.forgotten_dir.glob("*.json"))
        # 减去 forgetting_log.json 本身
        trash_count = len([f for f in trash_files if f.name != "forgetting_log.jsonl"])

        return {
            "total_forgotten": len(records),
            "by_reason": by_reason,
            "by_type": by_type,
            "trash_count": trash_count,
        }


# ============================================================================
# 全局单例
# ============================================================================

_forgetting_engine: Optional[ForgettingEngine] = None


def get_forgetting_engine(project_root: Optional[str] = None) -> ForgettingEngine:
    """
    获取遗忘引擎单例

    Args:
        project_root: 项目根目录

    Returns:
        ForgettingEngine 实例
    """
    global _forgetting_engine
    if _forgetting_engine is None:
        _forgetting_engine = ForgettingEngine(project_root)
    return _forgetting_engine


def reset_forgetting_engine() -> None:
    """重置遗忘引擎单例"""
    global _forgetting_engine
    _forgetting_engine = None
