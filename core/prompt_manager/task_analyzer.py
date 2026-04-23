#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务分析器 (TaskAnalyzer) - 分析任务完成情况并生成复盘报告

负责：
- 分析任务执行情况
- 识别任务执行中的问题
- 生成复盘报告
- 提取成功模式和失败教训

Phase 2 核心模块
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ============================================================================
# 枚举定义
# ============================================================================

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskComplexity(Enum):
    """任务复杂度"""
    TRIVIAL = "trivial"      # 简单
    EASY = "easy"            # 容易
    MEDIUM = "medium"        # 中等
    COMPLEX = "complex"      # 复杂
    VERY_COMPLEX = "very_complex"  # 非常复杂


@dataclass
class TaskRecord:
    """任务记录"""
    task_id: int
    description: str
    status: str
    complexity: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    subtasks: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    insights: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskAnalysisReport:
    """任务分析报告"""
    generation: int
    timestamp: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    completion_rate: float
    avg_duration: float
    success_patterns: List[str]
    failure_patterns: List[str]
    recommendations: List[str]
    task_records: List[TaskRecord]


# ============================================================================
# 任务分析器
# ============================================================================

class TaskAnalyzer:
    """
    任务分析器

    分析任务执行情况，提取模式和教训。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化任务分析器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 分析结果存储路径
        self._analysis_dir = self.project_root / "workspace" / "analytics"
        self._analysis_dir.mkdir(parents=True, exist_ok=True)

        # 任务历史记录
        self._task_history: List[TaskRecord] = []

    # =========================================================================
    # 任务记录
    # =========================================================================

    def record_task_start(
        self,
        task_id: int,
        description: str,
        complexity: str = "medium",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录任务开始

        Args:
            task_id: 任务 ID
            description: 任务描述
            complexity: 复杂度
            metadata: 元数据
        """
        record = TaskRecord(
            task_id=task_id,
            description=description,
            status=TaskStatus.IN_PROGRESS.value,
            complexity=complexity,
            start_time=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        self._task_history.append(record)

    def record_task_completion(
        self,
        task_id: int,
        insights: Optional[List[str]] = None,
    ) -> None:
        """
        记录任务完成

        Args:
            task_id: 任务 ID
            insights: 任务洞察
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.status = TaskStatus.COMPLETED.value
                record.end_time = datetime.now().isoformat()

                if record.start_time:
                    start = datetime.fromisoformat(record.start_time)
                    end = datetime.now()
                    record.duration_seconds = (end - start).total_seconds()

                if insights:
                    record.insights.extend(insights)

                break

    def record_task_failure(
        self,
        task_id: int,
        error: str,
    ) -> None:
        """
        记录任务失败

        Args:
            task_id: 任务 ID
            error: 错误信息
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.status = TaskStatus.FAILED.value
                record.end_time = datetime.now().isoformat()
                record.errors.append(error)

                if record.start_time:
                    start = datetime.fromisoformat(record.start_time)
                    end = datetime.now()
                    record.duration_seconds = (end - start).total_seconds()

                break

    def record_tool_call(
        self,
        task_id: int,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True,
    ) -> None:
        """
        记录工具调用

        Args:
            task_id: 任务 ID
            tool_name: 工具名称
            args: 工具参数
            result: 执行结果
            success: 是否成功
        """
        for record in reversed(self._task_history):
            if record.task_id == task_id:
                record.tool_calls.append({
                    "tool": tool_name,
                    "args": args or {},
                    "result": result,
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                })
                break

    # =========================================================================
    # 分析接口
    # =========================================================================

    def analyze_tasks(
        self,
        generation: int,
        task_records: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskAnalysisReport:
        """
        分析任务执行情况

        Args:
            generation: 世代
            task_records: 任务记录列表（可选，用于外部传入）

        Returns:
            任务分析报告
        """
        # 使用提供的记录或历史记录
        if task_records is None:
            task_records = [self._record_to_dict(r) for r in self._task_history]

        # 转换记录
        records = []
        for rec in task_records:
            records.append(TaskRecord(
                task_id=rec.get("task_id", 0),
                description=rec.get("description", ""),
                status=rec.get("status", TaskStatus.PENDING.value),
                complexity=rec.get("complexity", "medium"),
                start_time=rec.get("start_time"),
                end_time=rec.get("end_time"),
                duration_seconds=rec.get("duration_seconds", 0.0),
                subtasks=rec.get("subtasks", []),
                tool_calls=rec.get("tool_calls", []),
                errors=rec.get("errors", []),
                insights=rec.get("insights", []),
                metadata=rec.get("metadata", {}),
            ))

        # 统计
        total = len(records)
        completed = len([r for r in records if r.status == TaskStatus.COMPLETED.value])
        failed = len([r for r in records if r.status == TaskStatus.FAILED.value])

        # 计算完成率
        completion_rate = completed / total if total > 0 else 0.0

        # 计算平均时长
        completed_records = [r for r in records if r.duration_seconds > 0]
        avg_duration = (
            sum(r.duration_seconds for r in completed_records) / len(completed_records)
            if completed_records else 0.0
        )

        # 识别成功模式
        success_patterns = self._identify_success_patterns(records)

        # 识别失败模式
        failure_patterns = self._identify_failure_patterns(records)

        # 生成建议
        recommendations = self._generate_recommendations(
            records, success_patterns, failure_patterns
        )

        return TaskAnalysisReport(
            generation=generation,
            timestamp=datetime.now().isoformat(),
            total_tasks=total,
            completed_tasks=completed,
            failed_tasks=failed,
            completion_rate=completion_rate,
            avg_duration=avg_duration,
            success_patterns=success_patterns,
            failure_patterns=failure_patterns,
            recommendations=recommendations,
            task_records=records,
        )

    def generate_retrospective(
        self,
        generation: int,
    ) -> str:
        """
        生成任务复盘报告

        Args:
            generation: 世代

        Returns:
            Markdown 格式的复盘报告
        """
        report = self.analyze_tasks(generation)

        lines = [
            "# 任务执行复盘报告",
            "",
            f"**世代**: G{generation}",
            f"**生成时间**: {report.timestamp}",
            "",
            "---",
            "",
            "## 执行概览",
            "",
            f"- **总任务数**: {report.total_tasks}",
            f"- **已完成**: {report.completed_tasks}",
            f"- **失败**: {report.failed_tasks}",
            f"- **完成率**: {report.completion_rate:.0%}",
            f"- **平均耗时**: {self._format_duration(report.avg_duration)}",
            "",
        ]

        # 成功模式
        if report.success_patterns:
            lines.extend([
                "## 成功模式",
                "",
            ])
            for pattern in report.success_patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        # 失败模式
        if report.failure_patterns:
            lines.extend([
                "## 失败模式",
                "",
            ])
            for pattern in report.failure_patterns:
                lines.append(f"- {pattern}")
            lines.append("")

        # 建议
        if report.recommendations:
            lines.extend([
                "## 改进建议",
                "",
            ])
            for rec in report.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        # 详细记录
        lines.extend([
            "---",
            "",
            "## 详细记录",
            "",
        ])

        for record in report.task_records:
            status_icon = "✅" if record.status == "completed" else "❌"
            lines.append(f"### 任务 #{record.task_id} {status_icon}")
            lines.append(f"**描述**: {record.description}")
            lines.append(f"**状态**: {record.status}")
            lines.append(f"**复杂度**: {record.complexity}")

            if record.duration_seconds > 0:
                lines.append(f"**耗时**: {self._format_duration(record.duration_seconds)}")

            if record.tool_calls:
                lines.append(f"**工具调用**: {len(record.tool_calls)} 次")

            if record.errors:
                lines.append(f"**错误**: {len(record.errors)} 个")
                for error in record.errors[:3]:
                    lines.append(f"  - {error}")

            if record.insights:
                lines.append("**洞察**:")
                for insight in record.insights[:3]:
                    lines.append(f"  - {insight}")

            lines.append("")

        return "\n".join(lines)

    def save_analysis(
        self,
        report: TaskAnalysisReport,
        filepath: Optional[Path] = None,
    ) -> str:
        """
        保存分析报告

        Args:
            report: 分析报告
            filepath: 保存路径

        Returns:
            保存的文件路径
        """
        if filepath is None:
            filepath = self._analysis_dir / f"task_analysis_G{report.generation}.json"

        data = {
            "generation": report.generation,
            "timestamp": report.timestamp,
            "total_tasks": report.total_tasks,
            "completed_tasks": report.completed_tasks,
            "failed_tasks": report.failed_tasks,
            "completion_rate": report.completion_rate,
            "avg_duration": report.avg_duration,
            "success_patterns": report.success_patterns,
            "failure_patterns": report.failure_patterns,
            "recommendations": report.recommendations,
            "records": [self._record_to_dict(r) for r in report.task_records],
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(filepath)

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _record_to_dict(self, record: TaskRecord) -> Dict[str, Any]:
        """将任务记录转换为字典"""
        return {
            "task_id": record.task_id,
            "description": record.description,
            "status": record.status,
            "complexity": record.complexity,
            "start_time": record.start_time,
            "end_time": record.end_time,
            "duration_seconds": record.duration_seconds,
            "subtasks": record.subtasks,
            "tool_calls": record.tool_calls,
            "errors": record.errors,
            "insights": record.insights,
            "metadata": record.metadata,
        }

    def _identify_success_patterns(
        self,
        records: List[TaskRecord],
    ) -> List[str]:
        """识别成功模式"""
        patterns = []

        # 检查哪些复杂度等级完成率高
        complexity_stats: Dict[str, Dict[str, int]] = {}
        for record in records:
            if record.status == TaskStatus.COMPLETED.value:
                if record.complexity not in complexity_stats:
                    complexity_stats[record.complexity] = {"total": 0, "completed": 0}
                complexity_stats[record.complexity]["total"] += 1
                complexity_stats[record.complexity]["completed"] += 1
            else:
                if record.complexity not in complexity_stats:
                    complexity_stats[record.complexity] = {"total": 0, "completed": 0}
                complexity_stats[record.complexity]["total"] += 1

        for complexity, stats in complexity_stats.items():
            if stats["total"] > 0:
                rate = stats["completed"] / stats["total"]
                if rate >= 0.8:
                    patterns.append(
                        f"{complexity} 复杂度任务完成率高 ({rate:.0%})"
                    )

        # 检查成功工具使用
        tool_success: Dict[str, Dict[str, int]] = {}
        for record in records:
            if record.status == TaskStatus.COMPLETED.value:
                for call in record.tool_calls:
                    tool = call.get("tool", "unknown")
                    if tool not in tool_success:
                        tool_success[tool] = {"success": 0, "total": 0}
                    tool_success[tool]["total"] += 1
                    if call.get("success", True):
                        tool_success[tool]["success"] += 1

        for tool, stats in tool_success.items():
            if stats["total"] >= 3:
                rate = stats["success"] / stats["total"]
                if rate >= 0.9:
                    patterns.append(
                        f"'{tool}' 工具使用成功率高 ({rate:.0%})"
                    )

        # 检查洞察提取
        records_with_insights = [r for r in records if r.insights]
        if len(records_with_insights) >= len(records) * 0.5:
            patterns.append("善于从任务中提取洞察")

        return patterns

    def _identify_failure_patterns(
        self,
        records: List[TaskRecord],
    ) -> List[str]:
        """识别失败模式"""
        patterns = []

        # 检查失败任务
        failed_records = [r for r in records if r.status == TaskStatus.FAILED.value]

        if failed_records:
            patterns.append(
                f"存在 {len(failed_records)} 个失败任务需要关注"
            )

            # 统计失败原因
            error_types: Dict[str, int] = {}
            for record in failed_records:
                for error in record.errors:
                    error_type = self._classify_error(error)
                    error_types[error_type] = error_types.get(error_type, 0) + 1

            for error_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
                patterns.append(f"'{error_type}' 错误出现 {count} 次")

        # 检查超时或长时间未完成的任务
        long_tasks = [
            r for r in records
            if r.duration_seconds > 300 and r.status != TaskStatus.COMPLETED.value
        ]
        if long_tasks:
            patterns.append(
                f"存在 {len(long_tasks)} 个耗时过长 (>5分钟) 的任务"
            )

        # 检查工具调用失败
        failed_tool_calls: Dict[str, int] = {}
        for record in records:
            for call in record.tool_calls:
                if not call.get("success", True):
                    tool = call.get("tool", "unknown")
                    failed_tool_calls[tool] = failed_tool_calls.get(tool, 0) + 1

        for tool, count in sorted(failed_tool_calls.items(), key=lambda x: -x[1]):
            if count >= 2:
                patterns.append(
                    f"'{tool}' 工具调用失败 {count} 次"
                )

        return patterns

    def _classify_error(self, error: str) -> str:
        """分类错误类型"""
        error_lower = error.lower()

        if any(word in error_lower for word in ["timeout", "超时", "超时"]):
            return "超时"
        if any(word in error_lower for word in ["syntax", "语法"]):
            return "语法错误"
        if any(word in error_lower for word in ["permission", "权限", "拒绝"]):
            return "权限错误"
        if any(word in error_lower for word in ["not found", "不存在", "找不到"]):
            return "资源不存在"
        if any(word in error_lower for word in ["memory", "内存"]):
            return "内存错误"
        if any(word in error_lower for word in ["connection", "连接"]):
            return "连接错误"

        return "其他错误"

    def _generate_recommendations(
        self,
        records: List[TaskRecord],
        success_patterns: List[str],
        failure_patterns: List[str],
    ) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于失败模式建议
        for pattern in failure_patterns:
            if "超时" in pattern:
                recommendations.append("考虑优化超时设置或拆分长时间任务")
            elif "语法错误" in pattern:
                recommendations.append("加强代码编写前的语法检查")
            elif "权限错误" in pattern:
                recommendations.append("检查文件权限设置")
            elif "失败" in pattern and "工具" in pattern:
                tool_name = pattern.split("'")[1] if "'" in pattern else None
                if tool_name:
                    recommendations.append(f"检查 '{tool_name}' 工具的使用方式")
            elif "耗时过长" in pattern:
                recommendations.append("将大任务拆分为多个子任务")

        # 基于成功率建议
        total = len(records)
        completed = len([r for r in records if r.status == TaskStatus.COMPLETED.value])
        rate = completed / total if total > 0 else 0

        if rate < 0.5:
            recommendations.append("任务完成率偏低，建议简化任务复杂度")
        elif rate < 0.7:
            recommendations.append("任务完成率一般，建议增加任务规划时间")

        # 基于洞察建议
        records_with_insights = len([r for r in records if r.insights])
        if records_with_insights < total * 0.3:
            recommendations.append("建议从更多任务中提取洞察和教训")

        # 限制建议数量
        return recommendations[:5]

    def _format_duration(self, seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.0f} 秒"
        elif seconds < 3600:
            return f"{seconds / 60:.1f} 分钟"
        else:
            return f"{seconds / 3600:.1f} 小时"


# ============================================================================
# 全局单例
# ============================================================================

_task_analyzer: Optional[TaskAnalyzer] = None


def get_task_analyzer(project_root: Optional[str] = None) -> TaskAnalyzer:
    """获取任务分析器单例"""
    global _task_analyzer
    if _task_analyzer is None:
        _task_analyzer = TaskAnalyzer(project_root)
    return _task_analyzer
