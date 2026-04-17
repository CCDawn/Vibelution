#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义记忆检索器

基于 embedding 的语义搜索能力，支持记忆的向量化存储和检索。

功能：
- 记忆 embedding 索引
- 语义相似度搜索
- 相关记忆检索
"""

from __future__ import annotations

import json
import os
import math
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryEntry:
    """记忆条目"""
    id: str = ""
    content: str = ""
    memory_type: str = "general"  # general, decision, insight, code, tool
    generation: int = 1
    timestamp: str = ""
    access_count: int = 0
    last_access: str = ""
    importance: float = 0.5  # 0.0 - 1.0
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "memory_type": self.memory_type,
            "generation": self.generation,
            "timestamp": self.timestamp,
            "access_count": self.access_count,
            "last_access": self.last_access,
            "importance": self.importance,
            # embedding 不保存到磁盘，按需计算
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=data["id"],
            content=data["content"],
            memory_type=data.get("memory_type", "general"),
            generation=data.get("generation", 1),
            timestamp=data.get("timestamp", ""),
            access_count=data.get("access_count", 0),
            last_access=data.get("last_access", ""),
            importance=data.get("importance", 0.5),
        )


class SimpleEmbedder:
    """
    简易文本嵌入器

    使用词频统计生成伪embedding，
    实际生产环境应替换为 OpenAI/Cohere 等商业 embedding API
    """

    def __init__(self):
        # 常见词权重
        self.important_words = {
            "优化": 2.0, "改进": 2.0, "修复": 2.0, "bug": 2.0,
            "错误": 1.5, "失败": 1.5, "成功": 1.5,
            "压缩": 1.8, "记忆": 1.8, "检索": 1.5,
            "工具": 1.2, "调用": 1.2, "执行": 1.2,
            "配置": 1.3, "设置": 1.3, "参数": 1.2,
        }
        self.dimension = 128  # 嵌入维度

    def embed(self, text: str) -> List[float]:
        """
        生成文本 embedding

        Args:
            text: 输入文本

        Returns:
             embedding 向量
        """
        # 简单词袋 + 位置编码
        words = text.lower().split()
        vector = [0.0] * self.dimension

        for i, word in enumerate(words):
            # 词权重
            weight = self.important_words.get(word, 1.0)
            # 位置衰减
            pos_weight = 1.0 / (1.0 + i * 0.1)
            # 哈希到维度
            idx = hash(word) % self.dimension

            vector[idx] += weight * pos_weight

        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class SemanticRetriever:
    """
    语义记忆检索器

    支持：
    - 记忆索引和存储
    - 语义相似度搜索
    - 基于类型的过滤检索
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化语义检索器

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)
        self.memory_dir = self.project_root / "workspace" / "memory"
        self.index_file = self.memory_dir / "semantic_index.json"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 嵌入器
        self.embedder = SimpleEmbedder()

        # 记忆索引 {memory_id: MemoryEntry}
        self.index: Dict[str, MemoryEntry] = {}
        self._id_counter = 0

        # 加载已有索引
        self._load_index()

    def _generate_id(self, prefix: str = "mem") -> str:
        """生成记忆 ID"""
        self._id_counter += 1
        return f"{prefix}_{self._id_counter}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def _load_index(self) -> None:
        """加载索引"""
        if not self.index_file.exists():
            return

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.index = {k: MemoryEntry.from_dict(v) for k, v in data.items()}
            self._id_counter = len(self.index)
        except Exception:
            pass

    def _save_index(self) -> None:
        """保存索引"""
        data = {k: v.to_dict() for k, v in self.index.items()}
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # =========================================================================
    # 索引操作
    # =========================================================================

    def index_memory(
        self,
        content: str,
        memory_type: str = "general",
        generation: int = 1,
        importance: float = 0.5,
    ) -> MemoryEntry:
        """
        索引一条记忆

        Args:
            content: 记忆内容
            memory_type: 记忆类型
            generation: 世代号
            importance: 重要性 0.0-1.0

        Returns:
            记忆条目
        """
        memory_id = self._generate_id(prefix=memory_type[:3])
        entry = MemoryEntry(
            id=memory_id,
            content=content,
            memory_type=memory_type,
            generation=generation,
            timestamp=datetime.now().isoformat(),
            access_count=0,
            last_access="",
            importance=importance,
        )

        # 生成 embedding
        entry.embedding = self.embedder.embed(content)

        # 保存
        self.index[memory_id] = entry
        self._save_index()

        return entry

    def index_decision(
        self,
        decision: str,
        context: str = "",
        generation: int = 1,
    ) -> MemoryEntry:
        """
        索引关键决策

        Args:
            decision: 决策内容
            context: 决策上下文
            generation: 世代号

        Returns:
            记忆条目
        """
        content = f"{decision}"
        if context:
            content += f" (上下文: {context})"
        return self.index_memory(
            content=content,
            memory_type="decision",
            generation=generation,
            importance=0.8,
        )

    def index_insight(
        self,
        insight: str,
        category: str = "general",
        generation: int = 1,
    ) -> MemoryEntry:
        """
        索引洞察

        Args:
            insight: 洞察内容
            category: 分类
            generation: 世代号

        Returns:
            记忆条目
        """
        content = f"[{category}] {insight}"
        return self.index_memory(
            content=content,
            memory_type="insight",
            generation=generation,
            importance=0.7,
        )

    def index_tool_usage(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: str,
        success: bool,
        generation: int = 1,
    ) -> MemoryEntry:
        """
        索引工具使用

        Args:
            tool_name: 工具名称
            args: 工具参数
            result: 执行结果
            success: 是否成功
            generation: 世代号

        Returns:
            记忆条目
        """
        content = f"工具: {tool_name}, 成功: {success}"
        if not success:
            content += f", 错误: {result[:200]}"
        return self.index_memory(
            content=content,
            memory_type="tool",
            generation=generation,
            importance=0.6 if success else 0.9,  # 失败更重视
        )

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """
        获取记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            记忆条目
        """
        entry = self.index.get(memory_id)
        if entry:
            entry.access_count += 1
            entry.last_access = datetime.now().isoformat()
            self._save_index()
        return entry

    def delete(self, memory_id: str) -> bool:
        """
        删除记忆

        Args:
            memory_id: 记忆 ID

        Returns:
            是否成功删除
        """
        if memory_id in self.index:
            del self.index[memory_id]
            self._save_index()
            return True
        return False

    # =========================================================================
    # 检索操作
    # =========================================================================

    def search(
        self,
        query: str,
        top_k: int = 5,
        memory_type: Optional[str] = None,
        min_importance: float = 0.0,
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        语义搜索

        Args:
            query: 查询文本
            top_k: 返回数量
            memory_type: 过滤类型
            min_importance: 最低重要性

        Returns:
            (记忆条目, 相似度) 列表
        """
        # 生成查询 embedding
        query_embedding = self.embedder.embed(query)

        # 计算相似度
        results = []
        for entry in self.index.values():
            # 类型过滤
            if memory_type and entry.memory_type != memory_type:
                continue
            # 重要性过滤
            if entry.importance < min_importance:
                continue
            # 相似度计算
            if entry.embedding:
                similarity = self.embedder.cosine_similarity(
                    query_embedding, entry.embedding
                )
                results.append((entry, similarity))

        # 排序
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def search_decisions(self, query: str, top_k: int = 3) -> List[Tuple[MemoryEntry, float]]:
        """
        搜索相关决策

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            (记忆条目, 相似度) 列表
        """
        return self.search(query, top_k, memory_type="decision")

    def search_insights(self, query: str, top_k: int = 5) -> List[Tuple[MemoryEntry, float]]:
        """
        搜索相关洞察

        Args:
            query: 查询文本
            top_k: 返回数量

        Returns:
            (记忆条目, 相似度) 列表
        """
        return self.search(query, top_k, memory_type="insight")

    def search_by_type(self, memory_type: str, limit: int = 50) -> List[MemoryEntry]:
        """
        按类型获取记忆

        Args:
            memory_type: 记忆类型
            limit: 返回数量

        Returns:
            记忆列表
        """
        entries = [
            e for e in self.index.values()
            if e.memory_type == memory_type
        ]
        # 按时间排序
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    # =========================================================================
    # 统计信息
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息
        """
        by_type: Dict[str, int] = {}
        total_access = 0
        for entry in self.index.values():
            by_type[entry.memory_type] = by_type.get(entry.memory_type, 0) + 1
            total_access += entry.access_count

        return {
            "total_memories": len(self.index),
            "by_type": by_type,
            "total_accesses": total_access,
            "avg_importance": sum(e.importance for e in self.index.values()) / max(len(self.index), 1),
        }

    def cleanup_low_value(self, min_importance: float = 0.2) -> int:
        """
        清理低价值记忆

        Args:
            min_importance: 最低重要性阈值

        Returns:
            清理数量
        """
        to_delete = [
            memory_id for memory_id, entry in self.index.items()
            if entry.importance < min_importance and entry.access_count == 0
        ]
        for memory_id in to_delete:
            del self.index[memory_id]

        if to_delete:
            self._save_index()

        return len(to_delete)


# ============================================================================
# 全局单例
# ============================================================================

_retriever: Optional[SemanticRetriever] = None


def get_semantic_retriever(project_root: Optional[str] = None) -> SemanticRetriever:
    """
    获取语义检索器单例

    Args:
        project_root: 项目根目录

    Returns:
        SemanticRetriever 实例
    """
    global _retriever
    if _retriever is None:
        _retriever = SemanticRetriever(project_root)
    return _retriever


def reset_semantic_retriever() -> None:
    """重置语义检索器单例"""
    global _retriever
    _retriever = None
