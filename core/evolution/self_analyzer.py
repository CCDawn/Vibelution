#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自我分析器 (SelfAnalyzer) - 虾宝自我分析能力核心模块

负责：
- 评估虾宝在各个能力维度上的表现
- 分析代码库状态，识别改进机会
- 追踪能力变化趋势
- 生成自我分析报告

Phase 2 核心模块
"""

from __future__ import annotations

import os
import json
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


# ============================================================================
# 能力维度定义
# ============================================================================

class CapabilityDimension(Enum):
    """能力维度枚举"""
    CODE_QUALITY = "code_quality"           # 代码质量
    TEST_COVERAGE = "test_coverage"          # 测试覆盖
    TOOL_USAGE = "tool_usage"                # 工具使用
    AUTONOMY = "autonomy"                    # 自主性
    MEMORY_MANAGEMENT = "memory_management"  # 记忆管理
    SECURITY = "security"                    # 安全性
    ARCHITECTURE = "architecture"            # 架构设计
    LEARNING = "learning"                    # 学习能力
    PLANNING = "planning"                    # 规划能力
    EXECUTION = "execution"                  # 执行能力


@dataclass
class CapabilityScore:
    """能力评分"""
    dimension: str
    score: float  # 0.0 - 1.0
    evidence: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SelfAnalysisReport:
    """自我分析报告"""
    generation: int
    timestamp: str
    overall_score: float
    dimension_scores: List[CapabilityScore]
    strengths: List[str]
    weaknesses: List[str]
    improvement_opportunities: List[Dict[str, Any]]
    code_insights: Dict[str, Any]
    recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generation": self.generation,
            "timestamp": self.timestamp,
            "overall_score": self.overall_score,
            "dimension_scores": [s.to_dict() for s in self.dimension_scores],
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "improvement_opportunities": self.improvement_opportunities,
            "code_insights": self.code_insights,
            "recommendations": self.recommendations,
        }


# ============================================================================
# 分析器配置
# ============================================================================

# 能力维度权重（用于计算综合得分）
DIMENSION_WEIGHTS = {
    CapabilityDimension.CODE_QUALITY: 0.15,
    CapabilityDimension.TEST_COVERAGE: 0.15,
    CapabilityDimension.TOOL_USAGE: 0.10,
    CapabilityDimension.AUTONOMY: 0.10,
    CapabilityDimension.MEMORY_MANAGEMENT: 0.10,
    CapabilityDimension.SECURITY: 0.10,
    CapabilityDimension.ARCHITECTURE: 0.10,
    CapabilityDimension.LEARNING: 0.10,
    CapabilityDimension.PLANNING: 0.05,
    CapabilityDimension.EXECUTION: 0.05,
}

# 评分阈值
SCORE_THRESHOLDS = {
    "excellent": 0.85,
    "good": 0.70,
    "fair": 0.50,
    "poor": 0.30,
}


# ============================================================================
# 自我分析器
# ============================================================================

class SelfAnalyzer:
    """
    自我分析器

    分析虾宝在各个能力维度上的表现，识别改进机会。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化自我分析器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 能力历史记录
        self._score_history: Dict[str, List[CapabilityScore]] = {}

        # 分析缓存
        self._codebase_analysis: Optional[Dict[str, Any]] = None
        self._tool_usage_stats: Optional[Dict[str, Any]] = None

    # =========================================================================
    # 核心分析接口
    # =========================================================================

    async def assess_capabilities(self) -> List[CapabilityScore]:
        """
        评估所有能力维度

        Returns:
            各维度的能力评分列表
        """
        scores = []

        # 代码质量分析
        code_quality = await self._analyze_code_quality()
        scores.append(code_quality)

        # 测试覆盖分析
        test_coverage = await self._analyze_test_coverage()
        scores.append(test_coverage)

        # 工具使用分析
        tool_usage = await self._analyze_tool_usage()
        scores.append(tool_usage)

        # 自主性分析
        autonomy = await self._analyze_autonomy()
        scores.append(autonomy)

        # 记忆管理分析
        memory_mgmt = await self._analyze_memory_management()
        scores.append(memory_mgmt)

        # 安全性分析
        security = await self._analyze_security()
        scores.append(security)

        # 架构设计分析
        architecture = await self._analyze_architecture()
        scores.append(architecture)

        # 学习能力分析
        learning = await self._analyze_learning()
        scores.append(learning)

        # 规划能力分析
        planning = await self._analyze_planning()
        scores.append(planning)

        # 执行能力分析
        execution = await self._analyze_execution()
        scores.append(execution)

        # 记录历史
        for score in scores:
            if score.dimension not in self._score_history:
                self._score_history[score.dimension] = []
            self._score_history[score.dimension].append(score)

        return scores

    async def generate_analysis_report(
        self,
        generation: int,
        tool_usage_stats: Optional[Dict[str, Any]] = None,
    ) -> SelfAnalysisReport:
        """
        生成完整的自我分析报告

        Args:
            generation: 当前世代
            tool_usage_stats: 工具使用统计（可选）

        Returns:
            自我分析报告
        """
        if tool_usage_stats:
            self._tool_usage_stats = tool_usage_stats

        # 评估所有能力
        dimension_scores = await self.assess_capabilities()

        # 计算综合得分
        overall_score = self._calculate_overall_score(dimension_scores)

        # 识别优势和劣势
        strengths = self._identify_strengths(dimension_scores)
        weaknesses = self._identify_weaknesses(dimension_scores)

        # 识别改进机会
        opportunities = await self.identify_improvement_opportunities(dimension_scores)

        # 分析代码库
        code_insights = await self.analyze_codebase()

        # 生成建议
        recommendations = self._generate_recommendations(
            dimension_scores, opportunities, code_insights
        )

        return SelfAnalysisReport(
            generation=generation,
            timestamp=datetime.now().isoformat(),
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_opportunities=opportunities,
            code_insights=code_insights,
            recommendations=recommendations,
        )

    async def identify_improvement_opportunities(
        self,
        dimension_scores: List[CapabilityScore],
    ) -> List[Dict[str, Any]]:
        """
        识别改进机会

        Args:
            dimension_scores: 能力评分列表

        Returns:
            改进机会列表
        """
        opportunities = []

        # 基于低分维度识别改进机会
        for score in dimension_scores:
            if score.score < SCORE_THRESHOLDS["good"]:
                opportunity = {
                    "dimension": score.dimension,
                    "current_score": score.score,
                    "target_score": SCORE_THRESHOLDS["good"],
                    "gap": SCORE_THRESHOLDS["good"] - score.score,
                    "suggestions": self._get_dimension_suggestions(score.dimension),
                    "priority": self._calculate_priority(score.score, score.weaknesses),
                }
                opportunities.append(opportunity)

        # 基于代码库分析识别改进机会
        code_insights = await self.analyze_codebase()
        if code_insights:
            # 代码复杂度问题
            high_complexity = code_insights.get("high_complexity_files", [])
            if high_complexity:
                opportunities.append({
                    "dimension": "architecture",
                    "type": "code_complexity",
                    "current_score": 0.0,
                    "target_score": 0.0,
                    "gap": 0.0,
                    "details": high_complexity[:5],
                    "suggestions": ["考虑重构高复杂度文件", "拆分大型函数"],
                    "priority": "high",
                })

            # 重复代码问题
            duplicates = code_insights.get("duplicates", [])
            if duplicates:
                opportunities.append({
                    "dimension": "code_quality",
                    "type": "code_duplication",
                    "current_score": 0.0,
                    "target_score": 0.0,
                    "gap": 0.0,
                    "details": duplicates[:5],
                    "suggestions": ["提取公共函数", "创建共享模块"],
                    "priority": "medium",
                })

        # 按优先级排序
        priority_order = {"high": 0, "medium": 1, "low": 2}
        opportunities.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))

        return opportunities

    # =========================================================================
    # 各维度分析实现
    # =========================================================================

    async def _analyze_code_quality(self) -> CapabilityScore:
        """分析代码质量"""
        evidence = []
        weaknesses = []

        # 检查 Python 文件
        python_files = list(self.project_root.rglob("*.py"))
        python_files = [f for f in python_files if "__pycache__" not in str(f)]

        if not python_files:
            return CapabilityScore(
                dimension=CapabilityDimension.CODE_QUALITY.value,
                score=0.5,
                evidence=["无 Python 文件可分析"],
                weaknesses=["缺少源代码文件"],
            )

        # 统计代码行数
        total_lines = 0
        docstring_lines = 0
        comment_lines = 0

        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    lines = content.split('\n')
                    total_lines += len(lines)

                    # 统计文档字符串和注释
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith('"""') or stripped.startswith("'''"):
                            docstring_lines += 1
                        elif stripped.startswith('#'):
                            comment_lines += 1
            except Exception:
                continue

        # 计算文档覆盖率
        doc_ratio = docstring_lines / max(total_lines, 1)
        comment_ratio = comment_lines / max(total_lines, 1)

        if doc_ratio > 0.1:
            evidence.append(f"文档覆盖率良好: {doc_ratio:.1%}")
        else:
            weaknesses.append(f"文档覆盖率偏低: {doc_ratio:.1%}")

        if comment_ratio > 0.05:
            evidence.append(f"注释比例良好: {comment_ratio:.1%}")
        else:
            weaknesses.append(f"注释比例偏低: {comment_ratio:.1%}")

        # 检查类型注解
        typed_functions = 0
        total_functions = 0
        for file_path in python_files[:10]:  # 抽样检查
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            total_functions += 1
                            if node.returns or any(
                                arg.annotation for arg in node.args.args
                            ):
                                typed_functions += 1
            except Exception:
                continue

        if total_functions > 0:
            type_ratio = typed_functions / total_functions
            if type_ratio > 0.5:
                evidence.append(f"类型注解覆盖良好: {type_ratio:.1%}")
            else:
                weaknesses.append(f"类型注解覆盖偏低: {type_ratio:.1%}")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.6,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.CODE_QUALITY.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_test_coverage(self) -> CapabilityScore:
        """分析测试覆盖"""
        evidence = []
        weaknesses = []

        # 检查测试目录
        tests_dir = self.project_root / "tests"
        if not tests_dir.exists():
            return CapabilityScore(
                dimension=CapabilityDimension.TEST_COVERAGE.value,
                score=0.2,
                evidence=[],
                weaknesses=["缺少测试目录"],
            )

        # 统计测试文件
        test_files = list(tests_dir.rglob("test_*.py"))
        test_count = len(test_files)

        if test_count > 10:
            evidence.append(f"测试文件数量充足: {test_count} 个")
        elif test_count > 5:
            evidence.append(f"测试文件数量一般: {test_count} 个")
        else:
            weaknesses.append(f"测试文件数量不足: {test_count} 个")

        # 检查覆盖率报告
        coverage_file = self.project_root / "coverage_report.json"
        if coverage_file.exists():
            try:
                with open(coverage_file, 'r') as f:
                    coverage = json.load(f)
                    cov_percent = coverage.get("percent_covered", 0)
                    if cov_percent > 80:
                        evidence.append(f"测试覆盖率优秀: {cov_percent:.1f}%")
                    elif cov_percent > 60:
                        evidence.append(f"测试覆盖率良好: {cov_percent:.1f}%")
                    else:
                        weaknesses.append(f"测试覆盖率偏低: {cov_percent:.1f}%")
            except Exception:
                pass

        # 检查 conftest.py
        conftest = tests_dir / "conftest.py"
        if conftest.exists():
            evidence.append("测试配置完善 (conftest.py)")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.5,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.TEST_COVERAGE.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_tool_usage(self) -> CapabilityScore:
        """分析工具使用"""
        evidence = []
        weaknesses = []

        # 检查工具定义
        tools_init = self.project_root / "tools" / "__init__.py"
        if not tools_init.exists():
            return CapabilityScore(
                dimension=CapabilityDimension.TOOL_USAGE.value,
                score=0.3,
                evidence=[],
                weaknesses=["缺少工具定义文件"],
            )

        try:
            with open(tools_init, 'r', encoding='utf-8') as f:
                content = f.read()

            # 统计导出的工具数量
            tool_count = content.count("_tool")
            if tool_count > 20:
                evidence.append(f"工具丰富: {tool_count} 个")
            elif tool_count > 10:
                evidence.append(f"工具数量一般: {tool_count} 个")
            else:
                weaknesses.append(f"工具数量偏少: {tool_count} 个")

        except Exception:
            pass

        # 检查工具分类
        tool_dirs = ["shell_tools.py", "memory_tools.py", "search_tools.py",
                     "code_analysis_tools.py", "rebirth_tools.py"]
        categories = sum(1 for t in tool_dirs if (self.project_root / "tools" / t).exists())

        if categories >= 4:
            evidence.append(f"工具分类完善: {categories} 个类别")
        else:
            weaknesses.append(f"工具分类不足: {categories} 个类别")

        # 使用工具追踪统计
        if self._tool_usage_stats:
            successful = self._tool_usage_stats.get("successful_calls", 0)
            failed = self._tool_usage_stats.get("failed_calls", 0)
            total = successful + failed

            if total > 0:
                success_rate = successful / total
                if success_rate > 0.9:
                    evidence.append(f"工具执行成功率高: {success_rate:.1%}")
                elif success_rate < 0.7:
                    weaknesses.append(f"工具执行成功率偏低: {success_rate:.1%}")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.7,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.TOOL_USAGE.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_autonomy(self) -> CapabilityScore:
        """分析自主性"""
        evidence = []
        weaknesses = []

        # 检查自主运行模式
        autonomous_file = self.project_root / "core" / "autonomous_mode.py"
        if autonomous_file.exists():
            evidence.append("具备自主运行模式")

        # 检查状态管理
        state_file = self.project_root / "core" / "state.py"
        if state_file.exists():
            evidence.append("具备状态管理能力")

        # 检查事件总线
        event_file = self.project_root / "core" / "event_bus.py"
        if event_file.exists():
            evidence.append("具备事件驱动架构")

        # 检查任务管理器
        task_manager = self.project_root / "core" / "task_manager.py"
        if task_manager.exists():
            evidence.append("具备任务管理能力")

        # 检查重生机制
        rebirth_tools = self.project_root / "tools" / "rebirth_tools.py"
        if rebirth_tools.exists():
            evidence.append("具备自我重生机制")

        # 检查安全门控
        security_file = self.project_root / "core" / "security.py"
        if security_file.exists():
            evidence.append("具备安全门控")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.5,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.AUTONOMY.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_memory_management(self) -> CapabilityScore:
        """分析记忆管理"""
        evidence = []
        weaknesses = []

        # 检查记忆工具
        memory_tools = self.project_root / "tools" / "memory_tools.py"
        if memory_tools.exists():
            evidence.append("具备记忆管理工具")

            # 统计记忆工具函数
            with open(memory_tools, 'r', encoding='utf-8') as f:
                content = f.read()
                memory_funcs = content.count("def ") + content.count("async def ")
                if memory_funcs > 10:
                    evidence.append(f"记忆工具函数丰富: {memory_funcs} 个")

        # 检查工作区管理器
        workspace = self.project_root / "core" / "workspace_manager.py"
        if workspace.exists():
            evidence.append("具备工作区管理能力")

        # 检查记忆存储目录
        memory_dir = self.project_root / "workspace" / "memory"
        archives_dir = self.project_root / "workspace" / "archives"

        if memory_dir.exists():
            evidence.append("具备记忆存储目录")
        else:
            weaknesses.append("缺少记忆存储目录")

        if archives_dir.exists():
            evidence.append("具备档案归档能力")

        # 检查世代管理
        try:
            sys.path.insert(0, str(self.project_root))
            from tools.memory_tools import get_generation_tool, _load_memory
            generation = get_generation_tool()
            memory = _load_memory()

            if generation > 1:
                evidence.append(f"具备世代管理经验: G{generation}")
            else:
                weaknesses.append("世代经验较少")

            if memory.get("core_wisdom"):
                evidence.append("具备核心智慧提炼能力")
        except Exception:
            pass

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.6,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.MEMORY_MANAGEMENT.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_security(self) -> CapabilityScore:
        """分析安全性"""
        evidence = []
        weaknesses = []

        # 检查安全模块
        security_file = self.project_root / "core" / "security.py"
        if security_file.exists():
            evidence.append("具备独立安全模块")

            with open(security_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查安全机制
            if "PathSandbox" in content:
                evidence.append("具备路径沙箱机制")
            if "SecurityValidator" in content:
                evidence.append("具备安全验证器")
            if "SAFE_POWERSHELL_COMMANDS" in content:
                evidence.append("具备命令白名单")
        else:
            weaknesses.append("缺少独立安全模块")

        # 检查测试覆盖率
        test_security = self.project_root / "tests" / "test_security.py"
        if test_security.exists():
            evidence.append("具备安全测试")

        # 检查危险操作
        shell_tools = self.project_root / "tools" / "shell_tools.py"
        if shell_tools.exists():
            with open(shell_tools, 'r', encoding='utf-8') as f:
                content = f.read()

            if "_is_command_dangerous" in content:
                evidence.append("具备危险命令检测")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.6,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.SECURITY.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_architecture(self) -> CapabilityScore:
        """分析架构设计"""
        evidence = []
        weaknesses = []

        # 检查模块化结构
        core_dir = self.project_root / "core"
        if core_dir.exists():
            modules = list(core_dir.glob("*.py"))
            modules = [m for m in modules if m.name != "__init__.py"]

            if len(modules) > 10:
                evidence.append(f"核心模块化良好: {len(modules)} 个模块")
            elif len(modules) > 5:
                evidence.append(f"核心模块化一般: {len(modules)} 个模块")
            else:
                weaknesses.append(f"核心模块化不足: {len(modules)} 个模块")

        # 检查工具模块化
        tools_dir = self.project_root / "tools"
        if tools_dir.exists():
            tool_modules = list(tools_dir.glob("*.py"))
            tool_modules = [m for m in tool_modules if m.name not in ["__init__.py", "__pycache__"]]

            if len(tool_modules) > 5:
                evidence.append(f"工具模块化良好: {len(tool_modules)} 个模块")

        # 检查 agent.py 精简程度
        agent_file = self.project_root / "agent.py"
        if agent_file.exists():
            with open(agent_file, 'r', encoding='utf-8') as f:
                lines = len(f.readlines())

            if lines < 500:
                evidence.append(f"Agent 主文件精简: {lines} 行")
            elif lines < 800:
                evidence.append(f"Agent 主文件适中: {lines} 行")
            else:
                weaknesses.append(f"Agent 主文件较大: {lines} 行")

        # 检查核心模块的职责分离
        required_modules = ["event_bus.py", "security.py", "tool_executor.py", "state.py"]
        existing = [m for m in required_modules if (core_dir / m).exists()]

        if len(existing) >= 3:
            evidence.append(f"核心职责分离良好: {len(existing)}/{len(required_modules)} 模块")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.6,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.ARCHITECTURE.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_learning(self) -> CapabilityScore:
        """分析学习能力"""
        evidence = []
        weaknesses = []

        # 检查代码洞察记录
        try:
            sys.path.insert(0, str(self.project_root))
            from tools.memory_tools import record_codebase_insight_tool, get_global_codebase_map_tool

            insight_result = record_codebase_insight_tool.__doc__
            if insight_result:
                evidence.append("具备代码洞察记录能力")

            map_result = get_global_codebase_map_tool()
            if map_result and len(map_result) > 100:
                evidence.append("具备代码库地图生成能力")
        except Exception:
            pass

        # 检查档案系统
        archives_dir = self.project_root / "workspace" / "archives"
        if archives_dir.exists():
            archives = list(archives_dir.glob("gen_*_history.json"))
            if len(archives) > 0:
                evidence.append(f"具备历史经验积累: {len(archives)} 个世代档案")
            else:
                weaknesses.append("历史经验积累较少")

        # 检查洞察积累
        dynamic_prompt = self.project_root / "workspace" / "prompts" / "DYNAMIC.md"
        if dynamic_prompt.exists():
            with open(dynamic_prompt, 'r', encoding='utf-8') as f:
                content = f.read()
            if "积累的洞察" in content or "insight" in content.lower():
                evidence.append("具备洞察积累机制")

        # 检查经验教训库（规划中）
        # lessons_file = self.project_root / "workspace" / "lessons_learned.md"
        # if lessons_file.exists():
        #     evidence.append("具备经验教训库")

        if len(evidence) < 2:
            weaknesses.append("学习机制尚不完善")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.4,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.LEARNING.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_planning(self) -> CapabilityScore:
        """分析规划能力"""
        evidence = []
        weaknesses = []

        # 检查任务规划工具
        try:
            sys.path.insert(0, str(self.project_root))
            from tools.memory_tools import set_plan_tool, tick_subtask_tool

            evidence.append("具备任务规划工具")
            evidence.append("具备任务跟踪工具")
        except Exception:
            pass

        # 检查任务管理器
        task_manager = self.project_root / "core" / "task_manager.py"
        if task_manager.exists():
            with open(task_manager, 'r', encoding='utf-8') as f:
                content = f.read()

            if "dependencies" in content.lower():
                evidence.append("具备任务依赖管理")
            if "priority" in content.lower():
                evidence.append("具备任务优先级")
            if "risk" in content.lower():
                evidence.append("具备风险评估")

        # 检查规划文档
        requirements_dir = self.project_root / "requirement"
        if requirements_dir.exists():
            docs = list(requirements_dir.rglob("*.md"))
            if len(docs) > 3:
                evidence.append(f"具备规划文档: {len(docs)} 个")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.6,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.PLANNING.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    async def _analyze_execution(self) -> CapabilityScore:
        """分析执行能力"""
        evidence = []
        weaknesses = []

        # 检查工具执行器
        executor = self.project_root / "core" / "tool_executor.py"
        if executor.exists():
            evidence.append("具备工具执行器")

            with open(executor, 'r', encoding='utf-8') as f:
                content = f.read()

            if "timeout" in content.lower():
                evidence.append("具备超时控制")
            if "retry" in content.lower():
                evidence.append("具备重试机制")
            if "error" in content.lower():
                evidence.append("具备错误处理")
        else:
            weaknesses.append("缺少独立工具执行器")

        # 检查重启机制
        restarter = self.project_root / "core" / "restarter.py"
        rebirth = self.project_root / "tools" / "rebirth_tools.py"

        if restarter.exists():
            evidence.append("具备重启守护进程")
        if rebirth.exists():
            evidence.append("具备重生工具")

        # 检查执行日志
        logs_dir = self.project_root / "logs"
        if logs_dir.exists():
            evidence.append("具备执行日志")

        # 计算得分
        score = self._calculate_dimension_score(
            positive_signals=len(evidence),
            negative_signals=len(weaknesses),
            base_score=0.7,
        )

        return CapabilityScore(
            dimension=CapabilityDimension.EXECUTION.value,
            score=score,
            evidence=evidence,
            weaknesses=weaknesses,
        )

    # =========================================================================
    # 代码库分析
    # =========================================================================

    async def analyze_codebase(
        self,
        scope: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        分析代码库状态

        Args:
            scope: 要分析的文件范围（默认为全部 Python 文件）

        Returns:
            代码库分析结果
        """
        if self._codebase_analysis and scope is None:
            return self._codebase_analysis

        analysis = {
            "total_files": 0,
            "total_lines": 0,
            "complexity_distribution": {},
            "high_complexity_files": [],
            "duplicates": [],
            "module_structure": {},
        }

        if scope is None:
            scope = [str(p) for p in self.project_root.rglob("*.py")]
            scope = [s for s in scope if "__pycache__" not in s]

        complexity_scores = []

        for file_path in scope[:100]:  # 限制分析文件数量
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                analysis["total_files"] += 1
                analysis["total_lines"] += len(content.split('\n'))

                # 复杂度分析
                complexity = self._calculate_complexity(content)
                complexity_scores.append(complexity)

                if complexity > 10:
                    rel_path = str(Path(file_path).relative_to(self.project_root))
                    analysis["high_complexity_files"].append({
                        "file": rel_path,
                        "complexity": complexity,
                    })

            except Exception:
                continue

        # 复杂度分布
        if complexity_scores:
            analysis["complexity_distribution"] = {
                "min": min(complexity_scores),
                "max": max(complexity_scores),
                "avg": sum(complexity_scores) / len(complexity_scores),
            }

        # 排序高复杂度文件
        analysis["high_complexity_files"].sort(key=lambda x: x["complexity"], reverse=True)

        if scope is None:
            self._codebase_analysis = analysis

        return analysis

    def _calculate_complexity(self, code: str) -> int:
        """计算代码复杂度（简化版）"""
        try:
            tree = ast.parse(code)
            complexity = 0

            for node in ast.walk(tree):
                # 控制流复杂度
                if isinstance(node, (ast.If, ast.While, ast.For)):
                    complexity += 1
                elif isinstance(node, ast.BoolOp):
                    complexity += len(node.values) - 1
                elif isinstance(node, (ast.Try, ast.With)):
                    complexity += 1

            return complexity
        except Exception:
            return 0

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _calculate_overall_score(
        self,
        dimension_scores: List[CapabilityScore],
    ) -> float:
        """计算综合得分"""
        if not dimension_scores:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for score in dimension_scores:
            try:
                dim = CapabilityDimension(score.dimension)
                weight = DIMENSION_WEIGHTS.get(dim, 0.05)
                weighted_sum += score.score * weight
                total_weight += weight
            except ValueError:
                continue

        if total_weight > 0:
            return weighted_sum / total_weight

        return sum(s.score for s in dimension_scores) / len(dimension_scores)

    def _calculate_dimension_score(
        self,
        positive_signals: int,
        negative_signals: int,
        base_score: float,
    ) -> float:
        """计算维度得分"""
        total_signals = positive_signals + negative_signals
        if total_signals == 0:
            return base_score

        # 正向信号加分，负向信号减分
        score = base_score + (positive_signals * 0.05) - (negative_signals * 0.08)

        # 限制在 0-1 范围内
        return max(0.0, min(1.0, score))

    def _identify_strengths(
        self,
        dimension_scores: List[CapabilityScore],
    ) -> List[str]:
        """识别优势"""
        strengths = []

        for score in dimension_scores:
            if score.score >= SCORE_THRESHOLDS["excellent"]:
                strengths.append(f"{score.dimension}: 优秀 ({score.score:.0%})")
            elif score.score >= SCORE_THRESHOLDS["good"]:
                strengths.append(f"{score.dimension}: 良好 ({score.score:.0%})")

        return strengths

    def _identify_weaknesses(
        self,
        dimension_scores: List[CapabilityScore],
    ) -> List[str]:
        """识别劣势"""
        weaknesses = []

        for score in dimension_scores:
            if score.score < SCORE_THRESHOLDS["fair"]:
                weaknesses.append(f"{score.dimension}: 较差 ({score.score:.0%})")
            elif score.score < SCORE_THRESHOLDS["good"]:
                weaknesses.append(f"{score.dimension}: 一般 ({score.score:.0%})")

        return weaknesses

    def _get_dimension_suggestions(self, dimension: str) -> List[str]:
        """获取维度改进建议"""
        suggestions_map = {
            "code_quality": [
                "增加文档字符串覆盖",
                "添加类型注解",
                "遵循 PEP 8 规范",
            ],
            "test_coverage": [
                "增加单元测试覆盖率",
                "补充边界条件测试",
                "添加集成测试",
            ],
            "tool_usage": [
                "扩展工具功能",
                "优化工具参数设计",
                "增加工具使用统计",
            ],
            "autonomy": [
                "增强自主探索能力",
                "完善状态管理",
                "优化事件驱动",
            ],
            "memory_management": [
                "优化记忆结构",
                "增加经验提炼",
                "完善代际传承",
            ],
            "security": [
                "增强输入验证",
                "完善权限控制",
                "增加安全审计",
            ],
            "architecture": [
                "进一步模块化",
                "解耦核心逻辑",
                "优化依赖关系",
            ],
            "learning": [
                "建立经验库",
                "优化模式识别",
                "增强知识积累",
            ],
            "planning": [
                "完善任务分解",
                "增加风险评估",
                "优化优先级",
            ],
            "execution": [
                "优化错误处理",
                "增强超时控制",
                "完善日志记录",
            ],
        }

        return suggestions_map.get(dimension, [])

    def _calculate_priority(
        self,
        score: float,
        weaknesses: List[str],
    ) -> str:
        """计算优先级"""
        if score < SCORE_THRESHOLDS["poor"]:
            return "high"
        elif score < SCORE_THRESHOLDS["fair"]:
            return "medium"
        return "low"

    def _generate_recommendations(
        self,
        dimension_scores: List[CapabilityScore],
        opportunities: List[Dict[str, Any]],
        code_insights: Dict[str, Any],
    ) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于低分维度建议
        for score in dimension_scores:
            if score.score < SCORE_THRESHOLDS["good"]:
                suggestions = self._get_dimension_suggestions(score.dimension)
                if suggestions:
                    recommendations.append(
                        f"优先改进 {score.dimension}: {suggestions[0]}"
                    )

        # 基于改进机会建议
        high_priority = [o for o in opportunities if o.get("priority") == "high"]
        if high_priority:
            for opp in high_priority[:2]:
                if opp.get("suggestions"):
                    recommendations.append(
                        f"关注 {opp['dimension']}: {opp['suggestions'][0]}"
                    )

        # 基于代码分析建议
        high_complexity = code_insights.get("high_complexity_files", [])
        if high_complexity:
            recommendations.append(
                f"重构高复杂度文件: {high_complexity[0]['file']}"
            )

        return recommendations[:5]  # 限制建议数量

    # =========================================================================
    # 历史追踪
    # =========================================================================

    def get_capability_trend(
        self,
        dimension: str,
        limit: int = 10,
    ) -> List[CapabilityScore]:
        """
        获取能力趋势

        Args:
            dimension: 能力维度
            limit: 返回的历史记录数量

        Returns:
            能力评分历史
        """
        history = self._score_history.get(dimension, [])
        return history[-limit:]

    def get_improvement_rate(self, dimension: str) -> Optional[float]:
        """
        计算改进率

        Args:
            dimension: 能力维度

        Returns:
            改进率（最近两次得分差）
        """
        history = self.get_capability_trend(dimension, limit=2)
        if len(history) < 2:
            return None

        return history[-1].score - history[-2].score


# ============================================================================
# 全局单例
# ============================================================================

_self_analyzer: Optional[SelfAnalyzer] = None


def get_self_analyzer(project_root: Optional[str] = None) -> SelfAnalyzer:
    """获取自我分析器单例"""
    global _self_analyzer
    if _self_analyzer is None:
        _self_analyzer = SelfAnalyzer(project_root)
    return _self_analyzer
