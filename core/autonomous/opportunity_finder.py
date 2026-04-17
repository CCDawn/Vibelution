#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机会发现器 (OpportunityFinder) - Phase 8 自主探索引擎核心模块

负责：
- 主动扫描代码库发现改进机会
- 识别代码坏味道和技术债
- 评估改进的优先级和影响
- 生成可执行的机会报告

Phase 8.1 核心模块
"""

from __future__ import annotations

import os
import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import hashlib


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class ImprovementOpportunity:
    """改进机会"""
    opportunity_id: str
    category: str  # "code_quality", "test_coverage", "architecture", "documentation", "performance"
    title: str
    description: str
    file_path: Optional[str]
    line_range: Optional[Tuple[int, int]]
    severity: str  # "critical", "high", "medium", "low"
    estimated_effort_hours: float
    impact_score: float  # 0-10，影响越大分值越高
    confidence: float  # 0-1，发现的置信度
    evidence: List[str] = field(default_factory=list)
    suggested_action: str = ""
    related_opportunities: List[str] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_range": self.line_range,
            "severity": self.severity,
            "estimated_effort_hours": self.estimated_effort_hours,
            "impact_score": self.impact_score,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "suggested_action": self.suggested_action,
            "related_opportunities": self.related_opportunities,
            "discovered_at": self.discovered_at,
        }


@dataclass
class CodeSmell:
    """代码坏味道"""
    smell_type: str
    file_path: str
    line_number: int
    severity: str
    description: str
    code_snippet: str = ""
    suggestion: str = ""


@dataclass
class ScanResult:
    """扫描结果"""
    scan_id: str
    timestamp: str
    total_files_scanned: int
    opportunities: List[ImprovementOpportunity]
    code_smells: List[CodeSmell]
    statistics: Dict[str, Any]

    def get_by_category(self, category: str) -> List[ImprovementOpportunity]:
        return [o for o in self.opportunities if o.category == category]

    def get_by_severity(self, severity: str) -> List[ImprovementOpportunity]:
        return [o for o in self.opportunities if o.severity == severity]

    def get_top_opportunities(self, limit: int = 5) -> List[ImprovementOpportunity]:
        """获取最优先改进的机会（按 impact_score 排序）"""
        return sorted(self.opportunities, key=lambda x: (
            {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(x.severity, 0),
            x.impact_score
        ), reverse=True)[:limit]


# ============================================================================
# 代码指标计算器
# ============================================================================

class CodeMetricsCalculator:
    """代码指标计算器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self._cache: Dict[str, Dict] = {}

    def calculate_file_metrics(self, file_path: Path) -> Dict[str, Any]:
        """计算单个文件的指标"""
        if str(file_path) in self._cache:
            return self._cache[str(file_path)]

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            tree = ast.parse(content)
            metrics = self._analyze_ast(tree, content)
            metrics["path"] = str(file_path)
            metrics["size_bytes"] = file_path.stat().st_size

            self._cache[str(file_path)] = metrics
            return metrics
        except Exception:
            return {"path": str(file_path), "error": True}

    def _analyze_ast(self, tree: ast.AST, content: str) -> Dict[str, Any]:
        """分析 AST 获取指标"""
        lines = content.split('\n')

        metrics = {
            "total_lines": len(lines),
            "code_lines": sum(1 for line in lines if line.strip() and not line.strip().startswith('#')),
            "comment_lines": sum(1 for line in lines if line.strip().startswith('#')),
            "blank_lines": sum(1 for line in lines if not line.strip()),
            "function_count": 0,
            "class_count": 0,
            "import_count": 0,
            "max_function_length": 0,
            "avg_function_length": 0,
            "max_cyclomatic_complexity": 0,
            "avg_cyclomatic_complexity": 0,
        }

        functions = []
        classes = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                metrics["function_count"] += 1
                func_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 1
                functions.append({
                    "name": node.name,
                    "lineno": node.lineno,
                    "lines": func_lines,
                    "complexity": self._calculate_complexity(node),
                })
                metrics["max_function_length"] = max(metrics["max_function_length"], func_lines)
                metrics["max_cyclomatic_complexity"] = max(
                    metrics["max_cyclomatic_complexity"],
                    functions[-1]["complexity"]
                )
            elif isinstance(node, ast.ClassDef):
                metrics["class_count"] += 1
                classes.append(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                metrics["import_count"] += 1

        if functions:
            metrics["avg_function_length"] = sum(f["lines"] for f in functions) / len(functions)
            metrics["avg_cyclomatic_complexity"] = sum(f["complexity"] for f in functions) / len(functions)

        return metrics

    def _calculate_complexity(self, node: ast.AST) -> int:
        """计算圈复杂度"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity


# ============================================================================
# 重复代码检测器
# ============================================================================

class DuplicationDetector:
    """重复代码检测器"""

    def __init__(self, min_length: int = 6, min_duplications: int = 2):
        self.min_length = min_length
        self.min_duplications = min_duplications
        self._duplications: List[Dict] = []

    def scan_directory(self, directory: Path) -> List[Dict]:
        """扫描目录查找重复代码"""
        code_blocks: Dict[str, List[Tuple[str, int]]] = defaultdict(list)

        for py_file in directory.rglob("*.py"):
            if self._should_ignore(py_file):
                continue

            try:
                blocks = self._extract_code_blocks(py_file)
                for block in blocks:
                    normalized = self._normalize_block(block)
                    if normalized:
                        code_blocks[normalized].append((str(py_file), len(block)))
            except Exception:
                continue

        self._duplications = [
            {
                "block_length": length,
                "files": files,
                "duplication_count": len(files),
            }
            for normalized, files in code_blocks.items()
            for length in [max(f[1] for f in files)]
            if len(files) >= self.min_duplications
        ]

        return self._duplications

    def _should_ignore(self, file_path: Path) -> bool:
        """检查是否应该忽略文件"""
        ignore_patterns = [
            '__pycache__', '.pytest_cache', 'venv', 'env',
            'node_modules', '.git', 'tests/test_', '.pyc'
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in ignore_patterns)

    def _extract_code_blocks(self, file_path: Path) -> List[str]:
        """提取代码块"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            tree = ast.parse(content)
            blocks = []

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno and node.lineno:
                        lines = content.split('\n')[node.lineno-1:node.end_lineno]
                        block = '\n'.join(lines).strip()
                        if len(block.split('\n')) >= self.min_length:
                            blocks.append(block)

            return blocks
        except Exception:
            return []

    def _normalize_block(self, block: str) -> Optional[str]:
        """规范化代码块用于比较"""
        lines = block.split('\n')
        normalized_lines = []

        for line in lines:
            line = re.sub(r'".*?"', '"..."', line)
            line = re.sub(r"'.*?'", "'...'", line)
            line = re.sub(r'\d+', 'N', line)
            line = re.sub(r'\s+', ' ', line.strip())
            if line and not line.startswith('#'):
                normalized_lines.append(line)

        if len(normalized_lines) >= 3:
            return '\n'.join(normalized_lines)
        return None


# ============================================================================
# 测试覆盖率分析器
# ============================================================================

class TestCoverageAnalyzer:
    """测试覆盖率分析器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self._coverage_data: Dict[str, Any] = {}

    def analyze(self) -> Dict[str, Any]:
        """分析测试覆盖率"""
        source_files = self._get_source_files()
        test_files = self._get_test_files()

        coverage_map = {}
        for source_file in source_files:
            related_tests = self._find_related_tests(source_file, test_files)
            has_coverage = len(related_tests) > 0
            coverage_map[str(source_file)] = {
                "has_tests": has_coverage,
                "test_files": [str(t) for t in related_tests],
            }

        uncovered = [f for f, d in coverage_map.items() if not d["has_tests"]]

        return {
            "total_source_files": len(source_files),
            "total_test_files": len(test_files),
            "files_with_tests": len(source_files) - len(uncovered),
            "uncovered_files": uncovered,
            "coverage_percentage": (len(source_files) - len(uncovered)) / max(len(source_files), 1) * 100,
            "coverage_map": coverage_map,
        }

    def _get_source_files(self) -> List[Path]:
        """获取源文件列表"""
        source_files = []
        core_dir = self.project_root / "core"
        tools_dir = self.project_root / "tools"

        for directory in [core_dir, tools_dir, self.project_root]:
            if directory.exists():
                for py_file in directory.rglob("*.py"):
                    if not self._should_ignore(py_file):
                        source_files.append(py_file)

        return source_files

    def _get_test_files(self) -> List[Path]:
        """获取测试文件列表"""
        test_dir = self.project_root / "tests"
        if not test_dir.exists():
            return []

        return list(test_dir.rglob("test_*.py"))

    def _find_related_tests(self, source_file: Path, test_files: List[Path]) -> List[Path]:
        """查找相关的测试文件"""
        module_name = source_file.stem
        related = []

        for test_file in test_files:
            if module_name in test_file.stem:
                related.append(test_file)

        return related

    def _should_ignore(self, file_path: Path) -> bool:
        """检查是否应该忽略"""
        return '__pycache__' in str(file_path) or file_path.name.startswith('test_')


# ============================================================================
# 机会发现器
# ============================================================================

class OpportunityFinder:
    """
    机会发现器 - Phase 8 自主探索引擎核心

    功能：
    - 扫描代码库识别改进机会
    - 评估机会的优先级和影响
    - 生成可执行的机会报告
    """

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.metrics_calculator = CodeMetricsCalculator(project_root)
        self.duplication_detector = DuplicationDetector()
        self.coverage_analyzer = TestCoverageAnalyzer(project_root)
        self._opportunity_counter = 0

    def scan(self) -> ScanResult:
        """
        执行完整扫描，识别所有改进机会

        Returns:
            ScanResult: 扫描结果
        """
        scan_id = hashlib.md5(
            datetime.now().isoformat().encode()
        ).hexdigest()[:8]

        opportunities = []
        code_smells = []

        # 1. 扫描代码坏味道
        smells = self._scan_code_smells()
        code_smells.extend(smells)

        # 2. 识别改进机会
        opportunities.extend(self._find_quality_opportunities())
        opportunities.extend(self._find_test_coverage_opportunities())
        opportunities.extend(self._find_architecture_opportunities())
        opportunities.extend(self._find_documentation_opportunities())

        # 3. 计算统计信息
        statistics = self._calculate_statistics(opportunities, code_smells)

        return ScanResult(
            scan_id=scan_id,
            timestamp=datetime.now().isoformat(),
            total_files_scanned=len(list(self.project_root.rglob("*.py"))),
            opportunities=opportunities,
            code_smells=code_smells,
            statistics=statistics,
        )

    def _scan_code_smells(self) -> List[CodeSmell]:
        """扫描代码坏味道"""
        smells = []

        for py_file in self.project_root.rglob("*.py"):
            if self._should_ignore_file(py_file):
                continue

            try:
                file_smells = self._scan_file_smells(py_file)
                smells.extend(file_smells)
            except Exception:
                continue

        return smells

    def _scan_file_smells(self, file_path: Path) -> List[CodeSmell]:
        """扫描单个文件的坏味道"""
        smells = []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            tree = ast.parse(content)
            metrics = self.metrics_calculator.calculate_file_metrics(file_path)

            for node in ast.walk(tree):
                # 检测过长函数
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno and node.lineno:
                        func_length = node.end_lineno - node.lineno + 1
                        if func_length > 100:
                            smells.append(CodeSmell(
                                smell_type="long_method",
                                file_path=str(file_path),
                                line_number=node.lineno,
                                severity="high" if func_length > 200 else "medium",
                                description=f"函数 '{node.name}' 太长 ({func_length} 行)",
                                suggestion="考虑拆分为更小的函数",
                            ))

                        # 检测高复杂度
                        complexity = self.metrics_calculator._calculate_complexity(node)
                        if complexity > 15:
                            smells.append(CodeSmell(
                                smell_type="high_complexity",
                                file_path=str(file_path),
                                line_number=node.lineno,
                                severity="high" if complexity > 25 else "medium",
                                description=f"函数 '{node.name}' 圈复杂度过高 ({complexity})",
                                suggestion="考虑简化条件逻辑或提取子函数",
                            ))

                # 检测大类
                if isinstance(node, ast.ClassDef):
                    class_lines = node.end_lineno - node.lineno + 1 if node.end_lineno else 1
                    if class_lines > 500:
                        smells.append(CodeSmell(
                            smell_type="god_class",
                            file_path=str(file_path),
                            line_number=node.lineno,
                            severity="critical" if class_lines > 800 else "high",
                            description=f"类 '{node.name}' 过大 ({class_lines} 行)",
                            suggestion="考虑拆分为更小的类或模块",
                        ))

        except Exception:
            pass

        return smells

    def _find_quality_opportunities(self) -> List[ImprovementOpportunity]:
        """查找代码质量改进机会"""
        opportunities = []

        # 扫描重复代码
        duplications = self.duplication_detector.scan_directory(self.project_root)

        for dup in duplications[:5]:  # 限制数量
            files = [f[0] for f in dup["files"]]
            self._opportunity_counter += 1
            opportunities.append(ImprovementOpportunity(
                opportunity_id=f"dup_{self._opportunity_counter}",
                category="code_quality",
                title="重复代码",
                description=f"发现 {dup['duplication_count']} 处重复代码，可能可以提取为公共函数",
                file_path=files[0] if files else None,
                line_range=None,
                severity="medium",
                estimated_effort_hours=2.0,
                impact_score=6.0,
                confidence=0.85,
                evidence=[f"涉及文件: {', '.join(files[:3])}"],
                suggested_action="提取重复代码为公共函数或基类",
            ))

        # 扫描代码复杂度
        for py_file in self.project_root.rglob("*.py"):
            if self._should_ignore_file(py_file):
                continue

            try:
                metrics = self.metrics_calculator.calculate_file_metrics(py_file)
                if metrics.get("max_cyclomatic_complexity", 0) > 20:
                    self._opportunity_counter += 1
                    opportunities.append(ImprovementOpportunity(
                        opportunity_id=f"complex_{self._opportunity_counter}",
                        category="code_quality",
                        title="高圈复杂度代码",
                        description=f"文件存在圈复杂度超过 20 的函数",
                        file_path=str(py_file),
                        line_range=None,
                        severity="high",
                        estimated_effort_hours=4.0,
                        impact_score=7.0,
                        confidence=0.90,
                        evidence=[f"最大复杂度: {metrics['max_cyclomatic_complexity']}"],
                        suggested_action="重构高复杂度函数，简化条件逻辑",
                    ))
            except Exception:
                continue

        return opportunities

    def _find_test_coverage_opportunities(self) -> List[ImprovementOpportunity]:
        """查找测试覆盖率改进机会"""
        opportunities = []

        coverage = self.coverage_analyzer.analyze()
        uncovered = coverage.get("uncovered_files", [])

        for file_path in uncovered[:5]:  # 限制数量
            self._opportunity_counter += 1
            opportunities.append(ImprovementOpportunity(
                opportunity_id=f"test_{self._opportunity_counter}",
                category="test_coverage",
                title="缺少测试覆盖",
                description=f"文件缺少对应的测试文件",
                file_path=file_path,
                line_range=None,
                severity="medium",
                estimated_effort_hours=3.0,
                impact_score=5.0,
                confidence=0.95,
                evidence=[f"覆盖百分比: {coverage['coverage_percentage']:.1f}%"],
                suggested_action="添加单元测试以提高覆盖率",
            ))

        return opportunities

    def _find_architecture_opportunities(self) -> List[ImprovementOpportunity]:
        """查找架构改进机会"""
        opportunities = []

        # 检查 agent.py 是否过大
        agent_file = self.project_root / "agent.py"
        if agent_file.exists():
            try:
                with open(agent_file, 'r', encoding='utf-8') as f:
                    lines = len(f.readlines())

                if lines > 800:
                    self._opportunity_counter += 1
                    opportunities.append(ImprovementOpportunity(
                        opportunity_id=f"arch_{self._opportunity_counter}",
                        category="architecture",
                        title="agent.py 文件过大",
                        description=f"agent.py 超过 800 行 ({lines} 行)，建议拆分为模块",
                        file_path="agent.py",
                        line_range=None,
                        severity="high",
                        estimated_effort_hours=8.0,
                        impact_score=8.0,
                        confidence=0.95,
                        evidence=[f"当前行数: {lines}"],
                        suggested_action="将 agent.py 拆分为多个模块：llm_handler.py, tool_manager.py 等",
                    ))
            except Exception:
                pass

        return opportunities

    def _find_documentation_opportunities(self) -> List[ImprovementOpportunity]:
        """查找文档改进机会"""
        opportunities = []

        for py_file in self.project_root.rglob("*.py"):
            if self._should_ignore_file(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                tree = ast.parse(content)
                has_docstring = ast.get_docstring(tree) is not None

                if not has_docstring:
                    self._opportunity_counter += 1
                    opportunities.append(ImprovementOpportunity(
                        opportunity_id=f"doc_{self._opportunity_counter}",
                        category="documentation",
                        title="缺少模块文档",
                        description=f"文件缺少文档字符串",
                        file_path=str(py_file),
                        line_range=None,
                        severity="low",
                        estimated_effort_hours=0.5,
                        impact_score=3.0,
                        confidence=0.90,
                        evidence=["模块级文档字符串为空"],
                        suggested_action="添加模块级文档字符串",
                    ))
            except Exception:
                continue

        return opportunities

    def _should_ignore_file(self, file_path: Path) -> bool:
        """检查是否应该忽略文件"""
        ignore_patterns = [
            '__pycache__', '.pytest_cache', 'venv', 'env',
            'node_modules', '.git', 'backups', 'temp',
            'workspace/logs', 'cursor_report_history',
        ]
        path_str = str(file_path)
        return any(pattern in path_str for pattern in ignore_patterns)

    def _calculate_statistics(self, opportunities: List[ImprovementOpportunity],
                                smells: List[CodeSmell]) -> Dict[str, Any]:
        """计算统计信息"""
        by_category = defaultdict(int)
        by_severity = defaultdict(int)

        for opp in opportunities:
            by_category[opp.category] += 1
            by_severity[opp.severity] += 1

        return {
            "total_opportunities": len(opportunities),
            "total_code_smells": len(smells),
            "by_category": dict(by_category),
            "by_severity": dict(by_severity),
            "total_estimated_hours": sum(o.estimated_effort_hours for o in opportunities),
        }


# ============================================================================
# 单例和工具函数
# ============================================================================

_opportunity_finder_instance: Optional[OpportunityFinder] = None


def get_opportunity_finder(project_root: Optional[str] = None) -> OpportunityFinder:
    """获取机会发现器单例"""
    global _opportunity_finder_instance

    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if _opportunity_finder_instance is None:
        _opportunity_finder_instance = OpportunityFinder(project_root)

    return _opportunity_finder_instance


def reset_opportunity_finder() -> None:
    """重置机会发现器单例"""
    global _opportunity_finder_instance
    _opportunity_finder_instance = None


# ============================================================================
# 快捷函数
# ============================================================================

def find_opportunities(project_root: Optional[str] = None) -> ScanResult:
    """
    快捷函数：扫描并返回改进机会

    Args:
        project_root: 项目根目录

    Returns:
        ScanResult: 扫描结果
    """
    finder = get_opportunity_finder(project_root)
    return finder.scan()
