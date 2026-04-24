# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块

所有在此注册的 Tool 都会通过 agent._tools 传递给 LLM。
文档（SOUL.md / AGENTS.md）中提到的工具必须在此注册，否则 Agent 无法调用。
"""
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool, tool, StructuredTool
from tools.rebirth_tools import trigger_self_restart_tool as _restart_impl
from tools.memory_tools import (
    commit_compressed_memory_tool as _commit_compressed_impl,
    read_dynamic_prompt_tool as _read_dynamic_prompt_impl,
    add_insight_to_dynamic_tool as _add_insight_impl,
    write_dynamic_prompt_tool as _write_dynamic_prompt_impl,
    read_memory_tool as _read_memory_impl,
    get_memory_summary_tool as _get_memory_summary_impl,
)
from tools.memory_tools import (
    task_create_tool as _task_create_impl,
    task_update_tool as _task_update_impl,
    task_list_tool as _task_list_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.rebirth_tools import (
    enter_hibernation_tool as _enter_hibernation_impl,
)
from tools.web_search_tool import (
    web_search_tool as _web_search_impl,
)
import platform as _platform

_CURRENT_OS = _platform.system()

if _CURRENT_OS == "Windows":
    _OS_CHEATSHEET = """
当前系统: Windows PowerShell
- 看目录: Get-ChildItem -Recurse -Depth 3
- 搜内容: Select-String -Pattern "查找词" -Path *.py -Recurse
- 看前N行: Get-Content file.py -TotalCount 30
- 读后N行: Get-Content file.py -Tail 30
- 统计行数: (Get-Content file.py).Length
- 杀进程: Stop-Process -Id PID -Force
- 重启/刷新环境: refreshenv (或重启终端)
"""
else:
    _OS_CHEATSHEET = """
当前系统: Linux / macOS (Bash)
- 看目录: find . -maxdepth 3
- 搜内容: grep -rn "查找词" --include="*.py" .
- 看前N行: head -N file.py
- 读后N行: tail -N file.py
- 统计行数: wc -l file.py
- 找大文件: find . -name "*.py" -size +10k
    - 杀进程: kill -9 PID
"""

_CLI_TOOL_DOCSTRING = """
【万能 CLI 工具】执行任意 Shell 命令。你是资深架构师，请用最高效的命令组合！

""" + _OS_CHEATSHEET + """

=== ⚡ 核心纪律 (违者崩溃) ===
1. 禁区：绝不执行交互式命令 (vim, nano, top, less) 和无休止命令 (ping, tail -f)。
2. 管道：必须多用 `| head -n 20` 或 `| grep` 截断长输出，防止 Token 爆炸！
3. 限制：超过 500 行的文件，禁止用 cat/Get-Content 全量读取，必须用 head/tail。

=== 🔄 闭环准则 ===
修改代码后，立刻组合执行：`python -m py_compile <file>.py && pytest`

Args:
    command: 要执行的 Shell 命令（请确保语法兼容当前 """ + _CURRENT_OS + """ 系统）
    timeout: 建议: 文件操作 30s, 编译 60s, 测试/网络 120s
"""


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

    # @tool
    # def read_memory_tool() -> str:
    #     """
    #     【状态查询】读取当前世代索引（轻量级，不加载详细档案）。

    #     Returns:
    #         JSON 字符串，包含 current_generation / core_wisdom / current_goal / total_generations
    #     """
    #     return _read_memory_impl()

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
        注意重启后你的上下文会消失，所以你需要在重启前保存好你的上下文。

        Args:
            reason: 重启原因

        Returns:
            操作结果（原进程将退出）
        """
        return _restart_impl(reason=reason)

    # ── 代码分析工具 ────────────────────────────────────────────────────────

    @tool
    def grep_search_tool(regex_pattern: str = "", include_ext: str = ".py",
                         search_dir: str = ".", case_sensitive: bool = True,
                         max_results: int = 500) -> str:
        """
        全局正则表达式搜索 (Cursor/Aider 范式)。

        在项目中快速搜索代码，支持正则表达式。优先于 `cli_tool` 的 `cat`/`Get-Content` 使用！

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

        使用 SEARCH/REPLACE 块格式精准替换代码。比用 `cli_tool` 执行 `sed` 或 PowerShell `-replace` 更可靠！

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

    @tool
    def web_search_tool(query: str, max_results: int = 10) -> str:
        """
        网络搜索工具 - 基于 AutoGLM Web Search API。

        当需要获取实时信息、最新资讯、网络资料时使用此工具。

        Args:
            query: 搜索关键词（必填），尽量具体以获得更准确的结果
            max_results: 最大返回结果数，默认 10，建议 5-20

        Returns:
            包含搜索摘要和参考来源链接的格式化字符串
        """
        return _web_search_impl(query=query, max_results=max_results)

    # ── 文件操作工具 ────────────────────────────────────────────────────────

    def _cli_tool_impl(command: str = "", timeout: int = 60) -> str:
        from tools.shell_tools import execute_shell_command
        if not command:
            return '{"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"}'
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        return execute_shell_command(command, timeout=timeout)

    cli_tool = StructuredTool.from_function(_cli_tool_impl, name="cli_tool", description=_CLI_TOOL_DOCSTRING)

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

    # ── TaskManager 工具（基于 tasks.json） ─────────────────────────────

    @tool
    def task_create_tool(task_list: List[Dict], generation_goal: str = "") -> str:
        """
        【初始化任务清单】将子任务列表注册到系统内存并持久化。

        每个世代开始时，模型应首先分析当前状态，然后调用此工具
        注册本轮任务清单。该清单在世代内持续有效。

        Args:
            task_list: [{"description": "子任务描述"}, ...]
            generation_goal: 当前世代的核心目标（可选）

        Returns:
            成功创建的任务数量摘要
        """
        return _task_create_impl(task_list=task_list, generation_goal=generation_goal)

    @tool
    def task_update_tool(task_id: int, is_completed: bool, result_summary: str = "") -> str:
        """
        【更新任务状态】要求模型在每步操作后必须调用。

        每次完成以下任一操作后，必须立即调用：
        - 修改了任意文件（新建/编辑/删除）
        - 运行了测试或构建命令
        - 执行了任何有副作用的工具调用

        Args:
            task_id: 任务编号（来自 task_create 的返回值或 task_list 的 # 列）
            is_completed: True=标记完成，False=标记进行中
            result_summary: 操作结果摘要（必填，用于防止任务漂移）

        Returns:
            更新结果描述
        """
        return _task_update_impl(
            task_id=task_id,
            is_completed=is_completed,
            result_summary=result_summary
        )

    @tool
    def task_list_tool() -> str:
        """
        【检索任务进度】获取当前所有任务的详细进度，防止长对话中的任务漂移。

        Returns:
            格式化 Markdown 表格
        """
        return _task_list_impl()

    return [
        # SOUL.md 核心
        commit_compressed_memory_tool,
        # 世代与重启
        set_generation_task_tool,
        trigger_self_restart_tool,
        # 代码分析
        grep_search_tool,
        apply_diff_edit_tool,
        validate_diff_format_tool,
        list_file_entities_tool,
        get_code_entity_tool,
        web_search_tool,
        # 文件操作
        cli_tool,
        enter_hibernation_tool,
        # TaskManager（tasks.json）
        task_create_tool,
        task_update_tool,
        task_list_tool,
    ]
