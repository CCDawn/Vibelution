# `core/web/services` — Agent 全量索引

> **读者：coding Agent。** 写入前用本表定位 facade / pack。
> 规则：`docs/standards/development-standard.md` §8.3 / §24；总图：`docs/guides/ownership.md`。
> 数据：模块 docstring + routes 引用扫描 + tests 引用（启发式，非穷尽）。
> 验证以代码 import 与 `tests/select_tests.py` 为准。

## 用法

```text
1. 关键词 / facade 名 → 下方 Domain 表
2. Pack 非空 → 先读 Pack/README.md；改 pack 不堆 facade
3. Pack 空 → 改该 *_service.py；复杂逻辑再拆 pack
4. Routes → core/web/routes/<path>
5. Tests → tests/<file>；空则 select_tests.py
```

## Pack 域（有独立 README）

| Pack | Facade | README |
| --- | --- | --- |
| `session/` | `session_service.py` | [session/README.md](session/README.md) |
| `team_workflow/` | `team_workflow_orchestration_service.py` | [team_workflow/README.md](team_workflow/README.md) |
| `team/` | `team_service.py` | [team/README.md](team/README.md) |
| `team_knowledge/` | `team_knowledge_service.py` | [team_knowledge/README.md](team_knowledge/README.md) |
| `agent_directory/` | `agent_directory_service.py` | [agent_directory/README.md](agent_directory/README.md) |
| `runtime_scene/` | `runtime_scene_service.py` | [runtime_scene/README.md](runtime_scene/README.md) |
| `external_agent/` | — | [external_agent/README.md](external_agent/README.md) |

## 统计

- Facade `*_service.py`：**69**
- 有 pack README：**7**
- 仅单文件 facade：**63**

## Domain 速查

| Domain | Facades |
| --- | ---: |
| Session / Chat hot path (`session`) | 1 |
| Team workflow / SC / experiment (`team_workflow`) | 1 |
| Team registry / canvas (`team`) | 2 |
| Agent directory / config (`agent`) | 15 |
| Chat room / conversation index (`chat`) | 3 |
| Knowledge / RAG (`knowledge`) | 4 |
| Memory (`memory`) | 3 |
| Research / Challenge Cup (`research`) | 5 |
| Self / Supervised evolution (`evolution`) | 10 |
| Runtime / runtime scene (`runtime`) | 3 |
| Launcher / Reset (`launcher`) | 2 |
| Config / Provider / Model / Theme (`config`) | 7 |
| Workbench contract / preferences (`workbench`) | 2 |
| Git (`git`) | 1 |
| Logs / Diagnostics (`ops`) | 2 |
| Workspace files (`workspace`) | 1 |
| Tools registry (`tools`) | 1 |
| Skills (`skills`) | 2 |
| Pet (`pet`) | 1 |
| Computer Use (`computer_use`) | 1 |
| Data processing (`data`) | 1 |
| User content markdown (`content`) | 1 |

## Session / Chat hot path

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `session_service.py` | Real chat session payloads for the web workbench. | `session/` | `agents.py`, `cli_agents.py`, `sessions.py` | `test_agent_archive_session_lifecycle.py`, `test_agent_bulk_delete_service.py`, `test_agent_bulk_edit_service.py` |

## Team workflow / SC / experiment

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `team_workflow_orchestration_service.py` | Team workflow orchestration and candidate-store service. | `team_workflow/` | `team_workflows/_models.py`, `team_workflows/experiment.py`, `team_workflows/knowledge.py`, `team_workflows/orchestration.py`, `team_workflows/research_ops.py` | `test_agent_tool_contracts.py`, `test_candidate_schema_registry.py`, `test_challenge_cup_operations_tools.py` |

## Team registry / canvas

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `team_service.py` | Team registry and organization canvas service. | `team/` | `agents.py`, `research_evidence.py`, `research_loop.py`, `team_workflows/experiment.py`, `team_workflows/knowledge.py` | `test_agent_bulk_delete_service.py`, `test_agent_bulk_edit_service.py`, `test_agent_config_workspace_service.py` |
| `team_template_service.py` | Reusable Team templates for demo and onboarding flows. | — | `team_templates.py` | `test_team_template_routes.py` |

## Agent directory / config

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `agent_bulk_delete_service.py` | Bulk Agent delete/archive orchestration helpers. | — | `agents.py` | `test_agent_archive_session_lifecycle.py`, `test_agent_bulk_delete_service.py`, `test_agent_bulk_edit_service.py` |
| `agent_bulk_edit_service.py` | Bulk Agent edit orchestration helpers. | — | `agents.py` | `test_agent_bulk_edit_service.py` |
| `agent_config_change_service.py` | Append-only private drafts and revision evidence for Agent configuration. | — | `agents.py` | `test_agent_config_change_service.py` |
| `agent_config_workspace_service.py` | Read-only Agent configuration workspace aggregation. | — | `agents.py` | `test_agent_archive_session_lifecycle.py`, `test_agent_config_change_service.py`, `test_agent_config_workspace_routes.py` |
| `agent_directory_service.py` | Persistent AgentInstance registry for chat-facing agents. | `agent_directory/` | `agents.py` | `test_agent_archive_session_lifecycle.py`, `test_agent_avatar_model_repair.py`, `test_agent_avatar_role_defaults.py` |
| `agent_mode_binding_service.py` | Mode-to-Agent binding store for configurable Agent runtimes. | — | `agents.py` | `test_agent_bulk_delete_service.py`, `test_agent_bulk_edit_service.py`, `test_agent_config_workspace_service.py` |
| `agent_model_candidate_service.py` | Read-only projection of configured and observed Provider models for Agents. | — | — | `test_agent_model_candidate_service.py`, `test_session_llm_selection.py` |
| `agent_model_promotion_service.py` | Atomic promotion of one observed Provider model into one Agent binding. | — | `agents.py` | `test_agent_config_workspace_routes.py`, `test_agent_model_promotion_service.py` |
| `agent_role_tool_profile_service.py` | Single source of truth for fixed-role Agent tool profiles. | — | — | `test_agent_lifecycle_create_delete.py`, `test_agent_membership_indexes.py`, `test_agent_role_tool_profile_service.py` |
| `agent_tool_governance_service.py` | Controlled Agent tool-permission governance. | — | `agents.py` | `test_agent_config_workspace_service.py`, `test_agent_lifecycle_create_delete.py`, `test_agent_lifecycle_reset_policy.py` |
| `cli_agent_service.py` | Controlled non-interactive adapters for external CLI coding agents. | — | — | `test_cli_agent_service.py` |
| `cli_agent_terminal_service.py` | Persistent terminal sessions for configured CLI Agent adapters. | — | `cli_agents.py` | `test_cli_agent_service.py`, `test_cli_agent_task_kernel.py`, `test_web_lifecycle.py` |
| `project_agent_bus_service.py` | Project-level Agent communication bus. | — | `project_agent_bus.py` | `test_agent_orphan_team_private_sessions.py`, `test_developer_sandbox_path_routing.py`, `test_project_agent_bus_routes.py` |
| `prompt_template_service.py` | Prompt template index service for AgentInstance configuration. | — | `agents.py` | `test_agent_config_workspace_service.py`, `test_agent_lifecycle_create_delete.py`, `test_agent_lifecycle_reset_policy.py` |
| `supervised_agent_service.py` | Persistent AgentInstance alignment for supervised evolution roles. | — | `agents.py`, `evolution.py` | `test_agent_config_workspace_service.py`, `test_agent_lifecycle_create_delete.py`, `test_agent_lifecycle_reset_policy.py` |

## Chat room / conversation index

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `chat_room_service.py` | Chat room orchestration for multi-session agent discussion. | — | `agents.py`, `chat_rooms.py` | `test_agent_bulk_delete_service.py`, `test_agent_bulk_edit_service.py`, `test_agent_config_workspace_routes.py` |
| `conversation_service.py` | Unified conversation index for direct agents and group rooms. | — | `conversations.py` | `test_multi_agent_conversations.py`, `test_runtime_scene_package_index.py`, `test_session_workspace_isolation.py` |
| `conversation_timeline_service.py` | Conversation timeline projection for chat session messages. | — | — | `test_conversation_timeline_service.py` |

## Knowledge / RAG

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `rag_retrieval_service.py` | Governed RAG retrieval helpers for Team Knowledge. | — | `knowledge.py` | `test_rag_retrieval_service.py` |
| `rag_vector_index_service.py` | File-backed metadata for optional RAG vector indexing. | — | — | `test_developer_sandbox_path_routing.py`, `test_memory_cleanup_service.py`, `test_rag_vector_index_service.py` |
| `team_knowledge_service.py` | Team-scoped knowledge base storage and governance service. | `team_knowledge/` | `knowledge.py` | `test_agent_tool_contracts.py`, `test_developer_sandbox_path_routing.py`, `test_knowledge_routes.py` |
| `unified_knowledge_search_service.py` | Unified read-only search boundary for governed memory and formal knowledge. | — | — | `test_unified_knowledge_search_user_content.py` |

## Memory

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `memory_cleanup_service.py` | Hard-delete cleanup helpers for Memory Library targets. | — | `memory.py` | `test_memory_cleanup_service.py`, `test_select_tests.py`, `test_web_memory_routes.py` |
| `memory_graph_service.py` | Read-only project memory knowledge graph service. | — | `memory.py` | `test_team_knowledge_service.py`, `test_web_memory_routes.py` |
| `memory_service.py` | Agent memory overview and user management service. | — | `memory.py` | `test_agent_protocol.py`, `test_agent_tool_contracts.py`, `test_codebase_map_builder.py` |

## Research / Challenge Cup

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `challenge_cup_versioning_service.py` | Lightweight Challenge Cup candidate versioning ledger. | — | — | `test_challenge_cup_operations_tools.py`, `test_challenge_cup_versioning_service.py` |
| `research_evidence_service.py` | Web-facing ClaimEvidence service with no formal knowledge side effects. | — | `research_evidence.py` | `test_research_evidence_routes.py` |
| `research_loop_service.py` | Template-driven research loop orchestration service. | — | `research_loop.py` | `test_challenge_cup_operations_tools.py`, `test_memory_storage_finalization.py`, `test_research_loop_routes.py` |
| `research_organization_service.py` | Research organization graph and communication bus. | — | `research.py` | `test_context_engine.py`, `test_multi_agent_conversations.py`, `test_research_organization_service.py` |
| `research_service.py` | Web service facade for Research theme discovery. | — | `research.py` | `test_research_theme_discovery.py` |

## Self / Supervised evolution

**30 秒路由（控制面 / payload / worktree / 主测）：** [`evolution_services.md`](evolution_services.md)

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `chat_review_service.py` | Web payloads for reviewed chat-dataset candidates. | — | `evolution.py` | `test_web_app.py`, `test_web_evolution_routes.py` |
| `evolution_runtime_projection_service.py` | Unified runtime projections for evolution workspace surfaces. | — | `evolution.py` | `test_evolution_runtime_projection_service.py` |
| `evolution_service.py` | Real supervised evolution payloads for the web workbench. | — | `evolution.py` | `test_developer_sandbox_path_routing.py`, `test_evolution_service.py`, `test_runtime_scene_package_diagnosis.py` |
| `self_evolution_autonomous_loop_service.py` | Persistent no-score orchestration for user-approved self-evolution loops. | — | `evolution.py` | `test_self_evolution_autonomous_loop_service.py` |
| `self_evolution_control_service.py` | Bounded self-evolution run control for the web workbench. | — | `agents.py`, `evolution.py` | `test_agent_config_workspace_service.py`, `test_agent_lifecycle_create_delete.py`, `test_agent_lifecycle_reset_policy.py` |
| `self_evolution_service.py` | Real self-evolution payloads for the web workbench. | — | `evolution.py` | `test_self_evolution_service.py`, `test_web_app.py`, `test_web_config_routes.py` |
| `supervised_candidate_integration_service.py` | Transactional Git integration for supervised evolution candidates. | — | — | `test_supervised_candidate_integration_service.py` |
| `supervised_candidate_runtime_service.py` | Isolated execution contract for a supervised candidate harness. | — | — | `test_supervised_candidate_runtime_service.py` |
| `supervised_control_service.py` | Live supervised run control for the web workbench. | — | `evolution.py` | `test_developer_sandbox_path_routing.py`, `test_runtime_manager.py`, `test_session_detail_contract.py` |
| `supervised_worktree_evolution_service.py` | Supervised worktree self-evolution loop for the web workbench. | — | `evolution.py` | `test_developer_sandbox_path_routing.py`, `test_select_tests.py`, `test_supervised_runtime_activation_intent.py` |

## Runtime / runtime scene

**与 Launcher 共用迷你索引：** [`launcher_runtime.md`](launcher_runtime.md) · scene pack：[`runtime_scene/README.md`](runtime_scene/README.md)

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `runtime_manager_control_service.py` | Lightweight runtime-manager control checks for web services. | — | — | `test_runtime_manager_control_service.py` |
| `runtime_scene_service.py` | Structured runtime scene bundles for frontend inspection and agent diagnosis. | `runtime_scene/` | `agents.py`, `knowledge.py`, `launcher.py`, `logs.py`, `runtime.py` | `test_agent_protocol.py`, `test_challenge_cup_operations_tools.py`, `test_chat_next_state_signals.py` |
| `runtime_service.py` | Runtime summary helpers for the web shell. | — | `runtime.py` | `test_launcher_service.py`, `test_model_config_migration.py`, `test_runtime_service.py` |

## Launcher / Reset

**30 秒路由（生命周期 / 无控制台 / 主测）：** [`launcher_runtime.md`](launcher_runtime.md)

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `launcher_service.py` | Compatibility facade for the standalone Launcher service. | — | `launcher.py` | `test_launcher_developer_mode.py`, `test_launcher_service.py`, `test_supervised_runtime_activation_intent.py` |
| `reset_service.py` | Compatibility alias for Launcher-owned reset maintenance. | — | — | `test_developer_sandbox_path_routing.py`, `test_reset_service.py`, `test_web_misc_routes.py` |

## Config / Provider / Model / Theme

**30 秒路由（operator config / provider 草稿 / 模型引用 / 主测）：** [`config_services.md`](config_services.md)

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `avatar_image_service.py` | User avatar image storage helpers for the web workbench. | — | `config.py` | `test_web_config_routes.py` |
| `config_service.py` | Config workspace helpers for the web workbench. | — | `config.py` | `test_agent_archive_session_lifecycle.py`, `test_agent_config_workspace_routes.py`, `test_agent_config_workspace_service.py` |
| `model_capability_service.py` | Shared model capability inference for web services. | — | — | — |
| `model_reference_service.py` | LLM model reference lifecycle helpers. | — | `config.py` | `test_model_reference_service.py`, `test_provider_config_service.py`, `test_select_tests.py` |
| `provider_config_service.py` | Draft-only Provider registry orchestration for the config workbench. | — | `config.py` | `test_config_redaction.py`, `test_llm_config_v2_integration.py`, `test_provider_config_service.py` |
| `theme_background_service.py` | Workbench theme background image storage helpers. | — | `config.py` | `test_theme_background_service.py`, `test_web_config_routes.py` |
| `tool_policy_configuration_service.py` | Versioned Agent ToolPolicy configuration, validation, and explain projections. | — | `agents.py` | `test_agent_tool_policy_configuration.py` |

## Workbench contract / preferences

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `workbench_contract_service.py` | Shared workbench contract helpers for frontend-facing defaults and availability. | — | — | `test_web_config_routes.py` |
| `workbench_ui_preferences_service.py` | Project-local durable Workbench UI preferences (layout, shell chrome). | — | `workbench_ui.py` | `test_workbench_ui_preferences_service.py` |

## Git

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `git_status_service.py` | Git status and local commit helpers for the web workbench. | — | `git.py` | `test_git_status_service.py`, `test_web_git_routes.py` |

## Logs / Diagnostics

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `diagnostics_service.py` | Health diagnostics helpers for the web workbench. | — | `diagnostics.py` | `test_log_diagnostics.py` |
| `log_service.py` | Log tree, preview, and guarded cleanup helpers. | — | `logs.py` | `test_log_diagnostics.py`, `test_web_config_routes.py`, `test_web_log_routes.py` |

## Workspace files

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `file_service.py` | Workspace file tree and preview helpers. | — | `files.py` | `test_agent_lifecycle_create_delete.py`, `test_agent_membership_indexes.py`, `test_agent_role_tool_profile_service.py` |

## Tools registry

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `tool_registry_service.py` | Tool registry service for the local web workbench. | — | `tools.py` | `test_agent_tool_policy_configuration.py`, `test_computer_use_tool.py`, `test_select_tests.py` |

## Skills

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `skill_library_service.py` | External memory-backed skill library indexing and search. | — | — | `test_skill_library_service.py` |
| `skill_service.py` | Read-only skill library service for the web workbench. | — | `skills.py` | `test_skill_service.py`, `test_web_app.py` |

## Pet

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `pet_service.py` | Pet space summary helpers. | — | `pet.py` | `test_pet_web_actions.py` |

## Computer Use

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `computer_use_service.py` | Controlled Computer Use service for sandbox browser automation. | — | `computer_use.py` | `test_computer_use_tool.py`, `test_developer_sandbox_path_routing.py` |

## Data processing

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `data_processing_service.py` | Generic data processing substrate for agent-driven intake pipelines. | — | `data_processing.py` | `test_data_processing_routes.py`, `test_data_processing_service.py`, `test_research_project_agent_sessions.py` |

## User content markdown

| Facade | 职责（docstring） | Pack | Routes（主） | Tests（启发式） |
| --- | --- | --- | --- | --- |
| `user_content_markdown_service.py` | User markdown content space (read/index/delete semantics for workbench). | — | `user_content.py` | `test_team_knowledge_tools.py`, `test_unified_knowledge_search_user_content.py`, `test_user_content_markdown_service.py` |

## 硬边界（所有 facade）

| MUST | MUST NOT |
| --- | --- |
| Route 薄；业务在 service/pack | Route 直写 store / 无界业务 |
| 有 pack 时新逻辑进 pack + re-export | 只在 facade 无限堆实现 |
| 公共 JSON 有 `response_model` | 无故升高 untyped endpoint 预算 |
| Projection 只读派生 | Projection 第二写入 |
| 改后聚焦测试 | 无验证声称完成 |

## 维护

- 新增 `*_service.py`：同一 PR 更新本表一行（或重跑生成脚本）。
- 拆 pack：填 Pack 列并添加 `README.md`（30 秒 routing 表）。
- Docstring 第一句 = 一句话职责（本索引依赖）。
- 重生成：`python scripts/_gen_services_readme.py`
