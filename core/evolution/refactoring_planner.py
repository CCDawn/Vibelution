#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构规划器 (RefactoringPlanner) - 识别改进点并生成重构计划

Phase 3 核心模块

负责：
- 分析代码库识别重构机会
- 评估重构风险和收益
- 生成详细的重构计划
- 提供备选方案
"""

from __future__ import annotations

import os
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class RefactoringOpportunity:
    """重构机会"""
    opportunity_id: str
    file_path: str
    code_smell: str
    severity: str  # "high", "medium", "low"
    description: str
    estimated_lines: int
    estimated_effort: float  # 小时
    benefits: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    suggested_approach: str = ""


@dataclass
class RefactoringTask:
    """重构任务"""
    task_id: str
    description: str
    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    dependencies: List[str] = field(default_factory=list)
    estimated_time: float = 0.0
    priority: str = "medium"
    verification_steps: List[str] = field(default_factory=list)


@dataclass
class RefactoringPlan:
    """重构计划"""
    plan_id: str
    goal_description: str
    opportunities: List[RefactoringOpportunity] = field(default_factory=list)
    tasks: List[RefactoringTask] = field(default_factory=list)
    total_estimated_time: float = 0.0
    risk_level: str = "medium"
    rollback_plan: str = ""
    success_criteria: List[str] = field(default_factory=list)


# ============================================================================
# 代码坏味道定义
# ============================================================================

CODE_SMELLS = {
    "god_class": {
        "name": "上帝类",
        "description": "类过大，职责过多",
        "threshold": {"lines": 500, "functions": 30, "classes": 10},
        "approach": "职责分离，提取子类或模块",
    },
    "long_method": {
        "name": "过长方法",
        "description": "方法代码行数过多",
        "threshold": {"lines": 100},
        "approach": "拆分为多个小方法",
    },
    "high_complexity": {
        "name": "高圈复杂度",
        "description": "控制流过于复杂",
        "threshold": {"cyclomatic": 15},
        "approach": "简化条件，使用策略模式或提取方法",
    },
    "duplicated_code": {
        "name": "重复代码",
        "description": "存在相似的代码片段",
        "threshold": {"similarity": 0.8, "occurrences": 3},
        "approach": "提取公共函数或使用模板方法",
    },
    "dead_code": {
        "name": "死代码",
        "description": "未使用的代码",
        "threshold": {},
        "approach": "删除未使用的代码",
    },
    "magic_numbers": {
        "name": "魔法数字",
        "description": "硬编码的数字常量",
        "threshold": {"occurrences": 3},
        "approach": "提取为命名常量",
    },
    "long_parameter_list": {
        "name": "过长参数列表",
        "description": "函数参数过多",
        "threshold": {"params": 5},
        "approach": "使用参数对象或配置类",
    },
}


# ============================================================================
# 重构规划器
# ============================================================================

class RefactoringPlanner:
    """
    重构规划器

    分析代码库，识别重构机会，生成重构计划。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化重构规划器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 分析结果缓存
        self._opportunities: List[RefactoringOpportunity] = []
        self._analysis_cache: Dict[str, Any] = {}

    # =========================================================================
    # 核心接口
    # =========================================================================

    async def create_plan(
        self,
        goal,
        bottlenecks: List[Any],
    ) -> RefactoringPlan:
        """
        创建重构计划

        Args:
            goal: 进化目标
            bottlenecks: 识别的瓶颈

        Returns:
            重构计划
        """
        # 识别重构机会
        opportunities = await self.identify_opportunities(
            target_dimensions=[b.dimension for b in bottlenecks]
        )

        # 生成重构任务
        tasks = self._generate_tasks(opportunities)

        # 创建计划
        plan = RefactoringPlan(
            plan_id=f"plan_{goal.goal_id}_{int(datetime.now().timestamp())}",
            goal_description=goal.description,
            opportunities=opportunities,
            tasks=tasks,
            total_estimated_time=sum(t.estimated_time for t in tasks),
            risk_level=self._assess_risk_level(opportunities),
            success_criteria=self._generate_success_criteria(goal),
        )

        return plan

    async def identify_opportunities(
        self,
        target_dimensions: Optional[List[str]] = None,
    ) -> List[RefactoringOpportunity]:
        """
        识别重构机会

        Args:
            target_dimensions: 目标能力维度

        Returns:
            重构机会列表
        """
        self._opportunities = []

        # 获取 Python 文件
        python_files = self._get_python_files()

        # 分析每个文件
        for file_path in python_files[:50]:  # 限制分析数量
            try:
                opportunities = await self._analyze_file(file_path)
                self._opportunities.extend(opportunities)
            except Exception:
                continue

        # 按严重程度排序
        self._opportunities.sort(
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.severity, 2)
        )

        return self._opportunities

    def _generate_tasks(self, opportunities: List[RefactoringOpportunity]) -> List[RefactoringTask]:
        """生成重构任务"""
        tasks = []

        for i, opp in enumerate(opportunities[:10]):  # 限制任务数量
            task = RefactoringTask(
                task_id=f"refactor_task_{i + 1}",
                description=f"重构 {opp.file_path}: {opp.code_smell}",
                file_path=opp.file_path,
                estimated_time=opp.estimated_effort,
                priority=opp.severity,
                verification_steps=[
                    f"检查 {opp.file_path} 语法",
                    f"运行相关测试",
                    "验证功能正常",
                ],
            )
            tasks.append(task)

        return tasks

    def _assess_risk_level(self, opportunities: List[RefactoringOpportunity]) -> str:
        """评估风险等级"""
        high_count = sum(1 for o in opportunities if o.severity == "high")

        if high_count > 5:
            return "high"
        elif high_count > 0:
            return "medium"
        return "low"

    def _generate_success_criteria(self, goal) -> List[str]:
        """生成成功标准"""
        return [
            "代码语法正确",
            "所有测试通过",
            f"{goal.target_dimension} 评分提升",
        ]

    # =========================================================================
    # 文件分析
    # =========================================================================

    def _get_python_files(self) -> List[Path]:
        """获取项目中的 Python 文件"""
        files = []
        for pattern in ["*.py", "**/*.py"]:
            for f in self.project_root.glob(pattern):
                if "__pycache__" not in str(f) and ".pytest_cache" not in str(f):
                    files.append(f)
        return files

    async def _analyze_file(self, file_path: Path) -> List[RefactoringOpportunity]:
        """分析单个文件"""
        opportunities = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return opportunities

        # 解析 AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return opportunities

        # 检查各项指标
        lines = content.split('\n')

        # 1. 检查文件长度 (上帝类)
        if len(lines) > CODE_SMELLS["god_class"]["threshold"]["lines"]:
            opportunities.append(RefactoringOpportunity(
                opportunity_id=f"god_class_{file_path.name}",
                file_path=str(file_path),
                code_smell="god_class",
                severity="high" if len(lines) > 800 else "medium",
                description=f"文件过长 ({len(lines)} 行)",
                estimated_lines=0,
                estimated_effort=4.0,
                benefits=["提高可维护性", "便于测试"],
                risks=["可能影响现有功能"],
                suggested_approach=CODE_SMELLS["god_class"]["approach"],
            ))

        # 2. 检查方法长度
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if hasattr(node, 'end_lineno') and hasattr(node, 'lineno'):
                    method_lines = node.end_lineno - node.lineno + 1
                    if method_lines > CODE_SMELLS["long_method"]["threshold"]["lines"]:
                        opportunities.append(RefactoringOpportunity(
                            opportunity_id=f"long_method_{file_path.name}_{node.lineno}",
                            file_path=str(file_path),
                            code_smell="long_method",
                            severity="medium",
                            description=f"方法 '{node.name}' 过长 ({method_lines} 行)",
                            estimated_lines=0,
                            estimated_effort=2.0,
                            start_line=node.lineno,
                            end_line=node.end_lineno,
                            benefits=["提高可读性", "便于复用"],
                            risks=["需要仔细测试"],
                            suggested_approach=CODE_SMELLS["long_method"]["approach"],
                        ))

        # 3. 检查圈复杂度
        complexity = self._calculate_complexity(tree)
        if complexity > CODE_SMELLS["high_complexity"]["threshold"]["cyclomatic"]:
            opportunities.append(RefactoringOpportunity(
                opportunity_id=f"high_complexity_{file_path.name}",
                file_path=str(file_path),
                code_smell="high_complexity",
                severity="high" if complexity > 20 else "medium",
                description=f"圈复杂度过高 ({complexity})",
                estimated_lines=0,
                estimated_effort=3.0,
                benefits=["降低维护难度", "减少 Bug"],
                risks=["重构可能引入错误"],
                suggested_approach=CODE_SMELLS["high_complexity"]["approach"],
            ))

        # 4. 检查函数参数数量
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                param_count = len(node.args.args)
                if param_count > CODE_SMELLS["long_parameter_list"]["threshold"]["params"]:
                    opportunities.append(RefactoringOpportunity(
                        opportunity_id=f"long_params_{file_path.name}_{node.lineno}",
                        file_path=str(file_path),
                        code_smell="long_parameter_list",
                        severity="low",
                        description=f"方法 '{node.name}' 参数过多 ({param_count})",
                        estimated_lines=0,
                        estimated_effort=1.0,
                        benefits=["提高可读性"],
                        risks=["可能改变调用方式"],
                        suggested_approach=CODE_SMELLS["long_parameter_list"]["approach"],
                    ))

        return opportunities

    def _calculate_complexity(self, tree: ast.AST) -> int:
        """计算圈复杂度"""
        complexity = 1

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1

        return complexity

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def get_opportunities_summary(self) -> Dict[str, Any]:
        """获取重构机会摘要"""
        if not self._opportunities:
            return {"total": 0, "by_severity": {}, "by_type": {}}

        by_severity = defaultdict(int)
        by_type = defaultdict(int)

        for opp in self._opportunities:
            by_severity[opp.severity] += 1
            by_type[opp.code_smell] += 1

        return {
            "total": len(self._opportunities),
            "by_severity": dict(by_severity),
            "by_type": dict(by_type),
            "estimated_total_time": sum(o.estimated_effort for o in self._opportunities),
        }

    def generate_refactoring_report(self) -> str:
        """生成重构报告"""
        summary = self.get_opportunities_summary()

        lines = [
            "# 代码重构报告",
            "",
            f"**生成时间**: {datetime.now().isoformat()}",
            "",
            "## 概览",
            "",
            f"- **总重构机会**: {summary['total']}",
            f"- **预计总工时**: {summary['estimated_total_time']:.1f} 小时",
            "",
            "### 按严重程度分布",
            "",
        ]

        by_severity = summary.get("by_severity", {})
        for severity in ["high", "medium", "low"]:
            count = by_severity.get(severity, 0)
            lines.append(f"- **{severity.upper()}**: {count} 个")

        lines.extend([
            "",
            "### 按类型分布",
            "",
        ])

        by_type = summary.get("by_type", {})
        for smell_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"- **{smell_type}**: {count} 个")

        # 列出高优先级机会
        high_priority = [o for o in self._opportunities if o.severity == "high"]
        if high_priority:
            lines.extend([
                "",
                "## 高优先级重构机会",
                "",
            ])
            for opp in high_priority[:5]:
                lines.append(f"### {opp.file_path}")
                lines.append(f"- **问题**: {opp.description}")
                lines.append(f"- **建议**: {opp.suggested_approach}")
                lines.append("")

        return "\n".join(lines)


# ============================================================================
# 全局单例
# ============================================================================

_refactoring_planner: Optional[RefactoringPlanner] = None


def get_refactoring_planner(project_root: Optional[str] = None) -> RefactoringPlanner:
    """获取重构规划器单例"""
    global _refactoring_planner
    if _refactoring_planner is None:
        _refactoring_planner = RefactoringPlanner(project_root)
    return _refactoring_planner
