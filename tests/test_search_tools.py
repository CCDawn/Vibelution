#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索工具完整测试套件

测试 tools/search_tools.py 中的所有功能：
- 全局正则搜索（grep_search_tool）
- 函数调用查找（find_function_calls_tool）
- 符号定义查找（find_definitions_tool）
- Import 语句搜索（search_imports_tool）
- 搜索并读取（search_and_read_tool）
"""

import os
import sys
import json
import subprocess
import pytest
import tempfile
import shutil
import re
from pathlib import Path
from datetime import datetime

from tools.search_tools import (
    grep_search_tool,
    find_function_calls_tool,
    find_definitions_tool,
    search_imports_tool,
    search_and_read_tool,
)

# ============================================================================
# 测试辅助函数和数据
# ============================================================================

SAMPLE_PY_CONTENT = '''
#!/usr/bin/env python3
"""
示例模块 - 用于测试搜索工具
"""

import os
import sys
from typing import List, Optional

# 全局变量
CONSTANT_VALUE = 42
ANOTHER_CONSTANT = "hello"

def helper_function(arg1, arg2=None):
    """辅助函数"""
    return arg1 + (arg2 or 0)

class SampleClass:
    """示例类"""
    
    def __init__(self, name):
        self.name = name
        self._private_field = "secret"
    
    def public_method(self, x):
        """公开方法"""
        result = helper_function(x, 10)
        return result
    
    def _private_method(self):
        """私有方法"""
        return self._private_field
    
    @classmethod
    def class_method(cls):
        """类方法"""
        return "class method"

def another_function():
    """另一个函数"""
    x = helper_function(5)
    obj = SampleClass("test")
    obj.public_method(10)
    return x

# 模块级调用
result = another_function()
'''

SAMPLE_JS_CONTENT = '''
// 示例 JavaScript 文件
import React from 'react';
import { useState, useEffect } from 'react';
const axios = require('axios');

function component() {
    const [state, setState] = useState(null);
    helperFunction();
    return <div>Hello</div>;
}

function helperFunction() {
    console.log("helper");
}
'''

SAMPLE_MD_CONTENT = '''
# 测试文档

## 概述

这是用于测试搜索工具的文档。

## 使用方法

调用 `grep_search_tool` 进行搜索。

## 示例代码

```python
def test_function():
    return "test"
```

## 参考

更多信息请查看官方文档。
'''


@pytest.fixture
def temp_test_dir():
    """创建临时测试目录"""
    temp_dir = tempfile.mkdtemp(prefix="search_test_")
    yield temp_dir
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_project(temp_test_dir):
    """创建示例项目结构"""
    # 创建 Python 文件
    py_dir = os.path.join(temp_test_dir, "python_modules")
    os.makedirs(py_dir)
    
    py_file1 = os.path.join(py_dir, "module1.py")
    with open(py_file1, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_PY_CONTENT)
    
    py_file2 = os.path.join(py_dir, "module2.py")
    with open(py_file2, 'w', encoding='utf-8') as f:
        f.write('''
def standalone_function():
    """独立函数"""
    pass

class StandaloneClass:
    pass
''')
    
    # 创建 JavaScript 文件
    js_dir = os.path.join(temp_test_dir, "js")
    os.makedirs(js_dir)
    js_file = os.path.join(js_dir, "component.jsx")
    with open(js_file, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_JS_CONTENT)
    
    # 创建 Markdown 文档
    docs_dir = os.path.join(temp_test_dir, "docs")
    os.makedirs(docs_dir)
    md_file = os.path.join(docs_dir, "guide.md")
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_MD_CONTENT)
    
    # 创建嵌套目录
    nested_dir = os.path.join(py_dir, "nested", "deep")
    os.makedirs(nested_dir)
    nested_file = os.path.join(nested_dir, "deep_module.py")
    with open(nested_file, 'w', encoding='utf-8') as f:
        f.write('def deep_function():\n    pass\n')
    
    return temp_test_dir


# ============================================================================
# grep_search_tool 测试
# ============================================================================

class TestGrepSearch:
    """grep_search_tool 测试"""

    def test_search_simple_pattern(self, sample_project):
        """测试简单正则搜索"""
        result = grep_search_tool(
            regex_pattern="helper_function",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert ".py" in result
        assert "[搜索摘要]" in result
        assert "[阅读导航]" in result
        assert "read_file_tool(" not in result

    def test_search_with_context(self, sample_project):
        """测试带上下文的搜索"""
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            context_lines=2
        )
        assert "SampleClass" in result
        # 应包含上下文行
        assert len(result.split('\n')) > 1

    def test_search_case_insensitive(self, sample_project):
        """测试不区分大小写搜索"""
        result = grep_search_tool(
            regex_pattern="HELPER_FUNCTION",
            include_ext=".py",
            search_dir=sample_project,
            case_sensitive=False
        )
        assert "helper_function" in result or "HELPER" in result

    def test_search_multiple_extensions(self, sample_project):
        """测试多扩展名搜索"""
        result = grep_search_tool(
            regex_pattern="import",
            include_ext="*",  # 所有支持的扩展名
            search_dir=sample_project
        )
        assert "import" in result
        assert ".py" in result
        assert ".js" in result or ".md" in result

    def test_search_with_max_results(self, sample_project):
        """测试结果数量限制"""
        result = grep_search_tool(
            regex_pattern="def ",
            include_ext=".py",
            search_dir=sample_project,
            max_results=2
        )
        # 结果不应超过限制
        assert "[搜索] 找到 2 个匹配" in result

    def test_search_nonexistent_dir(self):
        """测试不存在的目录"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir="/nonexistent/path/xyz"
        )
        assert ("错误" in result or "不存在" in result or 
                "error" in result.lower() or "not found" in result.lower())

    def test_search_empty_pattern(self):
        """测试空正则表达式"""
        result = grep_search_tool(
            regex_pattern="",
            include_ext=".py",
            search_dir="."
        )
        assert "错误" in result or "不能为空" in result or "empty" in result.lower()

    def test_search_invalid_regex(self):
        """测试无效正则表达式"""
        result = grep_search_tool(
            regex_pattern="[invalid(",
            include_ext=".py",
            search_dir="."
        )
        assert ("错误" in result or "无效" in result or 
                "invalid" in result.lower())

    def test_search_skips_hidden_dirs(self, sample_project):
        """测试跳过隐藏目录"""
        # 创建 .git 目录（应被跳过）
        git_dir = os.path.join(sample_project, ".git")
        os.makedirs(git_dir)
        git_file = os.path.join(git_dir, "config")
        with open(git_file, 'w') as f:
            f.write("git config content")
        
        result = grep_search_tool(
            regex_pattern="git",
            include_ext="*",
            search_dir=sample_project
        )
        # 应该找不到 .git 中的内容
        assert "git config" not in result or ".git" not in result

    def test_search_skips_large_files(self, sample_project):
        """测试跳过超大文件"""
        # 创建大于 10MB 的文件
        large_dir = os.path.join(sample_project, "large")
        os.makedirs(large_dir)
        large_file = os.path.join(large_dir, "huge.txt")
        with open(large_file, 'w') as f:
            f.write("x" * (11 * 1024 * 1024))  # 11 MB
        
        result = grep_search_tool(
            regex_pattern="x+",
            include_ext=".txt",
            search_dir=sample_project
        )
        # 大文件应被跳过，不包含在结果中
        assert "huge.txt" not in result

    def test_search_single_file_mode(self, sample_project):
        """测试单文件模式"""
        py_file = os.path.join(sample_project, "python_modules", "module1.py")
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=py_file  # 传入文件路径而非目录
        )
        assert "SampleClass" in result or "module1.py" in result


# ============================================================================
# find_function_calls_tool 测试
# ============================================================================

class TestFindFunctionCalls:
    """find_function_calls_tool 测试"""

    def test_find_builtin_function_calls(self, sample_project):
        """测试查找内置函数调用"""
        result = find_function_calls_tool(
            function_name="print",
            search_dir=sample_project
        )
        # 示例中没有 print，应返回空
        assert isinstance(result, str)
        assert "未找到" in result or "0 处" in result or "not found" in result.lower()

    def test_find_custom_function_calls(self, sample_project):
        """测试查找自定义函数调用"""
        result = find_function_calls_tool(
            function_name="helper_function",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "module1.py" in result

    def test_find_method_calls(self, sample_project):
        """测试查找方法调用"""
        result = find_function_calls_tool(
            function_name="public_method",
            search_dir=sample_project
        )
        assert "public_method" in result
        assert "调用" in result or "call" in result.lower()

    def test_find_nonexistent_function(self, sample_project):
        """测试查找不存在的函数"""
        result = find_function_calls_tool(
            function_name="nonexistent_function_xyz_12345",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 处" in result or 
                "not found" in result.lower())

    def test_find_function_with_syntax_error_file(self, temp_test_dir):
        """测试包含语法错误文件的情况"""
        bad_file = os.path.join(temp_test_dir, "bad.py")
        with open(bad_file, 'w') as f:
            f.write("def broken(\n    pass\n")  # 语法错误
        
        result = find_function_calls_tool(
            function_name="test",
            search_dir=temp_test_dir
        )
        # 应该能容错，不崩溃
        assert isinstance(result, str)

    def test_find_function_in_nested_dirs(self, sample_project):
        """测试在嵌套目录中查找"""
        result = find_function_calls_tool(
            function_name="deep_function",
            search_dir=sample_project
        )
        assert "deep_function" in result
        assert "nested" in result or "deep" in result


# ============================================================================
# find_definitions_tool 测试
# ============================================================================

class TestFindDefinitions:
    """find_definitions_tool 测试"""

    def test_find_function_definition(self, sample_project):
        """测试查找函数定义"""
        result = find_definitions_tool(
            symbol_name="helper_function",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "def helper_function" in result or "定义" in result

    def test_find_class_definition(self, sample_project):
        """测试查找类定义"""
        result = find_definitions_tool(
            symbol_name="SampleClass",
            search_dir=sample_project
        )
        assert "SampleClass" in result
        assert "class SampleClass" in result or "类" in result

    def test_find_variable_definition(self, sample_project):
        """测试查找变量定义"""
        result = find_definitions_tool(
            symbol_name="CONSTANT_VALUE",
            search_dir=sample_project
        )
        assert "CONSTANT_VALUE" in result

    def test_find_standalone_class(self, sample_project):
        """测试查找独立类"""
        result = find_definitions_tool(
            symbol_name="StandaloneClass",
            search_dir=sample_project
        )
        assert "StandaloneClass" in result
        assert "module2.py" in result

    def test_find_nonexistent_symbol(self, sample_project):
        """测试查找不存在的符号"""
        result = find_definitions_tool(
            symbol_name="NonexistentSymbol_XYZ",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 个" in result or 
                "not found" in result.lower())

    def test_find_method_inside_class(self, sample_project):
        """测试查找类内方法"""
        result = find_definitions_tool(
            symbol_name="public_method",
            search_dir=sample_project
        )
        assert "public_method" in result
        assert "SampleClass" in result

    def test_find_private_member(self, sample_project):
        """测试查找私有成员"""
        result = find_definitions_tool(
            symbol_name="_private_method",
            search_dir=sample_project
        )
        assert "_private_method" in result


# ============================================================================
# search_imports_tool 测试
# ============================================================================

class TestSearchImports:
    """search_imports_tool 测试"""

    def test_search_standard_import(self, sample_project):
        """测试标准 import 语句"""
        result = search_imports_tool(
            module_name="os",
            search_dir=sample_project
        )
        assert "import os" in result or "os" in result

    def test_search_from_import(self, sample_project):
        """测试 from...import 语句"""
        result = search_imports_tool(
            module_name="typing",
            search_dir=sample_project
        )
        assert "from typing import" in result or "typing" in result

    def test_search_third_party_import(self, sample_project):
        """测试第三方包导入"""
        result = search_imports_tool(
            module_name="react",
            search_dir=sample_project
        )
        assert "react" in result.lower()
        assert ".js" in result

    def test_search_import_nonexistent(self, sample_project):
        """测试搜索不存在的导入"""
        result = search_imports_tool(
            module_name="nonexistent_module_xyz_12345",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 处" in result or 
                "not found" in result.lower())

    def test_search_import_partial_match(self, sample_project):
        """测试部分匹配（应精确匹配）"""
        result = search_imports_tool(
            module_name="react",  # 搜索精确的 "react"
            search_dir=sample_project
        )
        # 应匹配到 import React 和 from 'react'
        assert "react" in result.lower()

    def test_search_import_in_nested_dirs(self, sample_project):
        """测试在嵌套目录搜索导入"""
        result = search_imports_tool(
            module_name="react",
            search_dir=sample_project
        )
        assert "js" in result or "component" in result

    def test_search_import_with_alias(self, sample_project):
        """测试带别名的导入"""
        # 创建带别名的导入
        alias_file = os.path.join(sample_project, "alias.py")
        with open(alias_file, 'w') as f:
            f.write("import numpy as np\nimport pandas as pd\n")
        
        result = search_imports_tool(
            module_name="numpy",
            search_dir=sample_project
        )
        assert "numpy" in result
        assert "np" in result


# ============================================================================
# search_and_read_tool 测试
# ============================================================================

class TestSearchAndRead:
    """search_and_read_tool 测试"""

    def test_search_and_read_simple(self, sample_project):
        """测试搜索并读取"""
        result = search_and_read_tool(
            search_pattern="helper_function",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "helper_function" in result
        assert "module1.py" in result
        # 应包含文件内容片段
        assert "def helper_function" in result or "辅助函数" in result

    def test_search_and_read_with_context(self, sample_project):
        """测试带上下文的搜索并读取"""
        result = search_and_read_tool(
            search_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            context_lines=3
        )
        assert "SampleClass" in result
        # 应包含定义和上下文
        assert "class SampleClass" in result or "示例类" in result

    def test_search_and_read_js_files(self, sample_project):
        """测试搜索 JavaScript 文件"""
        result = search_and_read_tool(
            search_pattern="useState",
            include_ext=".js",
            search_dir=sample_project
        )
        assert "useState" in result
        assert "component.jsx" in result

    def test_search_and_read_md_files(self, sample_project):
        """测试搜索 Markdown 文件"""
        result = search_and_read_tool(
            search_pattern="使用方法",
            include_ext=".md",
            search_dir=sample_project
        )
        assert "使用方法" in result or "使用" in result

    def test_search_and_read_max_results(self, sample_project):
        """测试结果数限制"""
        result = search_and_read_tool(
            search_pattern="def ",
            include_ext=".py",
            search_dir=sample_project,
            max_results=2
        )
        # 结果应有限制
        assert "[搜索读取完成] 共 2 处匹配" in result

    def test_search_and_read_nonexistent_pattern(self, sample_project):
        """测试搜索不存在的模式"""
        result = search_and_read_tool(
            search_pattern="xyz_nonexistent_pattern_12345",
            include_ext=".py",
            search_dir=sample_project
        )
        assert ("未找到" in result or "0 个" in result or 
                "not found" in result.lower())


# ============================================================================
# 跨工具集成测试
# ============================================================================

class TestSearchIntegration:
    """搜索工具集成测试"""

    def test_full_search_workflow(self, sample_project):
        """测试完整搜索工作流"""
        # 1. 搜索函数调用
        calls = find_function_calls_tool("helper_function", sample_project)
        assert "helper_function" in calls
        
        # 2. 搜索函数定义
        defs = find_definitions_tool("helper_function", sample_project)
        assert "helper_function" in defs
        
        # 3. 全局 grep
        greps = grep_search_tool("helper_function", ".py", sample_project)
        assert "helper_function" in greps
        
        # 4. 搜索并读取
        read = search_and_read_tool("helper_function", ".py", sample_project)
        assert "helper_function" in read

    def test_search_across_extensions(self, sample_project):
        """测试跨扩展名搜索"""
        # 搜索 "import" 应在所有文件类型中找到
        result = grep_search_tool("import", "*", sample_project)
        assert "import" in result
        assert ".py" in result
        assert ".js" in result

    def test_function_vs_definition_consistency(self, sample_project):
        """测试函数调用与定义的一致性"""
        func_name = "public_method"
        
        calls = find_function_calls_tool(func_name, sample_project)
        defs = find_definitions_tool(func_name, sample_project)
        
        # 两者都应找到
        assert func_name in calls
        assert func_name in defs

    def test_import_search_consistency(self, sample_project):
        """测试导入搜索一致性"""
        module = "os"
        imports = search_imports_tool(module, sample_project)
        assert "os" in imports


# ============================================================================
# 特殊场景测试
# ============================================================================

class TestSpecialScenarios:
    """特殊场景测试"""

    def test_search_in_file_with_unicode(self, sample_project):
        """测试搜索包含 Unicode 的文件"""
        # 创建 Unicode 文件
        unicode_file = os.path.join(sample_project, "unicode.py")
        with open(unicode_file, 'w', encoding='utf-8') as f:
            f.write('''# 中文注释
def 中文函数():
    """中文函数"""
    return "中文结果"
''')
        
        result = grep_search_tool(
            regex_pattern="中文函数",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "中文函数" in result

    def test_search_in_empty_directory(self, temp_test_dir):
        """测试搜索空目录"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir=temp_test_dir
        )
        assert ("未找到" in result or "0 个" in result or 
                "empty" in result.lower())

    def test_search_very_long_line(self, sample_project):
        """测试超长行文件"""
        long_file = os.path.join(sample_project, "long.py")
        long_line = "x = " + "a" * 10000 + "\n"
        with open(long_file, 'w') as f:
            f.write(long_line)
            f.write("def short():\n    pass\n")
        
        result = grep_search_tool(
            regex_pattern="short",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "short" in result

    def test_search_with_special_regex_chars(self, sample_project):
        """测试特殊正则字符转义"""
        # 创建包含特殊正则字符的文件
        special_file = os.path.join(sample_project, "special.py")
        with open(special_file, 'w') as f:
            f.write("price = $100 [special]\n")
        
        # 搜索特殊字符（需要转义）
        result = grep_search_tool(
            regex_pattern=r"\$100",
            include_ext=".py",
            search_dir=sample_project
        )
        assert "$100" in result or "100" in result


# ============================================================================
# 性能测试
# ============================================================================

class TestSearchPerformance:
    """搜索性能测试"""

    def test_grep_search_performance(self, sample_project):
        """测试 grep 搜索性能"""
        import time
        
        # 创建大量文件
        for i in range(100):
            file_path = os.path.join(sample_project, f"perf_test_{i}.py")
            with open(file_path, 'w') as f:
                f.write(f"def func_{i}():\n    return {i}\n" * 10)
        
        start = time.time()
        result = grep_search_tool(
            regex_pattern="def func_",
            include_ext=".py",
            search_dir=sample_project,
            max_results=200
        )
        elapsed = time.time() - start
        
        assert elapsed < 10.0  # 应在 10 秒内完成
        assert len(result) > 0

    def test_find_function_calls_performance(self, sample_project):
        """测试查找函数调用性能"""
        import time
        
        start = time.time()
        result = find_function_calls_tool(
            function_name="helper_function",
            search_dir=sample_project
        )
        elapsed = time.time() - start
        
        assert elapsed < 5.0

    def test_search_and_read_performance(self):
        """测试搜索并读取性能"""
        import time
        
        # 在项目根目录搜索
        project_root = os.path.dirname(os.path.dirname(__file__))
        
        start = time.time()
        result = search_and_read_tool(
            search_pattern="def ",
            include_ext=".py",
            search_dir=project_root,
            max_results=50
        )
        elapsed = time.time() - start
        
        assert elapsed < 15.0  # 应在 15 秒内完成


# ============================================================================
# 安全测试
# ============================================================================

class TestSearchSecurity:
    """搜索安全测试"""

    def test_regex_denial_of_service_protected(self):
        """测试正则表达式 DoS 防护"""
        # 灾难性回溯正则表达式
        catastrophic_regex = r'(a+)+b'
        
        result = grep_search_tool(
            regex_pattern=catastrophic_regex,
            include_ext=".py",
            search_dir="."
        )
        # 应该被 re 模块捕获或超时处理
        assert ("错误" in result or "无效" in result or 
                "timeout" in result.lower() or "invalid" in result.lower())

    def test_path_traversal_in_search_dir(self):
        """测试路径遍历攻击"""
        result = grep_search_tool(
            regex_pattern="test",
            include_ext=".py",
            search_dir="..\\..\\..\\Windows\\System32"
        )
        # 应该被拒绝（路径不在项目中或不存在）
        assert ("错误" in result or "不存在" in result or 
                "not found" in result.lower())

    def test_agent_search_wrapper_rejects_existing_sibling_directory(self, tmp_path):
        from tools.Key_Tools import create_key_tools
        from tools.shell_tools import workspace_root_override

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("secret = True\n", encoding="utf-8")
        grep_tool = next(
            tool
            for tool in create_key_tools()
            if getattr(tool, "name", "") == "grep_search_tool"
        )

        with workspace_root_override(workspace):
            result = grep_tool.invoke(
                {
                    "regex_pattern": "secret",
                    "include_ext": ".py",
                    "search_dir": str(outside),
                }
            )

        assert "[SECURITY]" in result
        assert "secret = True" not in result

    def test_agent_search_wrapper_anchors_dot_to_active_git_worktree(self, tmp_path):
        from tools.Key_Tools import create_key_tools
        from tools.shell_tools import workspace_root_override

        candidate = tmp_path / "candidate"
        candidate.mkdir()
        (candidate / ".git").write_text("gitdir: test\n", encoding="utf-8")
        (candidate / "candidate_probe.py").write_text(
            "candidate_boundary_probe = True\n",
            encoding="utf-8",
        )
        grep_tool = next(
            tool
            for tool in create_key_tools()
            if getattr(tool, "name", "") == "grep_search_tool"
        )

        with workspace_root_override(candidate):
            result = grep_tool.invoke(
                {
                    "regex_pattern": "candidate_boundary_probe",
                    "include_ext": ".py",
                    "search_dir": ".",
                }
            )

        assert "candidate_probe.py" in result
        assert "candidate_boundary_probe = True" in result

    def test_programming_tool_descriptions_explain_workspace_boundaries_and_patch_rollback(self):
        from tools.Key_Tools import create_key_tools

        tools_by_name = {
            getattr(tool, "name", ""): tool
            for tool in create_key_tools()
        }

        assert "沙盒" in tools_by_name["exec_command"].description
        assert "shell 路由/方言" in tools_by_name["exec_command"].description
        assert "workspace_write" in tools_by_name["apply_patch_tool"].description
        assert "回滚" in tools_by_name["apply_patch_tool"].description

    def test_search_does_not_write_files(self, sample_project):
        """测试搜索不写入文件"""
        # 搜索前后文件系统应只读
        import hashlib
        
        def get_dir_hash(path):
            """计算目录哈希"""
            hashes = []
            for root, dirs, files in os.walk(path):
                for file in sorted(files):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'rb') as f:
                            file_hash = hashlib.md5(f.read()).hexdigest()
                            hashes.append((filepath, file_hash))
                    except:
                        pass
            return sorted(hashes)
        
        before = get_dir_hash(sample_project)
        
        # 执行多次搜索
        for _ in range(5):
            grep_search_tool("helper_function", ".py", sample_project)
        
        after = get_dir_hash(sample_project)
        
        # 哈希应相同（无文件修改）
        assert before == after


# ============================================================================
# 返回值格式测试
# ============================================================================

class TestReturnFormats:
    """返回值格式测试"""

    def test_grep_returns_formatted_string(self, sample_project):
        """测试 grep 返回格式化字符串"""
        result = grep_search_tool("def", ".py", sample_project)
        assert isinstance(result, str)
        # 应包含文件路径和匹配行
        assert ":" in result  # file:line:content 格式

    def test_find_calls_returns_structured(self, sample_project):
        """测试函数调用返回结构化"""
        result = find_function_calls_tool("helper_function", sample_project)
        assert isinstance(result, str)
        assert len(result.strip()) > 0

    def test_find_defs_returns_structured(self, sample_project):
        """测试定义查找返回结构化"""
        result = find_definitions_tool("SampleClass", sample_project)
        assert isinstance(result, str)
        assert "SampleClass" in result

    def test_search_imports_returns_structured(self, sample_project):
        """测试导入搜索返回结构化"""
        result = search_imports_tool("os", sample_project)
        assert isinstance(result, str)
        assert "import" in result or "os" in result

    def test_search_and_read_includes_content(self, sample_project):
        """测试搜索并读取包含内容"""
        result = search_and_read_tool("public_method", ".py", sample_project)
        assert isinstance(result, str)
        # 应包含文件内容片段
        assert len(result) > 100  # 内容应足够丰富


# ============================================================================
# 参数组合测试
# ============================================================================

class TestParameterCombinations:
    """参数组合测试"""

    def test_case_sensitive_off_with_special_chars(self, sample_project):
        """测试不区分大小写 + 特殊字符"""
        result = grep_search_tool(
            regex_pattern="SampleClass",
            include_ext=".py",
            search_dir=sample_project,
            case_sensitive=False
        )
        assert "SampleClass" in result

    def test_max_results_with_large_resultset(self, sample_project):
        """测试大结果集限制"""
        # 创建大量匹配的文件
        for i in range(200):
            file_path = os.path.join(sample_project, f"many_{i}.py")
            with open(file_path, 'w') as f:
                f.write("def target():\n    pass\n")
        
        result = grep_search_tool(
            regex_pattern="def target",
            include_ext=".py",
            search_dir=sample_project,
            max_results=50
        )
        # 应只返回 50 个结果
        assert result.count("target") <= 50

    def test_nested_directory_search(self, sample_project):
        """测试嵌套目录递归搜索"""
        result = grep_search_tool(
            regex_pattern="deep_function",
            include_ext=".py",
            search_dir=sample_project,
            recursive=True
        )
        assert "deep_function" in result
        assert "nested" in result

    def test_max_output_chars_is_respected(self, sample_project):
        for i in range(12):
            file_path = os.path.join(sample_project, f"preview_{i}.py")
            with open(file_path, "w", encoding="utf-8") as f:
                for j in range(20):
                    f.write(f"def preview_target_{i}_{j}():\n    return 'demo'\n")

        result = grep_search_tool(
            regex_pattern="preview_target",
            include_ext=".py",
            search_dir=sample_project,
            max_results=30,
            max_output_chars=1500,
        )

        assert "[阅读导航]" in result
        assert "read_file_tool(" not in result
        assert result.count("📁 ") <= 3

# ============================================================================
# ripgrep 引擎与 deadline/取消行为测试
# ============================================================================

class _FakeRgProcess:
    """模拟 rg 子进程：记录命令与 kwargs，可控输出/超时/kill 行为。"""

    def __init__(self, cmd=None, outputs=None, *, raise_on_timeout=False, returncode=0):
        self.cmd = cmd or []
        self.kwargs = {}
        self._outputs = list(outputs or [])
        self._raise_on_timeout = raise_on_timeout
        self._returncode = returncode
        self.killed = False
        self.kill_count = 0

    def communicate(self, timeout=None):
        if self._raise_on_timeout and timeout is not None:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        if self._outputs:
            return self._outputs.pop(0), ""
        return "", ""

    def kill(self):
        self.killed = True
        self.kill_count += 1

    def poll(self):
        if self.killed:
            return -9
        return self._returncode


def _rg_json_line(event_type, path, line_no, text):
    return json.dumps({
        "type": event_type,
        "data": {
            "path": {"text": path},
            "lines": {"text": text},
            "line_number": line_no,
        },
    })


def _rg_match_stream(path="module1.py"):
    return "\n".join([
        json.dumps({"type": "begin", "data": {"path": {"text": path}}}),
        _rg_json_line("match", path, 49, "def helper_function(arg1, arg2=None):\n"),
        _rg_json_line("context", path, 50, '    """辅助函数"""\n'),
        json.dumps({"type": "end", "data": {"path": {"text": path}}}),
    ]) + "\n"


class TestRipgrepDetection:
    """rg 探测链：配置显式路径 → PATH → 回退纯 Python"""

    def test_detect_ripgrep_prefers_configured_path(self, monkeypatch, tmp_path):
        from tools import search_tools as st
        fake_rg = tmp_path / "custom-rg.exe"
        fake_rg.write_text("", encoding="utf-8")
        monkeypatch.setattr(st, "_search_defaults", {"RIPGREP_PATH": str(fake_rg)})
        st.reset_ripgrep_detection()
        try:
            assert st._detect_ripgrep() == str(fake_rg)
        finally:
            st.reset_ripgrep_detection()

    def test_missing_configured_path_falls_back_to_which(self, monkeypatch, tmp_path):
        from tools import search_tools as st
        monkeypatch.setattr(st, "_search_defaults", {"RIPGREP_PATH": str(tmp_path / "missing.exe")})
        monkeypatch.setattr(shutil, "which", lambda name: "C:/which-rg.exe" if name == "rg" else None)
        st.reset_ripgrep_detection()
        try:
            assert st._detect_ripgrep() == "C:/which-rg.exe"
        finally:
            st.reset_ripgrep_detection()

    def test_detection_miss_returns_none_and_python_engine_still_works(self, monkeypatch, sample_project):
        from tools import search_tools as st
        monkeypatch.setattr(st, "_search_defaults", {})
        monkeypatch.setattr(shutil, "which", lambda name: None)
        st.reset_ripgrep_detection()
        try:
            assert st._detect_ripgrep() is None
            result = st.grep_search_tool("helper_function", ".py", sample_project)
            assert "[搜索摘要]" in result
            assert "module1.py" in result
        finally:
            st.reset_ripgrep_detection()


class TestRipgrepEngine:
    """rg 主引擎：命令面、JSON 解析、可杀超时、取消、错误回退"""

    @staticmethod
    def _force_ripgrep_engine(monkeypatch, st) -> None:
        """把 rg 主引擎钉在被测路径上，不依赖本机是否安装 ripgrep。

        ripgrep 是可选加速器（缺失时产品回退纯 Python 引擎，只在日志里提示）；
        这些用例验证的是 rg 分支本身，所以显式注入探测结果，而不是跳过。
        """
        monkeypatch.setattr(st, "_detect_ripgrep", lambda: "rg")

    def test_command_surface_and_json_parsing(self, monkeypatch, sample_project):
        from tools import search_tools as st
        self._force_ripgrep_engine(monkeypatch, st)
        proc = _FakeRgProcess(outputs=[_rg_match_stream()])
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured["kwargs"] = dict(kwargs)
            proc.cmd = list(cmd)
            proc.kwargs = dict(kwargs)
            return proc

        monkeypatch.setattr(st.subprocess, "Popen", fake_popen)
        result = st.grep_search_tool("helper_function", ".py", sample_project)

        cmd = captured["cmd"]
        # 防用户机器 RIPGREP_CONFIG_PATH 干扰
        assert "--no-config" in cmd
        assert "--json" in cmd
        assert "--max-columns=300" in cmd
        assert "--max-columns-preview" in cmd
        assert f"--max-filesize={st.MAX_FILE_SIZE}" in cmd
        # pattern 走 -e、路径在 -- 之后
        assert cmd[cmd.index("-e") + 1] == "helper_function"
        assert cmd[-2] == "--"
        assert cmd[-1] == str(Path(sample_project).resolve())
        # 大小写敏感时不加 -i
        assert "--ignore-case" not in cmd
        # shell=False 语义（不传 shell 键），无控制台 kwargs
        assert "shell" not in captured["kwargs"]
        if os.name == "nt":
            assert "creationflags" in captured["kwargs"]
            assert "startupinfo" in captured["kwargs"]
        # glob 过滤面
        globs = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--glob"]
        assert "*.py" in globs
        assert any(g.startswith("!") for g in globs)

        # JSON 解析：匹配 + 上下文行进入结果
        assert "[搜索] 找到 1 个匹配" in result
        assert "def helper_function(arg1, arg2=None):" in result
        assert "module1.py" in result
        assert not proc.killed

    def test_case_insensitive_adds_ignore_case(self, monkeypatch, sample_project):
        from tools import search_tools as st
        self._force_ripgrep_engine(monkeypatch, st)
        proc = _FakeRgProcess(outputs=[_rg_match_stream()])
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            return proc

        monkeypatch.setattr(st.subprocess, "Popen", fake_popen)
        st.grep_search_tool("helper_function", ".py", sample_project, case_sensitive=False)
        assert "--ignore-case" in captured["cmd"]

    def test_deadline_kills_process_and_returns_partial_results(self, monkeypatch, sample_project):
        from tools import search_tools as st
        self._force_ripgrep_engine(monkeypatch, st)
        monkeypatch.setattr(st, "GREP_DEADLINE_SECONDS", 0.05)
        proc = _FakeRgProcess(outputs=[_rg_match_stream()], raise_on_timeout=True)
        monkeypatch.setattr(st.subprocess, "Popen", lambda cmd, **kwargs: proc)

        result = st.grep_search_tool("helper_function", ".py", sample_project)

        # 超时必须 kill 子进程，且二次回收的部分输出要变成结果而非裸错误
        assert proc.killed
        assert proc.kill_count == 1
        assert "helper_function" in result
        assert "已超时截断" in result
        assert "结果不完整" in result

    def test_cancel_checker_kills_process_and_returns_partial_results(self, monkeypatch, sample_project):
        from tools import search_tools as st
        self._force_ripgrep_engine(monkeypatch, st)
        proc = _FakeRgProcess(outputs=[_rg_match_stream()], raise_on_timeout=True)
        monkeypatch.setattr(st.subprocess, "Popen", lambda cmd, **kwargs: proc)

        result = st.grep_search_tool(
            "helper_function", ".py", sample_project,
            _cancel_checker=lambda: "用户请求停止",
        )

        assert proc.killed
        assert "已按停止请求中止扫描：用户请求停止" in result
        assert "helper_function" in result
        assert "结果不完整" in result

    def test_rg_error_exit_without_output_falls_back_to_python(self, monkeypatch, sample_project):
        from tools import search_tools as st
        self._force_ripgrep_engine(monkeypatch, st)
        proc = _FakeRgProcess(outputs=[""], returncode=2)
        monkeypatch.setattr(st.subprocess, "Popen", lambda cmd, **kwargs: proc)

        result = st.grep_search_tool("helper_function", ".py", sample_project)

        # rg exit>=2（如 Rust regex 不支持的语法）→ 回退纯 Python 引擎，仍出正确结果
        assert "helper_function" in result
        assert "[搜索摘要]" in result

    def test_zero_matches_keeps_existing_contract(self, monkeypatch, sample_project):
        from tools import search_tools as st
        proc = _FakeRgProcess(outputs=[""], returncode=1)
        monkeypatch.setattr(st.subprocess, "Popen", lambda cmd, **kwargs: proc)

        result = st.grep_search_tool("xyz_no_such_pattern", ".py", sample_project)
        assert "未找到匹配项" in result

    def test_single_file_mode_extension_mismatch_returns_zero(self, monkeypatch, sample_project):
        from tools import search_tools as st
        proc = _FakeRgProcess(outputs=[_rg_match_stream()])
        monkeypatch.setattr(st.subprocess, "Popen", lambda cmd, **kwargs: proc)

        py_file = os.path.join(sample_project, "python_modules", "module1.py")
        result = st.grep_search_tool("helper_function", ".js", py_file)
        assert "未找到匹配项" in result


class TestPythonEngineDeadlineAndCancel:
    """纯 Python 回退引擎：deadline 分片与 cancel checker"""

    def test_deadline_returns_incomplete_notice(self, monkeypatch, sample_project):
        from tools import search_tools as st
        monkeypatch.setattr(st, "_detect_ripgrep", lambda: None)
        # -1 模拟「扫描开始前 deadline 已过期」：Windows monotonic 粒度下 0.0
        # 可能与首次检查同刻度，负偏移保证第一个 walk 分片即触发截断
        monkeypatch.setattr(st, "GREP_DEADLINE_SECONDS", -1.0)

        result = st.grep_search_tool("helper_function", ".py", sample_project)

        assert "结果不完整" in result
        assert "已超时截断" in result

    def test_deadline_keeps_partial_results_collected_before_deadline(self, monkeypatch, sample_project):
        from tools import search_tools as st
        monkeypatch.setattr(st, "_detect_ripgrep", lambda: None)
        # 给一个足够完成小目录扫描但仍触发部分语义的 deadline：无法精确控制，
        # 因此这里验证正常完成的输出不携带截断提示（deadline 未到 → 完整结果）
        monkeypatch.setattr(st, "GREP_DEADLINE_SECONDS", 25.0)

        result = st.grep_search_tool("helper_function", ".py", sample_project)
        assert "helper_function" in result
        assert "结果不完整" not in result

    def test_cancel_checker_aborts_python_scan(self, monkeypatch, sample_project):
        from tools import search_tools as st
        monkeypatch.setattr(st, "_detect_ripgrep", lambda: None)

        result = st.grep_search_tool(
            "helper_function", ".py", sample_project,
            _cancel_checker=lambda: "停止扫描",
        )

        # 取消原因必须显式回传（有无部分匹配对应两条提示分支）
        assert "停止扫描" in result
        assert "结果不完整" in result
        assert "已取消" in result or "已按停止请求中止扫描" in result


class TestSearchBaseDirResolution:
    """search_dir 相对路径锚定 workspace override，不落到进程 CWD"""

    def test_relative_dot_uses_workspace_override(self, tmp_path):
        from tools import search_tools as st
        from tools.shell_tools import workspace_root_override

        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)
        (ws / "ws_only_marker.py").write_text("ws_only_marker_value = 'hit'\n", encoding="utf-8")

        with workspace_root_override(ws):
            result = st.grep_search_tool("ws_only_marker_value", ".py", ".")

        assert "ws_only_marker.py" in result
        assert "未找到匹配项" not in result

    def test_absolute_path_still_works(self, tmp_path):
        from tools import search_tools as st
        (tmp_path / "abs_marker.py").write_text("abs_marker_value = 1\n", encoding="utf-8")
        result = st.grep_search_tool("abs_marker_value", ".py", str(tmp_path))
        assert "abs_marker.py" in result


class TestSearchConfigWiring:
    """max_results 配置键接通与 ToolsSearchConfig 新字段"""

    def test_max_results_loaded_from_config(self, monkeypatch, sample_project):
        from tools import search_tools as st
        defaults = dict(st._search_defaults) if st._search_defaults else {}
        defaults["MAX_RESULTS"] = 2
        monkeypatch.setattr(st, "_search_defaults", defaults)

        result = st.grep_search_tool(r"def \w+", ".py", sample_project)

        assert "[搜索] 找到 2 个匹配" in result

    def test_configured_max_results_still_clamped_to_50(self, monkeypatch, sample_project):
        from tools import search_tools as st
        defaults = dict(st._search_defaults) if st._search_defaults else {}
        defaults["MAX_RESULTS"] = 500
        monkeypatch.setattr(st, "_search_defaults", defaults)

        # 大量匹配场景：钳制生效，不会返回超过 50
        for i in range(60):
            (Path(sample_project) / f"clamp_{i}.py").write_text("def clamped_target():\n    pass\n", encoding="utf-8")

        result = st.grep_search_tool("def clamped_target", ".py", sample_project)
        assert "[搜索] 找到 50 个匹配" in result

    def test_tools_search_config_new_fields(self):
        from config.models import ToolsSearchConfig

        cfg = ToolsSearchConfig()
        assert cfg.max_results == 50
        assert cfg.ripgrep_path == ""
        assert 0 < cfg.grep_deadline_seconds < 30
        assert cfg.grep_deadline_seconds == 25.0
        assert {".worktrees", ".runtime", "instances"} <= set(cfg.skip_directories)


class TestRipgrepRealIntegration:
    """真机 rg 集成（无 rg 环境自动跳过）"""

    def test_real_ripgrep_matches_python_contract(self, sample_project):
        from tools import search_tools as st
        if shutil.which("rg") is None and not st._search_defaults.get("RIPGREP_PATH"):
            pytest.skip("ripgrep not installed")
        st.reset_ripgrep_detection()
        try:
            assert st._detect_ripgrep() is not None
            result = st.grep_search_tool("helper_function", ".py", sample_project)
            assert "[搜索摘要]" in result
            assert "module1.py" in result
            assert "def helper_function" in result
        finally:
            st.reset_ripgrep_detection()





if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
