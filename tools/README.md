# Agent Tools 全量索引（R14）

**读者：coding Agent。**
**目标：30 秒内从工具名定位实现文件、授权链路与主测；新工具必须注册到 `Key_Tools`，禁止平行 registry。**

权威授权：[`docs/agents/tool-authorization-entrypoints.md`](../docs/agents/tool-authorization-entrypoints.md) · 机器可读 baseline：`tests/fixtures/tool_authorization/`。
Registry 元数据：`core/web/services/tool_catalog.py`（`TOOL_CATALOG`）· 工作台：`core/web/services/tool_registry_service.py`。

---

## 注册与授权链（所有工具共用）

```text
Model 可见性
  → SelfEvolvingAgent._init_llm / _get_llm_for_current_mode
  → ToolPolicy v2（agent_directory · agent_role_tool_profile_service）
  → create_key_tools() / create_llm_facing_tools() 过滤

执行（不可绕过）
  → ToolLifecycleBridge（语义 call identity）
  → ToolExecutor.execute
  → core/authorization/tool_authorization_service.authorize_tool_call
  → tools/* 实现 或 Key_Tools 包装体

注册 SSOT
  → tools/Key_Tools.py :: create_key_tools()（95 个 canonical 名）
  → 新工具：实现模块 + Key_Tools 导入/包装 + tool_catalog 条目 + 聚焦 pytest
```

**禁止：** 在 route/service 直接 `ToolExecutor` 调未注册名；在 `Key_Tools` 外暴露第二套 LLM tool list；协议 adapter 自行增删授权。

---

## 模块索引（工具名 → 文件 → 主测）

| 实现文件 | 工具名（canonical） | 主测 |
| --- | --- | --- |
| `Key_Tools.py`（包装） | `read_file_tool` · `write_file_tool` · `glob_tool` · `apply_patch_tool` · `apply_diff_edit_tool` · `web_fetch_tool` · `exec_command` · `cli_tool` · `write_stdin` · `task_start_tool` · `task_stop_tool` · `task_output_tool` · `run_test_for_tool` · `web_search_tool` 等 26 个（见 `create_key_tools()`） | `test_agent_protocol.py` · `test_shell_tools.py` · `test_code_analysis_tools.py` |
| `shell_tools.py` | （`exec_command` / `cli_tool` 实现） | `test_shell_tools.py` · `test_shell_tools_routing.py` |
| `code_analysis_tools.py` | （`apply_diff_edit_tool` / `apply_patch_tool` / `read_file_tool` 实现） | `test_code_analysis_tools.py` |
| `search_tools.py` | `grep_search_tool` | `test_search_tools.py` |
| `web_search_tool.py` | `web_search_tool` | `test_research_search_tools.py` |
| `research_search_tools.py` | `batch_web_search_tool` · `news_search_tool` · `paper_search_tool` · `project_search_tool` · `search_summarize_sources_tool` | `test_research_search_tools.py` |
| `memory_tools.py` | `read_memory_tool` · `get_memory_summary_tool` · `get_core_context_tool` · `get_current_goal_tool` · `commit_compressed_memory_tool` · `record_learning_tool` · `search_memory_tool` · `search_error_archive_tool` · `task_create_tool` · `task_update_tool` · `task_list_tool` | `test_memory_tools.py` |
| `token_manager.py` | `compress_context_tool` | `test_memory_tools.py` · `test_agent_protocol.py` |
| `episodic_memory_tools.py` | `append_personal_memory_tool` · `supersede_personal_memory_tool` | `test_agent_tool_contracts.py` |
| `session_reference_tools.py` | `session_reference_query_tool` | `test_agent_protocol.py` |
| `team_knowledge_tools.py` | `unified_memory_search_tool` · `knowledge_proposal_tool` · `knowledge_ingestion_tool` · `knowledge_governance_*` · `knowledge_steward_*` · `knowledge_rating_suggestion_tool` · `knowledge_operations_health_tool` | `test_team_knowledge_tools.py` · `test_agent_tool_contracts.py` |
| `skill_library_tools.py` | `skill_library_search_tool` | `test_agent_tool_contracts.py` |
| `git_tools.py` | `get_git_status_summary_tool` · `get_recent_changes_tool` · `get_entity_history_tool` · `explain_current_worktree_tool` · `open_evolution_transaction_tool` · `close_evolution_transaction_tool` · `get_evolution_fitness_tool` | `test_agent_protocol.py` |
| `source_collection_stage_tools.py` | `source_collection_context_tool` · `source_collection_stage_writeback_tool` | `test_agent_tool_contracts.py` |
| `challenge_cup_operations_tools.py` | `challenge_cup_experiment_*` · `challenge_cup_iteration_*` · `challenge_cup_versioning_*`（context/writeback 各 3） | `test_challenge_cup_operations_tools.py` |
| `research_knowledge_tools.py` | `research_knowledge_query_tool` | `test_research_knowledge_tools.py` |
| `research_organization_tools.py` | `research_agent_creation_proposal_tool` · `research_communication_edge_proposal_tool` · `research_proposal_apply_tool` | `test_research_organization_tools.py` |
| `agent_message_tools.py` | `agent_message_tool` | `test_agent_tool_contracts.py` |
| `agent_tool_governance_tools.py` | `agent_tool_permission_request_tool` | `test_tool_authorization_execution.py` |
| `cli_agent_tools.py` | `cli_agent_run_tool` | `test_agent_protocol.py` |
| `session_child_tools.py` | `create_child_session_tool` · `list_child_sessions_tool` | `test_agent_protocol.py` |
| `project_operation_tools.py` | `agent_create_tool` · `agent_update_tool` · `agent_archive_tool` · `agent_reset_tool` · `session_create_tool` · `session_update_tool` · `session_stop_tool` · `session_delete_tool` · `agent_inbox_list_tool` · `agent_message_consume_tool` · `agent_messages_consume_all_tool` · `knowledge_base_acl_grant_tool` | `test_project_operation_tools.py` |
| `conversation_history_tools.py` | `history_search_tool` · `history_fetch_tool` · `history_timeline_tool` · `history_checkpoint_tool` | `test_agent_protocol.py` |
| `conversation_log_tools.py` | `conversation_log_inspect_tool` | `test_conversation_log_tools.py` |
| `python_intelligence_tools.py` | `code_symbol_tool` · `python_lint_tool` | `test_python_intelligence_tools.py` |
| `plan_tools.py` | `plan_update_tool` | `test_agent_protocol.py` |
| `computer_use_tools.py` | `computer_use_session_tool` · `computer_use_task_tool` | `test_agent_protocol.py` |
| `image2_tools.py` | `image2_generate_tool` | `test_image2_tools.py` |
| `rebirth_tools.py` | `trigger_self_restart_tool` | `test_rebirth_tools.py` |
| `core/infrastructure/mental_model.py` | `get_mental_state_tool` · `update_self_model_tool` · `update_diagnosis_rules_tool` · `get_self_model_tool` · `record_evolution_tool` | `test_agent_protocol.py` |
| `core/infrastructure/workspace_cleaner.py` | `list_workspace_debris_tool` · `clean_workspace_debris_tool` · `get_session_files_tool` | `test_agent_protocol.py` |

已退役（不得复活）：`knowledge_query_tool` · `knowledge_rag_retrieve_tool` · `unified_knowledge_search_tool` — 见 `tests/test_agent_tool_contracts.py` `RETIRED_TOOL_NAMES`。

---

## 非注册 helper（勿当 Agent 工具入口）

| 文件 | 用途 |
| --- | --- |
| `compression_quality.py` · `compression_strategy.py` | 上下文压缩策略 |
| `research_search_backends.py` · `research_search_quality.py` | 搜索后端/质量 |
| `key_info_extractor.py` | 键信息抽取 helper |
| `agent_tools.py` | `spawn_agent` 子进程实现；`spawn_agent_tool` 包装在 `Key_Tools.py` 内，是否进入 `create_key_tools()` 以运行时返回列表为准 |
| `__init__.py` | 包标记；不 re-export 工具 |

---

## 主测（可复制）

```powershell
# 注册合同 + 协作/记忆/evolution 工具面
.\.venv\Scripts\python.exe -m pytest tests\test_agent_tool_contracts.py tests\test_tool_authorization_execution.py -q

# Shell / 搜索 / 代码编辑
.\.venv\Scripts\python.exe -m pytest tests\test_shell_tools.py tests\test_search_tools.py tests\test_code_analysis_tools.py -q

# Memory / knowledge tools
.\.venv\Scripts\python.exe -m pytest tests\test_memory_tools.py tests\test_team_knowledge_tools.py -q

# Research / Challenge Cup / 组织
.\.venv\Scripts\python.exe -m pytest tests\test_research_search_tools.py tests\test_research_knowledge_tools.py tests\test_research_organization_tools.py tests\test_challenge_cup_operations_tools.py -q

# 路由合同（工具注册与 API 投影）
.\.venv\Scripts\python.exe -m pytest tests\test_tools_route_contract.py -q

# 影响面（改 Key_Tools 或单模块后）
.\.venv\Scripts\python.exe tests\select_tests.py --changed-file tools/Key_Tools.py --commands-only
```

改 `tool_catalog.py` / ToolPolicy 时加跑：`test_agent_config_workspace_service.py`（ToolPolicy 段）与 `tests/fixtures/tool_authorization/*` 结构测试。

---

## 新增工具 checklist

1. 在 owning `tools/*_tools.py`（或经评估后的 `core/infrastructure/*`）实现。
2. `Key_Tools.py` 导入并在 `_build_key_tools()` 注册；更新 `TOOL_CATALOG` category/bundle。
3. 授权：确认 ToolPolicy baseline / role profile 是否需要显式 allow。
4. 添加/扩展聚焦 pytest；跑 `test_agent_tool_contracts.py`。
5. 更新本 README 对应模块行。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`docs/agents/tool-authorization-entrypoints.md`](../docs/agents/tool-authorization-entrypoints.md) | 可见性/执行入口 inventory |
| [`docs/agents/project-operation-catalog.md`](../docs/agents/project-operation-catalog.md) | 项目操作目录：Agent/Session 操作面、访问类与生命周期 |
| [`core/web/services/memory_rag_services.md`](../core/web/services/memory_rag_services.md) | unified_memory / knowledge 工具落 service 侧 |
| [`docs/guides/agent-dev-roi-backlog.md`](../docs/guides/agent-dev-roi-backlog.md) | R14 DoD |
| [`core/web/services/README.md`](../core/web/services/README.md) | backend facade 索引（仿本表结构） |
