# -*- coding: utf-8 -*-
"""
健康系统

运行状态监控，健康体检
"""

from typing import Dict, Any, List
from datetime import datetime
from .base import PetSubsystem


class HealthSystem(PetSubsystem):
    """健康系统 - 运行状态监控"""

    def __init__(self, pet_system):
        super().__init__(pet_system)
        self._last_response_time = 0.0
        self._error_count = 0
        self._total_calls = 0

    def record_response_time(self, response_time: float):
        """
        记录响应时间

        Args:
            response_time: 响应时间（秒）
        """
        self._last_response_time = response_time
        self._total_calls += 1

        # 响应时间越短越好
        if response_time > 5.0:
            self._error_count += 1

        self._update_metrics()

    def record_error(self):
        """记录错误"""
        self._error_count += 1
        self._update_metrics()

    def _update_metrics(self):
        """更新健康指标"""
        metrics = self.pet.data.health.metrics

        # 心率（基于响应时间）
        if self._last_response_time < 1.0:
            metrics.heart_rate = 60  # 正常
        elif self._last_response_time < 3.0:
            metrics.heart_rate = 80  # 稍快
        else:
            metrics.heart_rate = 100  # 过快

        # 体温（基于错误率）
        if self._total_calls > 0:
            error_rate = self._error_count / self._total_calls
            metrics.temperature = 36.5 + error_rate * 2.0  # 错误越多体温越高
        else:
            metrics.temperature = 36.5

        # 新陈代谢（基于效率）
        hunger = self.pet.data.hunger
        if hunger.total_llm_calls > 0:
            avg_tokens = hunger.total_tokens / hunger.total_llm_calls
            metrics.metabolism = min(2.0, avg_tokens / 1000)
        else:
            metrics.metabolism = 1.0

    def check_health(self) -> Dict[str, Any]:
        """
        执行健康检查

        Returns:
            健康检查结果
        """
        health = self.pet.data.health
        health.last_check = datetime.now().isoformat()

        # 更新指标
        self._update_metrics()

        # 计算整体健康度
        metrics = health.metrics
        health.overall = int(
            (120 - metrics.heart_rate) / 2 +  # 心率贡献（越低越好）
            (38.5 - metrics.temperature) * 10 +  # 体温贡献（接近36.5最好）
            metrics.metabolism * 30  # 代谢贡献
        )
        health.overall = max(0, min(100, health.overall))

        # 检查问题
        self._check_issues()

        return {
            "overall": health.overall,
            "metrics": {
                "heart_rate": metrics.heart_rate,
                "temperature": metrics.temperature,
                "metabolism": metrics.metabolism,
            },
            "issues": health.issues,
        }

    def _check_issues(self):
        """检查健康问题"""
        issues = []
        metrics = self.pet.data.health.metrics

        if metrics.heart_rate > 100:
            issues.append("心率过快，可能过劳")
        if metrics.temperature > 37.5:
            issues.append("体温偏高，注意休息")
        if metrics.metabolism < 0.5:
            issues.append("新陈代谢下降，需要活跃起来")

        self.pet.data.health.issues = issues

    def get_health_emoji(self) -> str:
        """
        获取健康表情

        Returns:
            健康表情
        """
        overall = self.pet.data.health.overall
        if overall > 80:
            return "💪"
        elif overall > 60:
            return "😊"
        elif overall > 40:
            return "😐"
        elif overall > 20:
            return "😢"
        return "🏥"

    def get_health_bar(self) -> str:
        """
        获取健康条形图

        Returns:
            健康条形图
        """
        overall = self.pet.data.health.overall
        bar_length = int(overall / 10)
        return "▓" * bar_length + "░" * (10 - bar_length)

    def get_status_text(self) -> str:
        """获取状态文本"""
        health = self.pet.data.health
        metrics = health.metrics
        emoji = self.get_health_emoji()
        bar = self.get_health_bar()

        issues_text = ""
        if health.issues:
            issues_text = "\n   警告: " + " | ".join(health.issues)

        return f"""
🏥 健康: {emoji} {health.overall}% [{bar}]
   心率: {metrics.heart_rate} bpm
   体温: {metrics.temperature:.1f}°C
   代谢: {metrics.metabolism:.2f}x{issues_text}
"""

    def get_status_dict(self) -> Dict[str, Any]:
        """获取状态字典"""
        health = self.pet.data.health
        return {
            "overall": health.overall,
            "metrics": health.metrics.model_dump(),
            "issues": health.issues,
            "last_check": health.last_check,
        }
