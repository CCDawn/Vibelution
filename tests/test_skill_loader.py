#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SkillLoader 测试用例

测试 Skill 加载器、解析、LangChain Tool 转换功能。
"""

import os
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(project_root))


class TestSkillLoaderParse:
    """SkillLoader 解析测试"""

    def test_parse_skill_md_basic(self, tmp_path):
        from core.ecosystem.skill_loader import SkillLoader

        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        meta_file = skill_dir / "SKILL.md"
        meta_file.write_text("""# test_skill

## 基本信息
- name: test_skill
- description: 测试解析
- version: 1.0.0
- trigger_keywords: ["test"]
""", encoding="utf-8")

        meta = SkillLoader.parse_skill_md(skill_dir)
        assert meta is not None
        assert meta.name == "test_skill"
        assert meta.description == "测试解析"

    def test_parse_skill_md_with_params(self, tmp_path):
        from core.ecosystem.skill_loader import SkillLoader

        skill_dir = tmp_path / "param_skill"
        skill_dir.mkdir()
        meta_file = skill_dir / "SKILL.md"
        meta_file.write_text("""# param_skill

## 基本信息
- name: param_skill
- description: 测试参数解析
- version: 1.0.0

## parameters

- name: query
  type: string
  required: true
  description: 查询参数
- name: max_results
  type: integer
  required: false
  default: 10
  description: 最大结果数
""", encoding="utf-8")

        meta = SkillLoader.parse_skill_md(skill_dir)
        assert meta is not None
        assert len(meta.parameters) == 2
        assert meta.parameters[0].name == "query"
        assert meta.parameters[0].required is True
        assert meta.parameters[1].name == "max_results"
        assert meta.parameters[1].default == 10

    def test_parse_skill_md_missing_file(self, tmp_path):
        from core.ecosystem.skill_loader import SkillLoader

        skill_dir = tmp_path / "no_meta"
        skill_dir.mkdir()

        meta = SkillLoader.parse_skill_md(skill_dir)
        assert meta is None


class TestSkillLoaderLoad:
    """SkillLoader 加载测试"""

    def test_load_from_directory_missing_impl(self, tmp_path):
        from core.ecosystem.skill_loader import SkillLoader

        skill_dir = tmp_path / "no_impl"
        skill_dir.mkdir()

        meta_file = skill_dir / "SKILL.md"
        meta_file.write_text("""# no_impl
- name: no_impl
- description: Test
""", encoding="utf-8")

        result = SkillLoader.load_from_directory(skill_dir)
        assert result is None

    def test_load_from_directory_no_such_dir(self, tmp_path):
        from core.ecosystem.skill_loader import SkillLoader

        result = SkillLoader.load_from_directory(tmp_path / "not_exist")
        assert result is None


class TestSkillLoaderLangChain:
    """SkillLoader LangChain 转换测试"""

    def test_create_tool_from_meta(self):
        from core.ecosystem.skill_loader import SkillLoader
        from core.ecosystem.skill_registry import SkillMeta, SkillParam

        meta = SkillMeta(
            name="lc_convert",
            description="LangChain 转换测试",
            parameters=[
                SkillParam(name="query", type="string", required=True, description="查询")
            ]
        )

        def impl_func(query: str) -> dict:
            return {"query": query}

        tool = SkillLoader.create_tool_from_meta(meta, impl_func)
        assert tool.name == "skill_lc_convert"
        assert tool.description == "LangChain 转换测试"


class TestSkillLoaderShortcut:
    """SkillLoader 快捷函数测试"""

    def test_parse_skill_meta_shortcut(self, tmp_path):
        from core.ecosystem.skill_loader import parse_skill_meta

        skill_dir = tmp_path / "shortcut_test"
        skill_dir.mkdir()
        meta_file = skill_dir / "SKILL.md"
        meta_file.write_text("""# shortcut_test
- name: shortcut_test
- description: 快捷函数测试
""", encoding="utf-8")

        meta = parse_skill_meta(skill_dir)
        assert meta is not None
        assert meta.name == "shortcut_test"


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
