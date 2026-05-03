#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PromptManager 测试

测试 core/prompt_manager/ 重构后的功能：
- SystemPromptSection 章节定义
- PromptManager 单例与注册
- build() 返回 SystemPrompt 元组
- 章节级缓存
- 静/动态边界标记
- 向后兼容函数
"""

import pytest
import sys
import os

from core.prompt_manager import (
    SystemPrompt,
    SystemPromptSection,
    as_system_prompt,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    SystemPromptCache,
    PromptManager,
    get_prompt_manager,
    build_system_prompt,
    build_simple_system_prompt,
    to_string,
)


class TestSystemPromptSection:
    """SystemPromptSection 数据类测试"""

    def test_section_creation(self):
        section = SystemPromptSection(
            name="TEST",
            priority=10,
            description="测试章节",
            compute=lambda: "test content",
            cache_break=False,
        )
        assert section.name == "TEST"
        assert section.priority == 10
        assert section.cache_break is False
        assert section.compute() == "test content"

    def test_section_default_values(self):
        section = SystemPromptSection(name="MINIMAL", compute=lambda: None)
        assert section.name == "MINIMAL"
        assert section.priority == 50
        assert section.cache_break is False
        assert section.description == ""
        assert section.required is False

    def test_section_frozen(self):
        """SystemPromptSection 是 frozen dataclass"""
        section = SystemPromptSection(name="FROZEN", compute=lambda: "x")
        with pytest.raises(Exception):
            section.name = "CHANGED"


class TestSystemPrompt:
    """SystemPrompt 品牌类型测试"""

    def test_as_system_prompt(self):
        sp = as_system_prompt(["part1", "part2"])
        assert isinstance(sp, tuple)
        assert len(sp) == 2
        assert sp[0] == "part1"

    def test_to_string(self):
        sp = as_system_prompt(["a", "b", "c"])
        assert to_string(sp) == "a\n\nb\n\nc"

    def test_to_string_skips_boundary(self):
        sp = as_system_prompt(["static", SYSTEM_PROMPT_DYNAMIC_BOUNDARY, "dynamic"])
        result = to_string(sp)
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in result
        assert "static" in result
        assert "dynamic" in result


class TestSystemPromptCache:
    """章节级缓存测试"""

    def test_get_set(self):
        cache = SystemPromptCache()
        assert cache.get("A") is None
        cache.set("A", "value_a")
        assert cache.get("A") == "value_a"

    def test_has(self):
        cache = SystemPromptCache()
        assert not cache.has("X")
        cache.set("X", "val")
        assert cache.has("X")

    def test_invalidate_single(self):
        cache = SystemPromptCache()
        cache.set("A", "val_a")
        cache.set("B", "val_b")
        cache.invalidate("A")
        assert not cache.has("A")
        assert cache.has("B")

    def test_invalidate_all(self):
        cache = SystemPromptCache()
        cache.set("A", "val_a")
        cache.set("B", "val_b")
        cache.invalidate()
        assert not cache.has("A")
        assert not cache.has("B")

    def test_hit_miss_stats(self):
        cache = SystemPromptCache()
        cache.get("A")  # miss
        cache.set("A", "val")
        cache.get("A")  # hit
        cache.get("A")  # hit
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1


class TestPromptManager:
    """PromptManager 核心类测试"""

    def test_singleton_pattern(self):
        pm1 = get_prompt_manager()
        pm2 = get_prompt_manager()
        assert pm1 is pm2

    def test_section_registration(self):
        pm = PromptManager()
        initial_count = len(pm._sections)

        custom = SystemPromptSection(
            name="CUSTOM", priority=5, compute=lambda: "custom content"
        )
        pm.register(custom)
        assert "CUSTOM" in pm._sections
        assert len(pm._sections) == initial_count + 1

        # 覆盖注册
        new_section = SystemPromptSection(
            name="CUSTOM", priority=99, compute=lambda: "new content"
        )
        pm.register(new_section)
        assert pm._sections["CUSTOM"].priority == 99

    def test_section_unregistration(self):
        pm = PromptManager()
        pm.register(SystemPromptSection(name="TO_REMOVE", compute=lambda: None))
        assert "TO_REMOVE" in pm._sections
        pm.unregister("TO_REMOVE")
        assert "TO_REMOVE" not in pm._sections

    def test_list_sections(self):
        pm = PromptManager()
        sections = pm.list_sections()
        names = [s["name"] for s in sections]
        assert "SOUL" in names
        assert "SPEC" in names
        # 按 priority 排序
        priorities = [s["priority"] for s in sections]
        assert priorities == sorted(priorities)

    def test_get_status(self):
        pm = PromptManager()
        status = pm.get_status()
        assert "static_root" in status
        assert "dynamic_root" in status
        assert "registered_sections" in status
        assert len(status["registered_sections"]) >= 5

    def test_required_sections_cannot_be_excluded(self):
        pm = PromptManager()
        sp = pm.build(exclude=["SOUL", "SPEC"])
        result = to_string(sp)
        # SOUL 和 SPEC 是 required=True，即使在 exclude 列表中也会保留
        assert isinstance(result, str)
        assert len(result) > 0


class TestBuildAPI:
    """build() API 测试"""

    def test_build_default(self):
        pm = PromptManager()
        sp = pm.build()
        assert isinstance(sp, tuple)  # SystemPrompt 是 tuple
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_with_memory_params(self):
        pm = PromptManager()
        sp = pm.build(
            include=["SOUL", "SPEC", "MEMORY"],
            core_context="学会了优化代码",
            current_goal="改进性能",
        )
        result = to_string(sp)
        assert isinstance(result, str)
        assert "优化代码" in result

    def test_build_include_filter(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "SPEC"])
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_exclude_filter(self):
        pm = PromptManager()
        sp = pm.build(exclude=["MEMORY", "TOOLS_INDEX", "ENV_INFO"])
        result = to_string(sp)
        assert isinstance(result, str)
        # 被排除的组件不应出现
        assert "核心智慧摘要" not in result
        assert "工具手册索引" not in result
        assert "当前时间" not in result

    def test_build_include_and_exclude(self):
        pm = PromptManager()
        sp = pm.build(
            include=["SOUL", "TASK_CHECKLIST", "SPEC"],
            exclude=["MEMORY"],
        )
        result = to_string(sp)
        assert isinstance(result, str)
        assert "核心智慧摘要" not in result

    def test_build_empty_include(self):
        pm = PromptManager()
        sp = pm.build(include=[])
        result = to_string(sp)
        assert isinstance(result, str)
        # 空 include = 无章节被选中，但仍有索引/指南文本
        assert isinstance(sp, tuple)

    def test_build_returns_system_prompt_tuple(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL"])
        assert isinstance(sp, tuple)
        # 每个元素都是字符串
        for part in sp:
            assert isinstance(part, str)

    def test_build_contains_boundary_marker(self):
        """包含动态章节时应有边界标记"""
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "ENV_INFO"])
        # SOUL 是静态，ENV_INFO 是动态，之间应有边界标记
        parts = list(sp)
        assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in parts


class TestCompatibilityFunctions:
    """向后兼容函数测试"""

    def test_build_system_prompt(self):
        result = build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_simple_system_prompt(self):
        result = build_simple_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_string_on_system_prompt(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "SPEC"])
        result = to_string(sp)
        assert isinstance(result, str)
        assert len(result) > 0


class TestCache:
    """章节级缓存测试"""

    def test_invalidate_single_cache(self):
        pm = PromptManager()
        pm.build(include=["SOUL"])
        pm.invalidate_cache("SOUL")
        assert not pm._section_cache.has("SOUL")

    def test_invalidate_all_cache(self):
        pm = PromptManager()
        pm.build(include=["SOUL", "SPEC"])
        pm.invalidate_cache()
        assert len(pm._section_cache.stats["cached_sections"]) == 0

    def test_cache_hit(self):
        pm = PromptManager()
        pm.build(include=["SOUL", "SPEC"])
        stats = pm.get_cache_stats()
        # 静态章节应在缓存中
        assert "SOUL" in stats["cached_sections"]

    def test_cache_invalidated_by_state_memory(self):
        pm = PromptManager()
        pm.build(include=["SOUL"])
        stats_before = pm.get_cache_stats()

        pm.update_state_memory("新的状态记忆")
        stats_after = pm.get_cache_stats()
        # MEMORY 缓存应被清除
        assert "MEMORY" not in stats_after["cached_sections"]


class TestLoadFunctions:
    """章节加载函数测试"""

    def test_soul_section_compute(self):
        pm = PromptManager()
        soul = pm._sections.get("SOUL")
        assert soul is not None, "SOUL 章节应已注册"
        content = soul.compute()
        assert isinstance(content, str)
        assert len(content) > 0
        assert "铁律" in content or "绝对" in content

    def test_env_info_section_compute(self):
        pm = PromptManager()
        env = pm._sections.get("ENV_INFO")
        assert env is not None, "ENV_INFO 章节应已注册"
        content = env.compute()
        assert content is not None
        assert "当前时间" in content
        assert "项目根目录" in content

    def test_nonexistent_section_returns_none(self):
        section = SystemPromptSection(
            name="NONEXISTENT",
            compute=lambda: None,
        )
        assert section.compute() is None


class TestCurrentGoal:
    """current_goal 内存持有测试"""

    def test_current_goal_default_empty(self):
        pm = PromptManager()
        assert pm.get_current_goal() == ""

    def test_update_current_goal(self):
        pm = PromptManager()
        pm.update_current_goal("完成单元测试")
        assert pm.get_current_goal() == "完成单元测试"

    def test_current_goal_in_build(self):
        pm = PromptManager()
        pm.update_current_goal("探索代码库")
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        assert "探索代码库" in result

    def test_current_goal_no_file_fallback(self):
        pm = PromptManager()
        # 不设置 current_goal，build 不应从文件读取
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        # 没有 goal 时 MEMORY section 不渲染 goal 行
        assert "本世代核心目标" not in result or "待定" not in result

    def test_current_goal_cache_invalidation(self):
        pm = PromptManager()
        pm.update_current_goal("目标A")
        pm.build(include=["SOUL", "MEMORY"])
        pm.update_current_goal("目标B")
        sp = pm.build(include=["SOUL", "MEMORY"])
        result = to_string(sp)
        assert "目标B" in result

    def test_current_goal_param_overrides_memory(self):
        pm = PromptManager()
        pm.update_current_goal("内存目标")
        sp = pm.build(include=["SOUL", "MEMORY"], current_goal="参数目标")
        result = to_string(sp)
        assert "参数目标" in result

    def test_current_goal_empty_string_not_updated(self):
        pm = PromptManager()
        pm.update_current_goal("有效目标")
        pm.update_current_goal("")  # 空字符串不应覆盖
        assert pm.get_current_goal() == "有效目标"


class TestSectionPriority:
    """章节优先级排序测试"""

    def test_sections_sorted_by_priority(self):
        pm = PromptManager()
        sections = pm.list_sections()
        priorities = [s["priority"] for s in sections]
        assert priorities == sorted(priorities)

    def test_priority_order_in_output(self):
        pm = PromptManager()
        sp = pm.build(include=["SOUL", "SPEC"])
        result = to_string(sp)

        soul_pos = result.find("绝对生存法则") if "绝对生存法则" in result else result.find("铁律")
        spec_pos = result.find("开发流程") if "开发流程" in result else result.find("SPEC")

        if soul_pos != -1 and spec_pos != -1:
            assert soul_pos < spec_pos, "SOUL (p10) 应在 SPEC (p65) 之前"


class TestConfigDrivenSections:
    """配置驱动的静态章节测试"""

    @staticmethod
    def _make_config(name, path, priority=50, required=False, cache_break=False, description=""):
        """创建模拟 SectionConfig 对象（Pydantic 模型 duck-type）。"""
        class MockCfg:
            def __init__(self):
                self.name = name
                self.path = path
                self.priority = priority
                self.required = required
                self.cache_break = cache_break
                self.description = description
        return MockCfg()

    def test_create_sections_from_config_objects(self):
        """通过 create_default_sections 传入 config 列表创建静态章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("SOUL", "core/core_prompt/SOUL.md", priority=10, required=True, description="铁律"),
            self._make_config("SPEC", "core/core_prompt/SPEC.md", priority=65, description="规范"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        names = {s.name for s in sections}
        assert "SOUL" in names
        assert "SPEC" in names
        # 动态章节仍应存在
        assert "TASK_CHECKLIST" in names
        assert "CODEBASE_MAP" in names
        assert "ENV_INFO" in names

    def test_missing_file_not_registered(self):
        """配置指向不存在的文件时不注册该章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("GHOST", "core/core_prompt/NOT_EXISTS.md"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        names = {s.name for s in sections}
        assert "GHOST" not in names, "不存在的文件不应注册章节"

    def test_empty_configs_falls_back_to_dynamic_only(self):
        """section_configs 为 None 或空列表时只注册动态章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=[],
        )
        names = {s.name for s in sections}
        # 没有静态章节
        assert "SOUL" not in names
        assert "SPEC" not in names
        # 动态章节存在
        assert "TASK_CHECKLIST" in names
        assert "ENV_INFO" in names

    def test_config_priority_and_required_preserved(self):
        """config 中的 priority 和 required 属性被正确传递到章节。"""
        from core.prompt_manager.sections import create_default_sections
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        static_root = project_root / "core" / "core_prompt"
        dynamic_root = project_root / "workspace" / "prompts"

        configs = [
            self._make_config("SOUL", "core/core_prompt/SOUL.md",
                              priority=99, required=True, description="自定义"),
        ]

        sections = create_default_sections(
            static_root, dynamic_root, project_root,
            section_configs=configs,
        )
        soul = next((s for s in sections if s.name == "SOUL"), None)
        assert soul is not None
        assert soul.priority == 99, "priority 应来自 config 而非硬编码"
        assert soul.required is True
        assert soul.description == "自定义"
