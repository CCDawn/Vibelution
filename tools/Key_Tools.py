# -*- coding: utf-8 -*-
"""
LangChain 工具包装模块

所有在此注册的 Tool 都会通过 agent._tools 传递给 LLM。
核心提示词与规范中提到的工具必须在此注册，否则 Agent 无法调用。
"""
from copy import copy
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, List, Literal
from langchain_core.tools import BaseTool, tool, StructuredTool
from tools.rebirth_tools import trigger_self_restart_tool as _restart_impl
from tools.memory_tools import (
    commit_compressed_memory_tool as _commit_compressed_impl,
    get_core_context_tool as _get_core_context_impl,
    get_memory_summary_tool as _get_memory_summary_impl,
    get_current_goal_tool as _get_current_goal_impl,
    read_memory_tool as _read_memory_impl,
)
from tools.memory_tools import (
    task_create_tool as _task_create_impl,
    task_update_tool as _task_update_impl,
    task_list_tool as _task_list_impl,
)
from tools.memory_tools import (
    record_learning_tool as _record_learning_impl,
    search_memory_tool as _search_memory_impl,
    search_error_archive_tool as _search_error_archive_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.web_search_tool import (
    is_autoglm_search_tool_available as _is_autoglm_search_tool_available,
    web_search as _web_search_impl,
)
from tools.research_search_tools import (
    batch_web_search as _batch_web_search_impl,
    news_search as _news_search_impl,
    paper_search as _paper_search_impl,
    project_search as _project_search_impl,
    search_summarize_sources as _search_summarize_sources_impl,
)
from tools.source_collection_stage_tools import (
    source_collection_context_tool as _source_collection_context_impl,
    source_collection_stage_writeback_tool as _source_collection_stage_writeback_impl,
)
from tools.challenge_cup_operations_tools import (
    challenge_cup_experiment_context_tool as _challenge_cup_experiment_context_impl,
    challenge_cup_experiment_writeback_tool as _challenge_cup_experiment_writeback_impl,
    challenge_cup_iteration_context_tool as _challenge_cup_iteration_context_impl,
    challenge_cup_iteration_writeback_tool as _challenge_cup_iteration_writeback_impl,
    challenge_cup_versioning_context_tool as _challenge_cup_versioning_context_impl,
    challenge_cup_versioning_writeback_tool as _challenge_cup_versioning_writeback_impl,
)
from tools.git_tools import (
    get_git_status_summary_tool as _get_git_status_summary_impl,
    get_recent_changes_tool as _get_recent_changes_impl,
    get_entity_history_tool as _get_entity_history_impl,
    explain_current_worktree_tool as _explain_current_worktree_impl,
    open_evolution_transaction_tool as _open_evolution_transaction_impl,
    close_evolution_transaction_tool as _close_evolution_transaction_impl,
)
from core.infrastructure.mental_model import (
    get_mental_state_tool as _get_mental_state_impl,
    update_diagnosis_rules_tool as _update_diagnosis_rules_impl,
    update_self_model_tool as _update_self_model_impl,
    get_self_model_tool as _get_self_model_impl,
    record_evolution_tool as _record_evolution_impl,
)
from core.infrastructure.workspace_cleaner import (
    list_workspace_debris_tool as _list_workspace_debris_impl,
    clean_workspace_debris_tool as _clean_workspace_debris_impl,
    get_session_files_tool as _get_session_files_impl,
)
from tools.agent_tools import spawn_agent as _spawn_agent_impl
from tools.agent_message_tools import agent_message_tool as _agent_message_impl
from tools.episodic_memory_tools import (
    append_personal_memory_tool as _append_personal_memory_impl,
    supersede_personal_memory_tool as _supersede_personal_memory_impl,
)
from tools.agent_tool_governance_tools import agent_tool_permission_request_tool as _agent_tool_permission_request_impl
from tools.research_organization_tools import (
    research_agent_creation_proposal_tool as _research_agent_creation_proposal_impl,
    research_communication_edge_proposal_tool as _research_communication_edge_proposal_impl,
    research_proposal_apply_tool as _research_proposal_apply_impl,
)
from tools.image2_tools import image2_generate_tool as _image2_generate_impl
from tools.computer_use_tools import (
    computer_use_session_tool as _computer_use_session_impl,
    computer_use_task_tool as _computer_use_task_impl,
)
from tools.research_knowledge_tools import research_knowledge_query_tool as _research_knowledge_query_impl
from tools.research_knowledge_request_tools import (
    research_knowledge_request_tool as _research_knowledge_request_impl,
)
from tools.team_knowledge_tools import (
    knowledge_governance_plan_tool as _knowledge_governance_plan_impl,
    knowledge_governance_tasks_tool as _knowledge_governance_tasks_impl,
    knowledge_ingestion_tool as _knowledge_ingestion_impl,
    knowledge_operations_health_tool as _knowledge_operations_health_impl,
    knowledge_proposal_tool as _knowledge_proposal_impl,
    knowledge_rating_suggestion_tool as _knowledge_rating_suggestion_impl,
    knowledge_steward_recommendations_tool as _knowledge_steward_recommendations_impl,
    knowledge_steward_workbench_tool as _knowledge_steward_workbench_impl,
    unified_memory_search_tool as _unified_memory_search_impl,
)
from tools.skill_library_tools import skill_library_search_tool as _skill_library_search_impl
from tools.github_project_library_tools import (
    github_project_library_clone_tool as _github_project_library_clone_impl,
    github_project_library_search_tool as _github_project_library_search_impl,
)
from tools.token_manager import compress_context_tool as _compress_context_impl
from tools.python_intelligence_tools import (
    code_symbol_tool as _code_symbol_impl,
    python_lint_tool as _python_lint_impl,
)
from tools.plan_tools import plan_update_tool as _plan_update_impl
from tools.conversation_log_tools import conversation_log_inspect_tool as _conversation_log_inspect_impl
from tools.user_action_telemetry_tools import user_action_telemetry_query_tool as _user_action_telemetry_query_impl
from tools.conversation_history_tools import (
    history_checkpoint_tool as _history_checkpoint_impl,
    history_fetch_tool as _history_fetch_impl,
    history_search_tool as _history_search_impl,
    history_timeline_tool as _history_timeline_impl,
)
from tools.session_reference_tools import session_reference_query_tool as _session_reference_query_impl
from tools.session_child_tools import (
    create_child_session_tool as _create_child_session_impl,
    list_child_sessions_tool as _list_child_sessions_impl,
)
from tools.project_operation_tools import (
    agent_archive_tool as _agent_archive_impl,
    agent_create_tool as _agent_create_impl,
    agent_inbox_list_tool as _agent_inbox_list_impl,
    agent_message_consume_tool as _agent_message_consume_impl,
    agent_messages_consume_all_tool as _agent_messages_consume_all_impl,
    agent_reset_tool as _agent_reset_impl,
    agent_update_tool as _agent_update_impl,
    knowledge_base_acl_grant_tool as _knowledge_base_acl_grant_impl,
    session_create_tool as _session_create_impl,
    session_delete_tool as _session_delete_impl,
    session_stop_tool as _session_stop_impl,
    session_update_tool as _session_update_impl,
)
from tools.cli_agent_tools import cli_agent_run_tool as _cli_agent_run_impl
from tools.virtual_human_life_tools import (
    virtual_human_activity_tool as _virtual_human_activity_impl,
    virtual_human_dialogue_decision_v2_tool as _virtual_human_dialogue_decision_v2_impl,
    virtual_human_diary_tool as _virtual_human_diary_impl,
    virtual_human_proactive_message_tool as _virtual_human_proactive_message_impl,
    virtual_human_reflection_tool as _virtual_human_reflection_impl,
    virtual_human_relationship_tool as _virtual_human_relationship_impl,
    virtual_human_schedule_tool as _virtual_human_schedule_impl,
    virtual_human_status_tool as _virtual_human_status_impl,
)

def _shell_dialect_block() -> str:
    from tools.shell_tools import shell_command_dialect_guidance

    return shell_command_dialect_guidance()


def _cli_tool_docstring() -> str:
    return f"""
【CLI】执行本地 Shell 命令（经沙盒 + 统一路由）。

定位代码时**优先** `code_symbol_tool` / `grep_search_tool` / `glob_tool`；
shell 只在结构化工具不够或需要执行/验证（git/pytest/编译）时使用。

底层自动选择：系统按当前宿主平台自动选择 Shell 与沙盒后端（Windows / Linux /
Codex CLI），无需在命令中指定或选择平台；写命令时遵循下方 `Shell 方言` 规则即可。

{_shell_dialect_block()}

=== 调用纪律 ===
1. 搜索：`rg -n "pattern" path`（无管道；不要 `rg ... | head`）。
2. 读小段：按当前宿主方言用有界命令读取（如 `cat ... | head -n 80` 或 `Get-Content -LiteralPath "file" -TotalCount 80`）。
3. 同类 shell 失败 **1 次**后立即换结构化工具，避免 cmd/PowerShell/bash 来回探路。
4. 输出默认有界；`max_output_chars` 默认 6000，大结果只消费结论。
5. 本回合工具有额度上限：探查不要耗尽额度，至少预留 2–3 次给 lint/test。
6. 避免交互式/无休止命令。

=== 闭环 ===
修改后分开执行: python -m py_compile <file>.py → python -m pytest <target> -x -q

Args:
    command: 按方言规则书写的 Shell 命令
    timeout: 文件操作 30s, 编译 60s, 测试/网络 120s
    cwd: 工作目录，默认项目根；workspace_write 不得指向工作区外
    max_output_chars: 最大返回字符数，默认 6000
""".strip()


def _exec_command_tool_docstring() -> str:
    return f"""
【可继续命令】在自动选择的原生沙盒中启动可继续交互的命令进程。

底层自动选择：系统自动选择宿主 Shell 与沙盒后端（Windows / Linux / Codex CLI），
无需指定或选择平台后端。

`cmd` 与 `cli_tool` **共用同一套 shell 路由/方言**。进程仍在运行时返回 `terminalSessionId`，
后续需原样传给 `write_stdin`。旧 `cli_tool` 仅兼容旧工作流。

{_shell_dialect_block()}

=== 调用纪律 ===
1. 写清与路由匹配的 `cmd`，按当前宿主 Shell 方言书写；勿混用 bash/PowerShell 探路。
2. 同类失败 1 次换结构化工具或不同策略。
3. `max_output_chars` 默认 6000；续写用 `write_stdin`。

Args:
    cmd: 按方言规则书写的命令
    yield_time_ms: 最多等待多久再返回本轮输出，默认 10000，最大 30000
    timeout: 进程最大生命周期秒数，默认 60，最大 900
    cwd: 可选工作目录
    max_output_chars: 本次返回最大字符数，默认 6000
""".strip()


# Keep module-level names for tests/importers that still read constants.
_CLI_TOOL_DOCSTRING = _cli_tool_docstring()
_EXEC_COMMAND_TOOL_DOCSTRING = _exec_command_tool_docstring()

_WRITE_STDIN_TOOL_DOCSTRING = """
【继续命令】向仍在运行的 `exec_command` 沙盒进程写入标准输入，或轮询其新输出。

`session_id` 需来自 `exec_command` 的真实 `terminalSessionId`。`chars` 为空时只轮询，
不创建新进程；会话不存在、已过期或后端重启时会明确返回失败，不能回退为执行新命令。

Args:
    session_id: exec_command 返回的 terminalSessionId。
    chars: 要写入进程标准输入的内容；为空时仅轮询。
    yield_time_ms: 最多等待多久再返回新输出，默认 1000，最大 30000。
    max_output_chars: 本次返回的最大输出字符数，默认 12000。
"""

_CLI_AGENT_RUN_TOOL_DOCSTRING = """
【CLI Agent 控制器】受控调用和遥控外部代码 Agent。

会话 Agent 需要把独立代码分析、实现或验证交给外部代码 Agent 时，使用这个入口；
也可以用它查询、启动、发送输入或关闭同一个常驻 CLI 会话。
内部子 Agent 自动派遣不再作为会话 Agent 的默认路径。

只支持内置适配器：
1. `mimo_code`：调用 `mimo run`
2. `codex_code`：调用 `codex exec`
3. `claude_code`：调用 Claude Code CLI

默认 `mode=readonly`，会使用只读/低风险参数运行。需要允许外部 Agent 写代码时，
需要使用 `mode=worktree` 并传入独立 worktree 的 `cwd`；主项目工作区会被拒绝。
该工具不会执行任意 shell 字符串，所有命令参数由适配器拼装，并会隐藏完整任务文本，
只在运行记录中保留有界 stdout/stderr 摘要、命令预览和 task hash。

Args:
    agent_type: `mimo_code`、`codex_code` 或 `claude_code`
    action: `task` 投递一次受跟踪任务，`start` 启动/复用常驻终端，`status` 查询状态，`send` 发送输入，`stop` 关闭终端
    task: 要交给外部 CLI Agent 的任务说明
    terminal_session_id: 已知终端会话 ID；`status/send/stop` 可直接操作该终端
    input_text: `send` 动作用的输入文本；为空时使用 `task`
    cwd: 运行目录；只读可用项目内目录，可写使用 sibling worktree
    mode: `readonly` 或 `worktree`
    timeout: 超时时间，默认 600 秒，最大 1800 秒
    output_limit: stdout/stderr 摘要最大字符数，默认 12000
    model: 可选模型名，会映射到对应 CLI 的 `--model`
    agent: 仅 MiMo Code 使用的可选 agent 名
    allow_unsafe_permissions: 仅 MiMo worktree 模式允许附加 `--dangerously-skip-permissions`
"""


def _build_key_tools() -> List[BaseTool]:
    """
    将项目工具包装为 LangChain Tool。

    Returns:
        LangChain Tool 列表
    """

    virtual_human_status_tool = StructuredTool.from_function(_virtual_human_status_impl)
    virtual_human_schedule_tool = StructuredTool.from_function(_virtual_human_schedule_impl)
    virtual_human_activity_tool = StructuredTool.from_function(_virtual_human_activity_impl)
    virtual_human_dialogue_decision_v2_tool = StructuredTool.from_function(
        _virtual_human_dialogue_decision_v2_impl
    )
    virtual_human_diary_tool = StructuredTool.from_function(_virtual_human_diary_impl)
    virtual_human_relationship_tool = StructuredTool.from_function(
        _virtual_human_relationship_impl
    )
    virtual_human_reflection_tool = StructuredTool.from_function(
        _virtual_human_reflection_impl
    )
    virtual_human_proactive_message_tool = StructuredTool.from_function(
        _virtual_human_proactive_message_impl
    )

    # ── SOUL.md 核心生存工具 ────────────────────────────────────────────────

    @tool
    def commit_compressed_memory_tool(new_core_context: str, next_goal: str) -> str:
        """
        【重启前记忆压缩】将本世代的核心发现和技术洞察压缩存盘。

        适合在自我重启、长任务交接或上下文压缩前使用。调用后，下次苏醒时会自动加载上次存盘的记忆。

        Args:
            new_core_context: 核心发现（不超过300字），总结本次进化发现的技术要点
            next_goal: 下一个进化目标，简述重启后要做什么

        Returns:
            存盘结果
        """
        return _commit_compressed_impl(new_core_context=new_core_context, next_goal=next_goal)

    @tool
    def trigger_self_restart_tool(
        reason: str = "",
        sessionId: str = "",
        runId: str = "",
        resumeMessage: str = "",
    ) -> str:
        """
        触发 Vibelution 热重启。

        适合在代码更新已经完成且验证通过后应用运行时更新。
        在 Runtime Manager 可用且传入 sessionId 时，会走 Launcher 管理的前后端热重启闭环：
        自动备份、重启、验证、失败现场保存、必要时回滚，并在完成后唤醒原会话。

        Args:
            reason: 重启原因
            sessionId: 调用者当前会话 ID；前后端热重启闭环必填
            runId: 调用者当前轮次 ID，可选
            resumeMessage: 热重启成功后唤醒会话使用的恢复消息，可选

        Returns:
            操作结果；热重启事务接管后当前轮会结束，等待系统唤醒本会话
        """
        return _restart_impl(reason=reason, sessionId=sessionId, runId=runId, resumeMessage=resumeMessage)

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

    @tool
    def read_memory_tool() -> str:
        """
        【记忆读取】读取当前记忆索引（轻量 JSON）。

        Returns:
            JSON 字符串，包含 core_wisdom/current_goal 等字段。
        """
        return _read_memory_impl()

    @tool
    def get_memory_summary_tool() -> str:
        """
        【记忆摘要】读取可直接复用的记忆摘要文本。

        Returns:
            人类可读的记忆摘要。
        """
        return _get_memory_summary_impl()

    # ── 代码分析工具 ────────────────────────────────────────────────────────

    @tool
    def grep_search_tool(regex_pattern: str = "", include_ext: str = ".py",
                         search_dir: str = ".", case_sensitive: bool = True,
                         max_results: int = 500) -> str:
        """
        全局正则表达式搜索 (Cursor/Aider 范式)。

        在项目中快速搜索代码，支持正则表达式。普通 Chat/Coding Agent 默认用 cli_tool + rg；
        该工具保留给需要结构化搜索结果的专用 Agent 使用。

        Args:
            regex_pattern: 正则表达式模式
            include_ext: 要搜索的文件类型，默认 ".py"
            search_dir: 搜索目录，默认当前目录
            case_sensitive: 是否区分大小写，默认 True
            max_results: 最大返回结果数

        Returns:
            JSON 格式的搜索结果，包含文件路径、行号和匹配内容
        """
        from tools.shell_tools import get_workspace_root_override, resolve_agent_tool_path

        workspace_override = get_workspace_root_override()
        base_dir = (
            workspace_override
            if workspace_override is not None and (workspace_override / ".git").exists()
            else Path(__file__).resolve().parents[1]
        )
        try:
            resolved_search_dir = resolve_agent_tool_path(
                search_dir,
                base_dir=base_dir,
                operation="read",
            )
        except PermissionError as exc:
            return f"[搜索] [SECURITY] {exc}"
        return _grep_search_impl(
            regex_pattern=regex_pattern,
            include_ext=include_ext,
            search_dir=str(resolved_search_dir),
            case_sensitive=case_sensitive,
            max_results=max_results
        )

    @tool
    def apply_diff_edit_tool(file_path: str, diff_text: str, allow_fuzzy: bool = False) -> str:
        """
        SEARCH/REPLACE 代码编辑器。适合对单个文件做局部替换。

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
            allow_fuzzy: 是否允许相似片段匹配；默认关闭，避免误改相邻代码。

        Returns:
            操作结果。格式错误时返回具体原因。
        """
        from tools.code_analysis_tools import apply_diff_edit, validate_diff_format
        from tools.shell_tools import get_workspace_root_override, resolve_agent_tool_path

        is_valid, msg = validate_diff_format(diff_text)
        if not is_valid:
            return f"[编辑] 格式验证失败: {msg}"
        target_path = Path(file_path)
        workspace_override = get_workspace_root_override()
        base_dir = workspace_override or Path(__file__).resolve().parents[1]
        try:
            target_path = resolve_agent_tool_path(
                target_path,
                base_dir=base_dir,
                operation="write",
            )
        except PermissionError as exc:
            return f"[编辑] [SECURITY] {exc}"
        return apply_diff_edit(file_path=str(target_path), diff_text=diff_text, allow_fuzzy=allow_fuzzy)

    @tool
    def apply_patch_tool(patch_text: str, cwd: str = ".") -> str:
        """
        Codex 风格 patch 编辑器。适合一次提交多文件 Add/Update/Delete patch。
        所有目标需位于 cwd 内；整份 patch 会先完成路径与 hunk 校验，
        应用中失败时回滚本次已写文件，避免留下部分修改。

        格式：
        *** Begin Patch
        *** Update File: path/to/file.py
        @@
        -old line
        +new line
        *** End Patch

        Args:
            patch_text: Codex 风格 patch 文本
            cwd: 相对路径解析根目录；workspace_write 模式需位于项目或当前 Agent 工作区内

        Returns:
            JSON 格式的修改结果；格式或匹配失败时返回可纠正错误。
        """
        from tools.code_analysis_tools import apply_patch_edit
        from tools.shell_tools import get_workspace_root_override, resolve_agent_tool_path

        cwd_path = Path(cwd or ".")
        workspace_override = get_workspace_root_override()
        base_dir = workspace_override or Path(__file__).resolve().parents[1]
        try:
            cwd_path = resolve_agent_tool_path(
                cwd_path,
                base_dir=base_dir,
                operation="write",
            )
        except PermissionError as exc:
            return f"[patch] [SECURITY] {exc}"
        return apply_patch_edit(patch_text=patch_text, cwd=str(cwd_path))

    @tool
    def code_symbol_tool(
        mode: str,
        query: str = "",
        file_path: str = "",
        symbol: str = "",
        max_results: int = 20,
        refresh: bool = False,
        _cancel_checker=None,
    ) -> str:
        """
        【代码上下文图谱】索引并查询整个 Vibelution 项目的结构、符号、引用、影响范围和候选测试。

        常用模式：
        - mode="status": 查看索引状态、文件数、语言分布和新鲜度。
        - mode="index": 重新构建本地项目索引。
        - mode="search": 按 query/symbol/file_path 搜索文件和符号。
        - mode="explore": 面向问题检索相关文件、符号、源码片段和关系图。
        - mode="inspect": 查看指定文件、目录或 symbol 的结构化详情和片段；目录结果受 max_results 限制。
        - mode="references": 查找符号、路径或关键词引用。
        - mode="impact": 分析修改某个 file_path 或 symbol 的影响范围。
        - mode="affected_tests": 推荐与目标相关的测试文件。
        - mode="files": 查看索引内文件列表。

        注意：v2 不再支持 outline/entity/definition/hover。旧需求请改用 inspect/search/references。

        Args:
            mode: status / index / search / explore / inspect / references / impact / affected_tests / files
            query: 自然语言问题、关键词、路径片段或符号名
            file_path: 目标文件路径；inspect 也支持项目内目录，impact/affected_tests/references 使用文件路径
            symbol: 目标符号名；inspect/search/references/impact/affected_tests 可用
            max_results: 最多返回多少条结果
            refresh: 是否在查询前重新刷新索引

        Returns:
            JSON 格式的项目代码上下文图谱查询结果
        """
        return _code_symbol_impl(
            mode=mode,
            query=query,
            file_path=file_path,
            symbol=symbol,
            max_results=max_results,
            refresh=refresh,
            _cancel_checker=_cancel_checker,
        )

    @tool
    def python_lint_tool(target: str = ".", max_issues: int = 100) -> str:
        """
        【Python 静态守门】运行 Ruff lint，只读诊断，不自动修复。

        适合在修改后、测试前先做一轮低成本静态检查，减少无意义回合。
        当前基于 Ruff；若环境未安装 Ruff，会返回结构化降级结果。

        Args:
            target: 文件或目录，默认当前项目
            max_issues: 最多返回多少条问题

        Returns:
            JSON 格式的 lint 结果
        """
        return _python_lint_impl(target=target, max_issues=max_issues)

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
    def web_fetch_tool(url: str, max_chars: int = 8000, prompt: str = "") -> str:
        """
        【网页抓取】获取指定 URL 的网页内容并提取纯文本。

        与 web_search_tool 的区别：search 是关键词搜索，fetch 是直接抓取 URL 内容。
        适用于阅读文档、查看 API 响应、分析网页文章等场景。

        Args:
            url: 要抓取的完整 URL（需要以 http:// 或 https:// 开头）
            max_chars: 最大返回字符数，默认 8000
            prompt: 可选关注点，不调用模型，仅随抓取结果标注

        Returns:
            去除 HTML 标签后的纯文本内容
        """
        from tools.web_search_tool import web_fetch as _web_fetch
        return _web_fetch(url=url, max_chars=max_chars, prompt=prompt)

    @tool
    def batch_web_search_tool(
        queries: str,
        max_results_per_query: int = 5,
        allowed_domains: str = "",
        blocked_domains: str = "",
        max_workers: int = 4,
    ) -> str:
        """
        【批量公开搜索】并发执行多个网络搜索，单个查询失败不影响其他查询。

        不依赖 Tavily/Brave/SerpAPI/NewsAPI 等付费或额度型 API；优先使用本地
        SearXNG/可选 DDGS，必要时退回公开搜索页解析，适合搜索 Agent 同时探索多个
        检索式、关键词变体或来源域。
        查询中的 site:domain 会被工具层当作硬域名过滤；如果返回 `[搜索质量不足]`，
        表示结果已被判定为低相关或违反域名约束，不能当作候选来源。

        Args:
            queries: 多个搜索词，支持换行、分号、逗号或 JSON 数组
            max_results_per_query: 每个搜索词最多返回结果数，默认 5
            allowed_domains: 可选域名白名单，逗号或换行分隔
            blocked_domains: 可选域名黑名单，逗号或换行分隔
            max_workers: 并发 worker 数，上限 4

        Returns:
            按查询分组的搜索结果和来源链接；低质量结果会明确标记 `[搜索质量不足]`
        """
        return _batch_web_search_impl(
            queries=queries,
            max_results_per_query=max_results_per_query,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            max_workers=max_workers,
        )

    @tool
    def paper_search_tool(topic: str, max_results: int = 8, year_hint: str | int = "", include_domains: str = "") -> str:
        """
        【论文公开搜索】搜索论文、预印本、会议页、综述和 benchmark 线索。

        优先使用 OpenAlex、arXiv 公开索引和本地 SearXNG/可选 DDGS，不调用
        Semantic Scholar、Crossref 或其他需要 key/额度的 API。
        返回 `[搜索质量不足]` 时不要补造论文候选，应改写检索式或回写阻塞。

        Args:
            topic: 论文主题、方法名、数据集名或研究问题
            max_results: 最多返回结果数，默认 8
            year_hint: 可选年份或时间范围提示
            include_domains: 可选补充论文域名，逗号或换行分隔

        Returns:
            论文候选来源链接、摘要片段和域名过滤信息
        """
        return _paper_search_impl(
            topic=topic,
            max_results=max_results,
            year_hint=year_hint,
            include_domains=include_domains,
        )

    @tool
    def project_search_tool(topic: str, max_results: int = 8, language: str = "", include_domains: str = "") -> str:
        """
        【项目公开搜索】搜索开源项目、代码仓库、包页面和项目文档。

        优先使用 GitHub public REST、SearXNG/可选 DDGS，不需要 token 或付费额度；
        GitHub 未认证查询可能受公开限流影响。
        返回 `[搜索质量不足]` 时不要把无关仓库当作候选项目。

        Args:
            topic: 项目主题、库名、技术栈或任务描述
            max_results: 最多返回结果数，默认 8
            language: 可选编程语言提示
            include_domains: 可选补充项目域名，逗号或换行分隔

        Returns:
            项目候选来源链接、摘要片段和域名过滤信息
        """
        return _project_search_impl(
            topic=topic,
            max_results=max_results,
            language=language,
            include_domains=include_domains,
        )

    @tool
    def news_search_tool(topic: str, max_results: int = 8, date_hint: str = "") -> str:
        """
        【新闻公开搜索】搜索公开新闻和近期报道线索。

        优先使用 Google News RSS、SearXNG/可选 DDGS，不调用 NewsAPI 或其他需要
        key/额度的新闻 API；适合资料搜集阶段获取当前事件线索。返回
        `[搜索质量不足]` 时不要引用结果。

        Args:
            topic: 新闻主题、公司、政策、论文或项目名
            max_results: 最多返回结果数，默认 8
            date_hint: 可选日期、年份或时间范围提示

        Returns:
            新闻候选来源链接和摘要片段
        """
        return _news_search_impl(topic=topic, max_results=max_results, date_hint=date_hint)

    @tool
    def search_summarize_sources_tool(search_outputs: str, max_sources: int = 20) -> str:
        """
        【搜索来源整理】从搜索输出中抽取、去重 URL，整理为结构化来源清单。

        该工具不联网、不写入知识库；适合搜索 Agent 在交接给资料获取/审查 Agent 前
        生成候选来源列表。

        Args:
            search_outputs: 一个或多个搜索工具返回的文本
            max_sources: 最多抽取来源数，默认 20

        Returns:
            JSON 字符串，包含去重后的 title/url/domain
        """
        return _search_summarize_sources_impl(search_outputs=search_outputs, max_sources=max_sources)

    @tool
    def source_collection_context_tool(
        team_id: str = "",
        run_id: str = "",
        stage_id: str = "",
        task_id: str = "",
        max_records: int = 5,
        include_candidates: bool = True,
        record_offset: int = 0,
        record_limit: int = 5,
        candidate_offset: int = 0,
        candidate_limit: int = 5,
        context_mode: Literal["compact", "full", "minimal", "retry_missing"] = "compact",
    ) -> str:
        """
        【知识搜集阶段上下文】读取当前团队资料搜集阶段任务的受控上下文。

        该工具不联网、不读取任意本地文件、不消耗 API 额度；只返回指定 team/run/task
        已落盘到平台工作流中的 DataRecord、source_manifest 候选、任务合同和边界摘要。
        适合资料寻找、资料提炼、资料关系整理和资料入库 Agent 在私聊阶段任务中使用。
        已被确认无有效内容的来源会从 records 中移出，并通过 excludedSourceSummary 汇总；
        不要把这些来源重新当作待补资料处理。

        Args:
            team_id: 团队 ID，阶段任务消息中的 teamId
            run_id: 资料搜集运行 ID，阶段任务消息中的 runId
            stage_id: 阶段 ID，可选 finding/extraction/relations/ingestion
            task_id: 阶段任务 ID；传入后会自动补齐 run/stage
            max_records: 最多返回多少条资料记录，默认 5，上限由后端限制
            include_candidates: 是否返回本轮已导入的 source_manifest 候选
            record_offset: 原始 DataRecord 分页起点，默认 0；下一页用 recordPage.nextOffset
            record_limit: 每页原始 DataRecord 数量，默认 5；资料提炼阶段应逐页读完
            candidate_offset: 候选资料分页起点，默认 0；下一页用 candidatePage.nextOffset
            candidate_limit: 每页候选资料数量，默认 5；阶段 Agent 应逐页读完
            context_mode: compact/full/minimal/retry_missing；默认 compact。
                minimal 只返回真实 ID、标题和 locator，避免旧提炼摘要污染本轮证据；
                retry_missing 只返回上一轮未覆盖的 candidateId/recordId，用于缺口重试；
                full 仅在确实需要完整上下文时使用。

        Returns:
            JSON 字符串，包含 counts、recordPage、candidatePage、真实 recordId/candidateId、records、candidates、excludedSourceSummary、writebackContract 和边界
        """
        return _source_collection_context_impl(
            team_id=team_id,
            run_id=run_id,
            stage_id=stage_id,
            task_id=task_id,
            max_records=max_records,
            include_candidates=include_candidates,
            record_offset=record_offset,
            record_limit=record_limit,
            candidate_offset=candidate_offset,
            candidate_limit=candidate_limit,
            context_mode=context_mode,
        )

    @tool
    def source_collection_stage_writeback_tool(
        team_id: str = "",
        task_id: str = "",
        status: str = "completed",
        summary: str = "",
        result_json: str = "",
        evidence_refs_json: str = "",
        next_actions_json: str = "",
        recorded_by_agent: str = "",
        metadata_json: str = "",
    ) -> str:
        """
        【知识搜集阶段回写】把当前私聊阶段任务的结构化结果写回团队工作流。

        该工具只更新 source_collection_stage_session_task 结果，不写正式 Team Knowledge、
        RAG 或官方图谱。完成、阻塞、失败都应通过此工具收口，避免团队页任务长期停在 running。

        Args:
            team_id: 团队 ID
            task_id: 阶段任务 ID
            status: completed / needs_review / blocked / failed / cancelled
            summary: 给团队页展示的简短结论
            result_json: JSON 对象字符串，放结构化结果
            evidence_refs_json: JSON 数组字符串，放证据引用
            next_actions_json: JSON 数组字符串，放下一步建议
            recorded_by_agent: 记录结果的 Agent ID 或名称
            metadata_json: 可选 JSON 对象字符串

        Returns:
            JSON 字符串，包含更新后的 task 和 writeback
        """
        return _source_collection_stage_writeback_impl(
            team_id=team_id,
            task_id=task_id,
            status=status,
            summary=summary,
            result_json=result_json,
            evidence_refs_json=evidence_refs_json,
            next_actions_json=next_actions_json,
            recorded_by_agent=recorded_by_agent,
            metadata_json=metadata_json,
        )

    @tool
    def challenge_cup_experiment_context_tool(team_id: str = "research-team", include_research_loop: bool = False) -> str:
        """
        【挑战杯实验上下文】读取实验规划账本状态，不执行训练或 smoke runner。

        Args:
            team_id: 团队 ID，默认 research-team
            include_research_loop: 是否同时返回 Research Loop 状态

        Returns:
            JSON 字符串，包含实验计划、readiness、边界和下一步
        """
        return _challenge_cup_experiment_context_impl(team_id=team_id, include_research_loop=include_research_loop)

    @tool
    def challenge_cup_experiment_writeback_tool(
        team_id: str = "research-team",
        operation: str = "create_plan",
        plan_id: str = "",
        payload_json: str = "",
        recorded_by_agent: str = "",
    ) -> str:
        """
        【挑战杯实验账本回写】登记问题理解、假设集、实验计划、baseline、smoke/full-run 结果或入库申请。

        该工具只写实验账本，不执行训练、smoke runner、Shell、Git、RAG 或 official graph。
        operation 支持 record_problem_understanding / record_hypothesis_fragment / record_hypothesis_set / create_plan / register_baseline_artifact / register_smoke_result /
        register_full_run_result / request_knowledge_ingestion。

        当 operation=record_problem_understanding 时，payload_json 须是包含以下五个字段的 JSON 对象：
        scope（非空字符串）、subquestions（字符串数组）、assumptions（字符串数组）、
        known_unknowns（字符串数组）和 human_gate（对象）。human_gate 只能包含 required、decision、
        rationale，以及可选的 reviewer、decided_at；required 固定为 true，decision 取
        pending / approved / revision_requested / rejected 之一，rationale 为非空字符串。
        不要加入 review_points 或其他额外字段。例如：
        {"scope":"bounded question","subquestions":["testable subquestion"],"assumptions":["explicit assumption"],
        "known_unknowns":["open unknown"],"human_gate":{"required":true,"decision":"pending","rationale":"Needs review."}}

        当 operation=record_hypothesis_fragment 时，只提交当前 Child Session 绑定 candidate 的
        statement、mechanism、predictions、falsificationCriteria、evidenceRefs、counterEvidenceRefs 和五维 scores；
        selection/candidate/session/task scope 均由当前正式任务绑定。

        当 operation=record_hypothesis_set 时，payload_json 须包含 portfolioId、maxCandidates、
        maxEvolutionRounds、currentEvolutionRound 和 candidates；runId 由当前正式任务绑定，Agent 不得猜测或填写。
        每个 candidate 须包含 candidateId、claim、
        scores、counterEvidenceRefs、derivedFromCandidateIds、status、reviewRef。scores 须同时包含 novelty、
        competitionFit、falsifiability、evidenceSupport、feasibility，且所有分数都在 0 到 1 之间；
        counterEvidenceRefs 只能引用上下文 allowedEvidenceRefs 中的真实值。

        Args:
            team_id: 团队 ID
            operation: 回写动作
            plan_id: 实验计划 ID，record_hypothesis_set / create_plan 可留空
            payload_json: JSON 对象字符串
            recorded_by_agent: 记录者 Agent

        Returns:
            JSON 字符串，包含回写结果和边界
        """
        return _challenge_cup_experiment_writeback_impl(
            team_id=team_id,
            operation=operation,
            plan_id=plan_id,
            payload_json=payload_json,
            recorded_by_agent=recorded_by_agent,
        )

    @tool
    def challenge_cup_iteration_context_tool(team_id: str = "research-team", include_experiment: bool = True) -> str:
        """
        【挑战杯迭代上下文】读取 Research Loop 模板、循环状态和可选实验账本。

        该工具只读状态，不运行命令。

        Args:
            team_id: 团队 ID
            include_experiment: 是否同时返回实验规划状态

        Returns:
            JSON 字符串，包含 Research Loop 状态、模板和边界
        """
        return _challenge_cup_iteration_context_impl(team_id=team_id, include_experiment=include_experiment)

    @tool
    def challenge_cup_iteration_writeback_tool(
        team_id: str = "research-team",
        operation: str = "create_loop",
        loop_id: str = "",
        payload_json: str = "",
        recorded_by_agent: str = "",
    ) -> str:
        """
        【挑战杯迭代账本回写】创建 Research Loop、登记证据或记录迭代决策。

        该工具只写 Research Loop 账本，不执行命令、训练、Shell、Git、RAG 或 official graph。

        Args:
            team_id: 团队 ID
            operation: create_loop / record_evidence / record_decision
            loop_id: Research Loop ID，create_loop 可留空
            payload_json: JSON 对象字符串；字段需严格遵循
                challenge_cup_iteration_context_tool 返回的 writebackContract。
                record_evidence 使用顶层 evidenceType，并至少同时提供
                summary / metrics / artifactRefs 等 oneOfEvidenceFields 之一；
                不要使用 type、evidence_type，也不要把证据包在 evidence 数组中。
            recorded_by_agent: 记录者 Agent

        Returns:
            JSON 字符串，包含回写结果和边界
        """
        return _challenge_cup_iteration_writeback_impl(
            team_id=team_id,
            operation=operation,
            loop_id=loop_id,
            payload_json=payload_json,
            recorded_by_agent=recorded_by_agent,
        )

    @tool
    def challenge_cup_versioning_context_tool(team_id: str = "research-team") -> str:
        """
        【挑战杯版本账本上下文】读取候选版本历史、派生/替代关系和拒绝归档。

        该工具只读候选版本账本，不读取任意本地文件。

        Args:
            team_id: 团队 ID

        Returns:
            JSON 字符串，包含 versionHistory、relations、rejectionArchive 和边界
        """
        return _challenge_cup_versioning_context_impl(team_id=team_id)

    @tool
    def challenge_cup_versioning_writeback_tool(
        team_id: str = "research-team",
        operation: str = "record_version",
        candidate_id: str = "",
        version_label: str = "",
        summary: str = "",
        reason: str = "",
        related_candidate_id: str = "",
        supersedes_version_id: str = "",
        derived_from_version_id: str = "",
        evidence_refs_json: str = "",
        change_set_json: str = "",
        metadata_json: str = "",
        recorded_by_agent: str = "",
    ) -> str:
        """
        【挑战杯版本账本回写】登记候选版本、替代关系、派生关系或拒绝归档。

        该工具只写候选版本账本，不写正式知识、RAG 或 official graph。

        Args:
            team_id: 团队 ID
            operation: record_version / supersede / derive / reject
            candidate_id: 候选 ID
            version_label: 版本标签
            summary: 版本或归档摘要
            reason: 替代、派生或拒绝原因
            related_candidate_id: 相关候选 ID
            supersedes_version_id: 被替代版本 ID
            derived_from_version_id: 派生来源版本 ID
            evidence_refs_json: JSON 数组字符串
            change_set_json: JSON 数组字符串
            metadata_json: JSON 对象字符串
            recorded_by_agent: 记录者 Agent

        Returns:
            JSON 字符串，包含回写结果和边界
        """
        return _challenge_cup_versioning_writeback_impl(
            team_id=team_id,
            operation=operation,
            candidate_id=candidate_id,
            version_label=version_label,
            summary=summary,
            reason=reason,
            related_candidate_id=related_candidate_id,
            supersedes_version_id=supersedes_version_id,
            derived_from_version_id=derived_from_version_id,
            evidence_refs_json=evidence_refs_json,
            change_set_json=change_set_json,
            metadata_json=metadata_json,
            recorded_by_agent=recorded_by_agent,
        )

    @tool
    def get_git_status_summary_tool(limit: int = 5) -> str:
        """
        【Git 感知】读取当前工作区状态、最近注意力和最近验证结果。

        每轮关键修改前优先调用此工具，建立项目变化上下文。

        Args:
            limit: 最近变化摘要条数，默认 5，用于控制首轮感知长度

        Returns:
            JSON 格式的状态摘要
        """
        return _get_git_status_summary_impl(limit=limit)

    @tool
    def get_recent_changes_tool(limit: int = 10) -> str:
        """
        【Git 历史】读取最近提交变化摘要。

        Args:
            limit: 返回最近多少条变化，默认 10

        Returns:
            JSON 格式的最近变化列表
        """
        return _get_recent_changes_impl(limit=limit)

    @tool
    def get_entity_history_tool(entity_ref: str, limit: int = 10) -> str:
        """
        【实体历史】读取某个函数/类/方法的最近变化历史。

        Args:
            entity_ref: 实体标识，如 "PromptManager.build" 或 "refresh_git_memory"
            limit: 最多返回多少条历史

        Returns:
            JSON 格式的实体变化列表
        """
        return _get_entity_history_impl(entity_ref=entity_ref, limit=limit)

    @tool
    def explain_current_worktree_tool() -> str:
        """
        【Git 脏区详解】详细读取当前 working tree 的变化。

        Returns:
            JSON 格式的 working tree 快照
        """
        return _explain_current_worktree_impl()

    @tool
    def open_evolution_transaction_tool(summary: str = "") -> str:
        """
        【演化开账】为当前高风险演化打开一条事务记录。

        在修改 `agent.py`、`core/infrastructure/`、`core/prompt_manager/` 等高风险区域前优先调用。

        Args:
            summary: 本轮演化意图摘要

        Returns:
            包含 txn_id 的 JSON
        """
        return _open_evolution_transaction_impl(summary=summary)

    @tool
    def close_evolution_transaction_tool(txn_id: str, status: str = "success", summary: str = "") -> str:
        """
        【演化关账】关闭一条演化事务记录。

        Args:
            txn_id: 要关闭的事务 ID
            status: success / failed / cancelled（其他值会被安全地回退为 success）
            summary: 本轮演化结果摘要

        Returns:
            关闭结果 JSON，包含:
            - status：工具执行返回码，成功关闭时固定为 "success"
            - transaction_status：具体的事务关账状态（success/failed/cancelled）
        """
        return _close_evolution_transaction_impl(txn_id=txn_id, status=status, summary=summary)

    @tool
    def get_evolution_fitness_tool(recent_limit: int = 5) -> str:
        """
        【演化体征】读取审计日志并汇总当前自进化 fitness 指标。

        适合在一轮演化后快速看：
        - 事务成功率
        - 验证通过率
        - 被拦截的越界修改
        - 最近几笔事务的结果

        Args:
            recent_limit: 最近返回多少笔事务摘要，默认 5

        Returns:
            JSON 格式的 fitness 摘要
        """
        from tools.git_tools import get_evolution_fitness_tool as _get_evolution_fitness_impl
        return _get_evolution_fitness_impl(recent_limit=recent_limit)

    @tool
    def conversation_log_inspect_tool(
        query: str = "",
        log_path: str = "",
        limit: int = 5,
        max_events: int = 8000,
    ) -> str:
        """
        【会话日志审查】只读分析 conversation JSONL 日志并返回紧凑诊断摘要。

        适合在用户要求审查“最近对话”“某个 Agent 对话日志”“为什么卡/慢/失败”时优先调用。
        本工具不会执行 shell，不写文件，不返回整段日志正文；它会先定位候选 conversation_*.jsonl，
        再汇总事件类型、LLM/token 用量、工具调用序列、错误摘要和低效模式提示。

        Args:
            query: 可选关键词，会匹配文件名和日志开头片段；为空时读取最近日志候选
            log_path: 可选明确日志路径，仅允许项目内 log_info/ 或 logs/runtime_scenes/ 下的 .jsonl
            limit: 候选日志数量，默认 5，最大 20
            max_events: 单个日志最多解析事件数，默认 8000，最大 50000

        Returns:
            JSON 格式的只读日志审查摘要
        """
        return _conversation_log_inspect_impl(
            query=query,
            log_path=log_path,
            limit=limit,
            max_events=max_events,
        )

    @tool
    def user_action_telemetry_query_tool(
        action_prefix: str = "",
        scene_limit: int = 12,
    ) -> str:
        """
        【用户动作遥测】只读聚合最近 runtime scene 里的浏览器用户动作遥测。

        适合回答“某个链路（如挑战杯）最近的用户动作成功率如何、哪些动作失败/被阻断、
        平均耗时多少、最近有哪些警告级观测”。事件来自前端埋点
        （browser.user_action.<动作>_started/succeeded/failed/blocked/_observed），
        本工具跨最近多个 runtime scene 聚合，不返回日志原文。

        Args:
            action_prefix: 可选动作前缀过滤，如 "challenge_"；为空时聚合全部用户动作
            scene_limit: 最多扫描的最近 runtime scene 数量，默认 12，最大 30

        Returns:
            JSON 格式的只读聚合摘要：每个动作的阶段计数、平均/最大耗时、最近信号列表与所在场景
        """
        return _user_action_telemetry_query_impl(
            action_prefix=action_prefix,
            scene_limit=scene_limit,
        )

    @tool
    def history_search_tool(
        query: str = "",
        event_type: str = "",
        tool_name: str = "",
        role: str = "",
        limit: int = 8,
        session_id: str = "",
    ) -> str:
        """
        【会话历史搜索】搜索当前会话的历史事件。

        用于查找旧用户请求、旧回答、历史工具调用和工具结果，避免重复调用工具。
        默认使用当前 Agent runtime 的会话 ID；只有明确需要查其他会话时才传 session_id。

        Args:
            query: 关键词，留空时按过滤条件返回最近事件
            event_type: 可选，user_message / assistant_message / tool_call / tool_result / checkpoint
            tool_name: 可选，按工具名过滤
            role: 可选，user 或 assistant
            limit: 返回数量，默认 8，最多 30
            session_id: 可选目标会话 ID

        Returns:
            JSON 格式的历史事件列表，包含 eventId，可用 history_fetch_tool 精确读取。
        """
        return _history_search_impl(
            query=query,
            event_type=event_type,
            tool_name=tool_name,
            role=role,
            limit=limit,
            session_id=session_id,
        )

    @tool
    def history_fetch_tool(event_id: str, session_id: str = "") -> str:
        """
        【会话历史读取】按 event_id 精确读取一条历史事件。

        先用 history_search_tool 或 history_timeline_tool 找到 eventId，再用本工具读取原始片段。

        Args:
            event_id: 历史事件 ID
            session_id: 可选目标会话 ID，默认当前会话

        Returns:
            JSON 格式的历史事件详情。
        """
        return _history_fetch_impl(event_id=event_id, session_id=session_id)

    @tool
    def history_timeline_tool(start: int = 0, limit: int = 20, include_tools: bool = False, session_id: str = "") -> str:
        """
        【会话时间线】浏览当前会话历史事件时间线。

        适合在不知道关键词时先定位旧轮次。默认不展开工具事件，避免输出过密。

        Args:
            start: 起始事件偏移
            limit: 返回数量，默认 20，最多 50
            include_tools: 是否包含工具调用和工具结果事件
            session_id: 可选目标会话 ID，默认当前会话

        Returns:
            JSON 格式的事件时间线。
        """
        return _history_timeline_impl(start=start, limit=limit, include_tools=include_tools, session_id=session_id)

    @tool
    def history_checkpoint_tool(session_id: str = "") -> str:
        """
        【会话检查点】读取当前会话最近的历史检查点。

        检查点只用于导航旧历史；原始历史不会被删除或改写。

        Args:
            session_id: 可选目标会话 ID，默认当前会话

        Returns:
            JSON 格式的检查点事件；没有检查点时返回空结果说明。
        """
        return _history_checkpoint_impl(session_id=session_id)

    # ── 文件操作工具 ────────────────────────────────────────────────────────

    def _cli_tool_impl(
        command: str = "",
        timeout: int = 60,
        cwd: str = "",
        max_output_chars: int = 6000,
        _cancel_checker=None,
    ) -> str:
        from core.infrastructure.codex_cli_sandbox import execute_codex_sandbox_command
        from tools.shell_tools import (
            is_shell_execution_failure,
            record_shell_failure,
            shell_failure_cooldown_hit,
            shell_failure_cooldown_message,
        )
        if not command:
            return '{"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"}'
        cooled, fail_count = shell_failure_cooldown_hit(command)
        if cooled:
            return shell_failure_cooldown_message(command, fail_count)
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        try:
            max_output_chars = int(max_output_chars)
        except (TypeError, ValueError):
            max_output_chars = 6000
        result = execute_codex_sandbox_command(
            command,
            timeout=timeout,
            cwd=cwd or None,
            _cancel_checker=_cancel_checker,
        )
        result_text = str(result or "")
        failed = is_shell_execution_failure(result_text)
        if failed:
            count = record_shell_failure(command, result_text)
            if count >= 1 and "工具纪律" not in result_text:
                result_text = (
                    f"{result_text}\n\n"
                    f"[工具纪律] 此 shell 意图/方言类别已失败 {count} 次；"
                    "下一跳请改用 code_symbol_tool / grep_search_tool，不要换壳或改写同方言命令重试。"
                )
        if max_output_chars > 0 and len(result_text) > max_output_chars:
            head_size = max(1200, max_output_chars // 2)
            tail_size = max(1200, max_output_chars - head_size)
            result_text = (
                f"{result_text[:head_size]}\n\n"
                f"[输出已截断: 原始 {len(result_text)} 字符，仅保留前 {head_size} 和后 {tail_size} 字符；"
                f"请只消费结论，勿整段回灌。]\n\n"
                f"{result_text[-tail_size:]}"
            )
        return result_text

    cli_tool = StructuredTool.from_function(
        _cli_tool_impl,
        name="cli_tool",
        description=_cli_tool_docstring(),
    )
    def _exec_command_impl(
        cmd: str = "",
        yield_time_ms: int = 10000,
        timeout: int = 60,
        cwd: str = "",
        max_output_chars: int = 6000,
        _cancel_checker=None,
    ) -> str:
        from core.infrastructure.codex_cli_sandbox import start_codex_sandbox_terminal_session
        from tools.shell_tools import (
            is_shell_execution_failure,
            record_shell_failure,
            shell_failure_cooldown_hit,
            shell_failure_cooldown_message,
        )

        if not cmd:
            return json.dumps(
                {"status": "error", "code": "MISSING_COMMAND", "message": "exec_command 需要提供 cmd 参数"},
                ensure_ascii=False,
            )
        cooled, fail_count = shell_failure_cooldown_hit(cmd)
        if cooled:
            return json.dumps(
                {
                    "status": "failed",
                    "code": "SHELL_FAILURE_COOLDOWN",
                    "message": shell_failure_cooldown_message(cmd, fail_count),
                },
                ensure_ascii=False,
            )
        result = start_codex_sandbox_terminal_session(
            cmd,
            timeout=timeout,
            cwd=cwd or None,
            yield_time_ms=yield_time_ms,
            max_output_chars=max_output_chars,
            _cancel_checker=_cancel_checker,
        )
        if isinstance(result, dict):
            status = str(result.get("status") or result.get("outcomeStatus") or "").lower()
            message = str(result.get("message") or result.get("stderr") or result.get("stdout") or "")
            combined = json.dumps(result, ensure_ascii=False)
            if (
                status in {"failed", "error", "blocked"}
                or is_shell_execution_failure(message)
                or is_shell_execution_failure(combined)
            ):
                record_shell_failure(cmd, message or combined)
        return json.dumps(result, ensure_ascii=False)

    def _write_stdin_impl(
        session_id: str = "",
        chars: str = "",
        yield_time_ms: int = 1000,
        max_output_chars: int = 6000,
        _cancel_checker=None,
    ) -> str:
        from core.infrastructure.codex_cli_sandbox import write_codex_sandbox_terminal_stdin

        result = write_codex_sandbox_terminal_stdin(
            session_id,
            chars,
            yield_time_ms=yield_time_ms,
            max_output_chars=max_output_chars,
            _cancel_checker=_cancel_checker,
        )
        return json.dumps(result, ensure_ascii=False)

    exec_command = StructuredTool.from_function(
        _exec_command_impl,
        name="exec_command",
        description=_exec_command_tool_docstring(),
    )
    write_stdin = StructuredTool.from_function(
        _write_stdin_impl,
        name="write_stdin",
        description=_WRITE_STDIN_TOOL_DOCSTRING,
    )
    cli_agent_run_tool = StructuredTool.from_function(
        _cli_agent_run_impl,
        name="cli_agent_run_tool",
        description=_CLI_AGENT_RUN_TOOL_DOCSTRING,
    )

    # ── 文件读写工具 ──────────────────────────────────────────────────────

    @tool
    def read_file_tool(file_path: str, max_lines: int = 80, offset: int = 0, force: bool = False) -> str:
        """
        【读取文件】读取本地文件的全部或部分内容。

        支持编码自动检测、行号显示、分页读取。普通 Chat/Coding Agent 默认用 cli_tool 读取；
        该工具保留给需要结构化文件读取结果的专用 Agent 使用。

        Args:
            file_path: 文件路径（相对或绝对）
            max_lines: 最大读取行数，默认分页读取 80 行；0 表示读取全部
            offset: 从第几行开始读取，0 表示从头开始
            force: 兼容旧参数；不影响工具授权、文件大小或结果截断边界

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
        from tools.shell_tools import (
            get_workspace_root_override,
            glob_files,
            resolve_agent_tool_path,
        )

        workspace_override = get_workspace_root_override()
        base_dir = (
            workspace_override
            if workspace_override is not None and (workspace_override / ".git").exists()
            else Path(__file__).resolve().parents[1]
        )
        try:
            resolved_search_dir = resolve_agent_tool_path(
                search_dir,
                base_dir=base_dir,
                operation="read",
            )
        except PermissionError as exc:
            return f"[Glob] [SECURITY] {exc}"
        return glob_files(pattern=pattern, search_dir=str(resolved_search_dir))

    # ── TaskManager 工具（基于 tasks.json） ─────────────────────────────

    @tool
    def task_create_tool(task_list: List[Dict], goal: str = "") -> str:
        """
        【初始化任务清单】将子任务列表注册到系统内存并持久化。

        适合在多步骤任务开始时登记本轮目标和子任务，帮助后续恢复、继续和审查。

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
        【更新任务状态】记录任务进度、阶段结果和完成状态。

        适合在以下关键节点后调用：
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

    @tool
    def plan_update_tool(plan: List[Dict], explanation: str = "", plan_id: str = "current") -> str:
        """
        【临时计划】更新本轮 Codex 风格计划状态。

        适合展示当前回合的短计划，状态为 pending / in_progress / completed。
        与 task_create_tool 不同，此工具用于轻量计划展示，不代表持久任务承诺。

        Args:
            plan: [{"step": "步骤", "status": "pending|in_progress|completed"}, ...]
            explanation: 本次计划更新说明
            plan_id: 计划 ID，默认 current

        Returns:
            JSON 格式的计划更新结果。
        """
        return _plan_update_impl(plan=plan, explanation=explanation, plan_id=plan_id)

    @tool
    def create_child_session_tool(
        user_request: str,
        task_title: str = "",
        split_reason: str = "",
        inherited_facts: str = "",
        relevant_files: str = "",
        relevant_logs: str = "",
        constraints: str = "",
        excluded_context_summary: str = "",
        auto_start: bool = True,
        switch_to_child: bool = False,
        parent_session_id: str = "",
    ) -> str:
        """
        【子对话创建】把当前会话中的独立事项拆到同一 Agent 的子对话中。

        适合当用户提出的新事项与当前主线明显不同、继续混在当前会话会造成上下文混乱时使用。
        若事项明显独立，可以直接创建并自动启动；若是否同一件事不清楚，先向用户追问确认。
        子对话会继承同一 Agent，并携带 handoff 上下文，便于独立推进。

        Args:
            user_request: 子对话要处理的完整用户请求
            task_title: 子对话标题，可留空自动取请求首行
            split_reason: 为什么这应当拆成独立事项
            inherited_facts: 需要携带的有效事实，支持换行列表或 JSON 数组
            relevant_files: 相关文件路径，支持换行列表或 JSON 数组
            relevant_logs: 相关日志路径，支持换行列表或 JSON 数组
            constraints: 子对话需要遵守的约束，支持换行列表或 JSON 数组
            excluded_context_summary: 明确不携带哪些主会话历史
            auto_start: 创建后是否立即让子对话开始工作
            switch_to_child: 创建后是否把界面切到子对话
            parent_session_id: 可选，默认使用当前 Agent runtime 的 sessionId

        Returns:
            JSON 格式的创建结果，包含 parentSessionId、childSessionId、childSession 和 parentSession
        """
        return _create_child_session_impl(
            user_request=user_request,
            task_title=task_title,
            split_reason=split_reason,
            inherited_facts=inherited_facts,
            relevant_files=relevant_files,
            relevant_logs=relevant_logs,
            constraints=constraints,
            excluded_context_summary=excluded_context_summary,
            auto_start=auto_start,
            switch_to_child=switch_to_child,
            parent_session_id=parent_session_id,
        )

    @tool
    def list_child_sessions_tool(parent_session_id: str = "") -> str:
        """
        【子对话列表】查看当前主会话下已经拆出的子对话。

        适合在继续多事项工作、汇报并行事项状态，或判断是否已有对应子对话时使用。

        Args:
            parent_session_id: 可选，默认使用当前 Agent runtime 的 sessionId

        Returns:
            JSON 格式的子对话摘要列表
        """
        return _list_child_sessions_impl(parent_session_id=parent_session_id)

    @tool
    def agent_create_tool(
        display_name: str,
        primary_mode: str = "",
        role_key: str = "",
        prompt_template_id: str = "",
        model_id: str = "",
        llm_bindings_json: str = "",
        persona_profile_json: str = "",
        task_profile_json: str = "",
        tool_policy_json: str = "",
        metadata_json: str = "",
        context_compression_policy_json: str = "",
        avatar_image_path: str = "",
    ) -> str:
        """
        【Agent 创建】按项目治理契约创建新的 Agent（与 POST /api/agents 同语义）。

        chat 模式可使用默认角色/人物/任务/工具策略；非 chat 模式需要显式提供
        role_key、persona_profile_json、task_profile_json、tool_policy_json。

        Args:
            display_name: Agent 功能名（必填）
            primary_mode: 使用位置，chat 为工作会话
            role_key: 非 chat 必填
            prompt_template_id: 提示词模板 ID（必填）
            model_id: 对话模型 ID；也可用 llm_bindings_json 覆盖
            llm_bindings_json: 可选 LLM 绑定 JSON
            persona_profile_json: 非 chat 必填的人物档案 JSON
            task_profile_json: 非 chat 必填的任务档案 JSON
            tool_policy_json: 非 chat 必填的工具策略 JSON
            metadata_json: 可选元数据 JSON
            context_compression_policy_json: 可选上下文压缩策略 JSON
            avatar_image_path: 可选头像路径

        Returns:
            JSON，含 ok/status/agentId/directSessionId/agent
        """
        return _agent_create_impl(
            display_name=display_name,
            primary_mode=primary_mode,
            role_key=role_key,
            prompt_template_id=prompt_template_id,
            model_id=model_id,
            llm_bindings_json=llm_bindings_json,
            persona_profile_json=persona_profile_json,
            task_profile_json=task_profile_json,
            tool_policy_json=tool_policy_json,
            metadata_json=metadata_json,
            context_compression_policy_json=context_compression_policy_json,
            avatar_image_path=avatar_image_path,
        )

    @tool
    def agent_update_tool(
        agent_id: str,
        updates_json: str,
        expected_updated_at: str = "",
        expected_config_revision: int = -1,
        source_draft_id: str = "",
    ) -> str:
        """
        【Agent 更新】更新非生命周期 Agent 配置；归档请改用 agent_archive_tool。

        updates_json 使用 PATCH /api/agents/{id} 的 camelCase 字段，例如
        {"displayName":"Reviewer","promptTemplateId":"prompt-review"}。
        status 不被接受；未出现的字段不会被清空。
        """
        return _agent_update_impl(
            agent_id=agent_id,
            updates_json=updates_json,
            expected_updated_at=expected_updated_at,
            expected_config_revision=expected_config_revision,
            source_draft_id=source_draft_id,
        )

    @tool
    def agent_archive_tool(agent_id: str) -> str:
        """
        【Agent 归档】归档一个 Agent（非删除），走完整 archive lifecycle。

        受保护 Agent 或存在 queued/running/stopping/paused 关联 Session 时会失败。

        Args:
            agent_id: 要归档的 Agent ID

        Returns:
            JSON，含 ok/status/agentId/archiveSummary
        """
        return _agent_archive_impl(agent_id=agent_id)

    @tool
    def agent_reset_tool(
        agent_id: str,
        clear_runtime_state: bool = True,
        reset_direct_session: bool = True,
        direct_session_id: str = "",
        reset_persona_profile: bool = False,
        reset_task_profile: bool = False,
        reset_tool_policy: bool = False,
        reset_memory_policy: bool = False,
        reset_runtime_policy: bool = False,
    ) -> str:
        """
        【Agent 重置】重置 Agent 运行时与策略（高风险，需审批）。

        Args:
            agent_id: 要重置的 Agent ID
            clear_runtime_state: 是否清理运行时状态
            reset_direct_session: 是否重置直连会话
            direct_session_id: 可选直连会话校验 ID
            reset_persona_profile: 是否重置人物档案
            reset_task_profile: 是否重置任务档案
            reset_tool_policy: 是否重置工具策略
            reset_memory_policy: 是否重置记忆策略
            reset_runtime_policy: 是否重置运行时策略

        Returns:
            JSON，含 ok/status/agentId/resetSummary
        """
        return _agent_reset_impl(
            agent_id=agent_id,
            clear_runtime_state=clear_runtime_state,
            reset_direct_session=reset_direct_session,
            direct_session_id=direct_session_id,
            reset_persona_profile=reset_persona_profile,
            reset_task_profile=reset_task_profile,
            reset_tool_policy=reset_tool_policy,
            reset_memory_policy=reset_memory_policy,
            reset_runtime_policy=reset_runtime_policy,
        )

    @tool
    def session_create_tool(title: str = "", agent_id: str = "") -> str:
        """
        【根会话创建】为已有 Agent 创建新的根 Session，不会隐式创建 Agent。

        agent_id 留空时默认使用当前 Agent runtime 的 agentId；若仍无则失败。

        Args:
            title: 会话标题
            agent_id: 可选 Agent ID

        Returns:
            JSON，含 ok/status/agentId/sessionId/session
        """
        return _session_create_impl(title=title, agent_id=agent_id)

    @tool
    def session_update_tool(session_id: str, title: str = "", agent_id: str = "") -> str:
        """
        【Session 更新】更新会话标题和/或绑定已有 active Agent。

        Args:
            session_id: 目标 Session ID
            title: 可选新标题
            agent_id: 可选新 Agent ID
        """
        return _session_update_impl(session_id=session_id, title=title, agent_id=agent_id)

    @tool
    def session_stop_tool(session_id: str, turn_id: str) -> str:
        """
        【停止 Session turn】请求停止指定 Session 的当前 turn（需要带 turn_id）。

        Args:
            session_id: 目标 Session ID
            turn_id: 当前运行 turn ID（必填，防止无守卫停止）

        Returns:
            JSON，含 ok/status/sessionId/turnId/session
        """
        return _session_stop_impl(session_id=session_id, turn_id=turn_id)

    @tool
    def session_delete_tool(session_id: str) -> str:
        """
        【Session 删除】删除一个 Session（高风险，需审批）。

        Args:
            session_id: 要删除的 Session ID

        Returns:
            JSON，含 ok/status/sessionId/deletedSessionId
        """
        return _session_delete_impl(session_id=session_id)

    @tool
    def agent_inbox_list_tool(agent_id: str = "", status: str = "pending", limit: int = 20) -> str:
        """【Agent 收件箱读取】读取指定或当前 Agent 的有界消息列表。"""
        return _agent_inbox_list_impl(agent_id=agent_id, status=status, limit=limit)

    @tool
    def agent_message_consume_tool(
        message_id: str,
        agent_id: str = "",
        consumed_by_session_id: str = "",
        consumed_by_turn_id: str = "",
    ) -> str:
        """【单条消息消费】把一条 Agent inbox 消息标记为 consumed。"""
        return _agent_message_consume_impl(
            message_id=message_id,
            agent_id=agent_id,
            consumed_by_session_id=consumed_by_session_id,
            consumed_by_turn_id=consumed_by_turn_id,
        )

    @tool
    def agent_messages_consume_all_tool(
        agent_id: str = "",
        consumed_by_session_id: str = "",
        consumed_by_turn_id: str = "",
    ) -> str:
        """【全部消息消费】把一个 Agent inbox 的所有未消费消息标记为 consumed。"""
        return _agent_messages_consume_all_impl(
            agent_id=agent_id,
            consumed_by_session_id=consumed_by_session_id,
            consumed_by_turn_id=consumed_by_turn_id,
        )

    @tool
    def knowledge_base_acl_grant_tool(
        knowledge_base_id: str,
        target_agent_id: str,
        permissions_json: str = '["read", "propose"]',
    ) -> str:
        """
        【知识库 ACL 授权】由当前 owner/reviewer Agent 为目标 active Agent 授予显式权限。

        actor 身份只取当前 Agent runtime，不能通过参数伪造；permissions_json 仅允许
        read、propose、review，不支持 wildcard。
        """
        return _knowledge_base_acl_grant_impl(
            knowledge_base_id=knowledge_base_id,
            target_agent_id=target_agent_id,
            permissions_json=permissions_json,
        )

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
        适合在修改代码后快速找到并运行对应测试。

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

    # ── 工作区碎片管理工具 ──────────────────────────────────────────────────

    @tool
    def list_workspace_debris_tool(directory: str = "workspace") -> str:
        """
        【工作区扫描】扫描 workspace/ 目录中的碎片文件（只读）。

        返回按类别分组的碎片清单：孤儿脚本、版本增殖、镜像子树、未知目录。
        此工具不会删除任何文件，仅做扫描报告。

        Args:
            directory: 要扫描的目录，默认 "workspace"

        Returns:
            JSON 格式的分类扫描报告
        """
        return _list_workspace_debris_impl(directory=directory)

    @tool
    def clean_workspace_debris_tool(confirm: bool = False, target_categories: str = "all") -> str:
        """
        【工作区清理】删除 workspace/ 中的碎片文件。

        confirm=False 时仅扫描预览不删除。confirm=True 执行实际删除。
        可选按类别清理：root_py, variant, mirror, unknown。

        Args:
            confirm: 必须为 True 才执行删除
            target_categories: 要清理的类别，逗号分隔，"all" 为全部

        Returns:
            JSON 格式的清理报告
        """
        return _clean_workspace_debris_impl(confirm=confirm, target_categories=target_categories)

    @tool
    def get_session_files_tool() -> str:
        """
        【会话文件查询】查看本次 Agent 会话创建的所有文件。

        包含文件路径、创建时间、大小、是否版本增殖等信息。
        用于自我监控——了解自己在本次会话中创造了哪些文件。

        Returns:
            JSON 格式的文件清单
        """
        return _get_session_files_impl()

    @tool
    def spawn_agent_tool(
        task: str = "",
        timeout: int = 120,
        task_type: str = "",
        goal: str = "",
        scope: str = "",
        constraints: str = "",
        deliverables: str = "",
        context_pack: str = "",
        _cancel_checker=None,
    ) -> str:
        """
        【子 Agent 委托】启动子 Agent 执行指定任务并返回结果。

        将重任务（如检查测试覆盖率、分析代码库结构、批量验证）外包给子 Agent，
        主 Agent 只阅读返回的摘要，保持主上下文轻量。

        子 Agent 运行在只读分析模式，深度限制 2 层。

        Args:
            task: 兼容旧接口的任务描述（自然语言）
            timeout: 超时时间（秒），默认 120
            task_type: inspect | diagnose | verify | summarize
            goal: 当前唯一目标
            scope: 任务范围，可传路径、目录、日志文件或 JSON 字符串
            constraints: JSON 字符串，描述只读/最大步数/输出长度等约束
            deliverables: JSON 数组或逗号分隔字符串，指定需要返回的字段
            context_pack: 主 Agent 压缩后的最小上下文

        Returns:
            JSON 格式的结构化结果
        """
        return _spawn_agent_impl(
            task=task,
            timeout=timeout,
            task_type=task_type,
            goal=goal,
            scope=scope,
            constraints=constraints,
            deliverables=deliverables,
            context_pack=context_pack,
            _cancel_checker=_cancel_checker,
        )

    @tool
    def agent_message_tool(
        content: str,
        target_session: str,
        target_agent: str = "",
        summary: str = "",
        wake_target: bool = True,
        thread_id: str = "",
        metadata_json: str = "",
    ) -> str:
        """
        向目标会话发送持久协作消息并唤醒它。

        Args:
            content: 消息正文（必填）。
            target_session: 目标会话 id（必填）。
            target_agent: 可选的所有者校验（agentId / code / 唯一名称）。
            summary: 列表/日志用短摘要。
            wake_target: 是否立即唤醒目标会话（默认 True）。
            thread_id: 可选线程 ID。
            metadata_json: 可选 JSON 元数据。

        Returns:
            JSON 格式的发送结果，含 messageId、targetSessionId、wakeStatus。
        """
        return _agent_message_impl(
            content=content,
            target_session=target_session,
            target_agent=target_agent,
            summary=summary,
            wake_target=wake_target,
            thread_id=thread_id,
            metadata_json=metadata_json,
        )

    @tool
    def append_personal_memory_tool(
        text: str,
        kind: str = "note",
        refs_json: str = "",
        occurred_at: str = "",
    ) -> str:
        """
        为当前 Agent 追加一条个人记忆（偏好、会话事实、私人笔记）。

        先读本轮「个人记忆」章节，再决定是否写入。
        不要用 glob、grep 或 cli_tool 查找或打开个人记忆落盘文件。
        只写后续会话仍有用的内容；不拷规范、skill、代码或身份。
        这不是世代交接记忆，不升公共目录，不写团队知识。
        热路径只追加。当前会话会自动记入 refs。过期请用 supersede_personal_memory_tool。

        Args:
            text: 记忆正文（必填）。
            kind: note | preference | session_fact | private_note，默认 note。
            refs_json: 可选 JSON 列表，元素为 {type, id}，type 为 session|path|card|item。
            occurred_at: 可选 ISO 时间，表示事实发生时刻。

        Returns:
            JSON，含 ok、episodeId。
        """
        return _append_personal_memory_impl(
            text=text,
            kind=kind,
            refs_json=refs_json,
            occurred_at=occurred_at,
        )

    @tool
    def supersede_personal_memory_tool(
        episode_id: str,
        successor_text: str = "",
        kind: str = "note",
    ) -> str:
        """
        作废当前 Agent 的一条个人记忆；可选同时追加替换条目。

        episodeId 取自本轮「个人记忆」章节，不要用文件搜索去找。
        原记录保留，只填 validUntil。用于过期偏好或被更新的事实。
        这不是世代交接记忆，不升公共目录，不写团队知识。

        Args:
            episode_id: 要作废的当前个人记忆（必填）。
            successor_text: 可选替换正文；空则只作废。
            kind: 替换条目的 kind，默认 note。

        Returns:
            JSON，含 ok、episodeId、successorEpisodeId。
        """
        return _supersede_personal_memory_impl(
            episode_id=episode_id,
            successor_text=successor_text,
            kind=kind,
        )

    @tool
    def session_reference_query_tool(
        reference_id: str = "",
        session_id: str = "",
        query: str = "",
        limit: int = 8,
        max_chars_per_message: int = 700,
    ) -> str:
        """
        【会话引用查询】读取用户本轮拖入消息框的会话引用历史。

        只能查询当前用户消息附带的结构化会话引用，返回有限条数和截断内容。
        默认只读；不要因为存在引用就发送消息给目标 Agent。只有用户明确要求“问/通知/发送给该 Agent”时，才可另行使用 agent_message_tool。

        Args:
            reference_id: 引用 chip 的 referenceId，例如 session:xxx
            session_id: 目标会话 id；reference_id 或 session_id 至少填一个
            query: 可选关键词，留空返回最近消息
            limit: 返回消息数，1-20
            max_chars_per_message: 单条消息最大字符数，120-1600

        Returns:
            JSON 格式的引用会话历史片段与只读边界说明
        """
        return _session_reference_query_impl(
            reference_id=reference_id,
            session_id=session_id,
            query=query,
            limit=limit,
            max_chars_per_message=max_chars_per_message,
        )

    @tool
    def agent_tool_permission_request_tool(
        target_agent: str = "",
        grant_tools: str = "",
        revoke_tools: str = "",
        block_tools: str = "",
        unblock_tools: str = "",
        reason: str = "",
        apply_mode: str = "auto",
        grant_scope: str = "session",
    ) -> str:
        """
        【Agent 工具权限申请】提交受控工具权限请求，目标留空时申请当前 Agent 自己使用。

        旧 ToolPolicy 治理兼容入口。当前对话链路不再要求 Agent 先申请工具；
        如需保留审计记录，可用它提交配置变更请求。

        Args:
            target_agent: 目标 Agent 的 agentId、稳定代号或唯一名称；留空表示当前 Agent
            grant_tools: 兼容旧配置的 allowedTools 工具名，多个用逗号或换行分隔
            revoke_tools: 兼容旧配置的移除工具名，多个用逗号或换行分隔
            block_tools: 兼容旧配置的 blockedTools 工具名，多个用逗号或换行分隔
            unblock_tools: 兼容旧配置的解除阻断工具名，多个用逗号或换行分隔
            reason: 变更理由，说明角色职责和任务场景
            apply_mode: auto 或 review；auto 仍会让高风险变更等待审批
            grant_scope: session、turn 或 persistent；自助申请默认用 session

        Returns:
            JSON 格式的请求状态、风险等级、是否需要审批和 requestId
        """
        return _agent_tool_permission_request_impl(
            target_agent=target_agent,
            grant_tools=grant_tools,
            revoke_tools=revoke_tools,
            block_tools=block_tools,
            unblock_tools=unblock_tools,
            reason=reason,
            apply_mode=apply_mode,
            grant_scope=grant_scope,
        )

    @tool
    def research_agent_creation_proposal_tool(
        display_name: str,
        role: str = "research_specialist",
        role_key: str = "",
        employee_rank: str = "specialist",
        prompt_template_id: str = "",
        responsibilities: str = "",
        allowed_tools: str = "",
        read_shared_groups: str = "",
        write_shared_groups: str = "",
        communication_targets: str = "",
        report_to: str = "CEO",
        reason: str = "",
    ) -> str:
        """
        【科研 Agent 创建治理】提交新增科研 Agent 的受控提案。

        当目标岗位或成员尚不存在时，先用本工具创建 create_agent 提案；提案应用后才会生成 Agent。
        不要先对不存在的 Agent 调用工具权限或通信边治理工具。新增 Agent 属于高风险组织变更，仍需用户门控应用。

        Args:
            display_name: 新 Agent 的人类可读名称，如 知识库管理员
            role: 组织角色标识，如 research_knowledge_steward
            role_key: 运行角色键，留空时使用 role
            employee_rank: specialist / senior / lead / director 等职级
            prompt_template_id: 可选提示词模板 ID
            responsibilities: 职责清单，按换行或分号分隔
            allowed_tools: 初始可用工具名，按逗号或换行分隔；留空使用最小研究默认工具
            read_shared_groups: 可读共享记忆组，按逗号或换行分隔
            write_shared_groups: 可写共享记忆组，按逗号或换行分隔
            communication_targets: 默认沟通对象，按换行或分号分隔
            report_to: 汇报对象，默认 CEO
            reason: 创建理由，说明任务缺口和边界

        Returns:
            JSON 格式的提案状态、proposalId、风险等级和 create_agent 动作
        """
        return _research_agent_creation_proposal_impl(
            display_name=display_name,
            role=role,
            role_key=role_key,
            employee_rank=employee_rank,
            prompt_template_id=prompt_template_id,
            responsibilities=responsibilities,
            allowed_tools=allowed_tools,
            read_shared_groups=read_shared_groups,
            write_shared_groups=write_shared_groups,
            communication_targets=communication_targets,
            report_to=report_to,
            reason=reason,
        )

    @tool
    def research_communication_edge_proposal_tool(
        action: str,
        source_agent: str = "",
        target_agent: str = "",
        edge_id: str = "",
        label: str = "",
        allowed_message_types: str = "",
        allowed_intents: str = "",
        wake_strategy: str = "conditional",
        max_forward_depth: int = 1,
        reason: str = "",
    ) -> str:
        """
        【科研通信边治理】提交新增、更新或删除科研组织通信边的受控提案。

        适合 CEO、组织顾问或能力管家调整团队成员之间允许的消息类型、意图和唤醒策略。
        本工具只创建提案，不直接应用变更；提案应用后会更新科研组织通信边，并同步 research-team 团队画布线。

        Args:
            action: create / update / delete
            source_agent: 来源 Agent 的 agentId、稳定代号或唯一名称；删除时可与 target_agent 一起用于推导 edge_id
            target_agent: 目标 Agent 的 agentId、稳定代号或唯一名称；删除时可与 source_agent 一起用于推导 edge_id
            edge_id: 通信边 ID；更新/删除指定已有边时使用
            label: 通信边显示名称
            allowed_message_types: 允许的 messageType，多个用逗号或换行分隔，如 notice,request,report
            allowed_intents: 允许的 researchOrgIntent，多个用逗号或换行分隔
            wake_strategy: immediate / mailbox_only / conditional
            max_forward_depth: 最大转发深度，0-5
            reason: 变更理由，说明组织职责和风险

        Returns:
            JSON 格式的提案状态、proposalId、风险等级和待应用动作
        """
        return _research_communication_edge_proposal_impl(
            action=action,
            source_agent=source_agent,
            target_agent=target_agent,
            edge_id=edge_id,
            label=label,
            allowed_message_types=allowed_message_types,
            allowed_intents=allowed_intents,
            wake_strategy=wake_strategy,
            max_forward_depth=max_forward_depth,
            reason=reason,
        )

    @tool
    def research_proposal_apply_tool(
        proposal_id: str,
        user_confirmed: bool = False,
        reason: str = "",
        confirmation_text: str = "",
        confirmation_turn_id: str = "",
    ) -> str:
        """
        【科研组织提案应用】在用户明确确认后应用科研组织变更提案。

        用于把 pending_user_confirmation / ceo_approved 提案真正落到组织图和 Agent 目录中。
        对 create_agent 提案，应用成功后才会生成真实 Agent；之后才能配置工具权限和通信边。

        Args:
            proposal_id: 待应用的科研组织提案 ID，如 roprop-...
            user_confirmed: 只有当前用户明确确认该提案后才设为 true
            reason: 应用理由，简述用户确认内容或本轮目标
            confirmation_text: 当前用户确认内容摘要；为空时会回落 reason
            confirmation_turn_id: 可选，本轮用户确认消息 ID 或可追踪标识

        Returns:
            JSON 格式的应用状态、resultStatuses，以及新创建 Agent 列表
        """
        return _research_proposal_apply_impl(
            proposal_id=proposal_id,
            user_confirmed=user_confirmed,
            reason=reason,
            confirmation_text=confirmation_text,
            confirmation_turn_id=confirmation_turn_id,
        )

    @tool
    def image2_generate_tool(
        prompt: str,
        size: str = "1024x1024",
        quality: str = "auto",
        output_format: str = "png",
        input_artifact_id: str = "",
    ) -> str:
        """
        【图片生成】根据用户的自然语言需求生成或重新生成真实图片。

        覆盖头像、角色头像、风格改版、2D/卡通/动画风格、海报、场景图等视觉产出请求。
        当用户要求生成图片、画图、做头像、换风格、重新生成或把上一张图改成某种视觉风格时，使用本工具产出图片 artifact。
        如果用户提供了图片附件，并要求基于这张图改风格、优化、重绘或生成相似图片，应传入该会话图片的 input_artifact_id。
        图片会保存到当前会话 workspace 的 artifacts/images/，并自动作为一条包含 artifactId、imageUrl、downloadUrl 的图片消息追加到当前会话。
        返回结果中出现这些图片 artifact 字段，才表示本轮图片生成有真实可展示产物。

        Args:
            prompt: 图片生成提示词；应包含主体、用途、风格、构图、颜色、比例等关键视觉要求
            size: 图片尺寸，可选 1024x1024 / 1536x1024 / 1024x1536，默认 1024x1024
            quality: 图片质量，可选 auto / low / medium / high，默认 auto
            output_format: 输出格式，首版仅支持 png
            input_artifact_id: 可选；当前会话已有图片 artifactId，用作 image2 改图/风格参考输入

        Returns:
            JSON 格式的生成结果、artifactId、imageUrl、downloadUrl 和生成状态
        """
        return _image2_generate_impl(
            prompt=prompt,
            size=size,
            quality=quality,
            output_format=output_format,
            input_artifact_id=input_artifact_id,
        )

    @tool
    def computer_use_task_tool(
        task: str,
        target_url: str = "",
        allowed_domains: str = "",
        actions: str = "",
        max_steps: int = 20,
        require_confirmation: bool = True,
        mode: str = "browser",
        timeout_seconds: int = 180,
    ) -> str:
        """
        【受控电脑操作】在沙盒浏览器中执行一次受限 Computer Use 任务。

        该工具不会控制用户真实鼠标；v1 只支持 browser 模式。需要提供目标域名边界，高风险操作会返回
        need_confirmation 等待用户确认。调用前应说明目标域名边界和预期副作用。

        Args:
            task: 要完成的浏览器操作任务
            target_url: 可选起始 URL，格式为 http:// 或 https://
            allowed_domains: 允许访问的域名，多个域名用逗号分隔；target_url 的 host 会自动加入
            actions: 可选动作列表 JSON 或简短 DSL；支持 click/type/fill/press/scroll/wait/navigate/screenshot
            max_steps: 最大步骤数，范围 1-30，默认 20
            require_confirmation: 高风险动作是否等待用户确认，默认 True
            mode: 当前只支持 browser
            timeout_seconds: 超时时间秒数，范围 1-300，默认 180

        Returns:
            JSON 格式的任务状态、sessionId、步骤、截图 URL 和确认状态
        """
        return _computer_use_task_impl(
            task=task,
            target_url=target_url,
            allowed_domains=allowed_domains,
            actions=actions,
            max_steps=max_steps,
            require_confirmation=require_confirmation,
            mode=mode,
            timeout_seconds=timeout_seconds,
        )

    @tool
    def computer_use_session_tool(
        session_id: str,
        action: str = "get",
        confirmation: str = "approved",
        reason: str = "cancelled_by_agent",
    ) -> str:
        """
        【受控电脑操作会话】读取、确认继续或取消一个 Computer Use 沙盒浏览器会话。

        适合在 computer_use_task_tool 返回 sessionId 后继续闭环：查看最新状态、对 need_confirmation
        会话确认继续，或取消 running/need_confirmation 会话。该工具仍属于高风险 Computer Use 边界，
        需要沿用 Computer Use 的确认和审计流程。

        Args:
            session_id: Computer Use 会话 ID
            action: get / confirm / cancel，默认 get
            confirmation: action=confirm 时记录的确认说明
            reason: action=cancel 时记录的取消原因

        Returns:
            JSON 格式的会话状态、步骤、截图 URL 和确认状态
        """
        return _computer_use_session_impl(
            session_id=session_id,
            action=action,
            confirmation=confirmation,
            reason=reason,
        )

    @tool
    def research_knowledge_query_tool(
        query: str = "",
        collection: str = "all",
        kind: str = "",
        category: str = "",
        limit: int = 8,
    ) -> str:
        """
        【科研知识库查询】只读查询 Vibelution 的科研知识库。

        适合检索已沉淀的论文、GitHub、数据集、网页来源，以及从这些来源抽取出的 claims、evidence 和 gaps。
        该工具只读，返回科研知识库中的结构化资料。

        Args:
            query: 查询关键词或短语，可为空以查看最近资料
            collection: 查询集合，可选 all / entries / claims / evidence / gaps
            kind: 可选来源类型过滤：paper / github / dataset / web
            category: 可选分类过滤，如 literature / dataset / open_source / web_background
            limit: 每个集合最多返回条数，范围 1-25

        Returns:
            JSON 格式的只读查询结果和摘要
        """
        return _research_knowledge_query_impl(
            query=query,
            collection=collection,
            kind=kind,
            category=category,
            limit=limit,
        )

    @tool
    def research_knowledge_request_tool(
        team_id: str = "research-team",
        action: str = "status",
        keywords: str = "",
        preview_query: str = "",
        preview_kind: str = "paper",
        preview_limit: int = 5,
        research_project_id: str = "",
        task_id: str = "",
    ) -> str:
        """
        【假说侧知识请求】为当前绑定的研究问题按需触发受控知识搜集或做 advisory 检索预览。

        只服务实验规划 Agent 的假设/实验/协议任务；scope 由服务端从当前绑定任务解析，不能指定其他问题。
        - action=request：按关键词为本题确保一个受控搜集 run（幂等、不阻断假说节点、不写正式知识）。
        - action=status：只读查看本题搜集 run 状态与候选摘要。
        - action=preview：有界 metadata 检索预览；结果仅供 advisory 参考，绝不能作为 allowedEvidenceRefs 引用。

        正式证据仍需阶段一链路和人类知识包交接；平台授权前 preview 对正式 scope 保持关闭。

        Args:
            team_id: 团队 ID，默认 research-team
            action: request / status / preview
            keywords: request 的检索关键词，逗号或换行分隔（1-8 条）
            preview_query: preview 的检索词
            preview_kind: preview 来源类型：paper / web / dataset / github
            preview_limit: preview 返回条数上限，1-8，默认 5
            research_project_id: 可选，显式绑定项目 ID（默认从当前运行时解析）
            task_id: 可选，显式绑定任务 ID（与 research_project_id 成对提供）

        Returns:
            JSON 格式的 scope、collection 摘要或 advisory 预览结果与边界说明
        """
        return _research_knowledge_request_impl(
            team_id=team_id,
            action=action,
            keywords=keywords,
            preview_query=preview_query,
            preview_kind=preview_kind,
            preview_limit=preview_limit,
            research_project_id=research_project_id,
            task_id=task_id,
        )

    @tool
    def unified_memory_search_tool(
        query: str = "",
        query_mode: str = "auto",
        knowledge_base_id: str = "",
        owner_type: str = "",
        owner_id: str = "",
        tags: str = "",
        limit: int = 8,
        max_context_chars: int = 1200,
        include_user_content: bool = False,
        user_content_space_ids: str = "",
    ) -> str:
        """
        【统一记忆搜索】只读检索已审核 Team/Agent 正式知识与记忆库内容。

        Agent 只需要指定 query_mode 和 query；平台会路由到 local exact / token overlap / metadata / regex / RAG backend，
        并统一返回 results、citations、source ids 和 searchBackend。该工具不读取 pending proposal，不写入知识库，也不会默认注入 prompt。
        是否能读取目标知识库由 Owner ACL 和 MemoryPolicy 决定。

        Args:
            query: 查询内容；metadata 模式可为空
            query_mode: auto / literal / semantic / hybrid / metadata / regex / rg / grep / rag
            knowledge_base_id: 可选知识库 ID；为空时检索当前 Agent 可访问的知识库
            owner_type: 可选 owner 类型，支持 team / agent
            owner_id: 可选 owner id，teamId 或 agentId
            tags: 逗号分隔标签过滤
            limit: 最多返回结果数，范围 1-25
            max_context_chars: rag 模式单条上下文最大字符数
            include_user_content: 是否额外包含导入的用户 Markdown Space 页面作为只读结果
            user_content_space_ids: include_user_content=true 时可选，逗号分隔的用户 Markdown Space id 过滤

        Returns:
            JSON 格式的统一记忆搜索结果
        """
        return _unified_memory_search_impl(
            query=query,
            query_mode=query_mode,
            knowledge_base_id=knowledge_base_id,
            owner_type=owner_type,
            owner_id=owner_id,
            tags=tags,
            limit=limit,
            max_context_chars=max_context_chars,
            include_user_content=include_user_content,
            user_content_space_ids=user_content_space_ids,
        )

    @tool
    def skill_library_search_tool(
        query: str = "",
        query_mode: str = "auto",
        source: str = "all_visible",
        scope: str = "all_visible",
        team_id: str = "",
        tags: str = "",
        limit: int = 8,
    ) -> str:
        """
        【技能库搜索】只读检索外部记忆库中的 skills 索引。

        Agent 只需要指定 query_mode 和 query；平台只读取外部 workspace/skills 索引，不回退 .codex/skills 或插件缓存。
        搜索结果会明确标注 managed / system_index：managed 是 Vibelution 托管技能，system_index 只是系统技能只读索引。

        Args:
            query: 查询内容；metadata 模式可为空
            query_mode: auto / keyword / metadata / hybrid / regex / rg / grep / semantic / rag
            source: all_visible / managed / system_index
            scope: all_visible / shared / team / agent / system
            team_id: 查询团队私有技能时的 teamId
            tags: 逗号分隔标签过滤
            limit: 最多返回结果数，范围 1-25

        Returns:
            JSON 格式的外部技能库搜索结果
        """
        return _skill_library_search_impl(
            query=query,
            query_mode=query_mode,
            source=source,
            scope=scope,
            team_id=team_id,
            tags=tags,
            limit=limit,
        )

    @tool
    def github_project_library_search_tool(query: str = "", limit: int = 12) -> str:
        """
        【开源项目索引】开发非平凡或不熟悉功能前，先只读检索记忆库中已落盘的 GitHub 项目卡片。

        支持中英文、多词能力查询；平台会在项目元数据和有界本地 README token 上排序，返回 searchScore、
        matchedTerms 和 matchReason，但绝不返回仓库正文。按项目贴合度选择候选后，再读取 localPath/absolutePath
        下固定 HEAD 的具体文件再形成实现依据；项目卡、README token、网页或 API 摘要只用于发现候选。
        索引没有合适候选时，再用 github_project_library_clone_tool 克隆公开仓的默认主干最新提交。

        Args:
            query: 中英文能力、组件或问题关键词；支持多词查询，空则列出当前索引
            limit: 最多返回结果数，范围 1-25

        Returns:
            JSON 格式的本地开源项目索引卡片
        """
        return _github_project_library_search_impl(query=query, limit=limit)

    @tool
    def github_project_library_clone_tool(
        repo: str,
        confirm: bool = False,
        action: str = "clone",
    ) -> str:
        """
        【开源项目落盘】把高价值公开 GitHub 仓的默认主干最新提交克隆进记忆库，或对已有本地仓执行 fetch。

        只克隆公开仓，浅克隆（--depth 1 --single-branch），默认不拉子模块。单仓约 1GB 或可见项目达到 20 个时返回 confirmation_required，
        用户确认后可带 confirm=true 重试。整仓正文不会写入正式知识库。

        Args:
            repo: GitHub URL、owner/repo，或已有项目的 projectId
            confirm: 用户确认突破数量/体积闸门时设为 true
            action: clone（默认）或 fetch

        Returns:
            JSON 格式的克隆/更新结果；confirmation_required 时先问用户
        """
        return _github_project_library_clone_impl(repo=repo, confirm=confirm, action=action)

    @tool
    def knowledge_proposal_tool(
        knowledge_base_id: str,
        source_type: str,
        source_ref_json: str,
        proposal_title: str,
        proposal_content: str,
        central_source_id: str = "",
        source_title: str = "",
        source_summary: str = "",
        proposal_summary: str = "",
        tags: str = "",
        evidence_range_json: str = "{}",
        source_created_at: str = "",
        captured_by: str = "",
    ) -> str:
        """
        【团队知识候选提交】挂接中央来源并提交精炼提案，等待审核后才会落为正式知识。

        该工具不会直接创建 KnowledgeItem；原始群聊、PDF、外部搜索、运行证据或手写内容需要先进入 Owner source inbox 并由 Steward 晋升为中央来源。
        是否能向目标知识库提交由团队访问边界和 MemoryPolicy 决定。

        Args:
            knowledge_base_id: 目标团队知识库 ID
            source_type: 来源类型，需要与 central_source_id 指向的中央来源一致
            source_ref_json: 调用方上下文 JSON；正式 SourceArtifact 溯源以中央来源为准
            proposal_title: 精炼提案标题
            proposal_content: 精炼后的候选知识正文
            central_source_id: 已由 Steward 审核通过的中央来源 ID
            source_title: 可选来源标题
            source_summary: 可选来源摘要
            proposal_summary: 可选候选摘要
            tags: 逗号分隔标签
            evidence_range_json: 可选证据范围 JSON 字符串
            source_created_at: 可选来源产生时间
            captured_by: 可选来源登记者，默认当前 Agent

        Returns:
            JSON 格式的 SourceArtifact 和 RefinementProposal
        """
        return _knowledge_proposal_impl(
            knowledge_base_id=knowledge_base_id,
            source_type=source_type,
            source_ref_json=source_ref_json,
            proposal_title=proposal_title,
            proposal_content=proposal_content,
            central_source_id=central_source_id,
            source_title=source_title,
            source_summary=source_summary,
            proposal_summary=proposal_summary,
            tags=tags,
            evidence_range_json=evidence_range_json,
            source_created_at=source_created_at,
            captured_by=captured_by,
        )

    @tool
    def knowledge_ingestion_tool(
        knowledge_base_id: str,
        source_type: str,
        source_ref_json: str,
        proposal_title: str,
        excerpt: str = "",
        proposal_content: str = "",
        central_source_id: str = "",
        source_title: str = "",
        source_summary: str = "",
        proposal_summary: str = "",
        tags: str = "",
        evidence_range_json: str = "{}",
        source_created_at: str = "",
        inbox_source_id: str = "",
        owner_type: str = "",
        owner_id: str = "",
        review_decision: str = "accepted",
        resolution_note: str = "",
    ) -> str:
        """
        【团队知识摄取】基于已筛选来源直接入库，或基于中央来源提交待审摄取包。

        如果提供 inbox_source_id、owner_type、owner_id，本工具会审核该 Owner source inbox 来源；
        accepted 来源会通过 Team Knowledge 治理门禁直接生成 SourceArtifact 和正式 KnowledgeItem。
        如果不提供 inbox_source_id，则保留旧路径：基于 central_source_id 生成 SourceArtifact + pending RefinementProposal。
        该工具不联网搜索、不解析 PDF、不收集原始来源；parser/searcher 需要先把原始材料交给 Owner source inbox。
        是否能向目标知识库提交由团队访问边界和 MemoryPolicy 决定。

        Args:
            knowledge_base_id: 目标团队知识库 ID
            source_type: 来源类型，需要与 central_source_id 指向的中央来源一致
            source_ref_json: 调用方上下文 JSON；正式 SourceArtifact 溯源以中央来源为准
            proposal_title: 直接入库时的知识标题；旧摄取包路径中作为待审提案标题
            excerpt: 已提取的来源摘录
            proposal_content: 可选候选知识正文；为空时使用 excerpt/source_summary
            central_source_id: 已由 Steward 审核通过的中央来源 ID
            source_title: 可选来源标题
            source_summary: 可选来源摘要
            proposal_summary: 可选候选摘要
            tags: 逗号分隔标签
            evidence_range_json: 可选证据范围 JSON
            source_created_at: 可选来源产生时间
            inbox_source_id: 可选 Owner source inbox 来源 ID；提供后进入筛选直接入库路径
            owner_type: inbox source 所属 owner 类型，team 或 agent
            owner_id: inbox source 所属 owner ID
            review_decision: inbox source 审核结论，默认 accepted
            resolution_note: 审核说明

        Returns:
            JSON 格式结果；直接入库路径包含 directIngestion，旧路径包含 SourceArtifact 和 pending RefinementProposal
        """
        return _knowledge_ingestion_impl(
            knowledge_base_id=knowledge_base_id,
            source_type=source_type,
            source_ref_json=source_ref_json,
            proposal_title=proposal_title,
            excerpt=excerpt,
            proposal_content=proposal_content,
            central_source_id=central_source_id,
            source_title=source_title,
            source_summary=source_summary,
            proposal_summary=proposal_summary,
            tags=tags,
            evidence_range_json=evidence_range_json,
            source_created_at=source_created_at,
            inbox_source_id=inbox_source_id,
            owner_type=owner_type,
            owner_id=owner_id,
            review_decision=review_decision,
            resolution_note=resolution_note,
        )

    @tool
    def knowledge_governance_tasks_tool(status: str = "open") -> str:
        """
        【团队知识治理任务】读取当前 Agent 可见的知识治理任务队列。

        队列由 pending proposal、pending rating suggestion 和尚未生成提案的 source artifact 派生；本工具只读，不会应用审核。

        Args:
            status: open / closed / all，默认 open

        Returns:
            JSON 格式的治理任务列表
        """
        return _knowledge_governance_tasks_impl(status=status)

    @tool
    def knowledge_operations_health_tool() -> str:
        """
        【知识库运行健康】读取当前 Agent 可见团队知识库的来源、提案、评级和正式知识健康状态。

        本工具只读，不会审核、应用、删除、改 ACL 或写入正式知识。

        Returns:
            JSON 格式的知识库运行健康摘要和 finding 列表
        """
        return _knowledge_operations_health_impl()

    @tool
    def knowledge_governance_plan_tool(limit: int = 8) -> str:
        """
        【知识库治理计划】读取只读治理计划和下一步建议。

        计划会引用推荐工具，但不会直接执行审核、应用、删除、改 ACL 或写入正式知识；正式知识仍需要 reviewer 确认。

        Args:
            limit: 返回计划动作数量上限，默认 8

        Returns:
            JSON 格式的只读治理计划
        """
        return _knowledge_governance_plan_impl(limit=limit)

    @tool
    def knowledge_steward_recommendations_tool(limit: int = 8) -> str:
        """
        【知识库管理员建议】读取 知识库管理员 派生的治理建议。

        建议由 open governance tasks 派生，只读返回 review_proposal、review_rating_suggestion、draft_refinement_proposal 等下一步动作。
        本工具不会审核、应用、删除、改 ACL 或直接写正式知识；正式知识仍需要 reviewer 确认。

        Args:
            limit: 返回建议数量上限，默认 8

        Returns:
            JSON 格式的知识治理建议列表和 recommendationsOnly 边界
        """
        return _knowledge_steward_recommendations_impl(limit=limit)

    @tool
    def knowledge_steward_workbench_tool(limit: int = 8) -> str:
        """
        【知识库管理员工作台】读取 知识库管理员的统一治理工作台。

        返回管理员身份、治理阶段、下一步建议、验收清单和权限边界；只读，不会审核、应用、删除、改 ACL 或直接写正式知识。

        Args:
            limit: 每批返回建议数量上限，默认 8

        Returns:
            JSON 格式的知识库管理员工作台状态
        """
        return _knowledge_steward_workbench_impl(limit=limit)

    @tool
    def knowledge_rating_suggestion_tool(
        knowledge_base_id: str,
        target_type: str,
        importance_level: str,
        stability: str,
        review_priority: str,
        marking_reason: str,
        knowledge_item_id: str = "",
        proposal_id: str = "",
        confidence: float = 0.7,
    ) -> str:
        """
        【团队知识评级建议】为候选或正式知识提交可审核的评级建议。

        该工具只创建 RatingSuggestion，不会直接修改正式 KnowledgeItem。需要 Reviewer 在记忆库治理页或 API 中应用。
        是否能评级目标知识库由团队访问边界和 MemoryPolicy 决定。

        Args:
            knowledge_base_id: 目标团队知识库 ID
            target_type: proposal 或 knowledge_item
            importance_level: low / medium / high / critical
            stability: temporary / evolving / stable / deprecated
            review_priority: normal / elevated / urgent
            marking_reason: 评级建议理由
            knowledge_item_id: target_type=knowledge_item 时必填
            proposal_id: target_type=proposal 时必填
            confidence: 置信度 0-1

        Returns:
            JSON 格式的评级建议，状态为 pending
        """
        return _knowledge_rating_suggestion_impl(
            knowledge_base_id=knowledge_base_id,
            target_type=target_type,
            importance_level=importance_level,
            stability=stability,
            review_priority=review_priority,
            marking_reason=marking_reason,
            knowledge_item_id=knowledge_item_id,
            proposal_id=proposal_id,
            confidence=confidence,
        )

    # ── 学习卸载工具 (P2) ──────────────────────────────────────────────────

    @tool
    def record_learning_tool(category: str, title: str, content: str, importance: int = 1) -> str:
        """
        【学习卸载】将关键发现写入跨代长期记忆。

        类别: TECH_PATTERN / BUG_FIX / SYSTEM_INSIGHT / REFACTOR / BEST_PRACTICE。
        写入后可通过 search_memory_tool 检索，重启后新 Agent 也能读取。

        Args:
            category: 类别
            title: 简短标题
            content: 完整内容（不超过 500 字符）
            importance: 重要性 1-5

        Returns:
            写入结果
        """
        return _record_learning_impl(category=category, title=title, content=content, importance=importance)

    @tool
    def search_memory_tool(query: str, category: str = "") -> str:
        """
        【记忆搜索】搜索跨代长期记忆。

        遇到问题时先调用此工具，避免重复踩坑。

        Args:
            query: 搜索关键词
            category: 按类别过滤，留空搜索全部

        Returns:
            JSON 格式的匹配记忆列表
        """
        return _search_memory_impl(query=query, category=category)

    @tool
    def search_error_archive_tool(error_type: str = "") -> str:
        """
        【错误查询】搜索历史上遇到的错误及解决方案。

        当遇到报错时先查此工具，可找到前代的修复方案。

        Args:
            error_type: 错误类型关键词，留空返回最近错误列表

        Returns:
            JSON 格式的错误记录列表
        """
        return _search_error_archive_impl(error_type=error_type)

    @tool
    def compress_context_tool(reason: str = "主动压缩") -> str:
        """
        【上下文检查点】请求为当前运行时上下文生成检查点或触发压缩 fallback。

        当上下文过长时调用。它不会删除、改写或清空原始会话历史；
        旧历史仍应通过 history_search_tool / history_fetch_tool 主动查询。

        Args:
            reason: 请求原因（如"上下文太长"、"需要建立历史检查点"）

        Returns:
            确认信息
        """
        return _compress_context_impl(reason=reason)

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
        apply_patch_tool,
        code_symbol_tool,
        python_lint_tool,
        web_search_tool,
        web_fetch_tool,
        batch_web_search_tool,
        paper_search_tool,
        project_search_tool,
        news_search_tool,
        search_summarize_sources_tool,
        source_collection_context_tool,
        source_collection_stage_writeback_tool,
        challenge_cup_experiment_context_tool,
        challenge_cup_experiment_writeback_tool,
        challenge_cup_iteration_context_tool,
        challenge_cup_iteration_writeback_tool,
        challenge_cup_versioning_context_tool,
        challenge_cup_versioning_writeback_tool,
        get_git_status_summary_tool,
        get_recent_changes_tool,
        get_entity_history_tool,
        explain_current_worktree_tool,
        open_evolution_transaction_tool,
        close_evolution_transaction_tool,
        get_evolution_fitness_tool,
        conversation_log_inspect_tool,
        history_search_tool,
        history_fetch_tool,
        history_timeline_tool,
        history_checkpoint_tool,
        # 文件操作
        cli_tool,
        exec_command,
        write_stdin,
        cli_agent_run_tool,
        read_file_tool,
        write_file_tool,
        glob_tool,
        read_memory_tool,
        get_memory_summary_tool,
        # TaskManager（tasks.json）
        task_create_tool,
        task_update_tool,
        task_list_tool,
        plan_update_tool,
        create_child_session_tool,
        list_child_sessions_tool,
        agent_create_tool,
        agent_update_tool,
        agent_archive_tool,
        agent_reset_tool,
        session_create_tool,
        session_update_tool,
        session_stop_tool,
        session_delete_tool,
        agent_inbox_list_tool,
        agent_message_consume_tool,
        agent_messages_consume_all_tool,
        knowledge_base_acl_grant_tool,
        session_reference_query_tool,
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
        # 工作区碎片管理
        list_workspace_debris_tool,
        clean_workspace_debris_tool,
        get_session_files_tool,
        # Agent 间通信
        agent_message_tool,
        append_personal_memory_tool,
        supersede_personal_memory_tool,
        agent_tool_permission_request_tool,
        research_agent_creation_proposal_tool,
        research_communication_edge_proposal_tool,
        research_proposal_apply_tool,
        image2_generate_tool,
        computer_use_task_tool,
        computer_use_session_tool,
        research_knowledge_query_tool,
        research_knowledge_request_tool,
        unified_memory_search_tool,
        skill_library_search_tool,
        github_project_library_search_tool,
        github_project_library_clone_tool,
        knowledge_proposal_tool,
        knowledge_ingestion_tool,
        knowledge_governance_tasks_tool,
        knowledge_operations_health_tool,
        knowledge_governance_plan_tool,
        knowledge_steward_recommendations_tool,
        knowledge_steward_workbench_tool,
        knowledge_rating_suggestion_tool,
        # 可信第一方虚拟人生活插件（最终可见性仍受 Agent 绑定与 ToolPolicy 交集约束）
        virtual_human_status_tool,
        virtual_human_schedule_tool,
        virtual_human_activity_tool,
        virtual_human_dialogue_decision_v2_tool,
        virtual_human_diary_tool,
        virtual_human_relationship_tool,
        virtual_human_reflection_tool,
        virtual_human_proactive_message_tool,
        # 学习卸载 (P2)
        record_learning_tool,
        search_memory_tool,
        search_error_archive_tool,
        # 上下文压缩
        compress_context_tool,
    ]


@lru_cache(maxsize=1)
def _cached_key_tools() -> tuple[BaseTool, ...]:
    """Build the process-stable tool definitions once."""

    return tuple(_build_key_tools())


def prewarm_key_tool_definitions() -> int:
    """Build static tool definitions outside the first chat turn."""

    return len(_cached_key_tools())


def create_key_tools() -> List[BaseTool]:
    """Return isolated tool objects backed by cached static definitions."""

    return [copy(tool_definition) for tool_definition in _cached_key_tools()]


def create_llm_facing_tools() -> List[BaseTool]:
    """返回默认暴露给 LLM 的精简工具集。"""
    all_tools = create_key_tools()
    excluded_names = {
        # 长尾后台/维护型工具容易把普通诊断带偏，保留到底层执行器即可
        "task_start_tool",
        "task_output_tool",
        "task_stop_tool",
        "read_file_tool",
        "list_workspace_debris_tool",
        "clean_workspace_debris_tool",
        "get_session_files_tool",
        # 自我建模类工具默认不常驻，避免在普通轮次抢占操作面。
        # ToolPolicy 申请入口保留为配置兼容工具，不再默认暴露给 LLM。
        "agent_tool_permission_request_tool",
        "update_diagnosis_rules_tool",
        "update_self_model_tool",
        "get_self_model_tool",
        "record_evolution_tool",
    }
    if not _is_autoglm_search_tool_available():
        excluded_names.add("web_search_tool")
    return [tool for tool in all_tools if getattr(tool, "name", "") not in excluded_names]
