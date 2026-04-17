#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码生成器 (CodeGenerator) - 根据规范生成改进代码

Phase 3 核心模块

负责：
- 根据重构计划生成代码修改
- 生成单元测试代码
- 生成文档注释
- 验证生成的代码
"""

from __future__ import annotations

import os
import re
import ast
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class GeneratedCode:
    """生成的代码"""
    file_path: str
    code_type: str  # "new", "modified", "test"
    content: str
    description: str
    verification_steps: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class CodeTemplate:
    """代码模板"""
    name: str
    template: str
    description: str
    variables: List[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    """生成结果"""
    success: bool
    generated_files: List[GeneratedCode] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: str = ""


# ============================================================================
# 代码模板库
# ============================================================================

CODE_TEMPLATES = {
    # 测试模板
    "test_class": """
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Test{model_name}:
    \"\"\"测试 {model_name} \"\"\"

    @pytest.fixture
    def instance(self):
        \"\"\"创建实例\"\"\"
        from {module_path} import {import_name}
        return {import_name}()

    def test_init(self, instance):
        \"\"\"测试初始化\"\"\"
        assert instance is not None

""",

    "test_method": """
    def test_{method_name}(self, instance):
        \"\"\"测试 {method_name} \"\"\"
        # TODO: 实现测试
        pass

""",

    # 文档字符串模板
    "docstring_module": '''
"""
{module_name} - {description}

{features}
"""

''',

    "docstring_class": '''
class {class_name}:
    """
    {description}

    Attributes:
        {attributes}
    """

''',

    "docstring_method": '''
    def {method_name}(self{params}) -> {return_type}:
        """
        {description}

        Args:
            {param_docs}
        
        Returns:
            {return_doc}
        
        Raises:
            {exceptions}
        """
''',

    # 函数重构模板
    "extract_method": '''
def {new_function_name}({params}):
    """
    {description}

    Args:
        {param_docs}

    Returns:
        {return_doc}
    """
    {body}
''',

    # 类型定义模板
    "dataclass_template": '''
@dataclass
class {class_name}:
    """
    {description}
    """
    {fields}
''',

    # 异常类模板
    "exception_template": '''
class {exception_name}(Exception):
    """自定义异常: {description}"""

    def __init__(self, message: str = "", details: Optional[Dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {{}}
''',
}


# ============================================================================
# 代码生成器
# ============================================================================

class CodeGenerator:
    """
    代码生成器

    根据重构计划生成代码修改。
    """

    def __init__(self, project_root: Optional[str] = None):
        """
        初始化代码生成器

        Args:
            project_root: 项目根目录路径
        """
        if project_root is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.project_root = Path(project_root)

        # 生成历史
        self._generation_history: List[GenerationResult] = []

    # =========================================================================
    # 核心接口
    # =========================================================================

    async def generate_from_plan(
        self,
        plan,
        context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """
        根据计划生成代码

        Args:
            plan: 重构计划
            context: 生成上下文

        Returns:
            生成结果
        """
        result = GenerationResult(success=True, generated_files=[])

        try:
            # 根据计划类型生成代码
            if hasattr(plan, 'tasks'):
                for task in plan.tasks:
                    generated = await self._generate_task_code(task, context)
                    if generated.error:
                        result.errors.append(generated.error)
                        result.success = False
                    else:
                        result.generated_files.append(generated)

            result.summary = f"生成了 {len(result.generated_files)} 个文件"
            self._generation_history.append(result)

        except Exception as e:
            result.success = False
            result.errors.append(str(e))
            result.summary = f"生成失败: {str(e)}"

        return result

    async def generate_test_code(
        self,
        target_file: str,
        test_type: str = "unit",
    ) -> GeneratedCode:
        """
        生成测试代码

        Args:
            target_file: 目标文件路径
            test_type: 测试类型 (unit, integration, e2e)

        Returns:
            生成的测试代码
        """
        file_path = Path(target_file)
        module_name = file_path.stem
        test_file_name = f"test_{module_name}.py"
        test_file_path = self.project_root / "tests" / test_file_name

        # 检查是否已存在
        if test_file_path.exists():
            return GeneratedCode(
                file_path=str(test_file_path),
                code_type="existing",
                content="",
                description=f"测试文件已存在: {test_file_name}",
                error="测试文件已存在",
            )

        # 生成测试代码
        template = CODE_TEMPLATES.get("test_class", "")
        content = self._generate_test_from_template(
            target_file=target_file,
            template=template,
        )

        return GeneratedCode(
            file_path=str(test_file_path),
            code_type="test",
            content=content,
            description=f"为 {target_file} 生成单元测试",
            verification_steps=[
                "运行 pytest 测试",
                "检查覆盖率",
            ],
        )

    async def generate_refactored_code(
        self,
        original_code: str,
        refactoring_type: str,
        params: Dict[str, Any],
    ) -> str:
        """
        生成重构后的代码

        Args:
            original_code: 原始代码
            refactoring_type: 重构类型
            params: 重构参数

        Returns:
            重构后的代码
        """
        if refactoring_type == "extract_method":
            return self._extract_method(original_code, params)
        elif refactoring_type == "add_type_hints":
            return self._add_type_hints(original_code, params)
        elif refactoring_type == "add_docstring":
            return self._add_docstrings(original_code, params)
        elif refactoring_type == "simplify_condition":
            return self._simplify_condition(original_code, params)
        else:
            return original_code

    # =========================================================================
    # 代码生成辅助
    # =========================================================================

    def _generate_test_from_template(
        self,
        target_file: str,
        template: str,
    ) -> str:
        """从模板生成测试代码"""
        file_path = Path(target_file)
        module_name = file_path.stem
        class_name = self._snake_to_pascal(module_name)

        # 尝试导入模块获取类名
        module_path = self._get_relative_path(target_file)
        import_path = module_path.replace("/", ".").replace("\\", ".")

        content = template.format(
            model_name=class_name,
            module_path=import_path,
            import_name=class_name,
        )

        # 添加文件头
        header = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
{class_name} 测试文件

测试 {target_file} 模块
"""

'''

        return header + content

    def _extract_method(
        self,
        original_code: str,
        params: Dict[str, Any],
    ) -> str:
        """提取方法重构"""
        function_name = params.get("new_function_name", "extracted_helper")
        start_line = params.get("start_line", 1)
        end_line = params.get("end_line", 10)

        lines = original_code.split('\n')
        method_body = '\n'.join(lines[start_line:end_line])

        template = CODE_TEMPLATES["extract_method"]
        extracted = template.format(
            new_function_name=function_name,
            params=params.get("params", ""),
            description=params.get("description", "提取的方法"),
            param_docs=params.get("param_docs", ""),
            return_doc=params.get("return_doc", "无"),
            body=method_body,
        )

        return extracted

    def _add_type_hints(
        self,
        original_code: str,
        params: Dict[str, Any],
    ) -> str:
        """添加类型注解"""
        try:
            tree = ast.parse(original_code)
        except SyntaxError:
            return original_code

        # 简单的类型推断
        lines = original_code.split('\n')
        result_lines = []

        for i, line in enumerate(lines):
            # 检查是否是函数定义
            match = re.match(r'(    def )(\w+)(\()', line)
            if match:
                # 添加返回类型注解
                if i > 0 and '-> ' not in lines[i - 1]:
                    indent = ' ' * (len(match.group(1)) + len(match.group(2)) + len(match.group(3)))
                    result_lines.append(f"{indent}# TODO: 添加类型注解")
            result_lines.append(line)

        return '\n'.join(result_lines)

    def _add_docstrings(
        self,
        original_code: str,
        params: Dict[str, Any],
    ) -> str:
        """添加文档字符串"""
        try:
            tree = ast.parse(original_code)
        except SyntaxError:
            return original_code

        lines = original_code.split('\n')
        result_lines = []

        in_function = False
        function_indent = 0

        for i, line in enumerate(lines):
            # 检查是否是函数定义
            match = re.match(r'^(\s*)def (\w+)\(', line)
            if match:
                in_function = True
                function_indent = len(match.group(1))
                result_lines.append(line)
                continue

            # 如果是新函数后的第一个内容，添加文档字符串
            if in_function and line.strip() and not line.strip().startswith('#'):
                if not line.strip().startswith('"""') and not line.strip().startswith("'''"):
                    indent = ' ' * (function_indent + 4)
                    docstring = f'{indent}"""TODO: 添加文档字符串"""'
                    result_lines.append(docstring)
                    in_function = False

            result_lines.append(line)

        return '\n'.join(result_lines)

    def _simplify_condition(
        self,
        original_code: str,
        params: Dict[str, Any],
    ) -> str:
        """简化条件表达式"""
        # 简化多重嵌套的 if-elif-else
        pattern = params.get("pattern", "")

        # 简单的布尔简化
        simplified = original_code
        simplified = re.sub(r'if (True|1):\s*\n\s*return True', 'return True', simplified)
        simplified = re.sub(r'if (False|0):\s*\n\s*return False', 'return False', simplified)

        return simplified

    # =========================================================================
    # 代码验证
    # =========================================================================

    def verify_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """
        验证代码语法

        Args:
            code: 待验证的代码

        Returns:
            (is_valid, error_message)
        """
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"语法错误: {e}"

    def verify_imports(self, code: str) -> Tuple[bool, List[str]]:
        """
        验证导入语句

        Args:
            code: 待验证的代码

        Returns:
            (is_valid, missing_imports)
        """
        missing = []

        # 提取所有导入
        import_pattern = r'(?:from (\S+) import |import (\S+))'
        imports = re.findall(import_pattern, code)

        for imp in imports:
            module_name = imp[0] or imp[1]
            try:
                __import__(module_name)
            except ImportError:
                missing.append(module_name)

        return len(missing) == 0, missing

    # =========================================================================
    # 工具方法
    # =========================================================================

    def _snake_to_pascal(self, snake_str: str) -> str:
        """将 snake_case 转换为 PascalCase"""
        components = snake_str.split('_')
        return ''.join(x.title() for x in components)

    def _get_relative_path(self, file_path: str) -> str:
        """获取相对于项目根目录的路径"""
        try:
            path = Path(file_path).relative_to(self.project_root)
            return str(path)
        except ValueError:
            return file_path

    def format_python_code(self, code: str) -> str:
        """
        格式化 Python 代码

        Args:
            code: 原始代码

        Returns:
            格式化后的代码
        """
        try:
            import autopep8
            return autopep8.code_to_string(code, options={
                'aggressive': 1,
            })
        except ImportError:
            # 如果没有 autopep8，返回原始代码
            return code

    def generate_import_section(
        self,
        imports: List[str],
        standard_library: List[str] = None,
        third_party: List[str] = None,
        local: List[str] = None,
    ) -> str:
        """
        生成标准化的导入部分

        Args:
            imports: 所有导入列表
            standard_library: 标准库
            third_party: 第三方库
            local: 本地导入

        Returns:
            格式化的导入代码
        """
        sections = []

        # 标准库
        if standard_library:
            sections.append('\n'.join(f"import {i}" for i in sorted(standard_library)))

        # 第三方库
        if third_party:
            if sections:
                sections.append('')
            sections.append('\n'.join(f"import {i}" for i in sorted(third_party)))

        # 本地导入
        if local:
            if sections:
                sections.append('')
            sections.append('\n'.join(f"from {i} import ..." for i in sorted(local)))

        return '\n'.join(sections)


# ============================================================================
# 全局单例
# ============================================================================

_code_generator: Optional[CodeGenerator] = None


def get_code_generator(project_root: Optional[str] = None) -> CodeGenerator:
    """获取代码生成器单例"""
    global _code_generator
    if _code_generator is None:
        _code_generator = CodeGenerator(project_root)
    return _code_generator
