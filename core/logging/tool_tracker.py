#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具效果追踪器 (ToolTracker) - 追踪工具使用效果和性能

负责：
- 记录工具调用统计
- 追踪工具成功率
- 分析工具使用模式
- 生成工具优化建议

Phase 2 核心模块
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import asdict


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ToolCallRecord:
    """工具调用记录"""
    tool_name: str
    timestamp: str
    duration_ms: float
    success: bool
    error: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result_preview: Optional[str] = None


@dataclass
class ToolStats:
    """工具统计"""
    tool_name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float('inf')
    max_duration_ms: float = 0.0
    last_used: Optional[str] = None
    error_types: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "total_duration_ms": self.total_duration_ms,
            "min_duration_ms": self.min_duration_ms if self.min_duration_ms != float('inf') else 0,
            "max_duration_ms": self.max_duration_ms,
            "last_used": self.last_used,
            "error_types": dict(self.error_types),
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
        }


@dataclass
class ToolAnalysisReport:
    """工具分析报告"""
    timestamp: str
    total_tools: int
    total_calls: int
    overall_success_rate: float
    most_used_tools: List[Dict[str, Any]]
    fastest_tools: List[Dict[str, Any]]
    slowest_tools: List[Dict[str, Any]]
    most_reliable_tools: List[Dict[str, Any]]
    problematic_tools: List[Dict[str, Any]]
    recommendations: List[str]


# ============================================================================
# 工具效果追踪器
# ============================================================================

class ToolTracker:
    """
    工具效果追踪器

    追踪工具的使用情况和效果。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化工具追踪器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 追踪数据存储路径
        self._data_dir = self.project_root / "workspace" / "analytics"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._stats_file = self._data_dir / "tool_stats.json"
        self._history_file = self._data_dir / "tool_history.json"

        # 内存中的统计数据
        self._stats: Dict[str, ToolStats] = {}
        self._recent_calls: List[ToolCallRecord] = []

        # 加载已有数据
        self._load_stats()

    # =========================================================================
    # 记录接口
    # =========================================================================

    def record_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        error: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        result_preview: Optional[str] = None,
    ) -> None:
        """
        记录工具调用

        Args:
            tool_name: 工具名称
            duration_ms: 执行时长（毫秒）
            success: 是否成功
            error: 错误信息
            args: 工具参数
            result_preview: 结果预览
        """
        # 创建调用记录
        record = ToolCallRecord(
            tool_name=tool_name,
            timestamp=datetime.now().isoformat(),
            duration_ms=duration_ms,
            success=success,
            error=error,
            args=args,
            result_preview=result_preview,
        )

        # 添加到历史
        self._recent_calls.append(record)

        # 限制历史长度
        if len(self._recent_calls) > 1000:
            self._recent_calls = self._recent_calls[-1000:]

        # 更新统计
        if tool_name not in self._stats:
            self._stats[tool_name] = ToolStats(tool_name=tool_name)

        stats = self._stats[tool_name]
        stats.total_calls += 1
        stats.total_duration_ms += duration_ms
        stats.last_used = record.timestamp

        if duration_ms < stats.min_duration_ms:
            stats.min_duration_ms = duration_ms
        if duration_ms > stats.max_duration_ms:
            stats.max_duration_ms = duration_ms

        if success:
            stats.successful_calls += 1
        else:
            stats.failed_calls += 1
            if error:
                # 简化错误类型
                error_type = self._classify_error(error)
                stats.error_types[error_type] += 1

        # 重新计算比率
        if stats.total_calls > 0:
            stats.success_rate = stats.successful_calls / stats.total_calls
            stats.avg_duration_ms = stats.total_duration_ms / stats.total_calls

        # 保存数据
        self._save_stats()

    def record_success(
        self,
        tool_name: str,
        duration_ms: float,
        args: Optional[Dict[str, Any]] = None,
        result_preview: Optional[str] = None,
    ) -> None:
        """记录成功的工具调用"""
        self.record_call(
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=True,
            args=args,
            result_preview=result_preview,
        )

    def record_failure(
        self,
        tool_name: str,
        duration_ms: float,
        error: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录失败的工具调用"""
        self.record_call(
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=False,
            error=error,
            args=args,
        )

    # =========================================================================
    # 查询接口
    # =========================================================================

    def get_tool_stats(self, tool_name: str) -> Optional[ToolStats]:
        """
        获取工具统计信息

        Args:
            tool_name: 工具名称

        Returns:
            工具统计
        """
        return self._stats.get(tool_name)

    def get_all_stats(self) -> List[ToolStats]:
        """
        获取所有工具统计

        Returns:
            工具统计列表
        """
        return list(self._stats.values())

    def get_usage_stats(self) -> Dict[str, Any]:
        """
        获取使用统计

        Returns:
            使用统计摘要
        """
        total_calls = sum(s.total_calls for s in self._stats.values())
        total_successful = sum(s.successful_calls for s in self._stats.values())
        total_duration = sum(s.total_duration_ms for s in self._stats.values())

        return {
            "total_tools": len(self._stats),
            "total_calls": total_calls,
            "total_successful": total_successful,
            "total_failed": total_calls - total_successful,
            "overall_success_rate": total_successful / total_calls if total_calls > 0 else 0,
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration / total_calls if total_calls > 0 else 0,
        }

    def get_most_used_tools(self, limit: int = 5) -> List[ToolStats]:
        """
        获取最常用的工具

        Args:
            limit: 返回数量

        Returns:
            工具统计列表
        """
        sorted_stats = sorted(
            self._stats.values(),
            key=lambda x: x.total_calls,
            reverse=True,
        )
        return sorted_stats[:limit]

    def get_fastest_tools(self, limit: int = 5, min_calls: int = 3) -> List[ToolStats]:
        """
        获取最快的工具

        Args:
            limit: 返回数量
            min_calls: 最小调用次数

        Returns:
            工具统计列表
        """
        filtered = [s for s in self._stats.values() if s.total_calls >= min_calls]
        sorted_stats = sorted(
            filtered,
            key=lambda x: x.avg_duration_ms,
        )
        return sorted_stats[:limit]

    def get_slowest_tools(self, limit: int = 5, min_calls: int = 3) -> List[ToolStats]:
        """
        获取最慢的工具

        Args:
            limit: 返回数量
            min_calls: 最小调用次数

        Returns:
            工具统计列表
        """
        filtered = [s for s in self._stats.values() if s.total_calls >= min_calls]
        sorted_stats = sorted(
            filtered,
            key=lambda x: x.avg_duration_ms,
            reverse=True,
        )
        return sorted_stats[:limit]

    def get_most_reliable_tools(self, limit: int = 5, min_calls: int = 3) -> List[ToolStats]:
        """
        获取最可靠的工具（成功率最高）

        Args:
            limit: 返回数量
            min_calls: 最小调用次数

        Returns:
            工具统计列表
        """
        filtered = [s for s in self._stats.values() if s.total_calls >= min_calls]
        sorted_stats = sorted(
            filtered,
            key=lambda x: (x.success_rate, x.total_calls),
            reverse=True,
        )
        return sorted_stats[:limit]

    def get_problematic_tools(self, min_calls: int = 2) -> List[ToolStats]:
        """
        获取问题工具（成功率低于阈值）

        Args:
            min_calls: 最小调用次数

        Returns:
            问题工具列表
        """
        threshold = 0.7  # 70% 成功率阈值
        return [
            s for s in self._stats.values()
            if s.total_calls >= min_calls and s.success_rate < threshold
        ]

    def get_tools_by_category(self) -> Dict[str, List[str]]:
        """
        按类别分组工具

        Returns:
            类别 -> 工具名称 映射
        """
        categories = {
            "shell": [],
            "memory": [],
            "search": [],
            "code_analysis": [],
            "rebirth": [],
            "task": [],
            "other": [],
        }

        for tool_name in self._stats.keys():
            if "shell" in tool_name.lower():
                categories["shell"].append(tool_name)
            elif "memory" in tool_name.lower():
                categories["memory"].append(tool_name)
            elif "search" in tool_name.lower():
                categories["search"].append(tool_name)
            elif "code" in tool_name.lower() or "analysis" in tool_name.lower():
                categories["code_analysis"].append(tool_name)
            elif "rebirth" in tool_name.lower() or "restart" in tool_name.lower():
                categories["rebirth"].append(tool_name)
            elif "task" in tool_name.lower() or "plan" in tool_name.lower():
                categories["task"].append(tool_name)
            else:
                categories["other"].append(tool_name)

        return categories

    def get_recent_calls(
        self,
        tool_name: Optional[str] = None,
        limit: int = 100,
    ) -> List[ToolCallRecord]:
        """
        获取最近的调用记录

        Args:
            tool_name: 工具名称过滤（可选）
            limit: 返回数量

        Returns:
            调用记录列表
        """
        if tool_name:
            filtered = [c for c in self._recent_calls if c.tool_name == tool_name]
            return filtered[-limit:]
        return self._recent_calls[-limit:]

    def get_usage_trend(
        self,
        tool_name: str,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        获取工具使用趋势

        Args:
            tool_name: 工具名称
            days: 统计天数

        Returns:
            趋势数据
        """
        # 按天统计
        daily_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"calls": 0, "success": 0})

        cutoff = datetime.now() - timedelta(days=days)

        for call in self._recent_calls:
            call_time = datetime.fromisoformat(call.timestamp)
            if call_time < cutoff:
                continue
            if call.tool_name != tool_name:
                continue

            day = call_time.strftime("%Y-%m-%d")
            daily_stats[day]["calls"] += 1
            if call.success:
                daily_stats[day]["success"] += 1

        # 转换为列表
        trend = []
        for day in sorted(daily_stats.keys()):
            stats = daily_stats[day]
            trend.append({
                "date": day,
                "calls": stats["calls"],
                "success": stats["success"],
                "success_rate": stats["success"] / stats["calls"] if stats["calls"] > 0 else 0,
            })

        return {
            "tool_name": tool_name,
            "period_days": days,
            "trend": trend,
        }

    # =========================================================================
    # 分析接口
    # =========================================================================

    def analyze_tools(self) -> ToolAnalysisReport:
        """
        分析所有工具

        Returns:
            工具分析报告
        """
        usage_stats = self.get_usage_stats()
        most_used = self.get_most_used_tools(5)
        fastest = self.get_fastest_tools(5)
        slowest = self.get_slowest_tools(5)
        most_reliable = self.get_most_reliable_tools(5)
        problematic = self.get_problematic_tools()

        # 生成建议
        recommendations = self._generate_recommendations(
            most_used, fastest, slowest, most_reliable, problematic
        )

        return ToolAnalysisReport(
            timestamp=datetime.now().isoformat(),
            total_tools=usage_stats["total_tools"],
            total_calls=usage_stats["total_calls"],
            overall_success_rate=usage_stats["overall_success_rate"],
            most_used_tools=[s.to_dict() for s in most_used],
            fastest_tools=[s.to_dict() for s in fastest],
            slowest_tools=[s.to_dict() for s in slowest],
            most_reliable_tools=[s.to_dict() for s in most_reliable],
            problematic_tools=[s.to_dict() for s in problematic],
            recommendations=recommendations,
        )

    def generate_report(self) -> str:
        """
        生成工具使用报告

        Returns:
            Markdown 格式的报告
        """
        report = self.analyze_tools()

        lines = [
            "# 工具使用效果报告",
            "",
            f"**生成时间**: {report.timestamp}",
            "",
            "---",
            "",
            "## 概览",
            "",
            f"- **工具总数**: {report.total_tools}",
            f"- **总调用次数**: {report.total_calls}",
            f"- **整体成功率**: {report.overall_success_rate:.1%}",
            "",
        ]

        # 最常用工具
        if report.most_used_tools:
            lines.extend([
                "## 最常用工具",
                "",
            ])
            for tool in report.most_used_tools:
                lines.append(
                    f"- **{tool['tool_name']}**: {tool['total_calls']} 次 "
                    f"(成功率: {tool['success_rate']:.0%})"
                )
            lines.append("")

        # 最快工具
        if report.fastest_tools:
            lines.extend([
                "## 响应最快的工具",
                "",
            ])
            for tool in report.fastest_tools:
                lines.append(
                    f"- **{tool['tool_name']}**: 平均 {tool['avg_duration_ms']:.0f}ms "
                    f"({tool['total_calls']} 次调用)"
                )
            lines.append("")

        # 最慢工具
        if report.slowest_tools:
            lines.extend([
                "## 响应最慢的工具",
                "",
            ])
            for tool in report.slowest_tools:
                lines.append(
                    f"- **{tool['tool_name']}**: 平均 {tool['avg_duration_ms']:.0f}ms "
                    f"({tool['total_calls']} 次调用)"
                )
            lines.append("")

        # 最可靠工具
        if report.most_reliable_tools:
            lines.extend([
                "## 最可靠的工具",
                "",
            ])
            for tool in report.most_reliable_tools:
                lines.append(
                    f"- **{tool['tool_name']}**: {tool['success_rate']:.0%} 成功率 "
                    f"({tool['successful_calls']}/{tool['total_calls']})"
                )
            lines.append("")

        # 问题工具
        if report.problematic_tools:
            lines.extend([
                "## 需要关注的工具",
                "",
            ])
            for tool in report.problematic_tools:
                lines.append(
                    f"- **{tool['tool_name']}**: {tool['success_rate']:.0%} 成功率 "
                    f"({tool['failed_calls']} 次失败)"
                )
                if tool['error_types']:
                    error_str = ", ".join(
                        f"{k}: {v}" for k, v in tool['error_types'].items()
                    )
                    lines.append(f"  - 错误类型: {error_str}")
            lines.append("")

        # 建议
        if report.recommendations:
            lines.extend([
                "## 优化建议",
                "",
            ])
            for rec in report.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # 持久化
    # =========================================================================

    def _load_stats(self) -> None:
        """从文件加载统计数据"""
        if not self._stats_file.exists():
            return

        try:
            with open(self._stats_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for tool_name, stats_data in data.items():
                stats = ToolStats(
                    tool_name=tool_name,
                    total_calls=stats_data.get("total_calls", 0),
                    successful_calls=stats_data.get("successful_calls", 0),
                    failed_calls=stats_data.get("failed_calls", 0),
                    total_duration_ms=stats_data.get("total_duration_ms", 0.0),
                    min_duration_ms=stats_data.get("min_duration_ms", float('inf')),
                    max_duration_ms=stats_data.get("max_duration_ms", 0.0),
                    last_used=stats_data.get("last_used"),
                    error_types=defaultdict(int, stats_data.get("error_types", {})),
                    success_rate=stats_data.get("success_rate", 0.0),
                    avg_duration_ms=stats_data.get("avg_duration_ms", 0.0),
                )
                self._stats[tool_name] = stats

        except Exception:
            pass

    def _save_stats(self) -> None:
        """保存统计数据到文件"""
        data = {
            tool_name: stats.to_dict()
            for tool_name, stats in self._stats.items()
        }

        try:
            with open(self._stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def clear_stats(self) -> None:
        """清除所有统计数据"""
        self._stats.clear()
        self._recent_calls.clear()
        self._save_stats()

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _classify_error(self, error: str) -> str:
        """分类错误类型"""
        error_lower = error.lower()

        if any(word in error_lower for word in ["timeout", "超时"]):
            return "超时"
        if any(word in error_lower for word in ["syntax", "语法"]):
            return "语法错误"
        if any(word in error_lower for word in ["not found", "不存在", "找不到", "no such file"]):
            return "文件不存在"
        if any(word in error_lower for word in ["permission", "权限", "拒绝", "denied"]):
            return "权限错误"
        if any(word in error_lower for word in ["encoding", "编码"]):
            return "编码错误"
        if any(word in error_lower for word in ["memory", "内存"]):
            return "内存错误"
        if any(word in error_lower for word in ["connection", "连接"]):
            return "连接错误"

        return "其他错误"

    def _generate_recommendations(
        self,
        most_used: List[ToolStats],
        fastest: List[ToolStats],
        slowest: List[ToolStats],
        most_reliable: List[ToolStats],
        problematic: List[ToolStats],
    ) -> List[str]:
        """生成优化建议"""
        recommendations = []

        # 问题工具建议
        for tool in problematic:
            recommendations.append(
                f"'{tool.tool_name}' 工具成功率较低 ({tool.success_rate:.0%})，"
                f"建议检查使用方式和错误原因"
            )

        # 慢工具优化建议
        if slowest and slowest[0].avg_duration_ms > 1000:
            recommendations.append(
                f"'{slowest[0].tool_name}' 工具响应较慢 (平均 {slowest[0].avg_duration_ms:.0f}ms)，"
                f"建议考虑优化或添加缓存"
            )

        # 工具使用建议
        if len(self._stats) < 10:
            recommendations.append(
                "工具种类较少，建议扩展工具集以提高能力"
            )

        # 可靠工具推广建议
        if most_reliable and len(most_reliable) >= 2:
            reliable_tools = [t.tool_name for t in most_reliable[:2]]
            recommendations.append(
                f"'{reliable_tools[0]}' 和 '{reliable_tools[1]}' 工具表现优秀，"
                f"可以作为其他工具的参考"
            )

        return recommendations[:5]


# ============================================================================
# 全局单例
# ============================================================================

_tool_tracker: Optional[ToolTracker] = None


def get_tool_tracker(project_root: Optional[str] = None) -> ToolTracker:
    """获取工具追踪器单例"""
    global _tool_tracker
    if _tool_tracker is None:
        _tool_tracker = ToolTracker(project_root)
    return _tool_tracker
