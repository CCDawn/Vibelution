#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码库认知地图 (CodebaseAnalyzer) - 自动分析项目代码结构

负责：
- 扫描项目代码结构
- 识别代码热点（高频修改区域）
- 分析模块依赖关系
- 生成架构演化图
- 识别代码坏味道

Phase 2 核心模块
"""

from __future__ import annotations

import os
import re
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class FileEntity:
    """文件实体"""
    path: str
    name: str
    file_type: str
    lines: int
    complexity: int
    functions: int
    classes: int
    imports: List[str] = field(default_factory=list)
    last_modified: Optional[str] = None
    modification_count: int = 0


@dataclass
class ModuleInfo:
    """模块信息"""
    name: str
    path: str
    purpose: str
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    complexity: int = 0
    health_score: float = 1.0


@dataclass
class CodeHotspot:
    """代码热点"""
    file_path: str
    reason: str
    metrics: Dict[str, Any]
    suggestions: List[str]


@dataclass
class CodebaseMap:
    """代码库地图"""
    project_name: str
    generated_at: str
    total_files: int
    total_lines: int
    modules: List[ModuleInfo]
    hotspots: List[CodeHotspot]
    dependency_graph: Dict[str, List[str]]
    metrics: Dict[str, Any]


# ============================================================================
# 代码库分析器
# ============================================================================

class CodebaseAnalyzer:
    """
    代码库认知地图分析器

    自动扫描和分析项目代码结构，生成认知地图。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化代码库分析器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 缓存
        self._file_entities: Dict[str, FileEntity] = {}
        self._module_info: Dict[str, ModuleInfo] = {}
        self._import_graph: Dict[str, Set[str]] = defaultdict(set)
        self._hotspots: List[CodeHotspot] = []

        # 模块用途描述
        self._module_purposes = self._init_module_purposes()

    def _init_module_purposes(self) -> Dict[str, str]:
        """初始化模块用途描述"""
        return {
            "agent.py": "Agent 主程序，协调各模块工作",
            "config.py": "配置文件管理",
            "core": "核心功能模块（orchestration, infrastructure, learning, pet_system, ui, logging 等）",
            "tools": "工具模块（shell, memory, search, code_analysis, rebirth, token 等）",
            "tests": "测试套件",
            "workspace": "工作区存储（prompts, memory, logs, transcripts 等）",
        }

    # =========================================================================
    # 核心分析接口
    # =========================================================================

    def scan_project(
        self,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        扫描项目结构

        Args:
            include_patterns: 包含的文件模式
            exclude_patterns: 排除的文件模式

        Returns:
            扫描结果
        """
        if include_patterns is None:
            include_patterns = ["*.py"]

        if exclude_patterns is None:
            exclude_patterns = [
                "__pycache__",
                "*.pyc",
                ".pytest_cache",
                ".git",
                "venv",
                ".venv",
                "env",
            ]

        files = []
        for pattern in include_patterns:
            for file_path in self.project_root.rglob(pattern):
                # 检查是否应该排除
                should_exclude = False
                for exclude in exclude_patterns:
                    if exclude in str(file_path):
                        should_exclude = True
                        break

                if not should_exclude:
                    files.append(file_path)

        # 分析每个文件
        entities = []
        for file_path in files:
            try:
                entity = self._analyze_file(file_path)
                entities.append(entity)
                self._file_entities[str(file_path)] = entity
            except Exception:
                continue

        # 构建导入图
        self._build_import_graph()

        # 识别热点
        self._identify_hotspots()

        return {
            "total_files": len(entities),
            "files": [self._entity_to_dict(e) for e in entities],
            "hotspots": [self._hotspot_to_dict(h) for h in self._hotspots],
        }

    def generate_codebase_map(self) -> CodebaseMap:
        """
        生成代码库地图

        Returns:
            代码库地图
        """
        # 确保已经扫描
        if not self._file_entities:
            self.scan_project()

        # 分析模块
        self._analyze_modules()

        # 构建依赖图
        dependency_graph = {k: list(v) for k, v in self._import_graph.items()}

        # 收集指标
        metrics = self._collect_metrics()

        return CodebaseMap(
            project_name=self.project_root.name,
            generated_at=datetime.now().isoformat(),
            total_files=len(self._file_entities),
            total_lines=sum(e.lines for e in self._file_entities.values()),
            modules=list(self._module_info.values()),
            hotspots=self._hotspots,
            dependency_graph=dependency_graph,
            metrics=metrics,
        )

    def get_module_dependencies(self, module_path: str) -> List[str]:
        """
        获取模块的依赖列表

        Args:
            module_path: 模块路径

        Returns:
            依赖该模块的其他模块列表
        """
        return list(self._import_graph.get(module_path, set()))

    def get_code_health(self, file_path: str) -> Dict[str, Any]:
        """
        获取代码健康度

        Args:
            file_path: 文件路径

        Returns:
            健康度评估
        """
        if file_path not in self._file_entities:
            return {"error": "文件未分析"}

        entity = self._file_entities[file_path]

        # 计算健康度
        health_score = 1.0
        issues = []

        # 复杂度检查
        if entity.complexity > 15:
            health_score -= 0.2
            issues.append(f"复杂度较高: {entity.complexity}")

        # 文件大小检查
        if entity.lines > 500:
            health_score -= 0.1
            issues.append(f"文件过大: {entity.lines} 行")

        # 函数大小检查
        if entity.functions > 20:
            health_score -= 0.1
            issues.append(f"函数过多: {entity.functions}")

        # 文档检查
        if entity.lines > 100:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    docstring_count = content.count('"""') + content.count("'''")
                    if docstring_count < 2:
                        health_score -= 0.1
                        issues.append("缺少文档字符串")
            except Exception:
                pass

        # 确保健康度在有效范围内
        health_score = max(0.0, min(1.0, health_score))

        return {
            "file": entity.path,
            "health_score": health_score,
            "issues": issues,
            "metrics": {
                "complexity": entity.complexity,
                "lines": entity.lines,
                "functions": entity.functions,
                "classes": entity.classes,
            },
        }

    # =========================================================================
    # 文件分析
    # =========================================================================

    def _analyze_file(self, file_path: Path) -> FileEntity:
        """分析单个文件"""
        try:
            stat = file_path.stat()
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"无法读取文件 {file_path}: {e}")

        # 解析 AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # 如果解析失败，使用简单的行数统计
            return FileEntity(
                path=str(file_path),
                name=file_path.name,
                file_type=self._get_file_type(file_path),
                lines=len(content.split('\n')),
                complexity=0,
                functions=0,
                classes=0,
                last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )

        # 统计（只取顶层定义，避免 ast.walk() 重复计入嵌套函数/类）
        functions = len([n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
        classes = len([n for n in tree.body if isinstance(n, ast.ClassDef)])

        # 计算复杂度
        complexity = self._calculate_complexity(tree)

        # 提取导入
        imports = self._extract_imports(tree)

        # 相对路径
        try:
            rel_path = str(file_path.relative_to(self.project_root))
        except ValueError:
            rel_path = str(file_path)

        return FileEntity(
            path=rel_path,
            name=file_path.name,
            file_type=self._get_file_type(file_path),
            lines=len(content.split('\n')),
            complexity=complexity,
            functions=functions,
            classes=classes,
            imports=imports,
            last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        )

    def _get_file_type(self, file_path: Path) -> str:
        """获取文件类型"""
        suffix = file_path.suffix.lower()

        type_map = {
            ".py": "python",
            ".md": "markdown",
            ".json": "json",
            ".toml": "config",
            ".yaml": "config",
            ".yml": "config",
        }

        return type_map.get(suffix, "other")

    def _calculate_complexity(self, code_or_tree) -> int:
        """计算圈复杂度"""
        if code_or_tree is None:
            return 0
        if isinstance(code_or_tree, str):
            try:
                tree = ast.parse(code_or_tree)
            except SyntaxError:
                return 0
        else:
            tree = code_or_tree
        complexity = 1  # 基础复杂度

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                complexity += 1
            elif isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.ExceptHandler):
                complexity += 1
            elif isinstance(node, ast.BoolOp):  # and, or
                complexity += len(node.values) - 1
            elif isinstance(node, ast.Try):     # try / except / finally
                complexity += len(node.handlers) + 1
            elif isinstance(node, ast.With):
                complexity += len(node.items)
            elif isinstance(node, ast.Match):
                complexity += len(node.cases)

        return complexity

    def _extract_imports(self, tree: ast.AST) -> List[str]:
        """提取导入语句"""
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        return imports

    # =========================================================================
    # 模块分析
    # =========================================================================

    def _analyze_modules(self) -> None:
        """分析模块结构"""
        # 按目录分组
        modules_by_dir: Dict[str, List[FileEntity]] = defaultdict(list)

        for entity in self._file_entities.values():
            if entity.file_type == "python":
                # 获取模块名
                parts = Path(entity.path).parts
                if len(parts) > 1:
                    module_dir = parts[0]
                else:
                    module_dir = entity.path.replace(".py", "")
                modules_by_dir[module_dir].append(entity)

        # 为每个模块生成信息
        for module_name, entities in modules_by_dir.items():
            module_path = module_name

            # 获取用途描述
            purpose = self._module_purposes.get(
                module_name,
                self._infer_module_purpose(module_name, entities),
            )

            # 计算总复杂度
            total_complexity = sum(e.complexity for e in entities)

            # 计算健康度
            health_score = sum(
                self.get_code_health(str(self.project_root / e.path))["health_score"]
                for e in entities
            ) / max(len(entities), 1)

            # 获取依赖
            dependencies = set()
            dependents = set()

            for entity in entities:
                for imp in entity.imports:
                    if imp.startswith("tools.") or imp.startswith("core."):
                        dependencies.add(imp)

            # 获取依赖当前模块的其他模块
            for other_name, other_entities in modules_by_dir.items():
                if other_name != module_name:
                    for other_entity in other_entities:
                        for imp in other_entity.imports:
                            if module_name in imp or any(
                                e.path in imp for e in entities
                            ):
                                dependents.add(other_name)

            self._module_info[module_name] = ModuleInfo(
                name=module_name,
                path=module_path,
                purpose=purpose,
                dependencies=list(dependencies),
                dependents=list(dependents),
                complexity=total_complexity,
                health_score=health_score,
            )

    def _infer_module_purpose(
        self,
        module_name: str,
        entities: List[FileEntity],
    ) -> str:
        """推断模块用途"""
        name_lower = module_name.lower()
        
        # 按优先级检查 - 更具体的模式在前
        if "tools" in name_lower:
            return "工具模块"
        if name_lower.startswith("test") or "_test" in name_lower or name_lower.endswith("_test"):
            return "测试模块"
        if "core" in name_lower and ("agent" in name_lower or "event" in name_lower or "state" in name_lower):
            return "核心功能模块"
        if "core" in name_lower:
            return "核心功能模块"
        if "docs" in name_lower:
            return "文档目录"
        if "workspace" in name_lower:
            return "工作区目录"
        if "requirement" in name_lower:
            return "需求文档目录"

        return "功能模块"

    # =========================================================================
    # 依赖图分析
    # =========================================================================

    def _build_import_graph(self) -> None:
        """构建导入依赖图"""
        for entity in self._file_entities.values():
            if entity.file_type != "python":
                continue

            for imp in entity.imports:
                # 标准化导入路径
                if imp.startswith("."):
                    continue

                # 映射到实际模块（精确到子模块）
                if imp.startswith("tools.") or imp == "tools":
                    parts = imp.split(".")
                    self._import_graph[entity.path].add(parts[0] + "." + parts[1] if len(parts) > 1 else imp)
                elif imp.startswith("core.") or imp == "core":
                    parts = imp.split(".")
                    self._import_graph[entity.path].add(parts[0] + "." + parts[1] if len(parts) > 1 else imp)
                elif imp in {"os", "sys", "json", "datetime", "typing", "pathlib", "re", "collections"}:
                    self._import_graph[entity.path].add("stdlib")

    # =========================================================================
    # 热点识别
    # =========================================================================

    def _identify_hotspots(self) -> None:
        """识别代码热点"""
        self._hotspots = []

        # 识别高复杂度文件
        for entity in self._file_entities.values():
            if entity.complexity > 15:
                self._hotspots.append(CodeHotspot(
                    file_path=entity.path,
                    reason="高圈复杂度",
                    metrics={
                        "complexity": entity.complexity,
                        "functions": entity.functions,
                        "lines": entity.lines,
                    },
                    suggestions=[
                        "考虑拆分为多个函数",
                        "使用策略模式简化分支",
                        "提取公共逻辑到工具函数",
                    ],
                ))

        # 识别大文件
        for entity in self._file_entities.values():
            if entity.lines > 500 and entity.file_type == "python":
                self._hotspots.append(CodeHotspot(
                    file_path=entity.path,
                    reason="文件过大",
                    metrics={
                        "lines": entity.lines,
                        "functions": entity.functions,
                        "classes": entity.classes,
                    },
                    suggestions=[
                        "考虑拆分为多个模块",
                        "提取独立功能到新文件",
                        "使用 __init__.py 导出接口",
                    ],
                ))

        # 识别过小文件（可能是重复代码）
        for entity in self._file_entities.values():
            if entity.lines < 20 and entity.lines > 0:
                self._hotspots.append(CodeHotspot(
                    file_path=entity.path,
                    reason="文件过小",
                    metrics={"lines": entity.lines},
                    suggestions=[
                        "考虑合并到相关模块",
                        "检查是否与其他文件重复",
                    ],
                ))

    # =========================================================================
    # 指标收集
    # =========================================================================

    def _collect_metrics(self) -> Dict[str, Any]:
        """收集代码库指标"""
        python_files = [e for e in self._file_entities.values() if e.file_type == "python"]

        if not python_files:
            return {}

        lines = [e.lines for e in python_files]
        complexities = [e.complexity for e in python_files]

        return {
            "python_files": len(python_files),
            "total_lines": sum(lines),
            "avg_file_length": sum(lines) / len(lines),
            "max_file_length": max(lines),
            "avg_complexity": sum(complexities) / len(complexities) if complexities else 0,
            "max_complexity": max(complexities) if complexities else 0,
            "total_functions": sum(e.functions for e in python_files),
            "total_classes": sum(e.classes for e in python_files),
            "hotspot_count": len(self._hotspots),
        }

    # =========================================================================
    # 工具方法
    # =========================================================================

    def _entity_to_dict(self, entity: FileEntity) -> Dict[str, Any]:
        """将文件实体转换为字典"""
        return {
            "path": entity.path,
            "name": entity.name,
            "file_type": entity.file_type,
            "lines": entity.lines,
            "complexity": entity.complexity,
            "functions": entity.functions,
            "classes": entity.classes,
            "imports": entity.imports,
            "last_modified": entity.last_modified,
        }

    def _hotspot_to_dict(self, hotspot: CodeHotspot) -> Dict[str, Any]:
        """将热点转换为字典"""
        return {
            "file": hotspot.file_path,
            "reason": hotspot.reason,
            "metrics": hotspot.metrics,
            "suggestions": hotspot.suggestions,
        }

    def format_as_markdown(self, codebase_map: Optional[CodebaseMap] = None) -> str:
        """
        格式化输出为 Markdown

        Args:
            codebase_map: 代码库地图（可选，如果不提供则重新生成）

        Returns:
            Markdown 格式的代码库地图
        """
        if codebase_map is None:
            codebase_map = self.generate_codebase_map()

        lines = [
            "# 代码库认知地图",
            "",
            f"**项目名称**: {codebase_map.project_name}",
            f"**生成时间**: {codebase_map.generated_at}",
            "",
            "---",
            "",
            "## 项目概览",
            "",
            f"- **总文件数**: {codebase_map.total_files}",
            f"- **总代码行数**: {codebase_map.total_lines}",
            f"- **模块数**: {len(codebase_map.modules)}",
            "",
            "## 指标统计",
            "",
        ]

        # 添加指标
        metrics = codebase_map.metrics
        if metrics:
            lines.extend([
                f"- Python 文件: {metrics.get('python_files', 0)}",
                f"- 函数总数: {metrics.get('total_functions', 0)}",
                f"- 类总数: {metrics.get('total_classes', 0)}",
                f"- 平均文件长度: {metrics.get('avg_file_length', 0):.0f} 行",
                f"- 平均复杂度: {metrics.get('avg_complexity', 0):.1f}",
                f"- 代码热点: {metrics.get('hotspot_count', 0)} 个",
                "",
            ])

        # 模块结构
        lines.extend([
            "## 模块结构",
            "",
        ])

        for module in codebase_map.modules:
            lines.append(f"### {module.name}")
            lines.append(f"- **路径**: `{module.path}`")
            lines.append(f"- **用途**: {module.purpose}")
            lines.append(f"- **复杂度**: {module.complexity}")
            lines.append(f"- **健康度**: {module.health_score:.0%}")

            if module.dependencies:
                lines.append(f"- **依赖**: {', '.join(module.dependencies)}")
            if module.dependents:
                lines.append(f"- **被依赖**: {', '.join(module.dependents)}")

            lines.append("")

        # 代码热点
        if codebase_map.hotspots:
            lines.extend([
                "## 代码热点",
                "",
            ])

            for hotspot in codebase_map.hotspots[:10]:  # 限制显示前 10 个
                lines.append(f"### `{hotspot.file_path}`")
                lines.append(f"- **原因**: {hotspot.reason}")

                metrics_str = ", ".join(
                    f"{k}: {v}" for k, v in hotspot.metrics.items()
                )
                lines.append(f"- **指标**: {metrics_str}")

                lines.append("- **建议**:")
                for suggestion in hotspot.suggestions:
                    lines.append(f"  - {suggestion}")

                lines.append("")

        return "\n".join(lines)


# ============================================================================
# 全局单例
# ============================================================================

_codebase_analyzer: Optional[CodebaseAnalyzer] = None


def get_codebase_analyzer(project_root: Optional[str] = None) -> CodebaseAnalyzer:
    """获取代码库分析器单例"""
    global _codebase_analyzer
    if _codebase_analyzer is None:
        _codebase_analyzer = CodebaseAnalyzer(project_root)
    return _codebase_analyzer
