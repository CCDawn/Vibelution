# -*- coding: utf-8 -*-
"""
core/capabilities/codebase_map_builder.py - AST 扫描 + 代码库地图生成

职责：
- 扫描 tools/、core/、tests/ 目录下的 .py 文件
- 对每个文件调用 AST 工具获取类/函数骨架
- 组装 Markdown 树，写入 workspace/prompts/codebase_map.md
- 提供缓存失效机制（TTL=24h + 文件变更检测）

导出函数：
- scan_and_build_codebase_map(project_root, force=False) -> str
- should_rescan(project_root) -> bool
- get_codebase_map() -> str
"""

from __future__ import annotations

import os
import re
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Set

from core.logging import debug_logger

# 扫描范围：相对项目根目录的子目录
_SCAN_DIRS = ["tools", "core", "tests"]

# 排除的文件（不扫描）
_EXCLUDE_FILES = {
    "__pycache__",
    "__init__.py",          # 空 __init__ 不值得在地图中单独列
    "conftest.py",
    "__init__.cpython",
}

# 缓存 TTL = 24 小时
_CACHE_TTL_HOURS = 24


# =============================================================================
# 路径解析（与 workspace_manager.py 保持一致）
# =============================================================================

def _resolve_project_root() -> Path:
    """推断项目根目录"""
    p = Path(__file__).parent.parent.parent.resolve()
    if (p / "agent.py").exists():
        return p
    import sys
    for sp in sys.path:
        candidate = os.path.join(sp, "agent.py")
        if os.path.exists(candidate):
            return Path(sp).resolve()
    return p


def _get_prompts_dir() -> Path:
    """获取 workspace/prompts/ 路径"""
    project_root = _resolve_project_root()
    prompts_dir = project_root / "workspace" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    return prompts_dir


def _get_codebase_map_path() -> Path:
    """获取 codebase_map.md 路径"""
    return _get_prompts_dir() / "codebase_map.md"


# =============================================================================
# AST 扫描
# =============================================================================

def _list_file_entities_fast(file_path: Path) -> Optional[dict]:
    """
    快速获取文件实体骨架（绕过工具层，直接调 AST）。

    Returns:
        dict with keys: classes (list), functions (list)
        每个元素: {"name": str, "lineno": int}
        返回 None 表示解析失败
    """
    try:
        import ast
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=str(file_path))

        classes = []
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "methods": methods,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 忽略嵌套在类/函数内部的定义（只取顶层）
                functions.append({
                    "name": node.name,
                    "lineno": node.lineno,
                })

        return {"classes": classes, "functions": functions}
    except Exception:
        return None


def _collect_python_files(project_root: Path) -> list[Path]:
    """收集所有需要扫描的 .py 文件"""
    files: list[Path] = []
    for scan_dir in _SCAN_DIRS:
        dir_path = project_root / scan_dir
        if not dir_path.is_dir():
            continue
        for root, _, filenames in os.walk(dir_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                if fname in _EXCLUDE_FILES:
                    continue
                fpath = Path(root) / fname
                # 排除 __pycache__ 目录
                if "__pycache__" in str(fpath):
                    continue
                files.append(fpath)
    return files


def _build_file_entry(fpath: Path, rel_root: Path) -> str:
    """为单个文件构建地图条目"""
    entities = _list_file_entities_fast(fpath)
    rel_path = fpath.relative_to(rel_root).as_posix()
    lines = [f"**`{rel_path}`**"]

    if entities is None:
        lines.append("  _(解析失败)_")
        return "\n".join(lines)

    parts: list[str] = []

    for cls in entities.get("classes", []):
        methods = cls.get("methods", [])
        method_str = ""
        if methods:
            method_str = f" [{', '.join(methods)}]"
        parts.append(f"  class {cls['name']}{method_str}")

    for fn in entities.get("functions", []):
        parts.append(f"  def {fn['name']}")

    if parts:
        lines.append("\n".join(parts))
    else:
        lines.append("  _(空模块)_")

    return "\n".join(lines)


# =============================================================================
# 核心函数
# =============================================================================

def scan_and_build_codebase_map(project_root: Optional[Path] = None, force: bool = False) -> str:
    """
    扫描代码库，生成 codebase_map.md。

    Args:
        project_root: 项目根目录（默认自动推断）
        force: True 时强制重新扫描，忽略缓存

    Returns:
        生成的地图内容（Markdown 字符串）
    """
    if project_root is None:
        project_root = _resolve_project_root()

    files = _collect_python_files(project_root)

    # 按目录分组，目录内按文件名排序
    from collections import defaultdict
    by_dir: defaultdict[Path, list[Path]] = defaultdict(list)
    for f in files:
        by_dir[f.parent].append(f)
    for d in by_dir:
        by_dir[d].sort(key=lambda p: p.name)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = [
        "# 代码库结构地图",
        "",
        f"_自动生成于 {timestamp}，TTL=24h 或代码变更时自动刷新_",
        "",
        "---",
        "",
    ]

    # 按扫描目录顺序输出
    scan_root_map = {project_root / d: d for d in _SCAN_DIRS}

    for scan_dir in _SCAN_DIRS:
        dir_path = project_root / scan_dir
        if dir_path not in by_dir:
            continue

        label = scan_dir.upper()
        lines.append(f"## 📁 {label}/")
        lines.append("")

        for fpath in by_dir[dir_path]:
            entry = _build_file_entry(fpath, project_root)
            lines.append(entry)
            lines.append("")

        lines.append("---")
        lines.append("")

    content = "\n".join(lines).strip()
    map_path = _get_codebase_map_path()

    # 写入文件（保留已有的 YAML front matter）
    front_matter = ""
    if map_path.exists():
        try:
            existing = map_path.read_text(encoding="utf-8")
            match = re.match(r'^---\s*\n.*?\n---(\n)?', existing, re.DOTALL)
            if match:
                front_matter = match.group(0)
        except Exception:
            pass

    final_content = (front_matter + content).strip()
    if front_matter:
        final_content += "\n"

    try:
        map_path.write_text(final_content, encoding="utf-8")
        debug_logger.info(f"[CodebaseMapBuilder] 地图已写入（保留 front matter）: {map_path}")
    except Exception as e:
        debug_logger.warning(f"[CodebaseMapBuilder] 写入失败: {e}")

    # 写入 .meta 文件记录扫描时间戳和文件列表哈希
    try:
        meta_path = map_path.with_suffix(".meta")
        file_list_hash = hashlib.md5(
            "|".join(str(f) for f in sorted(files)).encode()
        ).hexdigest()[:8]
        meta_path.write_text(
            f"generated_at={timestamp}\nfile_hash={file_list_hash}\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    return content


def should_rescan(project_root: Optional[Path] = None) -> bool:
    """
    检查是否需要重新扫描。

    Returns:
        True = 需要扫描（文件不存在 / 已过期 / 代码有变更）
        False = 缓存有效，跳过扫描
    """
    if project_root is None:
        project_root = _resolve_project_root()

    map_path = _get_codebase_map_path()
    if not map_path.exists():
        return True

    # 检查 TTL
    try:
        import time
        age_seconds = time.time() - map_path.stat().st_mtime
        if age_seconds > _CACHE_TTL_HOURS * 3600:
            debug_logger.debug("[CodebaseMapBuilder] 缓存已过期，需要重新扫描")
            return True
    except Exception:
        return True

    # 检查代码文件是否变更（与 meta 中的文件列表哈希对比）
    try:
        meta_path = map_path.with_suffix(".meta")
        if meta_path.exists():
            current_files = _collect_python_files(project_root)
            current_hash = hashlib.md5(
                "|".join(str(f) for f in sorted(current_files)).encode()
            ).hexdigest()[:8]
            meta_content = meta_path.read_text(encoding="utf-8")
            for line in meta_content.splitlines():
                if line.startswith("file_hash="):
                    cached_hash = line.split("=", 1)[1].strip()
                    if current_hash != cached_hash:
                        debug_logger.debug("[CodebaseMapBuilder] 代码文件有变更，需要重新扫描")
                        return True
                    break
    except Exception:
        pass

    return False


def get_codebase_map(force_refresh: bool = False) -> str:
    """
    获取代码库地图（优先读取缓存）。

    Args:
        force_refresh: True 时强制重新扫描

    Returns:
        地图内容字符串
    """
    if force_refresh or should_rescan():
        return scan_and_build_codebase_map()
    else:
        map_path = _get_codebase_map_path()
        if map_path.exists():
            try:
                return map_path.read_text(encoding="utf-8")
            except Exception:
                pass
        return scan_and_build_codebase_map()


# =============================================================================
# 便捷入口
# =============================================================================

__all__ = [
    "scan_and_build_codebase_map",
    "should_rescan",
    "get_codebase_map",
]
