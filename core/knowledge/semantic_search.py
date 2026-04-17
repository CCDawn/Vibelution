#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量语义搜索 (Semantic Search) - Phase 8 模块

Phase 8.5 模块
"""

from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import numpy as np


@dataclass
class SemanticEntry:
    """语义条目"""
    entry_id: str
    content: str
    content_type: str
    embedding: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "content": self.content,
            "content_type": self.content_type,
            "embedding": self.embedding,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
        }


@dataclass
class SearchResult:
    """搜索结果"""
    entry: SemanticEntry
    score: float
    highlights: List[str] = field(default_factory=list)


class EmbeddingService:
    """Embedding 生成服务"""

    def __init__(self, model_name: str = "simple", api_key: Optional[str] = None):
        self.model_name = model_name
        self.api_key = api_key
        self._cache: Dict[str, List[float]] = {}

    def encode(self, text: str) -> List[float]:
        """将文本编码为向量"""
        cache_key = hashlib.md5(text.encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        embedding = self._simple_embedding(text)
        self._cache[cache_key] = embedding
        return embedding

    def _simple_embedding(self, text: str) -> List[float]:
        """简化 Embedding（基于 TF-IDF）"""
        words = text.lower().split()
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1

        dimension = 128
        vector = [0.0] * dimension

        for i, word in enumerate(word_freq.keys()):
            if i >= dimension:
                break
            hash_val = sum(ord(c) * (31 ** j) for j, c in enumerate(word[:5]))
            idx = hash_val % dimension
            vector[idx] = word_freq[word] / max(len(words), 1)

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码"""
        return [self.encode(text) for text in texts]

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()


class VectorStore:
    """向量存储"""

    def __init__(self, storage_path: Optional[str] = None, embedding_dim: int = 128):
        if storage_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            storage_path = os.path.join(project_root, "workspace", "memory", "vector_store.json")

        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_dim = embedding_dim

        self._entries: Dict[str, SemanticEntry] = {}
        self._load()

    def add(self, entry: SemanticEntry) -> str:
        """添加条目"""
        entry.entry_id = entry.entry_id or self._generate_id(entry.content)
        self._entries[entry.entry_id] = entry
        self._save()
        return entry.entry_id

    def get(self, entry_id: str) -> Optional[SemanticEntry]:
        """获取条目"""
        return self._entries.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        """删除条目"""
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def search(
        self,
        query_embedding: List[float],
        limit: int = 10,
        min_score: float = 0.0,
        content_types: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """搜索相似条目"""
        results = []

        for entry in self._entries.values():
            if content_types and entry.content_type not in content_types:
                continue

            score = self._cosine_similarity(query_embedding, entry.embedding)

            if score >= min_score:
                results.append(SearchResult(entry=entry, score=score))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def count(self) -> int:
        """获取条目数量"""
        return len(self._entries)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _generate_id(self, content: str) -> str:
        """生成 ID"""
        return hashlib.md5(content[:100].encode()).hexdigest()[:16]

    def _load(self) -> None:
        """从文件加载"""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for entry_data in data.get("entries", []):
                try:
                    entry = SemanticEntry(
                        entry_id=entry_data["entry_id"],
                        content=entry_data["content"],
                        content_type=entry_data["content_type"],
                        embedding=entry_data["embedding"],
                        metadata=entry_data.get("metadata", {}),
                        created_at=entry_data.get("created_at", datetime.now().isoformat()),
                        updated_at=entry_data.get("updated_at", datetime.now().isoformat()),
                        tags=entry_data.get("tags", []),
                    )
                    self._entries[entry.entry_id] = entry
                except Exception:
                    continue
        except Exception:
            pass

    def _save(self) -> None:
        """保存到文件"""
        data = {
            "version": "1.0",
            "updated_at": datetime.now().isoformat(),
            "embedding_dim": self.embedding_dim,
            "entries": [e.to_dict() for e in self._entries.values()],
        }

        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class SemanticMemory:
    """语义记忆"""

    def __init__(
        self,
        storage_path: Optional[str] = None,
        embedding_service: Optional[EmbeddingService] = None,
    ):
        if embedding_service is None:
            embedding_service = EmbeddingService()

        self.embedding_service = embedding_service
        self.vector_store = VectorStore(storage_path)

    def add_memory(
        self,
        content: str,
        content_type: str = "memory",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """添加记忆"""
        embedding = self.embedding_service.encode(content)

        entry = SemanticEntry(
            entry_id="",
            content=content,
            content_type=content_type,
            embedding=embedding,
            metadata=metadata or {},
            tags=tags or [],
        )

        return self.vector_store.add(entry)

    def search_memories(
        self,
        query: str,
        content_types: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
        min_score: float = 0.5,
    ) -> List[SearchResult]:
        """搜索记忆"""
        query_embedding = self.embedding_service.encode(query)

        results = self.vector_store.search(
            query_embedding=query_embedding,
            limit=limit,
            min_score=min_score,
            content_types=content_types,
        )

        if tags:
            results = [r for r in results if any(t in r.entry.tags for t in tags)]

        return results

    def get_memory(self, memory_id: str) -> Optional[SemanticEntry]:
        """获取记忆"""
        return self.vector_store.get(memory_id)

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆"""
        return self.vector_store.remove(memory_id)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        by_type: Dict[str, int] = {}
        all_tags: set = set()

        for entry in self.vector_store._entries.values():
            by_type[entry.content_type] = by_type.get(entry.content_type, 0) + 1
            all_tags.update(entry.tags)

        return {
            "total_memories": self.vector_store.count(),
            "by_content_type": by_type,
            "unique_tags": len(all_tags),
        }


class SemanticSearchService:
    """语义搜索服务"""

    def __init__(self, storage_path: Optional[str] = None, model_name: str = "simple"):
        self.embedding_service = EmbeddingService(model_name=model_name)
        self.semantic_memory = SemanticMemory(
            storage_path=storage_path,
            embedding_service=self.embedding_service,
        )

    def add(
        self,
        content: str,
        content_type: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """添加内容"""
        return self.semantic_memory.add_memory(
            content=content,
            content_type=content_type,
            metadata=metadata,
            tags=tags,
        )

    def search(
        self,
        query: str,
        content_types: Optional[List[str]] = None,
        limit: int = 10,
        min_score: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """语义搜索"""
        results = self.semantic_memory.search_memories(
            query=query,
            content_types=content_types,
            limit=limit,
            min_score=min_score,
        )

        return [
            {
                "id": r.entry.entry_id,
                "content": r.entry.content,
                "content_type": r.entry.content_type,
                "score": r.score,
                "tags": r.entry.tags,
                "metadata": r.entry.metadata,
                "created_at": r.entry.created_at,
            }
            for r in results
        ]

    def search_experiences(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索经验"""
        return self.search(query=query, content_types=["experience"], limit=limit)

    def search_knowledge(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索知识"""
        return self.search(query=query, content_types=["knowledge"], limit=limit)

    def get_context_for_task(self, task_description: str, max_memories: int = 3) -> str:
        """为任务获取相关上下文"""
        results = self.search(query=task_description, limit=max_memories, min_score=0.4)

        if not results:
            return ""

        context_parts = ["相关经验："]
        for r in results:
            context_parts.append(f"- [{r['content_type']}] {r['content'][:200]}")

        return "\n".join(context_parts)


_semantic_search_instance: Optional[SemanticSearchService] = None


def get_semantic_search(
    storage_path: Optional[str] = None,
    model_name: str = "simple",
) -> SemanticSearchService:
    """获取语义搜索服务单例"""
    global _semantic_search_instance

    if _semantic_search_instance is None:
        _semantic_search_instance = SemanticSearchService(
            storage_path=storage_path,
            model_name=model_name,
        )

    return _semantic_search_instance


def reset_semantic_search() -> None:
    """重置语义搜索服务单例"""
    global _semantic_search_instance
    _semantic_search_instance = None


def semantic_search(
    query: str,
    content_types: Optional[List[str]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """快捷函数：执行语义搜索"""
    service = get_semantic_search()
    return service.search(query, content_types, limit)


def add_semantic_memory(
    content: str,
    content_type: str = "memory",
    tags: Optional[List[str]] = None,
) -> str:
    """快捷函数：添加语义记忆"""
    service = get_semantic_search()
    return service.add(content, content_type, tags=tags)
