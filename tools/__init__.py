# -*- coding: utf-8 -*-
"""
工具模块初始化文件

所有工具统一从 __init__.py 导入，工具名统一添加 _tool 后缀。
"""

# ============================================================================
# Shell 工具
# ============================================================================
from tools.shell_tools import (
    list_directory as list_directory_tool,
    check_python_syntax as check_python_syntax_tool,
    extract_symbols as extract_symbols_tool,
    backup_project as backup_project_tool,
    cleanup_test_files as cleanup_test_files_tool,
    execute_shell_command as execute_shell_command_tool,
    run_powershell as run_powershell_tool,
    run_batch as run_batch_tool,
    self_test as self_test_tool,
    get_agent_status as get_agent_status_tool,
)

# ============================================================================
# 记忆与任务管理工具 (整合自 memory_tools.py)
# ============================================================================
from tools.memory_tools import (
    # 记忆工具
    read_memory_tool,
    commit_compressed_memory_tool,
    get_generation_tool,
    get_current_goal_tool,
    get_core_context_tool,
    read_generation_archive_tool,
    list_archives_tool,
    read_dynamic_prompt_tool,
    update_generation_task_tool,
    add_insight_to_dynamic_tool,
    write_dynamic_prompt_tool,
    record_codebase_insight_tool,
    get_global_codebase_map_tool,
    get_memory_summary_tool,
    archive_generation_history,
    force_save_current_state,
    advance_generation,
    clear_generation_task,
    # 任务工具（TaskManager 体系）
    task_create_tool,
    task_update_tool,
    task_list_tool,
    task_breakdown_tool,
    task_prioritize_tool,
)

# ============================================================================
# 重生工具
# ============================================================================
from tools.rebirth_tools import (
    trigger_self_restart_tool,
    enter_hibernation_tool,
)

# ============================================================================
# 搜索工具
# ============================================================================
from tools.search_tools import (
    grep_search_tool,
    find_function_calls_tool,
    find_definitions_tool,
    search_imports_tool,
    search_and_read_tool,
)

# ============================================================================
# 代码分析工具
# ============================================================================
from tools.code_analysis_tools import (
    get_code_entity as get_code_entity_tool,
    list_file_entities as list_file_entities_tool,
    get_file_entities as get_file_entities_tool,
    apply_diff_edit as apply_diff_edit_tool,
    validate_diff_format as validate_diff_format_tool,
    preview_diff as preview_diff_tool,
)

# ============================================================================
# Token 管理工具
# ============================================================================
from tools.token_manager import (
    EnhancedTokenCompressor,
    truncate_tool_result as truncate_tool_result_tool,
    estimate_tokens_precise as estimate_tokens_precise_tool,
    estimate_messages_tokens as estimate_messages_tokens_tool,
    MessagePriority,
    format_compression_report as format_compression_report_tool,
)

# ============================================================================
# 网络搜索工具
# ============================================================================
from tools.web_search_tool import web_search_tool as web_search_tool
from tools.web_search_tool import web_search as web_search_impl

__all__ = [
    # Shell 工具
    "list_directory_tool",
    "check_python_syntax_tool",
    "extract_symbols_tool",
    "backup_project_tool",
    "cleanup_test_files_tool",
    "execute_shell_command_tool",
    "run_powershell_tool",
    "run_batch_tool",
    "self_test_tool",
    "get_agent_status_tool",
    # 记忆工具
    "read_memory_tool",
    "commit_compressed_memory_tool",
    "get_generation_tool",
    "get_current_goal_tool",
    "get_core_context_tool",
    "read_generation_archive_tool",
    "list_archives_tool",
    "read_dynamic_prompt_tool",
    "update_generation_task_tool",
    "add_insight_to_dynamic_tool",
    "write_dynamic_prompt_tool",
    "record_codebase_insight_tool",
    "get_global_codebase_map_tool",
    "get_memory_summary_tool",
    "archive_generation_history",
    "force_save_current_state",
    "advance_generation",
    "clear_generation_task",
    # 任务工具（TaskManager 体系）
    "task_create_tool",
    "task_update_tool",
    "task_list_tool",
    "task_breakdown_tool",
    "task_prioritize_tool",
    # 重生工具
    "trigger_self_restart_tool",
    "enter_hibernation_tool",
    # 搜索工具
    "grep_search_tool",
    "find_function_calls_tool",
    "find_definitions_tool",
    "search_imports_tool",
    "search_and_read_tool",
    # 代码分析工具
    "apply_diff_edit_tool",
    "validate_diff_format_tool",
    "preview_diff_tool",
    "get_code_entity_tool",
    "list_file_entities_tool",
    "get_file_entities_tool",
    # Token 管理工具
    "EnhancedTokenCompressor",
    "truncate_tool_result_tool",
    "estimate_tokens_precise_tool",
    "estimate_messages_tokens_tool",
    "MessagePriority",
    "format_compression_report_tool",
    # 网络搜索工具
    "web_search_tool",
    "web_search_impl",
]
