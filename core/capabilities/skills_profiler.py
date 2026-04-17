#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
能力画像系统 (SkillsProfiler) - 追踪和管理虾宝的能力矩阵

负责：
- 管理能力画像数据 (skills_profile.json)
- 追踪能力变化历史
- 更新能力评分
- 生成能力报告

Phase 2 核心模块
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class SkillEntry:
    """技能条目"""
    name: str
    score: float
    evidence: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "evidence": self.evidence,
            "weaknesses": self.weaknesses,
            "last_updated": self.last_updated,
        }


@dataclass
class EvolutionRecord:
    """进化记录"""
    generation: int
    timestamp: str
    focus: str
    improvement: str
    score_change: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generation": self.generation,
            "timestamp": self.timestamp,
            "focus": self.focus,
            "improvement": self.improvement,
            "score_change": self.score_change,
        }


@dataclass
class SkillsProfile:
    """能力画像"""
    current_generation: int
    skills_matrix: Dict[str, SkillEntry]
    evolution_history: List[EvolutionRecord]
    next_targets: List[str]
    last_analyzed: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_generation": self.current_generation,
            "skills_matrix": {
                k: {
                    "name": v.name,
                    "score": v.score,
                    "evidence": v.evidence,
                    "weaknesses": v.weaknesses,
                    "last_updated": v.last_updated,
                }
                for k, v in self.skills_matrix.items()
            },
            "evolution_history": [
                {
                    "generation": r.generation,
                    "timestamp": r.timestamp,
                    "focus": r.focus,
                    "improvement": r.improvement,
                    "score_change": r.score_change,
                }
                for r in self.evolution_history
            ],
            "next_targets": self.next_targets,
            "last_analyzed": self.last_analyzed,
        }


# ============================================================================
# 默认能力矩阵
# ============================================================================

DEFAULT_SKILLS_MATRIX = {
    "code_quality": SkillEntry(
        name="代码质量",
        score=0.7,
        evidence=["代码结构清晰", "遵循 PEP 8"],
        weaknesses=["文档覆盖率偏低"],
    ),
    "test_coverage": SkillEntry(
        name="测试覆盖",
        score=0.6,
        evidence=["基础测试覆盖"],
        weaknesses=["边界条件测试不足"],
    ),
    "tool_usage": SkillEntry(
        name="工具使用",
        score=0.8,
        evidence=["14+ 工具可用", "工具分类完善"],
        weaknesses=["动态工具加载待实现"],
    ),
    "autonomy": SkillEntry(
        name="自主性",
        score=0.6,
        evidence=["具备状态管理", "具备事件驱动"],
        weaknesses=["主动探索能力不足"],
    ),
    "memory_management": SkillEntry(
        name="记忆管理",
        score=0.75,
        evidence=["世代管理完善", "记忆归档功能"],
        weaknesses=["经验提取能力待增强"],
    ),
    "security": SkillEntry(
        name="安全性",
        score=0.7,
        evidence=["白名单机制", "路径沙箱"],
        weaknesses=["安全测试覆盖率待提升"],
    ),
    "architecture": SkillEntry(
        name="架构设计",
        score=0.65,
        evidence=["模块化设计", "16 个核心模块"],
        weaknesses=["agent.py 仍较大"],
    ),
    "learning": SkillEntry(
        name="学习能力",
        score=0.4,
        evidence=["具备记忆存储"],
        weaknesses=["主动学习机制待实现"],
    ),
    "planning": SkillEntry(
        name="规划能力",
        score=0.7,
        evidence=["任务清单机制", "子任务管理"],
        weaknesses=["动态调整能力待增强"],
    ),
    "execution": SkillEntry(
        name="执行能力",
        score=0.8,
        evidence=["工具执行器完善", "超时控制"],
        weaknesses=["并行执行待实现"],
    ),
}


# ============================================================================
# 能力画像管理器
# ============================================================================

class SkillsProfiler:
    """
    能力画像管理器

    负责加载、保存、更新能力画像数据。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化能力画像管理器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 能力画像文件路径
        self._profile_file = self.project_root / "workspace" / "memory" / "skills_profile.json"

        # 确保目录存在
        self._profile_file.parent.mkdir(parents=True, exist_ok=True)

        # 当前画像
        self._profile: Optional[SkillsProfile] = None

        # 加载画像
        self._load_profile()

    def _load_profile(self) -> None:
        """加载能力画像"""
        if not self._profile_file.exists():
            self._profile = self._create_default_profile()
            self._save_profile()
            return

        try:
            with open(self._profile_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 解析能力矩阵
            skills_matrix = {}
            for key, entry in data.get("skills_matrix", {}).items():
                skills_matrix[key] = SkillEntry(
                    name=entry.get("name", key),
                    score=entry.get("score", 0.5),
                    evidence=entry.get("evidence", []),
                    weaknesses=entry.get("weaknesses", []),
                    last_updated=entry.get("last_updated", datetime.now().isoformat()),
                )

            # 解析进化历史
            evolution_history = []
            for record in data.get("evolution_history", []):
                evolution_history.append(EvolutionRecord(
                    generation=record.get("generation", 1),
                    timestamp=record.get("timestamp", ""),
                    focus=record.get("focus", ""),
                    improvement=record.get("improvement", ""),
                    score_change=record.get("score_change", 0.0),
                ))

            self._profile = SkillsProfile(
                current_generation=data.get("current_generation", 1),
                skills_matrix=skills_matrix,
                evolution_history=evolution_history,
                next_targets=data.get("next_targets", []),
                last_analyzed=data.get("last_analyzed", datetime.now().isoformat()),
            )

        except Exception:
            self._profile = self._create_default_profile()

    def _create_default_profile(self) -> SkillsProfile:
        """创建默认能力画像"""
        return SkillsProfile(
            current_generation=1,
            skills_matrix=DEFAULT_SKILLS_MATRIX.copy(),
            evolution_history=[],
            next_targets=[
                "建立主动目标生成能力",
                "实现模块化 Agent",
                "构建知识图谱系统",
            ],
        )

    def _save_profile(self) -> bool:
        """保存能力画像到文件"""
        if self._profile is None:
            return False

        try:
            with open(self._profile_file, 'w', encoding='utf-8') as f:
                json.dump(self._profile.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # =========================================================================
    # 查询接口
    # =========================================================================

    def get_profile(self) -> SkillsProfile:
        """获取当前能力画像"""
        if self._profile is None:
            self._load_profile()
        return self._profile

    def get_skill_score(self, skill_name: str) -> float:
        """
        获取技能评分

        Args:
            skill_name: 技能名称

        Returns:
            技能评分 (0.0 - 1.0)
        """
        profile = self.get_profile()
        if skill_name in profile.skills_matrix:
            return profile.skills_matrix[skill_name].score
        return 0.0

    def get_skill_entry(self, skill_name: str) -> Optional[SkillEntry]:
        """
        获取技能条目

        Args:
            skill_name: 技能名称

        Returns:
            技能条目
        """
        profile = self.get_profile()
        return profile.skills_matrix.get(skill_name)

    def get_overall_score(self) -> float:
        """
        获取综合评分

        Returns:
            综合评分
        """
        profile = self.get_profile()
        if not profile.skills_matrix:
            return 0.0

        return sum(s.score for s in profile.skills_matrix.values()) / len(profile.skills_matrix)

    def get_evolution_history(self, limit: int = 10) -> List[EvolutionRecord]:
        """
        获取进化历史

        Args:
            limit: 返回记录数量限制

        Returns:
            进化记录列表
        """
        profile = self.get_profile()
        return profile.evolution_history[-limit:]

    def get_next_targets(self) -> List[str]:
        """获取下一阶段目标"""
        return self.get_profile().next_targets

    def get_low_score_skills(self, threshold: float = 0.6) -> List[str]:
        """
        获取低分技能列表

        Args:
            threshold: 阈值

        Returns:
            低分技能名称列表
        """
        profile = self.get_profile()
        return [
            name for name, entry in profile.skills_matrix.items()
            if entry.score < threshold
        ]

    # =========================================================================
    # 更新接口
    # =========================================================================

    def update_skill_score(
        self,
        skill_name: str,
        new_score: float,
        evidence: Optional[List[str]] = None,
        weaknesses: Optional[List[str]] = None,
    ) -> bool:
        """
        更新技能评分

        Args:
            skill_name: 技能名称
            new_score: 新评分 (0.0 - 1.0)
            evidence: 新证据列表
            weaknesses: 新弱点列表

        Returns:
            是否更新成功
        """
        profile = self.get_profile()

        if skill_name not in profile.skills_matrix:
            # 创建新技能条目
            profile.skills_matrix[skill_name] = SkillEntry(
                name=skill_name,
                score=new_score,
                evidence=evidence or [],
                weaknesses=weaknesses or [],
            )
        else:
            entry = profile.skills_matrix[skill_name]
            entry.score = max(0.0, min(1.0, new_score))
            entry.last_updated = datetime.now().isoformat()

            if evidence:
                entry.evidence.extend(evidence)
            if weaknesses:
                entry.weaknesses.extend(weaknesses)

        profile.last_analyzed = datetime.now().isoformat()
        return self._save_profile()

    def update_from_analysis(
        self,
        dimension_scores: List[Any],
    ) -> bool:
        """
        从自我分析报告更新能力画像

        Args:
            dimension_scores: 能力评分列表

        Returns:
            是否更新成功
        """
        profile = self.get_profile()

        for score in dimension_scores:
            skill_name = score.dimension
            if skill_name in profile.skills_matrix:
                entry = profile.skills_matrix[skill_name]
                entry.score = score.score
                entry.evidence = score.evidence
                entry.weaknesses = score.weaknesses
                entry.last_updated = datetime.now().isoformat()

        profile.last_analyzed = datetime.now().isoformat()
        return self._save_profile()

    def add_evolution_record(
        self,
        generation: int,
        focus: str,
        improvement: str,
        score_change: float = 0.0,
    ) -> bool:
        """
        添加进化记录

        Args:
            generation: 世代
            focus: 进化焦点
            improvement: 改进描述
            score_change: 评分变化

        Returns:
            是否添加成功
        """
        profile = self.get_profile()

        record = EvolutionRecord(
            generation=generation,
            timestamp=datetime.now().isoformat(),
            focus=focus,
            improvement=improvement,
            score_change=score_change,
        )

        profile.evolution_history.append(record)

        # 限制历史长度
        if len(profile.evolution_history) > 50:
            profile.evolution_history = profile.evolution_history[-50:]

        return self._save_profile()

    def update_next_targets(self, targets: List[str]) -> bool:
        """
        更新下一阶段目标

        Args:
            targets: 目标列表

        Returns:
            是否更新成功
        """
        profile = self.get_profile()
        profile.next_targets = targets[:10]  # 限制数量
        return self._save_profile()

    def mark_target_achieved(self, target: str) -> bool:
        """
        标记目标已达成

        Args:
            target: 已达成的目标

        Returns:
            是否标记成功
        """
        profile = self.get_profile()

        if target in profile.next_targets:
            profile.next_targets.remove(target)
            return self._save_profile()

        return False

    def advance_generation(self) -> bool:
        """推进世代"""
        profile = self.get_profile()
        profile.current_generation += 1
        return self._save_profile()

    # =========================================================================
    # 报告生成
    # =========================================================================

    def generate_report(self) -> str:
        """
        生成能力画像报告

        Returns:
            Markdown 格式的报告
        """
        profile = self.get_profile()

        lines = [
            "# 虾宝能力画像",
            "",
            f"**当前世代**: G{profile.current_generation}",
            f"**最后分析**: {profile.last_analyzed}",
            f"**综合评分**: {self.get_overall_score():.1%}",
            "",
            "---",
            "",
            "## 能力矩阵",
            "",
        ]

        # 按评分排序
        sorted_skills = sorted(
            profile.skills_matrix.items(),
            key=lambda x: x[1].score,
            reverse=True,
        )

        for skill_name, entry in sorted_skills:
            score_bar = self._generate_score_bar(entry.score)
            lines.append(f"### {entry.name} ({skill_name})")
            lines.append(f"**评分**: {score_bar} {entry.score:.0%}")
            lines.append("")

            if entry.evidence:
                lines.append("**优势**:")
                for e in entry.evidence[:3]:
                    lines.append(f"- {e}")
                lines.append("")

            if entry.weaknesses:
                lines.append("**待改进**:")
                for w in entry.weaknesses[:3]:
                    lines.append(f"- {w}")
                lines.append("")

            lines.append(f"最后更新: {entry.last_updated}")
            lines.append("")
            lines.append("---")
            lines.append("")

        # 进化历史
        if profile.evolution_history:
            lines.extend([
                "## 进化历史",
                "",
            ])

            for record in profile.evolution_history[-5:]:  # 最近 5 条
                lines.append(
                    f"- **G{record.generation}**: {record.focus} "
                    f"({record.improvement}) "
                    f"[{record.score_change:+.1%}]"
                )

            lines.append("")

        # 下一步目标
        if profile.next_targets:
            lines.extend([
                "## 下一步目标",
                "",
            ])

            for i, target in enumerate(profile.next_targets, 1):
                lines.append(f"{i}. {target}")

            lines.append("")

        return "\n".join(lines)

    def _generate_score_bar(self, score: float, length: int = 10) -> str:
        """生成评分条"""
        filled = int(score * length)
        empty = length - filled

        # 根据评分选择颜色
        if score >= 0.8:
            color = "🟢"
        elif score >= 0.6:
            color = "🟡"
        else:
            color = "🔴"

        return color * filled + "⚪️" * empty

    def export_json(self) -> str:
        """导出为 JSON 字符串"""
        return json.dumps(self._profile.to_dict(), ensure_ascii=False, indent=2)


# ============================================================================
# 全局单例
# ============================================================================

_skills_profiler: Optional[SkillsProfiler] = None


def get_skills_profiler(project_root: Optional[str] = None) -> SkillsProfiler:
    """获取能力画像管理器单例"""
    global _skills_profiler
    if _skills_profiler is None:
        _skills_profiler = SkillsProfiler(project_root)
    return _skills_profiler
