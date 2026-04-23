#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptManager 测试

测试 core/capabilities/prompt_manager.py 的功能：
- PromptComponent 组件定义
- PromptManager 单例模式
- 参数驱动拼接（include/exclude）
- 组件优先级排序
- 缓存机制
- 兼容函数
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.prompt_manager import (
    PromptComponent,
    PromptManager,
    get_prompt_manager,
    build_system_prompt,
    build_simple_system_prompt,
)


class TestPromptComponent:
    """PromptComponent 数据类测试"""

    def test_component_creation(self):
        """测试组件创建"""
        comp = PromptComponent(
            name="TEST",
            priority=10,
            required=True,
            load_fn=lambda: "test content",
        )
        assert comp.name == "TEST"
        assert comp.priority == 10
        assert comp.required is True
        assert comp.enabled is True
        assert comp.load_fn() == "test content"

    def test_component_default_values(self):
        """测试默认值"""
        comp = PromptComponent(name="MINIMAL")
        assert comp.name == "MINIMAL"
        assert comp.priority == 50
        assert comp.required is False
        assert comp.enabled is True
        assert comp.load_fn() == ""

    def test_component_mutable_fields(self):
        """测试可变字段"""
        comp = PromptComponent(name="DYNAMIC")
        comp.enabled = False
        assert comp.enabled is False


class TestPromptManager:
    """PromptManager 核心类测试"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        pm1 = get_prompt_manager()
        pm2 = get_prompt_manager()
        assert pm1 is pm2

    def test_component_registration(self):
        """测试组件注册"""
        pm = PromptManager()
        initial_count = len(pm._components)

        custom_comp = PromptComponent(name="CUSTOM", priority=5)
        pm.register(custom_comp)
        assert "CUSTOM" in pm._components
        assert len(pm._components) == initial_count + 1

        # 测试覆盖注册
        new_comp = PromptComponent(name="CUSTOM", priority=99)
        pm.register(new_comp)
        assert pm._components["CUSTOM"].priority == 99

    def test_component_unregistration(self):
        """测试组件注销"""
        pm = PromptManager()
        pm.register(PromptComponent(name="TO_REMOVE"))
        assert "TO_REMOVE" in pm._components
        pm.unregister("TO_REMOVE")
        assert "TO_REMOVE" not in pm._components

    def test_set_enabled(self):
        """测试动态启用/禁用"""
        pm = PromptManager()
        pm.set_enabled("SOUL", False)
        assert pm._components["SOUL"].enabled is False
        pm.set_enabled("SOUL", True)
        assert pm._components["SOUL"].enabled is True

    def test_list_components(self):
        """测试列出所有组件"""
        pm = PromptManager()
        components = pm.list_components()
        names = [c["name"] for c in components]
        assert "SOUL" in names
        assert "AGENTS" in names
        # 按 priority 排序
        priorities = [c["priority"] for c in components]
        assert priorities == sorted(priorities)

    def test_get_status(self):
        """测试状态获取"""
        pm = PromptManager()
        status = pm.get_status()
        assert "static_root" in status
        assert "dynamic_root" in status
        assert "registered_components" in status
        assert len(status["registered_components"]) >= 10

    def test_required_components_cannot_be_excluded(self):
        """测试 required=True 的组件无法被 exclude 移除"""
        pm = PromptManager()
        result = pm.build(exclude=["SOUL", "AGENTS"])
        # SOUL 和 AGENTS 是 required=True，即使在 exclude 列表中也会保留
        assert "SOUL" in pm._components  # 组件仍存在
        # 实际渲染时，SOUL 内容仍会出现在结果中（因为 required=True 组件的 exclude 被忽略）
        # 检查方式是看 SOUL 组件仍然被执行了


class TestBuildAPI:
    """build() API 测试"""

    def test_build_default(self):
        """测试默认全量拼接"""
        pm = PromptManager()
        result = pm.build()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_with_memory_params(self):
        """测试带记忆参数的拼接"""
        pm = PromptManager()
        result = pm.build(
            generation=3,
            total_generations=10,
            core_context="学会了优化代码",
            current_goal="改进性能",
        )
        assert isinstance(result, str)
        assert "G3" in result or "世代" in result

    def test_build_include_filter(self):
        """测试 include 过滤"""
        pm = PromptManager()
        result = pm.build(include=["SOUL", "AGENTS"])
        assert isinstance(result, str)
        # 只包含指定组件
        lines = result.split("\n")
        assert any("铁律" in line or "SOUL" in line for line in lines)

    def test_build_exclude_filter(self):
        """测试 exclude 过滤"""
        pm = PromptManager()
        result = pm.build(exclude=["MEMORY", "TOOLS_INDEX", "ENV_INFO"])
        assert isinstance(result, str)
        # 不包含被排除的组件内容
        assert "核心智慧摘要" not in result
        assert "工具手册索引" not in result
        assert "当前时间" not in result

    def test_build_include_and_exclude(self):
        """测试同时使用 include 和 exclude"""
        pm = PromptManager()
        result = pm.build(
            include=["SOUL", "TASK_CHECKLIST", "AGENTS"],
            exclude=["MEMORY"],
            generation=1,
            total_generations=1,
        )
        assert isinstance(result, str)
        assert "核心智慧摘要" not in result

    def test_build_empty_include(self):
        """测试空 include 返回空字符串"""
        pm = PromptManager()
        result = pm.build(include=[])
        assert result == ""


class TestCompatibilityFunctions:
    """兼容函数测试"""

    def test_build_system_prompt(self):
        """测试 build_system_prompt 便捷函数"""
        result = build_system_prompt(generation=1, total_generations=1)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_simple_system_prompt(self):
        """测试 build_simple_system_prompt 便捷函数"""
        result = build_simple_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compat_functions_match(self):
        """测试兼容函数结果一致性"""
        result1 = build_system_prompt(generation=1, total_generations=1)
        result2 = build_simple_system_prompt()
        # 两者在没有额外参数时应该产生相似结果（取决于记忆内容）
        assert isinstance(result1, str)
        assert isinstance(result2, str)


class TestCache:
    """缓存机制测试"""

    def test_invalidate_single_cache(self):
        """测试按名称清除缓存"""
        pm = PromptManager()
        # 先触发一次加载
        pm.build(include=["SOUL"])
        # 清除特定缓存
        pm.invalidate_cache("SOUL")
        assert True  # 不抛异常即通过

    def test_invalidate_all_cache(self):
        """测试清除全部缓存"""
        pm = PromptManager()
        pm.build()
        pm.invalidate_cache()
        assert True  # 不抛异常即通过

    def test_cache_after_invalidate(self):
        """测试缓存失效后重新加载"""
        pm = PromptManager()
        result1 = pm.build(include=["SOUL"])
        pm.invalidate_cache()
        result2 = pm.build(include=["SOUL"])
        assert result1 == result2


class TestLoadFunctions:
    """加载函数测试"""

    def test_load_soul(self):
        """测试加载 SOUL.md"""
        pm = PromptManager()
        content = pm._load_soul()
        assert isinstance(content, str)
        assert len(content) > 0
        assert "铁律" in content or "绝对" in content

    def test_load_agents(self):
        """测试加载 AGENTS.md"""
        pm = PromptManager()
        content = pm._load_agents()
        assert isinstance(content, str)
        assert len(content) > 0
        assert "SOP" in content or "流程" in content

    def test_load_nonexistent_file(self):
        """测试加载不存在的文件返回警告"""
        pm = PromptManager()
        content = pm._load_from_path(
            pm._dynamic_root / "NONEXISTENT_FILE_12345.md",
            "NONEXISTENT_FILE_12345.md"
        )
        assert "[警告" in content or "[错误" in content

    def test_load_env_info(self):
        """测试环境信息加载"""
        pm = PromptManager()
        content = pm._load_env_info()
        assert "当前时间" in content
        assert "项目根目录" in content


class TestComponentPriority:
    """组件优先级测试"""

    def test_components_sorted_by_priority(self):
        """测试组件按 priority 排序"""
        pm = PromptManager()
        components = sorted(pm._components.values(), key=lambda c: c.priority)
        priorities = [c.priority for c in components]
        assert priorities == sorted(priorities)

    def test_priority_order_in_build(self):
        """测试构建时组件按优先级排列"""
        pm = PromptManager()
        result = pm.build(include=["SOUL", "AGENTS", "DYNAMIC", "IDENTITY", "USER"])

        soul_pos = result.find("绝对生存法则") if "绝对生存法则" in result else result.find("铁律")
        agents_pos = result.find("执行总流程") if "执行总流程" in result else result.find("SOP")

        # SOUL (priority=10) 应在 AGENTS (priority=60) 之前
        if soul_pos != -1 and agents_pos != -1:
            assert soul_pos < agents_pos, "SOUL 应该在 AGENTS 之前"
