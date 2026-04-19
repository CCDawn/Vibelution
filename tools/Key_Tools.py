# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块

所有在此注册的 Tool 都会通过 agent._tools 传递给 LLM。
文档（SOUL.md / AGENTS.md）中提到的工具必须在此注册，否则 Agent 无法调用。
"""
from typing import List, Optional
from langchain_core.tools import BaseTool, tool

from tools.memory_tools import (
    commit_compressed_memory_tool as _commit_compressed_impl,
    read_dynamic_prompt_tool as _read_dynamic_prompt_impl,
    add_insight_to_dynamic_tool as _add_insight_impl,
    write_dynamic_prompt_tool as _write_dynamic_prompt_impl,
    read_memory_tool as _read_memory_impl,
    get_memory_summary_tool as _get_memory_summary_impl,
)
from tools.memory_tools import (
    set_plan_tool as _set_plan_impl,
    tick_subtask_tool as _tick_subtask_impl,
    modify_task_tool as _modify_task_impl,
    add_task_tool as _add_task_impl,
    remove_task_tool as _remove_task_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.shell_tools import (
    list_directory as _list_directory_impl,
    check_python_syntax as _check_python_syntax_impl,
    backup_project as _backup_project_impl,
    cleanup_test_files as _cleanup_test_impl,
    self_test as _self_test_impl,
    read_file as _read_file_impl,
    edit_file as _edit_file_impl,
    create_file as _create_file_impl,
)
from tools.rebirth_tools import (
    enter_hibernation_tool as _enter_hibernation_impl,
)


def create_key_tools() -> List[BaseTool]:
    """
    将项目工具包装为 LangChain Tool。

    Returns:
        LangChain Tool 列表
    """

    # ── SOUL.md 核心生存工具 ────────────────────────────────────────────────

    @tool
    def commit_compressed_memory_tool(new_core_context: str, next_goal: str) -> str:
        """
        【重启前必调】将本世代的核心发现和技术洞察压缩存盘。

        调用此工具后，下次苏醒时会自动加载上次存盘的记忆。

        Args:
            new_core_context: 核心发现（不超过300字），总结本次进化发现的技术要点
            next_goal: 下一个进化目标，简述重启后要做什么

        Returns:
            存盘结果
        """
        return _commit_compressed_impl(new_core_context=new_core_context, next_goal=next_goal)

    # @tool
    # def read_dynamic_prompt_tool() -> str:
    #     """
    #     【世代开始时必调】读取 workspace/prompts/DYNAMIC.md 的当前内容。

    #     用于了解当前世代的任务目标、历史积累的洞察。

    #     Returns:
    #         DYNAMIC.md 完整内容
    #     """
    #     return _read_dynamic_prompt_impl()

    # @tool
    # def add_insight_to_dynamic_tool(insight: str) -> str:
    #     """
    #     【随时追加】将重要发现追加到 DYNAMIC.md 的洞察积累区域。

    #     适用于在执行任务过程中发现关键技术点，需要记录下来供后续世代参考。

    #     Args:
    #         insight: 要追加的洞察内容

    #     Returns:
    #         更新结果
    #     """
    #     return _add_insight_impl(insight=insight)

    # @tool
    # def write_dynamic_prompt_tool(content: str) -> str:
    #     """
    #     【完整写入】用新内容全量替换 DYNAMIC.md 的正文。

    #     与 add_insight_to_dynamic_tool 的"追加"不同，本工具执行全量覆盖写入，
    #     适用于重写整个动态提示词区域。

    #     Args:
    #         content: 新的动态提示词完整内容

    #     Returns:
    #         更新结果
    #     """
    #     return _write_dynamic_prompt_impl(content=content)

    # ── 记忆系统工具 ──────────────────────────────────────────────────────

    @tool
    def read_memory_tool() -> str:
        """
        【状态查询】读取当前世代索引（轻量级，不加载详细档案）。

        Returns:
            JSON 字符串，包含 current_generation / core_wisdom / current_goal / total_generations
        """
        return _read_memory_impl()

    # @tool
    # def get_memory_summary_tool() -> str:
    #     """
    #     【人类可读摘要】获取当前记忆的人类可读摘要。

    #     用于快速了解 Agent 的当前状态。

    #     Returns:
    #         格式化的记忆摘要字符串
    #     """
    #     return _get_memory_summary_impl()

    # ── 世代与任务工具 ─────────────────────────────────────────────────────

    @tool
    def set_generation_task_tool(task: str) -> str:
        """
        【世代开始时必调】设置当前世代的任务。

        每个世代开始时，模型应首先分析当前状态，然后调用此工具
        将自己制定的任务写入系统提示词。该任务在整个世代有效，
        直到下个世代重新生成新任务。

        Args:
            task: 当前世代的任务描述（Markdown 格式）

        Returns:
            更新结果
        """
        from tools.memory_tools import update_generation_task_tool
        return update_generation_task_tool(task=task)

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
        from tools.rebirth_tools import trigger_self_restart_tool as _restart_impl
        return _restart_impl(reason=reason)

    # ── 代码分析工具 ────────────────────────────────────────────────────────

    @tool
    def grep_search_tool(regex_pattern: str = "", include_ext: str = ".py",
                         search_dir: str = ".", case_sensitive: bool = True,
                         max_results: int = 500) -> str:
        """
        全局正则表达式搜索 (Cursor/Aider 范式)。

        在项目中快速搜索代码，支持正则表达式。优先于 read_file_tool 使用！

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

        使用 SEARCH/REPLACE 块格式精准替换代码。比 edit_file_tool 更可靠！

        格式：
        <<<<<<< SEARCH
        要替换的旧代码（只需包含核心行，无需精确匹配缩进）
        =======
        新代码
        >>>>>>> REPLACE

        Args:
            file_path: 要编辑的文件路径
            diff_text: SEARCH/REPLACE 块文本

        Returns:
            操作结果描述
        """
        from tools.code_analysis_tools import apply_diff_edit
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
        from tools.code_analysis_tools import validate_diff_format
        is_valid, message = validate_diff_format(diff_text)
        return message

    @tool
    def list_file_entities_tool(file_path: str, entity_type: str = "all") -> str:
        """
        【AST 透视】列出 Python 文件的所有类和函数骨架。

        初次遇到任何未知的 .py 文件时，**第一步必须是**
        调用此工具获取结构大纲，禁止直接读取全文件！

        Args:
            file_path: Python 文件路径
            entity_type: 过滤类型 ('class', 'function', 'all')

        Returns:
            格式化的实体列表，包含名称、类型、位置
        """
        from tools.code_analysis_tools import list_file_entities
        return list_file_entities(file_path, entity_type)

    @tool
    def get_code_entity_tool(file_path: str, entity_name: str) -> str:
        """
        【AST 精准抽血】直接提取特定类或函数的完整代码。

        在 list_file_entities 获取大纲后，使用此工具精准提取目标代码。

        Args:
            file_path: Python 文件路径
            entity_name: 类名或函数名

        Returns:
            实体的完整代码及行号范围
        """
        from tools.code_analysis_tools import get_code_entity
        return get_code_entity(file_path, entity_name)

    # ── 文件操作工具 ────────────────────────────────────────────────────────

    @tool
    def cli_tool(command: str = "", timeout: int = 60) -> str:
        """
        【万能 CLI 工具】执行任意 Shell 命令，支持跨平台自动适配。

        底层自动检测当前操作系统并选择正确的 shell 执行：
        - Windows: cmd（PowerShell 风格） | Linux 命令 → Git Bash
        - Linux/macOS: /bin/bash | Windows 命令 → 拒绝并提示替代方案

        Args:
            command: 要执行的 Shell 命令（根据当前系统自动适配）
            timeout: 超时时间（秒），默认 60 秒；长时间命令建议设为 120

        Returns:
            合并后的命令输出（stdout + stderr）
            如果检测到跨平台问题，会在输出中说明
        """
        from tools.shell_tools import execute_shell_command
        if not command:
            return '{"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"}'
        # 确保 timeout 是整数，防止 float/int 类型不一致导致错误
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        return execute_shell_command(command, timeout=timeout)

    @tool
    def get_project_structure_tool(target_dir: str = ".", max_depth: int = 3) -> str:
        """
        获取当前项目的全局目录结构树。

        当需要了解代码在哪，或在多个文件夹中寻找文件时，
        必须首先调用此工具获取上帝视角。

        Args:
            target_dir: 要映射的目标目录，默认为当前目录 "."
            max_depth: 最大递归深度，默认为 3 层

        Returns:
            JSON 格式的项目结构树字符串
        """
        return _list_directory_impl(path=target_dir, recursive=max_depth > 0)

    @tool
    def check_python_syntax_tool(file_path: str) -> str:
        """
        【修改代码后必调】检查 Python 文件的语法正确性（AST 解析）。

        Args:
            file_path: Python 文件路径

        Returns:
            "Syntax OK" 或详细错误信息
        """
        return _check_python_syntax_impl(file_path=file_path)

    @tool
    def backup_project_tool(version_note: str = "") -> str:
        """
        备份当前项目到 backup/ 目录。

        Args:
            version_note: 备份说明（可选）

        Returns:
            备份结果
        """
        return _backup_project_impl(version_note=version_note)

    @tool
    def cleanup_test_files_tool(directory: str = ".", dry_run: bool = False) -> str:
        """
        扫描并清理测试产生的临时文件。

        完成任务后必须清理测试产物。禁止删除 agent.py, restarter.py, SOUL.md, AGENTS.md。

        Args:
            directory: 要扫描的目录，默认当前目录
            dry_run: True=只扫描不删除，False=执行清理

        Returns:
            清理结果
        """
        return _cleanup_test_impl(directory=directory, dry_run=dry_run)

    @tool
    def self_test_tool() -> str:
        """
        【状态检查】运行 Agent 自我检查，返回当前状态摘要。

        Returns:
            自检结果
        """
        return _self_test_impl()

    @tool
    def enter_hibernation_tool(duration: int = 300) -> str:
        """
        让 Agent 进入休眠状态一段时间。

        适用于需要等待外部条件成熟的场景。

        Args:
            duration: 休眠时长（秒），默认 300 秒（5 分钟），建议 60~3600

        Returns:
            操作结果描述
        """
        return _enter_hibernation_impl(duration=duration)

    @tool
    def list_directory_tool(target_dir: str = ".", show_hidden: bool = False,
                             recursive: bool = False) -> str:
        """
        列出目录内容。

        Args:
            target_dir: 目录路径，默认当前目录
            show_hidden: 是否显示隐藏文件
            recursive: 是否递归子目录

        Returns:
            目录列表结果
        """
        return _list_directory_impl(
            path=target_dir,
            show_hidden=show_hidden,
            recursive=recursive
        )

    @tool
    def read_file_tool(file_path: str, encoding: Optional[str] = None,
                       max_lines: Optional[int] = None,
                       show_line_numbers: bool = True,
                       offset: int = 0) -> str:
        """
        按行号读取文件片段（不要全文件读取大文件！）。

        Args:
            file_path: 文件路径
            encoding: 编码格式，默认自动检测
            max_lines: 最大读取行数，None=读取全部
            show_line_numbers: 是否显示行号
            offset: 起始行偏移

        Returns:
            文件内容
        """
        return _read_file_impl(
            file_path=file_path,
            encoding=encoding,
            max_lines=max_lines,
            show_line_numbers=show_line_numbers,
            offset=offset
        )

    @tool
    def edit_file_tool(file_path: str, search_string: str,
                       replace_string: str, create_backup: bool = True) -> str:
        """
        定位并替换文件中的内容。

        Args:
            file_path: 要编辑的文件路径
            search_string: 要替换的原字符串
            replace_string: 替换后的新字符串
            create_backup: 是否创建备份，默认 True

        Returns:
            操作结果
        """
        return _edit_file_impl(
            file_path=file_path,
            search_string=search_string,
            replace_string=replace_string,
            create_backup=create_backup
        )

    @tool
    def create_file_tool(file_path: str, content: str,
                         use_workspace: bool = True) -> str:
        """
        创建新文件或覆盖现有文件。

        Args:
            file_path: 文件路径
            content: 文件内容
            use_workspace: 是否使用 workspace 目录前缀

        Returns:
            操作结果
        """
        return _create_file_impl(
            file_path=file_path,
            content=content,
            use_workspace=use_workspace
        )

    # ── 任务清单工具 ───────────────────────────────────────────────────────

    @tool
    def set_plan_tool(goal: str, tasks: List[str]) -> str:
        """
        【计划制定工具】设置本轮任务清单

        每次苏醒确定本轮目标后，第一步必须调用此工具将大目标拆解为具体小任务。

        Args:
            goal: 本轮的总目标描述
            tasks: 子任务列表（3-5个），每个任务描述要具体可执行

        Returns:
            JSON 格式的执行结果
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
        # SOUL.md 核心
        commit_compressed_memory_tool,
        # 记忆系统
        read_memory_tool,
        # 世代与重启
        set_generation_task_tool,
        trigger_self_restart_tool,
        # 代码分析
        grep_search_tool,
        apply_diff_edit_tool,
        validate_diff_format_tool,
        list_file_entities_tool,
        get_code_entity_tool,
        # 文件操作
        cli_tool,
        get_project_structure_tool,
        check_python_syntax_tool,
        backup_project_tool,
        cleanup_test_files_tool,
        self_test_tool,
        enter_hibernation_tool,
        list_directory_tool,
        read_file_tool,
        edit_file_tool,
        create_file_tool,
        # 任务清单
        set_plan_tool,
        tick_subtask_tool,
        modify_task_tool,
        add_task_tool,
        remove_task_tool,
    ]
