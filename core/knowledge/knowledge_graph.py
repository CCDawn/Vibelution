#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识图谱 (KnowledgeGraph) - 代码关系分析和知识管理

Phase 4 核心模块

功能：
- 代码实体关系建模
- 函数调用链追踪
- 模块依赖分析
- 知识查询和推理
"""

from __future__ import annotations

import os
import json
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import re


# ============================================================================
# 知识图谱节点定义
# ============================================================================

@dataclass
class CodeEntity:
    """代码实体"""
    entity_id: str
    name: str
    entity_type: str  # module, class, function, method, variable
    file_path: str
    line_number: Optional[int] = None
    docstring: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeRelation:
    """代码关系"""
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str  # calls, imports, inherits, contains, uses
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 知识图谱
# ============================================================================

class KnowledgeGraph:
    """
    知识图谱

    管理代码实体和它们之间的关系：

    实体类型：
    - module: 模块文件
    - class: 类
    - function: 函数
    - method: 类方法
    - variable: 变量

    关系类型：
    - calls: 函数调用
    - imports: 导入关系
    - inherits: 继承关系
    - contains: 包含关系
    - uses: 使用关系

    使用方式：
        kg = KnowledgeGraph(project_root)
        kg.analyze_project()
        entities = kg.query_entities(type="function")
        relations = kg.query_relations(source="module_a")
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化知识图谱

        Args:
            project_root: 项目根目录
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 图谱数据
        self._entities: Dict[str, CodeEntity] = {}
        self._relations: List[CodeRelation] = []
        self._entity_index: Dict[str, List[str]] = defaultdict(list)  # 按类型索引
        self._relation_index: Dict[str, List[str]] = defaultdict(list)  # 按关系类型索引

        # 统计
        self._stats = {
            "entities_count": 0,
            "relations_count": 0,
            "last_analyzed": None,
        }

    # =========================================================================
    # 核心接口
    # =========================================================================

    def analyze_project(self) -> Dict[str, Any]:
        """
        分析整个项目

        Returns:
            分析统计
        """
        self._entities.clear()
        self._relations.clear()
        self._entity_index.clear()
        self._relation_index.clear()

        # 获取所有 Python 文件
        python_files = self._get_python_files()

        # 分析每个文件
        for file_path in python_files:
            try:
                self._analyze_file(file_path)
            except Exception:
                continue

        # 建立关系
        self._build_relations()

        # 更新统计
        self._stats["entities_count"] = len(self._entities)
        self._stats["relations_count"] = len(self._relations)
        self._stats["last_analyzed"] = datetime.now().isoformat()

        return self._stats

    def add_entity(self, entity: CodeEntity) -> None:
        """
        添加实体

        Args:
            entity: 代码实体
        """
        self._entities[entity.entity_id] = entity
        self._entity_index[entity.entity_type].append(entity.entity_id)

    def add_relation(self, relation: CodeRelation) -> None:
        """
        添加关系

        Args:
            relation: 代码关系
        """
        self._relations.append(relation)
        self._relation_index[relation.relation_type].append(relation.relation_id)

    # =========================================================================
    # 查询接口
    # =========================================================================

    def query_entities(
        self,
        entity_type: Optional[str] = None,
        name_pattern: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> List[CodeEntity]:
        """
        查询实体

        Args:
            entity_type: 实体类型过滤
            name_pattern: 名称模式（正则）
            file_path: 文件路径过滤

        Returns:
            匹配的实体列表
        """
        results = []

        # 按类型过滤
        if entity_type:
            entity_ids = self._entity_index.get(entity_type, [])
        else:
            entity_ids = list(self._entities.keys())

        # 应用其他过滤器
        for entity_id in entity_ids:
            entity = self._entities.get(entity_id)
            if not entity:
                continue

            if file_path and entity.file_path != file_path:
                continue

            if name_pattern:
                if not re.search(name_pattern, entity.name):
                    continue

            results.append(entity)

        return results

    def query_relations(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation_type: Optional[str] = None,
    ) -> List[CodeRelation]:
        """
        查询关系

        Args:
            source_id: 源实体 ID
            target_id: 目标实体 ID
            relation_type: 关系类型

        Returns:
            匹配的关系列表
        """
        results = []

        # 按类型过滤
        if relation_type:
            relation_ids = self._relation_index.get(relation_type, [])
        else:
            relation_ids = [r.relation_id for r in self._relations]

        # 应用其他过滤器
        for relation in self._relations:
            if relation.relation_id not in relation_ids:
                continue

            if source_id and relation.source_id != source_id:
                continue

            if target_id and relation.target_id != target_id:
                continue

            results.append(relation)

        return results

    def get_call_chain(
        self,
        function_id: str,
        max_depth: int = 5,
    ) -> List[Tuple[str, str]]:
        """
        获取函数调用链

        Args:
            function_id: 函数实体 ID
            max_depth: 最大深度

        Returns:
            调用链 [(caller, callee), ...]
        """
        call_chain = []
        visited = set()
        self._traverse_calls(function_id, call_chain, visited, 0, max_depth)
        return call_chain

    def _traverse_calls(
        self,
        entity_id: str,
        call_chain: List[Tuple[str, str]],
        visited: Set[str],
        depth: int,
        max_depth: int,
    ) -> None:
        """遍历调用关系"""
        if depth >= max_depth or entity_id in visited:
            return

        visited.add(entity_id)

        # 查找直接调用
        calls = self.query_relations(source_id=entity_id, relation_type="calls")
        for call in calls:
            call_chain.append((entity_id, call.target_id))
            self._traverse_calls(
                call.target_id, call_chain, visited, depth + 1, max_depth
            )

    def get_dependents(
        self,
        entity_id: str,
    ) -> List[CodeEntity]:
        """
        获取依赖该实体的其他实体

        Args:
            entity_id: 实体 ID

        Returns:
            依赖该实体的实体列表
        """
        dependents = []
        relations = self.query_relations(target_id=entity_id)

        for relation in relations:
            entity = self._entities.get(relation.source_id)
            if entity:
                dependents.append(entity)

        return dependents

    def get_dependencies(
        self,
        entity_id: str,
    ) -> List[CodeEntity]:
        """
        获取该实体依赖的其他实体

        Args:
            entity_id: 实体 ID

        Returns:
            该实体依赖的实体列表
        """
        dependencies = []
        relations = self.query_relations(source_id=entity_id)

        for relation in relations:
            entity = self._entities.get(relation.target_id)
            if entity:
                dependencies.append(entity)

        return dependencies

    # =========================================================================
    # 文件分析
    # =========================================================================

    def _get_python_files(self) -> List[Path]:
        """获取 Python 文件列表"""
        files = []
        for pattern in ["*.py", "**/*.py"]:
            for f in self.project_root.glob(pattern):
                if "__pycache__" not in str(f) and ".pytest_cache" not in str(f):
                    files.append(f)
        return files

    def _analyze_file(self, file_path: Path) -> None:
        """分析单个文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        # 添加模块实体
        module_id = self._get_module_id(file_path)
        module_entity = CodeEntity(
            entity_id=module_id,
            name=file_path.stem,
            entity_type="module",
            file_path=str(file_path),
            docstring=ast.get_docstring(tree),
        )
        self.add_entity(module_entity)

        # 分析类和函数
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._analyze_class(file_path, node, module_id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not isinstance(node, ast.ClassDef):
                    self._analyze_function(file_path, node, module_id)

    def _analyze_class(
        self,
        file_path: Path,
        class_node: ast.ClassDef,
        module_id: str,
    ) -> None:
        """分析类"""
        class_id = f"{module_id}.{class_node.name}"
        class_entity = CodeEntity(
            entity_id=class_id,
            name=class_node.name,
            entity_type="class",
            file_path=str(file_path),
            line_number=class_node.lineno,
            docstring=ast.get_docstring(class_node),
        )
        self.add_entity(class_entity)

        # 添加继承关系
        for base in class_node.bases:
            base_name = self._get_name_from_node(base)
            if base_name:
                base_id = f"{module_id}.{base_name}"
                relation = CodeRelation(
                    relation_id=f"inherits_{class_id}_{base_id}",
                    source_id=class_id,
                    target_id=base_id,
                    relation_type="inherits",
                )
                self.add_relation(relation)

        # 分析方法
        for node in class_node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_method(file_path, node, class_id)

    def _analyze_method(
        self,
        file_path: Path,
        method_node: ast.FunctionDef,
        class_id: str,
    ) -> None:
        """分析方法"""
        method_id = f"{class_id}.{method_node.name}"
        method_entity = CodeEntity(
            entity_id=method_id,
            name=method_node.name,
            entity_type="method",
            file_path=str(file_path),
            line_number=method_node.lineno,
            docstring=ast.get_docstring(method_node),
        )
        self.add_entity(method_entity)

        # 分析方法内的调用
        self._analyze_calls(file_path, method_node, method_id)

    def _analyze_function(
        self,
        file_path: Path,
        func_node: ast.FunctionDef,
        module_id: str,
    ) -> None:
        """分析函数"""
        func_id = f"{module_id}.{func_node.name}"
        func_entity = CodeEntity(
            entity_id=func_id,
            name=func_node.name,
            entity_type="function",
            file_path=str(file_path),
            line_number=func_node.lineno,
            docstring=ast.get_docstring(func_node),
        )
        self.add_entity(func_entity)

        # 分析函数内的调用
        self._analyze_calls(file_path, func_node, func_id)

    def _analyze_calls(
        self,
        file_path: Path,
        node: ast.FunctionDef,
        func_id: str,
    ) -> None:
        """分析函数调用"""
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                callee_name = self._get_call_name(child)
                if callee_name:
                    # 简化：使用文件名作为模块前缀
                    callee_id = f"?.{callee_name}"
                    relation = CodeRelation(
                        relation_id=f"calls_{func_id}_{callee_id}",
                        source_id=func_id,
                        target_id=callee_id,
                        relation_type="calls",
                    )
                    self.add_relation(relation)

    def _build_relations(self) -> None:
        """建立导入关系"""
        for entity_id, entity in self._entities.items():
            if entity.entity_type == "module":
                # 分析模块的导入
                try:
                    with open(entity.file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    tree = ast.parse(content)

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                module_name = alias.name
                                target_id = f"module:{module_name}"
                                relation = CodeRelation(
                                    relation_id=f"imports_{entity_id}_{target_id}",
                                    source_id=entity_id,
                                    target_id=target_id,
                                    relation_type="imports",
                                )
                                self.add_relation(relation)
                        elif isinstance(node, ast.ImportFrom):
                            module_name = node.module or ""
                            for alias in node.names:
                                target_id = f"{module_name}.{alias.name}"
                                relation = CodeRelation(
                                    relation_id=f"imports_{entity_id}_{target_id}",
                                    source_id=entity_id,
                                    target_id=target_id,
                                    relation_type="imports",
                                )
                                self.add_relation(relation)
                except Exception:
                    pass

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _get_module_id(self, file_path: Path) -> str:
        """获取模块 ID"""
        try:
            rel_path = file_path.relative_to(self.project_root)
            parts = list(rel_path.parts[:-1]) + [file_path.stem]
            return ".".join(parts)
        except ValueError:
            return file_path.stem

    def _get_name_from_node(self, node: ast.AST) -> Optional[str]:
        """从 AST 节点获取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """获取调用名称"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None

    # =========================================================================
    # 持久化
    # =========================================================================

    def save(self, file_path: Optional[str] = None) -> None:
        """
        保存图谱到文件

        Args:
            file_path: 文件路径
        """
        if file_path is None:
            file_path = str(self.project_root / "workspace" / "knowledge_graph.json")

        data = {
            "entities": {
                eid: {
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "entity_type": e.entity_type,
                    "file_path": e.file_path,
                    "line_number": e.line_number,
                    "docstring": e.docstring,
                    "metadata": e.metadata,
                }
                for eid, e in self._entities.items()
            },
            "relations": [
                {
                    "relation_id": r.relation_id,
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "relation_type": r.relation_type,
                    "metadata": r.metadata,
                }
                for r in self._relations
            ],
            "stats": self._stats,
        }

        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, file_path: str) -> None:
        """
        从文件加载图谱

        Args:
            file_path: 文件路径
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self._entities.clear()
        self._relations.clear()
        self._entity_index.clear()
        self._relation_index.clear()

        # 加载实体
        for entity_id, entity_data in data["entities"].items():
            entity = CodeEntity(**entity_data)
            self._entities[entity_id] = entity
            self._entity_index[entity.entity_type].append(entity_id)

        # 加载关系
        for relation_data in data["relations"]:
            relation = CodeRelation(**relation_data)
            self._relations.append(relation)
            self._relation_index[relation.relation_type].append(relation.relation_id)

        # 加载统计
        self._stats = data.get("stats", self._stats)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "entities_by_type": {
                et: len(eids) for et, eids in self._entity_index.items()
            },
            "relations_by_type": {
                rt: len(rids) for rt, rids in self._relation_index.items()
            },
        }


# ============================================================================
# 全局单例
# ============================================================================

_knowledge_graph: Optional[KnowledgeGraph] = None


def get_knowledge_graph(project_root: Optional[str] = None) -> KnowledgeGraph:
    """获取知识图谱单例"""
    global _knowledge_graph
    if _knowledge_graph is None:
        _knowledge_graph = KnowledgeGraph(project_root)
    return _knowledge_graph


def reset_knowledge_graph() -> None:
    """重置知识图谱"""
    global _knowledge_graph
    _knowledge_graph = None
