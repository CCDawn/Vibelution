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

    # ── 子代理工具 ────────────────────────────────────────────────────────

    @tool
    def agent_tool(task: str, timeout: int = 120) -> str:
        """
        【子代理】启动一个子 Agent 进程执行指定任务。

        子 Agent 以 --auto 模式运行，完成后返回结果。
        适用于将复杂任务分解给独立 Agent 执行的场景。
        注意：最多嵌套 2 层，防止无限递归。

        Args:
            task: 要委托给子 Agent 的任务描述
            timeout: 超时时间（秒），默认 120

        Returns:
            JSON 格式的子 Agent 执行结果
        """
        from tools.agent_tools import spawn_agent
        return spawn_agent(task=task, timeout=timeout)

    # ── Cron 定时任务工具 ──────────────────────────────────────────────────

    @tool
    def cron_create_tool(name: str, command: str, schedule: str) -> str:
        """
        【创建定时任务】安排命令在指定时间或间隔执行。

        调度表达式：
        - "interval:N" — 每 N 秒执行一次
        - "*/5 * * * *" — 标准 5 字段 cron (分 时 日 月 周)

        Args:
            name: 任务名称
            command: 要执行的 Shell 命令
            schedule: 调度表达式（interval 或 cron）

        Returns:
            包含 job_id 的 JSON
        """
        from core.infrastructure.cron_scheduler import get_cron_scheduler
        sched = get_cron_scheduler()
        return sched.create_job(name=name, command=command, schedule=schedule)

    @tool
    def cron_list_tool() -> str:
        """
        【列出定时任务】查看所有已创建的定时任务及其运行状态。

        Returns:
            JSON 格式的任务列表
        """
        from core.infrastructure.cron_scheduler import get_cron_scheduler
        sched = get_cron_scheduler()
        return sched.list_jobs()

    @tool
    def cron_delete_tool(job_id: str) -> str:
        """
        【删除定时任务】删除指定 ID 的定时任务。

        Args:
            job_id: 任务 ID（来自 cron_create 的返回值或 cron_list 的 id 列）

        Returns:
            操作结果
        """
        from core.infrastructure.cron_scheduler import get_cron_scheduler
        sched = get_cron_scheduler()
        return sched.delete_job(job_id=job_id)

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
        web_fetch_tool,
        # 文件操作
        cli_tool,
        enter_hibernation_tool,
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
        # Cron 定时
        cron_create_tool,
        cron_list_tool,
        cron_delete_tool,
        # 子代理
        agent_tool,
    ]
