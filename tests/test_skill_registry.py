#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SkillRegistry 测试用例

测试 Skill 发现、加载、安装、更新、卸载等核心功能。
"""

import os
import sys
import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any

import pytest

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(project_root))


class TestSkillMeta:
    """SkillMeta 数据结构测试"""

    def test_skill_meta_creation(self):
        from core.ecosystem.skill_registry import SkillMeta, SkillParam
        meta = SkillMeta(
            name="test_skill",
            description="测试 Skill",
            version="1.0.0",
            trigger_keywords=["测试", "test"],
        )
        assert meta.name == "test_skill"
        assert meta.description == "测试 Skill"
        assert meta.version == "1.0.0"
        assert "测试" in meta.trigger_keywords

    def test_skill_meta_to_dict(self):
        from core.ecosystem.skill_registry import SkillMeta
        meta = SkillMeta(
            name="test_skill",
            description="测试",
        )
        d = meta.to_dict()
        assert d["name"] == "test_skill"
        assert d["description"] == "测试"

    def test_skill_meta_from_dict(self):
        from core.ecosystem.skill_registry import SkillMeta
        data = {
            "name": "test",
            "description": "测试",
            "version": "2.0.0",
            "trigger_keywords": ["test"],
            "parameters": [
                {"name": "arg1", "type": "string", "required": True}
            ]
        }
        meta = SkillMeta.from_dict(data)
        assert meta.name == "test"
        assert meta.version == "2.0.0"
        assert len(meta.parameters) == 1
        assert meta.parameters[0].name == "arg1"


class TestSkillRegistryInit:
    """SkillRegistry 初始化测试"""

    def test_init_with_custom_dir(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry
        skills_dir = tmp_path / "skills"
        registry = SkillRegistry(skills_dir=str(skills_dir))
        assert registry.skills_dir == skills_dir
        assert skills_dir.exists()

    def test_init_creates_default_dir(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry
        skills_dir = tmp_path / "nonexistent"
        registry = SkillRegistry(skills_dir=str(skills_dir))
        assert skills_dir.exists()


class TestSkillDiscovery:
    """Skill 发现测试"""

    def test_discover_no_skills(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry
        registry = SkillRegistry(skills_dir=str(tmp_path))
        discovered = registry.discover_skills()
        assert len(discovered) == 0

    def test_discover_single_skill(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry
        # 创建测试 Skill
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        meta_file = skill_dir / "SKILL.md"
        meta_file.write_text("""# test_skill

## 基本信息
- name: test_skill
- description: 测试 Skill
- version: 1.0.0
""", encoding="utf-8")

        registry = SkillRegistry(skills_dir=str(tmp_path))
        discovered = registry.discover_skills()
        assert "test_skill" in discovered

    def test_discover_multiple_skills(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry
        for name in ["skill_a", "skill_b", "skill_c"]:
            skill_dir = tmp_path / name
            skill_dir.mkdir()
            meta_file = skill_dir / "SKILL.md"
            meta_file.write_text(f"""# {name}

## 基本信息
- name: {name}
- description: Test
- version: 1.0.0
""", encoding="utf-8")

        registry = SkillRegistry(skills_dir=str(tmp_path))
        discovered = registry.discover_skills()
        assert len(discovered) == 3
        assert set(discovered) == {"skill_a", "skill_b", "skill_c"}


class TestSkillMetaParsing:
    """SKILL.md 解析测试"""

    def test_parse_basic_meta(self):
        from core.ecosystem.skill_registry import SkillRegistry
        content = """# test

## 基本信息
- name: test
- description: 测试描述
- version: 1.0.0
- author: test_author
- trigger_keywords: ["搜索", "查"]
- tags: ["信息", "工具"]
"""
        registry = SkillRegistry(skills_dir="/tmp")
        meta = registry._parse_skill_md(content, "test")
        assert meta.name == "test"
        assert meta.description == "测试描述"
        assert meta.version == "1.0.0"
        assert "搜索" in meta.trigger_keywords

    def test_parse_parameters(self):
        from core.ecosystem.skill_registry import SkillRegistry
        content = """# test

## 基本信息
- name: test
- description: Test
- version: 1.0.0

## parameters

- name: query
  type: string
  required: true
  description: 搜索关键词
- name: limit
  type: integer
  required: false
  default: 5
  description: 结果数量
"""
        registry = SkillRegistry(skills_dir="/tmp")
        meta = registry._parse_skill_md(content, "test")
        assert len(meta.parameters) == 2
        assert meta.parameters[0].name == "query"
        assert meta.parameters[0].required is True
        assert meta.parameters[1].name == "limit"
        assert meta.parameters[1].default == 5


class TestSkillInstall:
    """Skill 安装测试（Agent 自我扩展核心）"""

    def test_install_skill_success(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(
            name="new_skill",
            description="新安装的 Skill",
            version="1.0.0",
            trigger_keywords=["new"],
        )
        impl_code = '''def execute(query: str = "") -> dict:
    return {"status": "ok", "query": query}
'''

        result = registry.install_skill(meta, impl_code)
        assert result["success"] is True

        # 验证目录结构
        skill_dir = tmp_path / "new_skill"
        assert skill_dir.exists()
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "impl.py").exists()

        # 验证内容
        impl_content = (skill_dir / "impl.py").read_text(encoding="utf-8")
        assert "execute" in impl_content

    def test_install_skill_duplicate(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="dup_skill", description="Test")
        result1 = registry.install_skill(meta, "def execute(): pass")
        assert result1["success"] is True

        result2 = registry.install_skill(meta, "def execute(): pass")
        assert result2["success"] is False
        assert "已存在" in result2["message"]

    def test_install_skill_with_parameters(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta, SkillParam

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(
            name="param_skill",
            description="带参数的 Skill",
            parameters=[
                SkillParam(name="query", type="string", required=True, description="查询"),
                SkillParam(name="limit", type="integer", required=False, default=10, description="限制"),
            ]
        )
        impl_code = '''def execute(query: str, limit: int = 10) -> dict:
    return {"query": query, "limit": limit}
'''
        result = registry.install_skill(meta, impl_code)
        assert result["success"] is True

        # 重新加载并验证
        registry2 = SkillRegistry(skills_dir=str(tmp_path))
        meta2 = registry2.get_skill("param_skill")
        assert meta2 is not None
        assert len(meta2.parameters) == 2


class TestSkillUpdate:
    """Skill 更新测试（Agent 自我扩展）"""

    def test_update_meta_only(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        # 先安装
        meta = SkillMeta(name="update_skill", description="原描述")
        registry.install_skill(meta, "def execute(): pass")

        # 再更新元数据
        new_meta = SkillMeta(name="update_skill", description="新描述", version="2.0.0")
        result = registry.update_skill("update_skill", meta=new_meta)
        assert result["success"] is True

        # 验证
        updated = registry.get_skill("update_skill")
        assert updated.description == "新描述"
        assert updated.version == "2.0.0"

    def test_update_impl_only(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="impl_skill", description="Test")
        registry.install_skill(meta, "def execute(): pass")

        new_impl = '''def execute() -> dict:
    return {"version": 2}
'''
        result = registry.update_skill("impl_skill", impl_code=new_impl)
        assert result["success"] is True

        skill_dir = tmp_path / "impl_skill"
        content = (skill_dir / "impl.py").read_text(encoding="utf-8")
        assert "version" in content

    def test_update_nonexistent(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry

        registry = SkillRegistry(skills_dir=str(tmp_path))
        result = registry.update_skill("not_exist", impl_code="pass")
        assert result["success"] is False


class TestSkillUninstall:
    """Skill 卸载测试（Agent 自我扩展）"""

    def test_uninstall_success(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="remove_skill", description="待删除")
        registry.install_skill(meta, "def execute(): pass")

        result = registry.uninstall_skill("remove_skill")
        assert result["success"] is True

        # 验证目录已删除
        assert not (tmp_path / "remove_skill").exists()
        assert registry.get_skill("remove_skill") is None

    def test_uninstall_nonexistent(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry

        registry = SkillRegistry(skills_dir=str(tmp_path))
        result = registry.uninstall_skill("not_exist")
        assert result["success"] is False


class TestSkillOptimize:
    """Skill 优化测试（Agent 自我扩展）"""

    def test_optimize_skill(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="opt_skill", description="待优化")
        registry.install_skill(meta, "def execute(): pass")

        optimized_impl = '''def execute() -> dict:
    # 优化后的版本，添加了缓存
    import time
    return {"time": time.time()}
'''
        result = registry.optimize_skill("opt_skill", optimized_impl)
        assert result["success"] is True

        content = (tmp_path / "opt_skill" / "impl.py").read_text(encoding="utf-8")
        assert "cache" in content or "time" in content


class TestSkillLoad:
    """Skill 加载测试"""

    def test_load_skill(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="load_skill", description="Test")
        impl_code = '''def execute(msg: str = "hello") -> dict:
    return {"message": msg}
'''
        registry.install_skill(meta, impl_code)

        success = registry.load_skill("load_skill")
        assert success is True
        assert "load_skill" in registry._loaded_skills

    def test_load_skill_execute(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="exec_skill", description="Test")
        impl_code = '''def execute(x: int, y: int = 5) -> dict:
    return {"sum": x + y, "product": x * y}
'''
        registry.install_skill(meta, impl_code)
        registry.load_skill("exec_skill")

        result = registry.execute_skill("exec_skill", {"x": 3, "y": 7})
        # result 是 JSON 字符串
        data = json.loads(result)
        assert data["sum"] == 10
        assert data["product"] == 21


class TestSkillSearch:
    """Skill 搜索测试"""

    def test_search_by_name(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        for name in ["web_search", "code_search", "file_search"]:
            meta = SkillMeta(name=name, description="Search functionality")
            registry.install_skill(meta, "def execute(): pass")

        results = registry.search_by_keyword("web")
        assert len(results) >= 1
        assert any(r.name == "web_search" for r in results)

    def test_search_by_tag(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(
            name="test_skill",
            description="Test",
            tags=["analysis", "tools"],
        )
        registry.install_skill(meta, "def execute(): pass")

        results = registry.search_by_keyword("analysis")
        assert len(results) >= 1


class TestSkillPrompt:
    """Skill 提示词生成测试"""

    def test_render_skill_prompt(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta, SkillParam

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(
            name="render_test",
            description="测试渲染",
            trigger_keywords=["测试"],
            parameters=[
                SkillParam(name="query", type="string", required=True, description="查询词")
            ]
        )
        registry.install_skill(meta, "def execute(): pass")

        prompt = registry.render_skill_prompt()
        assert "render_test" in prompt
        assert "测试渲染" in prompt
        assert "query" in prompt


class TestSkillPersistence:
    """Skill 持久化测试"""

    def test_persistence_after_reload(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        # 第一次安装
        registry1 = SkillRegistry(skills_dir=str(tmp_path))
        meta = SkillMeta(name="persist_skill", description="持久化测试")
        registry1.install_skill(meta, "def execute(): return 'v1'")

        # 第二次加载（模拟重启）
        registry2 = SkillRegistry(skills_dir=str(tmp_path))
        discovered = registry2.discover_skills()
        assert "persist_skill" in discovered

        meta2 = registry2.get_skill("persist_skill")
        assert meta2 is not None
        assert meta2.description == "持久化测试"


class TestSkillLangChain:
    """LangChain Tool 转换测试"""

    def test_to_langchain_tools(self, tmp_path):
        from core.ecosystem.skill_registry import SkillRegistry, SkillMeta

        registry = SkillRegistry(skills_dir=str(tmp_path))

        meta = SkillMeta(name="lc_tool", description="LangChain 测试")
        impl_code = '''def execute(query: str) -> dict:
    return {"result": query}
'''
        registry.install_skill(meta, impl_code)
        registry.load_skill("lc_tool")

        tools = registry.to_langchain_tools(["lc_tool"])
        assert len(tools) == 1
        assert tools[0].name == "skill_lc_tool"


# ============================================================================
# 运行入口
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
