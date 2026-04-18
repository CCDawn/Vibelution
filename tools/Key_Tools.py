# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块
"""
from typing import List, Optional
from langchain_core.tools import BaseTool, tool
from tools import *
from tools.memory_tools import (
    set_plan_tool as _set_plan_impl,
    tick_subtask_tool as _tick_subtask_impl,
    modify_task_tool as _modify_task_impl,
    add_task_tool as _add_task_impl,
    remove_task_tool as _remove_task_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.shell_tools import list_directory as _list_directory_impl

def create_key_tools() -> List[BaseTool]:
    """
    将项目工具包装为 LangChain Tool。

    Returns:
        LangChain Tool 列表
    """

    @tool
    def set_generation_task_tool(task: str) -> str:
        """
        【世代开始时必调】设置当前世代的任务。

        每个世代开始时，模型应首先分析当前状态，然后调用此工具
        将自己制定的任务写入系统提示词。该任务在整个世代有效，
        直到下个世代重新生成新任务。

        Args:
            task: 当前世代的任务描述（Markdown 格式）
                例如：
                ```
                1. 探索 tools/ 目录，分析现有工具的实现
                2. 识别可以改进的代码模式
                3. 实现至少一个代码改进
                4. 确保语法正确，重启验证
                ```

        Returns:
            更新结果
        """
        return update_generation_task_tool(task)
    @tool
    def trigger_self_restart_tool(reason: str = "") -> str:
        """
        触发 Agent 自我重启。

        用于应用代码更新。每次代码修改并自检通过后必须调用！

        Args:
            reason: 重启原因

        Returns:
            操作结果（原进程将退出）
        """
        return trigger_self_restart(reason)

    @tool
    def grep_search_tool(regex_pattern: str = "", include_ext: str = ".py",
                         search_dir: str = ".", case_sensitive: bool = True,
                         max_results: int = 500) -> str:
        """
        全局正则表达式搜索 (Cursor/Aider 范式)。

        在项目中快速搜索代码，支持正则表达式。优先于 read_local_file_tool 使用！

        适用场景：
        - 查找函数/变量定义位置
        - 查找函数的所有调用
        - 查找 import 语句
        - 快速定位关键词

        Args:
            regex_pattern: 正则表达式模式
            include_ext: 要搜索的文件类型，默认 ".py"
            search_dir: 搜索目录，默认当前目录
            case_sensitive: 是否区分大小写，默认 True
            max_results: 最大返回结果数

        Returns:
            JSON 格式的搜索结果，包含文件路径、行号和匹配内容
        """
        return _grep_search_impl(
            regex_pattern=regex_pattern,
            include_ext=include_ext,
            search_dir=search_dir,
            case_sensitive=case_sensitive,
            max_results=max_results
        )

    @tool
    def apply_diff_edit_tool(file_path: str, diff_text: str) -> str:
        """
        Diff Block 编辑器 (Cursor/Aider 范式)。

        使用 SEARCH/REPLACE 块格式精准替换代码。比 edit_local_file_tool 更可靠！

        格式：
        <<<<<<< SEARCH
        要替换的旧代码（只需包含核心行，无需精确匹配缩进）
        =======
        新代码
        >>>>>>> REPLACE

        【重要】SEARCH 块会自动规范化：
        - 行首空格会被忽略（允许宽松匹配）
        - 行尾空白会被忽略
        - 空行会被跳过
        
        可包含多个块一次性修改多处！

        Args:
            file_path: 要编辑的文件路径
            diff_text: SEARCH/REPLACE 块文本

        Returns:
            操作结果描述
        """
        return apply_diff_edit(file_path=file_path, diff_text=diff_text, allow_fuzzy=True)

    @tool
    def validate_diff_format_tool(diff_text: str) -> str:
        """
        验证 diff_text 格式是否正确。

        在实际编辑前验证格式，避免无效修改。

        Args:
            diff_text: 要验证的 diff 块文本

        Returns:
            验证结果
        """
        is_valid, message = validate_diff_format(diff_text)
        return message


    @tool
    def list_file_entities_tool(file_path: str, entity_type: str = "all") -> str:
        """
        【AST 透视】列出 Python 文件的所有类和函数骨架。

        ⚠️ 【铁律】当你初次遇到任何未知的 .py 文件时，**第一步必须是**
        调用此工具获取结构大纲，禁止直接读取全文件！

        使用 Python AST 解析，极速获取：
        - 所有类和函数名称
        - 行号位置
        - 文档字符串预览
        - 装饰器信息

        Args:
            file_path: Python 文件路径
            entity_type: 过滤类型 ('class', 'function', 'all')

        Returns:
            格式化的实体列表，包含名称、类型、位置
        """
        try:
            from tools.code_analysis_tools import list_file_entities
            return list_file_entities(file_path, entity_type)
        except Exception as e:
            return f"[AST 工具错误] 导入失败: {type(e).__name__}: {e}"

    @tool
    def get_code_entity_tool(file_path: str, entity_name: str) -> str:
        """
        【AST 精准抽血】直接提取特定类或函数的完整代码。

        在 list_file_entities 获取大纲后，使用此工具精准提取目标代码。

        适用场景：
        - 知道函数/类名，一键提取完整代码
        - 查看特定方法的实现
        - 避免读取整个大文件

        Args:
            file_path: Python 文件路径
            entity_name: 类名或函数名（如 "SelfEvolvingAgent"、"wake_up"）

        Returns:
            实体的完整代码及行号范围
        """
        try:
            from tools.code_analysis_tools import get_code_entity
            return get_code_entity(file_path, entity_name)
        except Exception as e:
            return f"[AST 工具错误] 导入失败: {type(e).__name__}: {e}"

    @tool
    def cli_tool(command: str = "", timeout: int = 60) -> str:
        """
        【万能 CLI 工具】执行任意 Shell 命令的终极工具。

        基于 CodeAct 范式，这是你的核心能力。你可以用它执行任何命令：
        - ls -la, tree, dir        # 列出目录
        - cat, type, head, tail   # 查看文件
        - grep, find, where        # 搜索文件/内容
        - python -m py_compile     # 语法检查
        - pytest, unittest         # 运行测试
        - pip list, pip install    # 包管理
        - git status, git diff     # Git 操作
        - 任何你想到的 Shell 命令

        Args:
            command: 要执行的 Shell 命令
            timeout: 超时时间（秒），默认 60 秒

        Returns:
            合并后的命令输出（stdout + stderr）
        """
        if not command:
            import json
            return json.dumps({"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"})
        return execute_shell_command(command, timeout=timeout)

    @tool
    def get_project_structure_tool(target_dir: str = ".", max_depth: int = 3) -> str:
        """
        获取当前项目的全局目录结构树。

        【极其重要】：当你刚接手一个新任务，不知道代码在哪，或者需要在多个文件夹中寻找文件时，
        必须首先调用此工具获取上帝视角！

        Args:
            target_dir: 要映射的目标目录，默认为当前目录 "."
            max_depth: 最大递归深度，默认为 3 层。

        Returns:
            JSON 格式的项目结构树字符串
        """
        return _list_directory_impl(path=target_dir, recursive=max_depth > 0)

    # 任务清单工具 (task_tools.py)
    @tool
    def set_plan_tool(goal: str, tasks: List[str]) -> str:
        """
        【计划制定工具】设置本轮任务清单

        每次苏醒确定本轮目标后，第一步必须调用此工具将大目标拆解为具体小任务。

        Args:
            goal: 本轮的总目标描述
            tasks: 子任务列表（3-5个），每个任务描述要具体可执行

        Returns:
            JSON 格式的执行结果，包含任务列表和当前状态
        """
        return _set_plan_impl(goal=goal, tasks=tasks)

    @tool
    def tick_subtask_tool(task_id: int, summary: str) -> str:
        """
        【任务打勾工具】标记任务完成并记录结论

        每完成一个小任务，必须立刻调用此工具打勾。

        Args:
            task_id: 任务编号
            summary: 该任务完成后的核心结论/成果
        """
        return _tick_subtask_impl(task_id=task_id, summary=summary)

    @tool
    def modify_task_tool(task_id: int, description: str) -> str:
        """
        【任务修改工具】修改已有任务的描述

        Args:
            task_id: 要修改的任务编号
            description: 新的任务描述
        """
        return _modify_task_impl(task_id=task_id, new_description=description)

    @tool
    def add_task_tool(description: str) -> str:
        """
        【追加任务工具】添加新任务到当前清单

        Args:
            description: 新任务的描述
        """
        return _add_task_impl(description=description)

    @tool
    def remove_task_tool(task_id: int) -> str:
        """
        【删除任务工具】从清单中移除任务

        Args:
            task_id: 要删除的任务编号
        """
        return _remove_task_impl(task_id=task_id)
    return [
        set_generation_task_tool,
        trigger_self_restart_tool,
        grep_search_tool,
        apply_diff_edit_tool,
        validate_diff_format_tool,
        list_file_entities_tool,
        get_code_entity_tool,
        cli_tool,
        get_project_structure_tool,
        set_plan_tool,
        tick_subtask_tool,
        modify_task_tool,
        add_task_tool,
        remove_task_tool,   
    ]
