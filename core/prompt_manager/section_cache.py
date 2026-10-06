# -*- coding: utf-8 -*-
"""章节级系统提示词缓存 — 每个 SystemPromptSection 独立缓存其 compute 结果"""

from __future__ import annotations

import time
from typing import Dict, Optional, Any


class SystemPromptCache:
    """章节级缓存。

    cache_break=False 的章节只计算一次（命中缓存），
    cache_break=True 的章节每轮重算（跳过缓存）。

    TTL 层：部分重 IO 的描述性动态章节（世界状态描述，如 CODEBASE_MAP、
    RUNTIME_LOG_INDEX、ENV_INFO）按注册的短 TTL 在窗口内复用上一次 compute
    结果，窗口到期后照常重算。TTL 条目与静态缓存分开放在 ``_ttl_cache``，
    ``get``/``set``/``has`` 的静态语义完全不变；``invalidate``/``clear`` 同时
    清理两层，注册/失效路径无需关心分层。
    """

    def __init__(self):
        self._cache: Dict[str, Optional[str]] = {}
        self._hits: int = 0
        self._misses: int = 0
        # (expire_at_monotonic, value)；仅描述性动态章节使用。
        self._ttl_cache: Dict[str, tuple[float, Optional[str]]] = {}
        self._ttl_hits: int = 0
        self._ttl_misses: int = 0

    # ---- 静态章节缓存（语义不变） ----

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

    # ---- 动态章节 TTL 缓存 ----

    def get_with_ttl(self, name: str, *, now: Optional[float] = None) -> tuple[bool, Optional[str]]:
        """返回 (是否命中, 缓存值)。命中窗口内不触发 compute。"""

        current = time.monotonic() if now is None else now
        entry = self._ttl_cache.get(name)
        if entry is not None and current < entry[0]:
            self._ttl_hits += 1
            return True, entry[1]
        if entry is not None:
            # 过期即丢弃，避免陈旧值在无 TTL 注册的路径上被误用。
            self._ttl_cache.pop(name, None)
        self._ttl_misses += 1
        return False, None

    def set_with_ttl(self, name: str, value: Optional[str], ttl_seconds: float, *, now: Optional[float] = None) -> None:
        current = time.monotonic() if now is None else now
        if ttl_seconds <= 0:
            self._ttl_cache.pop(name, None)
            return
        self._ttl_cache[name] = (current + float(ttl_seconds), value)

    # ---- 失效与统计 ----

    def invalidate(self, name: Optional[str] = None):
        """清除缓存。name 为 None 则清除全部（含 TTL 层）。"""
        if name:
            self._cache.pop(name, None)
            self._ttl_cache.pop(name, None)
        else:
            self._cache.clear()
            self._ttl_cache.clear()

    def clear(self):
        self._cache.clear()
        self._ttl_cache.clear()

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
            "ttl_hits": self._ttl_hits,
            "ttl_misses": self._ttl_misses,
            "ttl_sections": sorted(self._ttl_cache.keys()),
        }
