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
from tools.memory_tools import (
    record_learning_tool as _record_learning_impl,
    search_memory_tool as _search_memory_impl,
    search_error_archive_tool as _search_error_archive_impl,
)
from tools.search_tools import grep_search_tool as _grep_search_impl
from tools.web_search_tool import (
    web_search as _web_search_impl,
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
from tools.team_knowledge_tools import (
    knowledge_governance_plan_tool as _knowledge_governance_plan_impl,
    knowledge_governance_tasks_tool as _knowledge_governance_tasks_impl,
    knowledge_ingestion_tool as _knowledge_ingestion_impl,
    knowledge_operations_health_tool as _knowledge_operations_health_impl,
    knowledge_proposal_tool as _knowledge_proposal_impl,
    knowledge_query_tool as _knowledge_query_impl,
    knowledge_rag_retrieve_tool as _knowledge_rag_retrieve_impl,
    knowledge_rating_suggestion_tool as _knowledge_rating_suggestion_impl,
    knowledge_steward_recommendations_tool as _knowledge_steward_recommendations_impl,
    knowledge_steward_workbench_tool as _knowledge_steward_workbench_impl,
    unified_knowledge_search_tool as _unified_knowledge_search_impl,
)
from tools.token_manager import compress_context_tool as _compress_context_impl
from tools.python_intelligence_tools import (
    code_symbol_tool as _code_symbol_impl,
    python_lint_tool as _python_lint_impl,
)
from tools.plan_tools import plan_update_tool as _plan_update_impl
from tools.conversation_log_tools import conversation_log_inspect_tool as _conversation_log_inspect_impl
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
from tools.cli_agent_tools import cli_agent_run_tool as _cli_agent_run_impl

_CLI_TOOL_DOCSTRING = """
【CLI】执行任意 Shell 命令。

默认的本地工作入口，适合高效完成代码定位、文件检查、搜索、脚本、编译、测试和诊断。
优先用项目可用的快速命令收窄证据，例如 `rg`/`rg --files`、PowerShell `Get-Content`
配合 `Select-Object`、以及针对单文件或单测试目标的命令。

=== 使用建议 ===
1. 避免交互式命令 (vim, top, less) 和无休止命令 (ping, tail -f)。
2. 搜索优先 `rg -n "pattern" path`；列文件优先 `rg --files path`，再读取命中的小范围。
3. 读文件要限制输出：用 `Get-Content <file> | Select-Object -First/-Skip`，或只读相关文件。
4. 长输出先缩小目录、文件、测试名或行数；必要时用 `max_output_chars` 限制返回。
5. 命令链与管道 (`&&`、`||`、`|`、`;`、`` ` ``、`$()`) 会增加失败面，能拆开时分步运行。

=== 闭环 ===
修改代码后按顺序分开执行:
1. python -m py_compile <file>.py
2. python -m pytest <target> -x -q

Args:
    command: Shell 命令
    timeout: 文件操作 30s, 编译 60s, 测试/网络 120s
    cwd: 工作目录，默认项目根目录
    max_output_chars: 最大返回字符数，默认 12000；超出时保留开头和结尾摘要
"""

_CLI_AGENT_RUN_TOOL_DOCSTRING = """
【CLI Agent 调用】受控调用外部非交互式代码 Agent。

只支持内置适配器：
1. `mimo_code`：调用 `mimo run`
2. `codex_code`：调用 `codex exec`

默认 `mode=readonly`，会使用只读/低风险参数运行。需要允许外部 Agent 写代码时，
需要使用 `mode=worktree` 并传入独立 worktree 的 `cwd`；主项目工作区会被拒绝。
该工具不会执行任意 shell 字符串，所有命令参数由适配器拼装，并会隐藏完整任务文本，
只在运行记录中保留有界 stdout/stderr 摘要、命令预览和 task hash。

Args:
    agent_type: `mimo_code` 或 `codex_code`
    task: 要交给外部 CLI Agent 的任务说明
    cwd: 运行目录；只读可用项目内目录，可写使用 sibling worktree
    mode: `readonly` 或 `worktree`
    timeout: 超时时间，默认 600 秒，最大 1800 秒
    output_limit: stdout/stderr 摘要最大字符数，默认 12000
    model: 可选模型名，会映射到对应 CLI 的 `--model`
    agent: 仅 MiMo Code 使用的可选 agent 名
    allow_unsafe_permissions: 仅 MiMo worktree 模式允许附加 `--dangerously-skip-permissions`
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

        Returns:
            操作结果。格式错误时返回具体原因。
        """
        from tools.code_analysis_tools import apply_diff_edit, validate_diff_format
        is_valid, msg = validate_diff_format(diff_text)
        if not is_valid:
            return f"[编辑] 格式验证失败: {msg}"
        return apply_diff_edit(file_path=file_path, diff_text=diff_text, allow_fuzzy=True)

    @tool
    def apply_patch_tool(patch_text: str, cwd: str = ".") -> str:
        """
        Codex 风格 patch 编辑器。适合一次提交多文件 Add/Update/Delete patch。

        格式：
        *** Begin Patch
        *** Update File: path/to/file.py
        @@
        -old line
        +new line
        *** End Patch

        Args:
            patch_text: Codex 风格 patch 文本
            cwd: 相对路径解析根目录，默认项目根目录

        Returns:
            JSON 格式的修改结果；格式或匹配失败时返回可纠正错误。
        """
        from tools.code_analysis_tools import apply_patch_edit
        return apply_patch_edit(patch_text=patch_text, cwd=cwd)

    @tool
    def code_symbol_tool(
        mode: str,
        query: str = "",
        file_path: str = "",
        symbol: str = "",
        max_results: int = 20,
        refresh: bool = False,
    ) -> str:
        """
        【代码上下文图谱】索引并查询整个 Vibelution 项目的结构、符号、引用、影响范围和候选测试。

        常用模式：
        - mode="status": 查看索引状态、文件数、语言分布和新鲜度。
        - mode="index": 重新构建本地项目索引。
        - mode="search": 按 query/symbol/file_path 搜索文件和符号。
        - mode="explore": 面向问题检索相关文件、符号、源码片段和关系图。
        - mode="inspect": 查看指定 file_path 或 symbol 的结构化详情和片段。
        - mode="references": 查找符号、路径或关键词引用。
        - mode="impact": 分析修改某个 file_path 或 symbol 的影响范围。
        - mode="affected_tests": 推荐与目标相关的测试文件。
        - mode="files": 查看索引内文件列表。

        注意：v2 不再支持 outline/entity/definition/hover。旧需求请改用 inspect/search/references。

        Args:
            mode: status / index / search / explore / inspect / references / impact / affected_tests / files
            query: 自然语言问题、关键词、路径片段或符号名
            file_path: 目标文件路径；inspect/impact/affected_tests/references 可用
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
    def web_fetch_tool(url: str, max_chars: int = 8000) -> str:
        """
        【网页抓取】获取指定 URL 的网页内容并提取纯文本。

        与 web_search_tool 的区别：search 是关键词搜索，fetch 是直接抓取 URL 内容。
        适用于阅读文档、查看 API 响应、分析网页文章等场景。

        Args:
            url: 要抓取的完整 URL（需要以 http:// 或 https:// 开头）
            max_chars: 最大返回字符数，默认 8000

        Returns:
            去除 HTML 标签后的纯文本内容
        """
        from tools.web_search_tool import web_fetch as _web_fetch
        return _web_fetch(url=url, max_chars=max_chars)

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
            status: success / failed / cancelled
            summary: 本轮演化结果摘要

        Returns:
            关闭结果 JSON
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

    def _cli_tool_impl(command: str = "", timeout: int = 60, cwd: str = "", max_output_chars: int = 12000) -> str:
        from tools.shell_tools import execute_shell_command
        if not command:
            return '{"status": "error", "code": "MISSING_COMMAND", "message": "cli_tool 需要提供 command 参数"}'
        try:
            timeout = int(timeout)
        except (TypeError, ValueError):
            timeout = 60
        try:
            max_output_chars = int(max_output_chars)
        except (TypeError, ValueError):
            max_output_chars = 12000
        result = execute_shell_command(command, timeout=timeout, cwd=cwd or None)
        if max_output_chars > 0 and len(result) > max_output_chars:
            head_size = max(2000, max_output_chars // 2)
            tail_size = max(2000, max_output_chars - head_size)
            result = (
                f"{result[:head_size]}\n\n"
                f"[输出已截断: 原始 {len(result)} 字符，仅保留前 {head_size} 和后 {tail_size} 字符]\n\n"
                f"{result[-tail_size:]}"
            )
        return result

    cli_tool = StructuredTool.from_function(_cli_tool_impl, name="cli_tool", description=_CLI_TOOL_DOCSTRING)
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
            force: 兼容旧参数；不能用于绕过本轮重复读取或全文件治理

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
        switch_to_child: bool = True,
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
        target_agent: str,
        content: str,
        summary: str = "",
        wake_target: bool = True,
        thread_id: str = "",
        metadata_json: str = "",
    ) -> str:
        """
        【Agent 私信】从当前 Agent 向另一个 Agent 发送持久消息。

        适合把发现、请求、审查意见或交接信息发给指定 Agent。目标可用 agentId、A001 这类稳定代号或唯一名称。
        消息会写入目标 Agent 的 inbox；wake_target=True 时会尝试唤醒目标的空闲直聊会话。
        如果任一方属于科研组织图，消息会先经过科研组织通讯边、messageType/intent、监督策略和唤醒规则校验。

        Args:
            target_agent: 目标 Agent 的 agentId、稳定代号或唯一名称
            content: 要发送的消息正文
            summary: 简短摘要，留空时使用正文摘要
            wake_target: 是否尝试唤醒目标直聊会话，默认 True
            thread_id: 可选线程 ID，用于后续串联同一议题
            metadata_json: 可选 JSON 对象字符串，写入少量结构化元数据

        Returns:
            JSON 格式的发送结果、messageId 和唤醒状态
        """
        return _agent_message_impl(
            target_agent=target_agent,
            content=content,
            summary=summary,
            wake_target=wake_target,
            thread_id=thread_id,
            metadata_json=metadata_json,
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
    def knowledge_query_tool(query: str = "", knowledge_base_id: str = "", limit: int = 8) -> str:
        """
        【团队知识库查询】只读检索已审核落盘的团队正式知识。

        该工具只返回正式 KnowledgeItem，不读取 pending proposal，也不写入知识库。
        是否能读取目标知识库由团队访问边界和 MemoryPolicy 决定。

        Args:
            query: 查询关键词，可为空以查看最近正式知识
            knowledge_base_id: 可选知识库 ID；为空时检索当前 Agent 可访问的知识库
            limit: 最多返回条数，范围 1-25

        Returns:
            JSON 格式的正式知识条目列表
        """
        return _knowledge_query_impl(query=query, knowledge_base_id=knowledge_base_id, limit=limit)

    @tool
    def knowledge_rag_retrieve_tool(
        query: str = "",
        knowledge_base_id: str = "",
        owner_type: str = "",
        owner_id: str = "",
        retrieval_mode: str = "hybrid",
        provider: str = "local",
        top_k: int = 5,
        max_context_chars: int = 1200,
    ) -> str:
        """
        【正式知识 RAG 检索】只读检索已审核 Team/Agent 正式知识，并返回可引用的紧凑上下文候选。

        该工具返回 contexts 与 citations，不读取 pending proposal，不写入知识库，也不会默认注入 prompt。
        是否能读取目标知识库由 Owner ACL 和 MemoryPolicy 决定。

        Args:
            query: 查询关键词，可为空以查看最近正式知识
            knowledge_base_id: 可选知识库 ID；为空时检索当前 Agent 可访问的知识库
            owner_type: 可选 owner 类型，支持 team / agent
            owner_id: 可选 owner id，teamId 或 agentId
            retrieval_mode: exact / semantic / hybrid，默认 hybrid
            provider: 当前支持 local
            top_k: 最多返回上下文数量，范围 1-20
            max_context_chars: 单条上下文最大字符数

        Returns:
            JSON 格式的 RAG context candidates、citations 和 retrievalPolicy
        """
        return _knowledge_rag_retrieve_impl(
            query=query,
            knowledge_base_id=knowledge_base_id,
            owner_type=owner_type,
            owner_id=owner_id,
            retrieval_mode=retrieval_mode,
            provider=provider,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )

    @tool
    def unified_knowledge_search_tool(
        query: str = "",
        query_mode: str = "auto",
        knowledge_base_id: str = "",
        owner_type: str = "",
        owner_id: str = "",
        tags: str = "",
        limit: int = 8,
        max_context_chars: int = 1200,
    ) -> str:
        """
        【统一正式知识搜索】只读检索已审核 Team/Agent 正式知识。

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

        Returns:
            JSON 格式的统一正式知识搜索结果
        """
        return _unified_knowledge_search_impl(
            query=query,
            query_mode=query_mode,
            knowledge_base_id=knowledge_base_id,
            owner_type=owner_type,
            owner_id=owner_id,
            tags=tags,
            limit=limit,
            max_context_chars=max_context_chars,
        )

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
    ) -> str:
        """
        【团队知识半自动摄取】基于中央来源提交 SourceArtifact + pending RefinementProposal。

        该工具不联网搜索、不解析 PDF、不收集原始来源、不直接创建正式知识；parser/searcher 需要先把原始材料交给 Owner source inbox。
        正式 SourceArtifact 溯源以 central_source_id 对应的中央来源为准。
        是否能向目标知识库提交由团队访问边界和 MemoryPolicy 决定。

        Args:
            knowledge_base_id: 目标团队知识库 ID
            source_type: 来源类型，需要与 central_source_id 指向的中央来源一致
            source_ref_json: 调用方上下文 JSON；正式 SourceArtifact 溯源以中央来源为准
            proposal_title: 待审提案标题
            excerpt: 已提取的来源摘录
            proposal_content: 可选候选知识正文；为空时使用 excerpt/source_summary
            central_source_id: 已由 Steward 审核通过的中央来源 ID
            source_title: 可选来源标题
            source_summary: 可选来源摘要
            proposal_summary: 可选候选摘要
            tags: 逗号分隔标签
            evidence_range_json: 可选证据范围 JSON
            source_created_at: 可选来源产生时间

        Returns:
            JSON 格式的摄取包结果，包含 SourceArtifact 和 pending RefinementProposal
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
        【知识库管理员建议】读取 Knowledge Steward 派生的治理建议。

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
        【知识库管理员工作台】读取 Knowledge Steward 的统一治理工作台。

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
        get_git_status_summary_tool,
        get_recent_changes_tool,
        get_entity_history_tool,
        explain_current_worktree_tool,
        open_evolution_transaction_tool,
        close_evolution_transaction_tool,
        conversation_log_inspect_tool,
        history_search_tool,
        history_fetch_tool,
        history_timeline_tool,
        history_checkpoint_tool,
        # 文件操作
        cli_tool,
        cli_agent_run_tool,
        read_file_tool,
        write_file_tool,
        glob_tool,
        # TaskManager（tasks.json）
        task_create_tool,
        task_update_tool,
        task_list_tool,
        plan_update_tool,
        create_child_session_tool,
        list_child_sessions_tool,
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
        agent_tool_permission_request_tool,
        research_agent_creation_proposal_tool,
        research_communication_edge_proposal_tool,
        research_proposal_apply_tool,
        image2_generate_tool,
        computer_use_task_tool,
        computer_use_session_tool,
        research_knowledge_query_tool,
        unified_knowledge_search_tool,
        knowledge_query_tool,
        knowledge_rag_retrieve_tool,
        knowledge_proposal_tool,
        knowledge_ingestion_tool,
        knowledge_governance_tasks_tool,
        knowledge_operations_health_tool,
        knowledge_governance_plan_tool,
        knowledge_steward_recommendations_tool,
        knowledge_steward_workbench_tool,
        knowledge_rating_suggestion_tool,
        # 学习卸载 (P2)
        record_learning_tool,
        search_memory_tool,
        search_error_archive_tool,
        # 上下文压缩
        compress_context_tool,
    ]


def create_llm_facing_tools() -> List[BaseTool]:
    """返回默认暴露给 LLM 的精简工具集。"""
    all_tools = create_key_tools()
    excluded_names = {
        # 长尾后台/维护型工具容易把普通诊断带偏，保留到底层执行器即可
        "task_start_tool",
        "task_output_tool",
        "task_stop_tool",
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
    return [tool for tool in all_tools if getattr(tool, "name", "") not in excluded_names]
