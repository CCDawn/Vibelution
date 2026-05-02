# -*- coding: utf-8 -*-
"""章节级系统提示词缓存 — 每个 SystemPromptSection 独立缓存其 compute 结果"""

from __future__ import annotations

from typing import Dict, Optional, Any


class SystemPromptCache:
    """章节级缓存。

    cache_break=False 的章节只计算一次（命中缓存），
    cache_break=True 的章节每轮重算（跳过缓存）。
    """

    def __init__(self):
        self._cache: Dict[str, Optional[str]] = {}
        self._hits: int = 0
        self._misses: int = 0

    def get(self, name: str) -> Optional[str]:
        if name in self._cache:
            self._hits += 1
            return self._cache[name]
        self._misses += 1
        return None

    def set(self, name: str, value: Optional[str]) -> None:
        self._cache[name] = value

    def has(self, name: str) -> bool:
        return name in self._cache

    def invalidate(self, name: Optional[str] = None):
        """清除缓存。name 为 None 则清除全部。"""
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def clear(self):
        self._cache.clear()

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self.hit_rate:.1%}",
            "cached_sections": list(self._cache.keys()),
        }
