# -*- coding: utf-8 -*-
"""
core/core_prompt/__init__.py - 核心提示词管理器

双轨加载架构：
- 静态源：core/core_prompt/    内置只读模板（SOUL.md, AGENTS.md）
- 动态源：workspace/prompts/   用户可编辑覆盖层

加载策略：
- SOUL.md / AGENTS.md：优先从 workspace 加载（允许定制），不存在则回退到 core/core_prompt/
- IDENTITY.md / USER.md / DYNAMIC.md / COMPRESS_SUMMARY.md：仅从 workspace 加载
- 所有文件支持优雅回退（未找到时返回警告而非报错）
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict
from functools import lru_cache

logger = logging.getLogger(__name__)


# =============================================================================
# 路径解析
# =============================================================================

def _get_static_root() -> Path:
    """获取 core/core_prompt/ 静态路径（内置模板）"""
    return Path(__file__).parent.resolve()


def _get_dynamic_root() -> Path:
    """获取 workspace/prompts/ 动态路径（用户覆盖层）"""
    # 从 agent.py 所在位置推断项目根目录
    project_root = _resolve_project_root()
    return project_root / "workspace" / "prompts"


def _resolve_project_root() -> Path:
    """推断项目根目录"""
    # 从 agent 模块获取
    import sys
    for name, mod in list(sys.modules.items()):
        if name == "agent" and mod and getattr(mod, '__file__', None):
            return Path(mod.__file__).parent.resolve()

    # 回退：从 sys.path 搜索 agent.py
    for sp in sys.path:
        p = os.path.join(sp, "agent.py")
        if os.path.exists(p):
            return Path(sp).resolve()

    # 最保守回退：core/core_prompt 的上一级的上一级
    return Path(__file__).parent.parent.parent.resolve()


# =============================================================================
# CorePromptManager
# =============================================================================

class CorePromptManager:
    """
    双轨提示词加载器

    职责：
    - 静态加载 core/core_prompt/ 下的内置模板（SOUL.md, AGENTS.md）
    - 动态加载 workspace/prompts/ 下的用户文件（覆盖优先）
    - 缓存已加载内容避免重复读文件
    - 记录加载来源（static / dynamic）
    """

    # 核心静态文件（必须来自 core/core_prompt/，可被 workspace 覆盖）
    STATIC_FILES = {"SOUL.md", "AGENTS.md"}

    # 纯动态文件（仅来自 workspace/prompts/）
    DYNAMIC_FILES = {"IDENTITY.md", "USER.md", "DYNAMIC.md", "COMPRESS_SUMMARY.md"}

    # 所有受管理的文件
    ALL_FILES = STATIC_FILES | DYNAMIC_FILES

    def __init__(self):
        self._static_root = _get_static_root()
        self._dynamic_root = _get_dynamic_root()
        self._cache: Dict[str, str] = {}
        self._sources: Dict[str, str] = {}  # name -> "static" | "dynamic"

        # 预热：确保目录存在（不抛错）
        self._dynamic_root.mkdir(parents=True, exist_ok=True)

        logger.info(f"[CorePrompt] 初始化 - 静态: {self._static_root}")
        logger.info(f"[CorePrompt] 初始化 - 动态: {self._dynamic_root}")

    def load(self, name: str, prefer_workspace: bool = True) -> str:
        """
        加载指定提示词文件（支持双轨加载）。

        Args:
            name: 文件名，如 "SOUL.md", "IDENTITY.md"
            prefer_workspace: 是否优先从 workspace 加载（仅对 STATIC_FILES 生效）

        Returns:
            文件内容，未找到时返回警告文本
        """
        # 检查缓存
        cache_key = f"{name}:{prefer_workspace}"
        if cache_key in self._cache:
            logger.debug(f"[CorePrompt] 缓存命中: {name} (来源: {self._sources.get(cache_key, '?')})")
            return self._cache[cache_key]

        # 确定加载策略
        if name in self.STATIC_FILES and prefer_workspace:
            # 双轨：优先 workspace，回退 static
            content = self._load_with_fallback(name)
        elif name in self.STATIC_FILES:
            # 强制静态
            content = self._load_from_path(self._static_root / name, "static", name)
        else:
            # 纯动态
            content = self._load_from_path(self._dynamic_root / name, "dynamic", name)

        # 缓存
        self._cache[cache_key] = content
        self._sources[cache_key] = "workspace" if "workspace" in content[:30] else "static"

        return content

    def _load_with_fallback(self, name: str) -> str:
        """双轨加载：优先动态（workspace），回退静态（core/core_prompt/）"""
        dynamic_path = self._dynamic_root / name
        static_path = self._static_root / name

        # 优先 workspace
        if dynamic_path.exists():
            try:
                content = dynamic_path.read_text(encoding="utf-8").strip()
                logger.info(f"[CorePrompt] 动态加载 {name} from workspace")
                return content
            except Exception as e:
                logger.warning(f"[CorePrompt] workspace/{name} 读取失败: {e}，回退到 static")

        # 回退 static
        return self._load_from_path(static_path, "static", name)

    def _load_from_path(self, path: Path, source: str, name: str) -> str:
        """从指定路径加载文件"""
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8").strip()
                logger.info(f"[CorePrompt] 静态加载 {name} from core/core_prompt/")
                return content
            except Exception as e:
                return f"[错误: 无法读取 {path}: {e}]"
        else:
            return f"[警告: 找不到 {path}]"

    def load_soul(self) -> str:
        """加载 SOUL.md"""
        return self.load("SOUL.md", prefer_workspace=True)

    def load_agents(self) -> str:
        """加载 AGENTS.md"""
        return self.load("AGENTS.md", prefer_workspace=True)

    def load_identity(self) -> str:
        """加载 IDENTITY.md"""
        return self.load("IDENTITY.md", prefer_workspace=False)

    def load_user(self) -> str:
        """加载 USER.md"""
        return self.load("USER.md", prefer_workspace=False)

    def load_dynamic(self) -> str:
        """加载 DYNAMIC.md"""
        return self.load("DYNAMIC.md", prefer_workspace=False)

    def load_compress_summary(self) -> str:
        """加载 COMPRESS_SUMMARY.md"""
        return self.load("COMPRESS_SUMMARY.md", prefer_workspace=False)

    def invalidate_cache(self, name: Optional[str] = None):
        """
        清除缓存。

        Args:
            name: 指定清除某个文件的缓存，传 None 则清除全部
        """
        if name:
            keys_to_delete = [k for k in self._cache if k.startswith(f"{name}:")]
            for k in keys_to_delete:
                del self._cache[k]
                if k in self._sources:
                    del self._sources[k]
            logger.debug(f"[CorePrompt] 清除缓存: {name}")
        else:
            self._cache.clear()
            self._sources.clear()
            logger.debug("[CorePrompt] 清除全部缓存")

    def get_status(self) -> Dict:
        """获取加载器状态（调试用）"""
        return {
            "static_root": str(self._static_root),
            "dynamic_root": str(self._dynamic_root),
            "cached_files": list(self._cache.keys()),
            "all_managed_files": list(self.ALL_FILES),
        }


# =============================================================================
# 全局单例
# =============================================================================

_prompt_manager: Optional[CorePromptManager] = None


def get_prompt_manager() -> CorePromptManager:
    """获取全局 CorePromptManager 单例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = CorePromptManager()
    return _prompt_manager


# =============================================================================
# 便捷函数（与旧接口兼容）
# =============================================================================

def load_soul() -> str:
    """加载 SOUL.md（便捷函数）"""
    return get_prompt_manager().load_soul()


def load_agents() -> str:
    """加载 AGENTS.md（便捷函数）"""
    return get_prompt_manager().load_agents()


def load_prompt(name: str, prefer_workspace: bool = True) -> str:
    """通用加载函数"""
    return get_prompt_manager().load(name, prefer_workspace=prefer_workspace)


# =============================================================================
# 导出
# =============================================================================

__all__ = [
    "CorePromptManager",
    "get_prompt_manager",
    "load_soul",
    "load_agents",
    "load_prompt",
]
