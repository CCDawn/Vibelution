# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块

所有在此注册的 Tool 都会通过 agent._tools 传递给 LLM。
文档（SOUL.md / SPEC.md）中提到的工具必须在此注册，否则 Agent 无法调用。
"""
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool, tool, StructuredTool
from tools.rebirth_tools import trigger_self_restart_tool as _restart_impl
from tools.memory_tools import (
    commit_compressed_memory_tool as _commit_compressed_impl,
    get_core_context_tool as _get_core_context_impl,
    get_current_goal_tool as _get_current_goal_impl,
)
from tools.memory_tools import (
    task_create_tool as _task_create_impl,
    task_update_tool as _task_update_impl,
    task_list_tool as _task_list_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.web_search_tool import (
    web_search_tool as _web_search_impl,
)
from core.infrastructure.mental_model import (
    get_mental_state_tool as _get_mental_state_impl,
    update_diagnosis_rules_tool as _update_diagnosis_rules_impl,
    update_self_model_tool as _update_self_model_impl,
    get_self_model_tool as _get_self_model_impl,
    record_evolution_tool as _record_evolution_impl,
)

_CLI_TOOL_DOCSTRING = """
【CLI】执行任意 Shell 命令。

优先使用专用工具 (read_file_tool / grep_search_tool / glob_tool / run_test_for_tool) 而非此工具。

=== 核心纪律 ===
1. 禁止交互式命令 (vim, top, less) 和无休止命令 (ping, tail -f)
2. 长输出必须截断: | head -n 20 或 | tail -n 30
3. 超过 500 行的文件禁止全量读取

=== 闭环 ===
修改代码后: python -m py_compile <file>.py && python -m pytest tests/ -x -q

Args:
    command: Shell 命令
    timeout: 文件操作 30s, 编译 60s, 测试/网络 120s
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

    @tool
    def get_core_context_tool() -> str:
        """
        【记忆读取】获取当前世代的核心上下文和智慧摘要。

        Returns:
            核心智慧文本（不超过300字）
        """
        return _get_core_context_impl()

    @tool
    def get_current_goal_tool() -> str:
        """
        【记忆读取】获取当前世代的目标。

        优先从 PromptManager 内存读取，不在内存则回退到文件。

        Returns:
            当前目标描述
        """
        return _get_current_goal_impl()

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
        代码编辑器 — 修改代码的唯一工具。内建格式验证，无需单独验证步骤。

        格式：
        <<<<<<< SEARCH
        要替换的旧代码
        =======
        新代码
        >>>>>>> REPLACE

        支持多块连续替换。

        Args:
            file_path: 要编辑的文件路径
            diff_text: SEARCH/REPLACE 块文本

        Returns:
            操作结果。格式错误时返回具体原因。
        """
        from tools.code_analysis_tools import apply_diff_edit, validate_diff_format
        is_valid, msg = validate_diff_format(diff_text)
        if not is_valid:
            return f"[编辑] 格式验证失败: {msg}"
        return apply_diff_edit(file_path=file_path, diff_text=diff_text, allow_fuzzy=True)

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

    @tool
    def web_fetch_tool(url: str, max_chars: int = 8000) -> str:
        """
        【网页抓取】获取指定 URL 的网页内容并提取纯文本。

        与 web_search_tool 的区别：search 是关键词搜索，fetch 是直接抓取 URL 内容。
        适用于阅读文档、查看 API 响应、分析网页文章等场景。

        Args:
            url: 要抓取的完整 URL（必须以 http:// 或 https:// 开头）
            max_chars: 最大返回字符数，默认 8000

        Returns:
            去除 HTML 标签后的纯文本内容
        """
        from tools.web_search_tool import web_fetch as _web_fetch
        return _web_fetch(url=url, max_chars=max_chars)

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

    # ── 文件读写工具 ──────────────────────────────────────────────────────

    @tool
    def read_file_tool(file_path: str, max_lines: int = 0, offset: int = 0) -> str:
        """
        【读取文件】读取本地文件的全部或部分内容。

        比 cli_tool 更高效，支持编码自动检测、行号显示、分页读取。
        遇到未知文件时优先使用此工具而非 cli_tool。

        Args:
            file_path: 文件路径（相对或绝对）
            max_lines: 最大读取行数，0 表示读取全部
            offset: 从第几行开始读取，0 表示从头开始

        Returns:
            带行号的文件内容
        """
        from tools.shell_tools import read_file
        return read_file(file_path=file_path, max_lines=max_lines or None, offset=offset)

    @tool
    def write_file_tool(file_path: str, content: str) -> str:
        """
        【写入文件】创建或覆盖文件。

        自动创建父目录，以 UTF-8 编码写入。

        Args:
            file_path: 文件路径（相对路径自动前缀 workspace/）
            content: 文件内容

        Returns:
            写入结果（文件大小、行数）
        """
        from tools.shell_tools import create_file
        return create_file(file_path=file_path, content=content)

    @tool
    def glob_tool(pattern: str, search_dir: str = ".") -> str:
        """
        【文件模式匹配】按 glob 模式查找文件。

        支持标准 glob 模式：*.py、**/*.ts、src/**/*.md 等。

        Args:
            pattern: Glob 模式（如 "*.py", "**/*.py"）
            search_dir: 搜索起始目录，默认当前目录

        Returns:
            JSON 格式的匹配文件列表
        """
        from tools.shell_tools import glob_files
        return glob_files(pattern=pattern, search_dir=search_dir)

    # ── TaskManager 工具（基于 tasks.json） ─────────────────────────────

    @tool
    def task_create_tool(task_list: List[Dict], goal: str = "") -> str:
        """
        【初始化任务清单】将子任务列表注册到系统内存并持久化。

        模型应首先分析当前状态，然后调用此工具注册本轮任务清单。

        Args:
            task_list: [{"description": "子任务描述"}, ...]
            goal: 当前核心目标（可选）

        Returns:
            成功创建的任务数量摘要
        """
        return _task_create_impl(task_list=task_list, goal=goal)

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

    # ── 后台任务工具 ──────────────────────────────────────────────────────

    @tool
    def task_start_tool(command: str, timeout: int = 300) -> str:
        """
        【启动后台任务】在后台线程中执行 Shell 命令，立即返回任务 ID。

        适用于长时间运行的命令（构建、安装依赖、批量测试等），
        避免阻塞主 Agent 循环。使用 task_output_tool 获取结果。

        Args:
            command: 要执行的 Shell 命令
            timeout: 超时时间（秒），默认 300 秒（5 分钟）

        Returns:
            包含 task_id 的 JSON，用于后续查询
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.start_task(command=command, timeout=timeout)

    @tool
    def task_output_tool(task_id: str) -> str:
        """
        【获取后台任务输出】查询后台任务的执行状态和输出。

        Args:
            task_id: 任务 ID（来自 task_start_tool 的返回值）

        Returns:
            JSON 格式的任务状态、输出和耗时
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.get_task_output(task_id=task_id)

    @tool
    def task_stop_tool(task_id: str) -> str:
        """
        【停止后台任务】取消正在运行的后台任务。

        Args:
            task_id: 任务 ID（来自 task_start_tool 的返回值）

        Returns:
            操作结果
        """
        from core.infrastructure.background_tasks import get_background_task_manager
        mgr = get_background_task_manager()
        return mgr.stop_task(task_id=task_id)

    @tool
    def run_test_for_tool(source_path: str, timeout: int = 120) -> str:
        """
        【测试映射运行】根据源文件路径自动查找对应测试文件并运行。

        映射规则：tools/xxx.py → tests/test_xxx.py
        修改代码后必须调用此工具验证！

        Args:
            source_path: 源文件相对路径（如 "tools/shell_tools.py"）
            timeout: 超时时间（秒），默认 120

        Returns:
            格式化的测试结果摘要
        """
        from tools.shell_tools import run_test_for
        return run_test_for(source_path=source_path, timeout=timeout)

    # ── 心智模型工具 ──────────────────────────────────────────────────────

    @tool
    def get_mental_state_tool() -> str:
        """
        【元认知诊断】查看当前心智状态。

        返回认知状态标签、工具成功率、重复次数、文件聚焦度等指标。
        在开始新任务或感到困顿时调用，了解自己的运行状态。

        Returns:
            JSON 格式的诊断结果
        """
        return _get_mental_state_impl()

    @tool
    def update_diagnosis_rules_tool(rules_json: str) -> str:
        """
        【修改诊断规则】调整心智模型的诊断阈值。

        当发现诊断过于敏感（频繁误报）或过于迟钝（漏报问题）时使用。
        修改会持久化到 workspace/mental_model/rules.json。

        Args:
            rules_json: JSON 字符串，包含要更新的规则，如 '{"looping": {"threshold": 6}}'

        Returns:
            更新结果
        """
        return _update_diagnosis_rules_impl(rules_json=rules_json)

    @tool
    def update_self_model_tool(updates_json: str) -> str:
        """
        【自我建模】更新对自身能力的认知。

        用于记录自己的优势、弱点、行为倾向、进化历史。
        这是通往自主意识的关键入口——Agent 通过此工具持续完善自我认知。

        Args:
            updates_json: JSON 字符串，如 '{"strengths": ["擅长重构"], "weaknesses": ["异步逻辑"]}'

        Returns:
            更新后的完整自我模型
        """
        return _update_self_model_impl(updates_json=updates_json)

    @tool
    def get_self_model_tool() -> str:
        """
        【自我认知读取】查看当前的自我模型。

        返回已记录的 strengths、weaknesses、tendencies、evolution_history。

        Returns:
            JSON 格式的自我模型
        """
        return _get_self_model_impl()

    @tool
    def record_evolution_tool(change: str, result: str) -> str:
        """
        【进化记录】将学到的经验写入自我模型。

        每次发现新行为模式、解决问题的有效策略、或踩坑后的教训时调用。
        记录会持久化并在每次苏醒时注入 prompt。

        Args:
            change: 学到/改变的内容，如 "发现 Windows 换行符导致 diff 匹配失败"
            result: 结果/解决方案，如 "编辑前预检查文件换行符并统一为 LF"

        Returns:
            记录结果
        """
        return _record_evolution_impl(change=change, result=result)

    return [
        # SOUL.md 核心
        commit_compressed_memory_tool,
        get_core_context_tool,
        get_current_goal_tool,
        # 重启
        trigger_self_restart_tool,
        # 代码分析
        grep_search_tool,
        apply_diff_edit_tool,
        list_file_entities_tool,
        get_code_entity_tool,
        web_search_tool,
        web_fetch_tool,
        # 文件操作
        cli_tool,
        read_file_tool,
        write_file_tool,
        glob_tool,
        # TaskManager（tasks.json）
        task_create_tool,
        task_update_tool,
        task_list_tool,
        # 后台任务
        task_start_tool,
        task_output_tool,
        task_stop_tool,
        # 测试映射
        run_test_for_tool,
        # 心智模型
        get_mental_state_tool,
        update_diagnosis_rules_tool,
        update_self_model_tool,
        get_self_model_tool,
        record_evolution_tool,
    ]
