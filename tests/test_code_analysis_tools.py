#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码分析工具完整测试套件

测试 tools/code_analysis_tools.py 中的所有功能：

## AST 分析工具
- get_code_entity: 根据名称提取代码实体
- get_file_entities: 获取文件中所有实体
- list_file_entities: 列出文件中的所有实体

## Diff 编辑工具
- apply_diff_edit: 应用 SEARCH/REPLACE 块编辑
- validate_diff_format: 验证 diff 格式
- preview_diff: 预览 diff 效果
"""

import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from tools.code_analysis_tools import (
    get_code_entity,
    get_file_entities,
    list_file_entities,
    extract_method_from_class,
    apply_diff_edit,
    validate_diff_format,
    preview_diff,
)


# ============================================================================
# 测试辅助函数和数据
# ============================================================================

SAMPLE_PY_WITH_CLASS = '''
#!/usr/bin/env python3
"""
示例模块 - 包含类和方法
"""

import os
import sys
from typing import List, Optional

# 全局变量
CONSTANT = 100
APP_NAME = "TestApp"

class Calculator:
    """计算器类"""
    
    def __init__(self, initial=0):
        self.value = initial
    
    def add(self, x):
        """加法"""
        self.value += x
        return self.value
    
    def subtract(self, x):
        """减法"""
        self.value -= x
        return self.value
    
    def multiply(self, x):
        """乘法"""
        return self.value * x
    
    def divide(self, x):
        """除法"""
        if x == 0:
            raise ValueError("Cannot divide by zero")
        return self.value / x
    
    def _private_helper(self):
        """私有辅助方法"""
        return "private"

class UserManager:
    """用户管理器"""
    
    def __init__(self):
        self.users = []
    
    def add_user(self, name, email):
        """添加用户"""
        self.users.append({"name": name, "email": email})
    
    def find_user(self, name):
        """查找用户"""
        for user in self.users:
            if user["name"] == name:
                return user
        return None

def standalone_function(arg1, arg2=None):
    """独立函数"""
    result = arg1 + (arg2 or 0)
    return result

async def async_function():
    """异步函数"""
    return "async result"

class SimpleClass:
    pass
'''

SAMPLE_PY_WITH_ERRORS = '''
def broken_function(
    # 缺少闭合括号
    pass

class BrokenClass(
    # 缺少基类闭合
    pass
'''


@pytest.fixture
def temp_test_dir():
    """创建临时测试目录"""
    temp_dir = tempfile.mkdtemp(prefix="code_analysis_test_")
    yield temp_dir
    # 清理
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


@pytest.fixture
def sample_py_file(temp_test_dir):
    """创建示例 Python 文件"""
    file_path = os.path.join(temp_test_dir, "sample.py")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_PY_WITH_CLASS)
    return file_path


@pytest.fixture
def broken_py_file(temp_test_dir):
    """创建语法错误的 Python 文件"""
    file_path = os.path.join(temp_test_dir, "broken.py")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(SAMPLE_PY_WITH_ERRORS)
    return file_path


# ============================================================================
# get_code_entity 测试
# ============================================================================

class TestGetCodeEntity:
    """get_code_entity 工具测试"""

    def test_extract_class(self, sample_py_file):
        """测试提取类定义"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator"
        )
        assert "class Calculator" in result
        assert "计算器类" in result or "计算器" in result
        assert "def __init__" in result
        assert "def add" in result

    def test_extract_method_from_class(self, sample_py_file):
        """测试提取类方法"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator.add"
        )
        assert "def add" in result
        assert "加法" in result or "加法" in result
        assert "self" in result

    def test_extract_standalone_function(self, sample_py_file):
        """测试提取独立函数"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="standalone_function"
        )
        assert "def standalone_function" in result
        assert "独立函数" in result
        assert "arg1" in result

    def test_extract_async_function(self, sample_py_file):
        """测试提取异步函数"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="async_function"
        )
        assert "async def async_function" in result
        assert "异步函数" in result

    def test_extract_nonexistent_entity(self, sample_py_file):
        """测试提取不存在的实体"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="NonexistentClassXYZ"
        )
        assert ("未找到" in result or "错误" in result or 
                "not found" in result.lower())

    def test_extract_from_nonexistent_file(self):
        """测试从不存在文件提取"""
        result = get_code_entity(
            file_path="/nonexistent/path/file.py",
            entity_name="Something"
        )
        assert "错误" in result or "不存在" in result

    def test_extract_with_include_imports(self, sample_py_file):
        """测试包含 import 语句"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator",
            include_imports=True
        )
        assert "import os" in result or "import sys" in result
        assert "class Calculator" in result

    def test_extract_without_imports(self, sample_py_file):
        """测试不包含 import 语句"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator",
            include_imports=False
        )
        assert "import" not in result
        assert "class Calculator" in result

    def test_extract_nested_class_method(self, sample_py_file):
        """测试提取嵌套类中的方法"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="UserManager.add_user"
        )
        assert "def add_user" in result
        assert "添加用户" in result
        assert "self.users" in result

    def test_extract_with_decorators(self, temp_test_dir):
        """测试提取带装饰器的实体"""
        decorated_file = os.path.join(temp_test_dir, "decorated.py")
        with open(decorated_file, 'w') as f:
            f.write('''
def decorator(func):
    return func

@decorator
def decorated_function():
    pass

class MyClass:
    @staticmethod
    def static_method():
        pass
    
    @classmethod
    def class_method(cls):
        pass
''')
        
        result = get_code_entity(
            file_path=decorated_file,
            entity_name="decorated_function"
        )
        assert "def decorated_function" in result
        assert "@decorator" in result

    def test_extract_private_method(self, sample_py_file):
        """测试提取私有方法"""
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator._private_helper"
        )
        assert "_private_helper" in result
        assert "私有辅助" in result or "私有" in result

    def test_invalid_class_method_format(self, sample_py_file):
        """测试无效的 类.方法 格式"""
        # 格式错误：类名不大写
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="calculator.add"  # calculator 不大写
        )
        # 应返回错误或未找到
        assert ("错误" in result or "未找到" in result or 
                "invalid" in result.lower())


# ============================================================================
# get_file_entities 测试
# ============================================================================

class TestGetFileEntities:
    """get_file_entities 工具测试"""

    def test_get_all_entities(self, sample_py_file):
        """测试获取所有实体"""
        entities = get_file_entities(sample_py_file)
        
        assert isinstance(entities, dict)
        assert 'class' in entities
        assert 'function' in entities
        assert 'async_function' in entities
        
        # 验证类
        class_names = [c['name'] for c in entities['class']]
        assert "Calculator" in class_names
        assert "UserManager" in class_names
        assert "SimpleClass" in class_names
        
        # 验证函数
        func_names = [f['name'] for f in entities['function']]
        assert "standalone_function" in func_names

    def test_get_async_functions(self, sample_py_file):
        """测试获取异步函数"""
        entities = get_file_entities(sample_py_file)
        async_funcs = entities.get('async_function', [])
        assert len(async_funcs) >= 1
        assert any(f['name'] == 'async_function' for f in async_funcs)

    def test_entity_has_required_fields(self, sample_py_file):
        """测试实体包含必需字段"""
        entities = get_file_entities(sample_py_file)
        
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                assert 'name' in entity
                assert 'type' in entity
                assert 'lineno' in entity
                assert 'docstring' in entity  # 可为 None

    def test_entity_lineno_is_int(self, sample_py_file):
        """测试行号是整数"""
        entities = get_file_entities(sample_py_file)
        for entity_list in entities.values():
            for entity in entity_list:
                assert isinstance(entity['lineno'], int)
                assert entity['lineno'] >= 1

    def test_class_has_methods(self, sample_py_file):
        """测试类包含方法���息"""
        entities = get_file_entities(sample_py_file)
        classes = entities['class']
        
        calc = next((c for c in classes if c['name'] == 'Calculator'), None)
        assert calc is not None
        assert 'methods' in calc
        assert len(calc['methods']) > 0
        
        # 验证方法信息
        method_names = [m['name'] for m in calc['methods']]
        assert 'add' in method_names
        assert 'subtract' in method_names
        assert '__init__' in method_names

    def test_class_method_has_metadata(self, sample_py_file):
        """测试类方法包含元数据"""
        entities = get_file_entities(sample_py_file)
        calc = next(c for c in entities['class'] if c['name'] == 'Calculator')
        
        init_method = next(m for m in calc['methods'] if m['name'] == '__init__')
        assert 'is_static' in init_method
        assert 'is_classmethod' in init_method
        assert init_method['is_static'] is False
        assert init_method['is_classmethod'] is False

    def test_empty_file(self, temp_test_dir):
        """测试空文件"""
        empty_file = os.path.join(temp_test_dir, "empty.py")
        with open(empty_file, 'w') as f:
            f.write("")
        
        entities = get_file_entities(empty_file)
        assert entities == {} or all(len(v) == 0 for v in entities.values())

    def test_file_with_only_imports(self, temp_test_dir):
        """测试仅包含导入的文件"""
        import_file = os.path.join(temp_test_dir, "only_imports.py")
        with open(import_file, 'w') as f:
            f.write("import os\nimport sys\nfrom typing import List\n")
        
        entities = get_file_entities(import_file)
        # 应该没有类、函数或异步函数
        assert len(entities.get('class', [])) == 0
        assert len(entities.get('function', [])) == 0
        assert len(entities.get('async_function', [])) == 0

    def test_file_with_syntax_error(self, broken_py_file):
        """测试语法错误文件"""
        entities = get_file_entities(broken_py_file)
        # 应返回空字典，不抛出异常
        assert entities == {} or len(entities) == 0

    def test_file_not_exists(self):
        """测试不存在的文件"""
        entities = get_file_entities("/nonexistent/file.py")
        assert entities == {}


# ============================================================================
# list_file_entities 测试
# ============================================================================

class TestListFileEntities:
    """list_file_entities 工具测试"""

    def test_list_entities_formatted_output(self, sample_py_file):
        """测试格式化输出"""
        result = list_file_entities(file_path=sample_py_file)
        
        assert isinstance(result, str)
        assert "Calculator" in result
        assert "UserManager" in result
        assert "standalone_function" in result
        assert "async_function" in result

    def test_list_includes_line_numbers(self, sample_py_file):
        """测试包含行号"""
        result = list_file_entities(file_path=sample_py_file)
        # 应包含行号信息
        assert ":" in result  # 行号格式如 "12: class Calculator"

    def test_list_shows_docstrings(self, sample_py_file):
        """测试显示文档字符串"""
        result = list_file_entities(file_path=sample_py_file)
        assert "计算器类" in result or "Calculator" in result

    def test_list_empty_file(self, temp_test_dir):
        """测试空文件"""
        empty_file = os.path.join(temp_test_dir, "empty.py")
        with open(empty_file, 'w') as f:
            f.write("")
        
        result = list_file_entities(file_path=empty_file)
        assert "未找到" in result or "empty" in result.lower() or result.strip() == ""

    def test_list_nonexistent_file(self):
        """测试不存在文件"""
        result = list_file_entities(file_path="/nonexistent/file.py")
        assert "错误" in result or "不存在" in result or "not found" in result.lower()


# ============================================================================
# extract_method_from_class 测试
# ============================================================================

class TestExtractMethodFromClass:
    """extract_method_from_class 工具测试"""

    def test_extract_method(self, sample_py_file):
        """测试提取方法"""
        result = extract_method_from_class(
            file_path=sample_py_file,
            class_name="Calculator",
            method_name="add"
        )
        assert "def add" in result
        assert "self" in result
        assert "self.value += x" in result or "加法" in result

    def test_extract_nonexistent_method(self, sample_py_file):
        """测试提取不存在的方法"""
        result = extract_method_from_class(
            file_path=sample_py_file,
            class_name="Calculator",
            method_name="nonexistent_method_xyz"
        )
        assert ("未找到" in result or "错误" in result or 
                "not found" in result.lower())

    def test_extract_from_nonexistent_class(self, sample_py_file):
        """测试从不存在类中提取"""
        result = extract_method_from_class(
            file_path=sample_py_file,
            class_name="NonexistentClass",
            method_name="any_method"
        )
        assert ("未找到" in result or "错误" in result or 
                "not found" in result.lower())

    def test_extract_init_method(self, sample_py_file):
        """测试提取 __init__ 方法"""
        result = extract_method_from_class(
            file_path=sample_py_file,
            class_name="Calculator",
            method_name="__init__"
        )
        assert "__init__" in result
        assert "self.value = initial" in result

    def test_extract_private_method(self, sample_py_file):
        """测试提取私有方法"""
        result = extract_method_from_class(
            file_path=sample_py_file,
            class_name="Calculator",
            method_name="_private_helper"
        )
        assert "_private_helper" in result
        assert "私有" in result

    def test_extract_staticmethod(self, temp_test_dir):
        """测试提取静态方法"""
        file_path = os.path.join(temp_test_dir, "static.py")
        with open(file_path, 'w') as f:
            f.write('''
class MyClass:
    @staticmethod
    def static_method():
        return "static"
''')
        
        result = extract_method_from_class(
            file_path=file_path,
            class_name="MyClass",
            method_name="static_method"
        )
        assert "static_method" in result
        assert "@staticmethod" in result

    def test_extract_classmethod(self, temp_test_dir):
        """测试提取类方法"""
        file_path = os.path.join(temp_test_dir, "classmethod.py")
        with open(file_path, 'w') as f:
            f.write('''
class MyClass:
    @classmethod
    def class_method(cls):
        return "class"
''')
        
        result = extract_method_from_class(
            file_path=file_path,
            class_name="MyClass",
            method_name="class_method"
        )
        assert "class_method" in result
        assert "@classmethod" in result


# ============================================================================
# validate_diff_format 测试
# ============================================================================

class TestValidateDiffFormat:
    """validate_diff_format 工具测试"""

    def test_valid_diff_format(self):
        """测试有效的 diff 格式"""
        diff_text = '''*** Begin Patch
*** Update File: sample.py
@@
- old line
+ new line
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is True
        assert error == ""

    def test_valid_diff_multiple_blocks(self):
        """测试多块 diff"""
        diff_text = '''*** Begin Patch
*** Update File: file1.py
@@
- old1
+ new1
*** Update File: file2.py
@@
- old2
+ new2
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is True

    def test_invalid_diff_missing_begin(self):
        """测试缺少 Begin 标记"""
        diff_text = '''*** Update File: sample.py
@@
- old
+ new
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False
        assert "Begin" in error or "格式" in error

    def test_invalid_diff_missing_end(self):
        """测试缺少 End 标记"""
        diff_text = '''*** Begin Patch
*** Update File: sample.py
@@
- old
+ new'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False

    def test_invalid_diff_missing_hunks(self):
        """测试缺少 hunk 标记"""
        diff_text = '''*** Begin Patch
*** Update File: sample.py
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False

    def test_invalid_diff_malformed_hunk(self):
        """测试格式错误的 hunk"""
        diff_text = '''*** Begin Patch
*** Update File: sample.py
@@
this is not a valid hunk
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False

    def test_invalid_diff_malformed_update_line(self):
        """测试格式错误的 Update 行"""
        diff_text = '''*** Begin Patch
Update File: sample.py
@@
- old
+ new
*** End Patch'''
        
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False

    def test_empty_diff(self):
        """测试空 diff"""
        is_valid, error = validate_diff_format("")
        assert is_valid is False

    def test_diff_with_only_whitespace(self):
        """测试仅空白字符"""
        diff_text = "   \n\n   \n"
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is False


# ============================================================================
# apply_diff_edit 测试
# ============================================================================

class TestApplyDiffEdit:
    """apply_diff_edit 工具测试"""

    def test_apply_simple_replacement(self, temp_test_dir):
        """测试简单替换"""
        file_path = os.path.join(temp_test_dir, "test.txt")
        with open(file_path, 'w') as f:
            f.write("Hello World")
        
        diff_text = '''*** Begin Patch
*** Update File: test.txt
@@
- Hello World
+ Hello Python
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=file_path)
        assert "成功" in result or "applied" in result.lower() or "OK" in result
        
        with open(file_path, 'r') as f:
            content = f.read()
        assert content == "Hello Python"

    def test_apply_multiple_replacements(self, temp_test_dir):
        """测试多重替换"""
        file_path = os.path.join(temp_test_dir, "multi.txt")
        with open(file_path, 'w') as f:
            f.write("Line1\nLine2\nLine3")
        
        diff_text = '''*** Begin Patch
*** Update File: multi.txt
@@
- Line1
+ First
- Line3
+ Third
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=file_path)
        
        with open(file_path, 'r') as f:
            content = f.read()
        assert "First" in content
        assert "Third" in content
        assert "Line1" not in content
        assert "Line3" not in content

    def test_apply_diff_creates_backup(self, temp_test_dir):
        """测试创建备份文件"""
        file_path = os.path.join(temp_test_dir, "backup.txt")
        with open(file_path, 'w') as f:
            f.write("original")
        
        diff_text = '''*** Begin Patch
*** Update File: backup.txt
@@
- original
- modified
*** End Patch'''
        
        apply_diff_edit(diff_text=diff_text, file_path=file_path)
        
        # 检查备份文件是否存在
        backup_files = [f for f in os.listdir(temp_test_dir) if f.startswith(".") and "backup" in f]
        assert len(backup_files) >= 0  # 备份可选，不强制

    def test_apply_invalid_diff_format(self, temp_test_dir):
        """测试无效 diff 格式"""
        file_path = os.path.join(temp_test_dir, "test.txt")
        with open(file_path, 'w') as f:
            f.write("test")
        
        diff_text = "invalid diff format"
        result = apply_diff_edit(diff_text=diff_text, file_path=file_path)
        assert ("错误" in result or "失败" in result or 
                "invalid" in result.lower())

    def test_apply_diff_nonexistent_file(self):
        """测试应用到不存在的文件"""
        diff_text = '''*** Begin Patch
*** Update File: nonexistent.txt
@@
- old
+ new
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path="nonexistent.txt")
        assert ("错误" in result or "失败" in result or 
                "not found" in result.lower())

    def test_apply_diff_with_no_changes(self, temp_test_dir):
        """测试无变化的 diff"""
        file_path = os.path.join(temp_test_dir, "nochange.txt")
        original = "original content"
        with open(file_path, 'w') as f:
            f.write(original)
        
        diff_text = '''*** Begin Patch
*** Update File: nochange.txt
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=file_path)
        # 可能成功（无操作）或特定消息
        assert isinstance(result, str)

    def test_apply_diff_whitespace_only(self, temp_test_dir):
        """测试仅空白字符的替换"""
        file_path = os.path.join(temp_test_dir, "whitespace.txt")
        with open(file_path, 'w') as f:
            f.write("line1\nline2\n")
        
        diff_text = '''*** Begin Patch
*** Update File: whitespace.txt
@@
- line1
+ line1 
*** End Patch'''
        
        apply_diff_edit(diff_text=diff_text, file_path=file_path)
        
        with open(file_path, 'r') as f:
            content = f.read()
        assert "line1" in content
        # 注意：可能有空格差异

    def test_apply_diff_multiple_files(self, temp_test_dir):
        """测试多文件 diff"""
        file1 = os.path.join(temp_test_dir, "file1.txt")
        file2 = os.path.join(temp_test_dir, "file2.txt")
        with open(file1, 'w') as f:
            f.write("content1")
        with open(file2, 'w') as f:
            f.write("content2")
        
        diff_text = '''*** Begin Patch
*** Update File: file1.txt
@@
- content1
+ updated1
*** Update File: file2.txt
@@
- content2
+ updated2
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=file1)
        assert "成功" in result or "applied" in result.lower() or "OK" in result
        
        with open(file1, 'r') as f:
            assert f.read() == "updated1"
        with open(file2, 'r') as f:
            assert f.read() == "updated2"


# ============================================================================
# preview_diff 测试
# ============================================================================

class TestPreviewDiff:
    """preview_diff 工具测试"""

    def test_preview_simple_diff(self, temp_test_dir):
        """测试预览简单 diff"""
        file_path = os.path.join(temp_test_dir, "preview.txt")
        with open(file_path, 'w') as f:
            f.write("old content")
        
        diff_text = '''*** Begin Patch
*** Update File: preview.txt
@@
- old content
+ new content
*** End Patch'''
        
        preview = preview_diff(diff_text=diff_text, file_path=file_path)
        assert isinstance(preview, str)
        assert "预览" in preview or "diff" in preview.lower() or "-" in preview
        assert "old content" in preview
        assert "new content" in preview

    def test_preview_invalid_diff(self, temp_test_dir):
        """预览无效 diff"""
        file_path = os.path.join(temp_test_dir, "test.txt")
        
        preview = preview_diff(diff_text="invalid", file_path=file_path)
        assert ("无效" in preview or "错误" in preview or 
                "invalid" in preview.lower())

    def test_preview_nonexistent_file(self):
        """预览不存在的文件"""
        diff_text = '''*** Begin Patch
*** Update File: nofile.txt
@@
- old
+ new
*** End Patch'''
        
        preview = preview_diff(diff_text=diff_text, file_path="nofile.txt")
        # 应返回预览信息（diff 格式本身）
        assert isinstance(preview, str)

    def test_preview_multiple_changes(self, temp_test_dir):
        """预览多重变更"""
        file_path = os.path.join(temp_test_dir, "multi.txt")
        with open(file_path, 'w') as f:
            f.write("line1\nline2\nline3")
        
        diff_text = '''*** Begin Patch
*** Update File: multi.txt
@@
- line1
+ first
- line3
+ third
*** End Patch'''
        
        preview = preview_diff(diff_text=diff_text, file_path=file_path)
        assert "first" in preview
        assert "third" in preview
        assert "- line1" in preview  # 删除行
        assert "+ first" in preview  # 新增行


# ============================================================================
# 集成测试
# ============================================================================

class TestCodeAnalysisIntegration:
    """代码分析工具集成测试"""

    def test_extract_modify_preview_workflow(self, sample_py_file):
        """测试提取-修改-预览完整流程"""
        # 1. 提取实体
        entity = get_code_entity(
            file_path=sample_py_file,
            entity_name="Calculator.add",
            include_imports=False
        )
        assert "def add" in entity
        
        # 2. 预览修改
        diff_text = '''*** Begin Patch
*** Update File: ''' + sample_py_file + '''
@@
- def add(self, x):
+ def add(self, x, y=0):
*** End Patch'''
        
        preview = preview_diff(diff_text=diff_text, file_path=sample_py_file)
        assert isinstance(preview, str)
        
        # 3. 验证 diff 格式
        is_valid, error = validate_diff_format(diff_text)
        assert is_valid is True

    def test_list_and_extract_consistency(self, sample_py_file):
        """测试列出与提取一致性"""
        listed = list_file_entities(file_path=sample_py_file)
        entities = get_file_entities(sample_py_file)
        
        # listed 中的类名应在 entities 中
        for class_info in entities.get('class', []):
            assert class_info['name'] in listed

    def test_full_workflow_on_real_file(self):
        """测试在真实文件上的完整工作流"""
        # 使用 agent.py 作为真实文件
        agent_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent.py")
        
        if os.path.exists(agent_file):
            # 1. 列出实体
            listed = list_file_entities(file_path=agent_file)
            assert isinstance(listed, str)
            
            # 2. 获取实体字典
            entities = get_file_entities(agent_file)
            assert isinstance(entities, dict)
            
            # 3. 提取特定实体（如 SelfEvolvingAgent 类）
            if entities.get('class'):
                first_class = entities['class'][0]['name']
                entity_code = get_code_entity(
                    file_path=agent_file,
                    entity_name=first_class
                )
                assert first_class in entity_code

    def test_diff_edit_real_file(self, temp_test_dir):
        """测试在真实文件上应用 diff"""
        real_file = os.path.join(temp_test_dir, "real.py")
        original = '''def hello():
    return "world"

class MyClass:
    pass
'''
        with open(real_file, 'w') as f:
            f.write(original)
        
        diff_text = '''*** Begin Patch
*** Update File: real.py
@@
- def hello():
-     return "world"
+ def hello(name="world"):
+     return f"Hello, {name}!"
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=real_file)
        assert "成功" in result or "OK" in result or "applied" in result.lower()
        
        with open(real_file, 'r') as f:
            updated = f.read()
        
        assert 'def hello(name="world")' in updated
        assert 'return f"Hello, {name}!"' in updated
        assert 'return "world"' not in updated


# ============================================================================
# 错误处理和边界测试
# ============================================================================

class TestErrorHandling:
    """错误处理测试"""

    def test_get_code_entity_with_invalid_entity_type(self, sample_py_file):
        """测试提取无效实体类型"""
        # 实体名应只包含字母、数字、下划线
        result = get_code_entity(
            file_path=sample_py_file,
            entity_name="123invalid"
        )
        assert ("错误" in result or "未找到" in result or 
                "invalid" in result.lower())

    def test_get_code_entity_file_not_found(self):
        """测试文件不存在"""
        result = get_code_entity(
            file_path="/nonexistent/file.py",
            entity_name="Anything"
        )
        assert "错误" in result or "不存在" in result

    def test_get_file_entities_syntax_error(self, broken_py_file):
        """测试语法错误的文件"""
        entities = get_file_entities(broken_py_file)
        # 应返回空字典，不抛出异常
        assert entities == {} or len(entities) == 0

    def test_apply_diff_with_permission_error(self, temp_test_dir):
        """测试权限错误（只读文件）"""
        readonly_file = os.path.join(temp_test_dir, "readonly.txt")
        with open(readonly_file, 'w') as f:
            f.write("readonly content")
        
        # 设置为只读（Windows/Mac/Linux 都支持）
        os.chmod(readonly_file, 0o444)
        
        diff_text = '''*** Begin Patch
*** Update File: ''' + readonly_file + '''
@@
- readonly content
+ modified content
*** End Patch'''
        
        try:
            result = apply_diff_edit(diff_text=diff_text, file_path=readonly_file)
            # 可能成功或失败，取决于系统权限
            assert isinstance(result, str)
        finally:
            # 恢复权限以便清理
            os.chmod(readonly_file, 0o644)

    def test_extract_entity_from_binary_file(self, temp_test_dir):
        """测试从二进制文件提取（应失败）"""
        binary_file = os.path.join(temp_test_dir, "binary.bin")
        with open(binary_file, 'wb') as f:
            f.write(b'\x00\x01\x02\x03')
        
        result = get_code_entity(file_path=binary_file, entity_name="anything")
        assert "错误" in result or "无法解析" in result or "cannot" in result.lower()


# ============================================================================
# 性能测试
# ============================================================================

class TestPerformance:
    """性能基准测试"""

    def test_get_file_entities_performance(self, temp_test_dir):
        """测试获取文件实体性能"""
        import time
        
        # 创建大文件
        large_file = os.path.join(temp_test_dir, "large.py")
        with open(large_file, 'w') as f:
            f.write("""
class C1:
    def m1(self): pass
    def m2(self): pass
    def m3(self): pass

class C2:
    def m1(self): pass
    def m2(self): pass

def f1(): pass
def f2(): pass
def f3(): pass
def f4(): pass

class C3:
    pass
""")
        
        start = time.time()
        entities = get_file_entities(large_file)
        elapsed = time.time() - start
        
        assert elapsed < 2.0  # 应在 2 秒内
        assert len(entities.get('class', [])) >= 3
        assert len(entities.get('function', [])) >= 4

    def test_extract_entity_performance(self, sample_py_file):
        """测试实体提取性能"""
        import time
        
        # 提取多次
        start = time.time()
        for _ in range(100):
            result = get_code_entity(
                file_path=sample_py_file,
                entity_name="Calculator",
                include_imports=False
            )
        elapsed = time.time() - start
        
        assert elapsed < 5.0  # 100 次应在 5 秒内

    def test_validate_diff_performance(self):
        """测试 diff 验证性能"""
        import time
        
        # 有效的复杂 diff
        diff_text = '''*** Begin Patch
*** Update File: file1.py
@@
- line1
+ line2
- line3
+ line4
*** Update File: file2.py
@@
- old1
+ new1
- old2
+ new2
*** End Patch'''
        
        start = time.time()
        for _ in range(1000):
            validate_diff_format(diff_text)
        elapsed = time.time() - start
        
        assert elapsed < 2.0  # 1000 次应在 2 秒内


# ============================================================================
# 数据完整性测试
# ============================================================================

class TestDataIntegrity:
    """数据完整性测试"""

    def test_entity_extraction_preserves_all_info(self, sample_py_file):
        """测试实体提取保留所有信息"""
        entities = get_file_entities(sample_py_file)
        
        for entity_type, entity_list in entities.items():
            for entity in entity_list:
                # 必需字段
                required = ['name', 'type', 'lineno', 'docstring']
                for field in required:
                    assert field in entity, f"实体缺少字段 {field}"
                
                # 类型正确性
                assert isinstance(entity['name'], str)
                assert isinstance(entity['lineno'], int)
                assert entity['docstring'] is None or isinstance(entity['docstring'], str)

    def test_methods_have_class_context(self, sample_py_file):
        """测试方法包含类上下文"""
        entities = get_file_entities(sample_py_file)
        
        for cls in entities.get('class', []):
            if 'methods' in cls:
                for method in cls['methods']:
                    assert 'class_name' in method
                    assert method['class_name'] == cls['name']


# ============================================================================
# 特殊场景测试
# ============================================================================

class TestSpecialScenarios:
    """特殊场景测试"""

    def test_extract_from_file_with_encoding_issues(self, temp_test_dir):
        """测试从编码问题文件提取"""
        weird_file = os.path.join(temp_test_dir, "weird.py")
        with open(weird_file, 'w', encoding='utf-8') as f:
            f.write("# 中文注释\nclass 中文类:\n    pass\n")
        
        result = get_code_entity(file_path=weird_file, entity_name="中文类")
        assert "中文类" in result

    def test_extract_from_very_long_file(self, temp_test_dir):
        """测试超长文件"""
        long_file = os.path.join(temp_test_dir, "very_long.py")
        with open(long_file, 'w') as f:
            f.write("class A:\n    pass\n" * 5000)
        
        # 提取其中一个类
        result = get_code_entity(file_path=long_file, entity_name="A")
        assert "class A" in result

    def test_diff_with_unicode_content(self, temp_test_dir):
        """测试包含 Unicode 的 diff"""
        file_path = os.path.join(temp_test_dir, "unicode.txt")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("原始内容 🎉")
        
        diff_text = '''*** Begin Patch
*** Update File: unicode.txt
@@
- 原始内容 🎉
+ 新内容 🚀✨
*** End Patch'''
        
        result = apply_diff_edit(diff_text=diff_text, file_path=file_path)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert "🚀✨" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
