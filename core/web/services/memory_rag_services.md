# Memory / RAG 迷你索引（R12）

**读者：coding Agent。**
**目标：30 秒内定位 memory/RAG 写入、硬删除、索引与只读搜索边界；不要在 projection 或 route 里开第二写入者。**

权威细则：[`docs/standards/development-standard.md`](../../../docs/standards/development-standard.md) SSOT 表 · [`team_knowledge/README.md`](team_knowledge/README.md) pack 地图。
全量 facade 表：[`README.md`](README.md) § Memory · § Knowledge / RAG。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| Agent Memory 概览 / user-managed / channel 投影 | `memory_service.py` → `vibelution_storage.resolve_project_memory_home` | 在 overview 路径直接 `shutil.rmtree`；绕过 ACL 读他人 private memory |
| Memory Library **硬删除**（preview → confirm → execute） | `memory_cleanup_service.py`（route：`memory.py`） | 无 preview token / 无确认短语删库；route 直删磁盘 |
| Memory **知识图谱**（只读） | `memory_graph_service.py` | graph service 写 JSONL/SQLite；把 body/prompt 无界打进 graph 节点 |
| Team 正式知识库 CRUD / proposal / inbox promote | `team_knowledge_service.py` + [`team_knowledge/`](team_knowledge/) pack | 在 `rag_*` 或 `unified_*` 里改 items.jsonl；ranking 模块写盘 |
| RAG **检索**（governed contexts） | `rag_retrieval_service.py` → `team_knowledge_service` | 第二套 retrieval 绕过 reviewed formal knowledge |
| RAG **向量索引元数据**（可选 local vector） | `rag_vector_index_service.py` | 索引层当 KB SSOT；cleanup 不走 preview grant |
| **统一只读搜索**（Agent/Team memory + 可选 user content） | `unified_knowledge_search_service.py` | unified search 写删除/索引；把 tool 授权塞进来 |
| 用户 Markdown 空间（import/index/delete 语义） | `user_content_markdown_service.py`（route：`user_content.py`） | 与 formal knowledge JSONL 混写同一 owner 路径 |
| 外部 Skill Library 索引/搜索 | `skill_library_service.py` | 与 team_knowledge 双写同一路径 |
| 开源 GitHub 项目索引（默认主干浅克隆 + 生成 INDEX） | `github_project_library_service.py` | 把整仓正文写入 KnowledgeItem / RAG；未落盘就把网页当结论 |
| ClaimEvidence（无 formal KB 副作用） | `research_evidence_service.py` | evidence 写入 team knowledge items |
| HTTP 路由 / DTO | `memory.py` · `knowledge.py` · `user_content.py` | route 业务体；日志输出完整 memory body |

**「谁负责硬删除？」** → 仅 `memory_cleanup_service.execute_memory_cleanup`（需 preview token + 确认短语 `硬删除记忆`）；KB 行级删除仍走其 target 编排，不得散落各 service。

**「谁负责索引？」** → formal knowledge 内容 SSOT 在 `team_knowledge/*`；可选 vector 元数据在 `rag_vector_index_service`；BM25/semantic 检索编排看 `rag_retrieval_service` + `team_knowledge/search_ranking.py`（纯函数，不写盘）。

---

## SSOT：写入 / 删除 / 索引 / 只读

```text
写入 SSOT
  → team_knowledge_service + team_knowledge/ pack：KB CRUD、proposal、inbox、public catalog
  → memory_service：Agent memory overview、user-managed overrides、managed audit
  → user_content_markdown_service：用户 markdown 空间文件与索引语义

硬删除 SSOT
  → memory_cleanup_service：TARGET_TYPES 统一 preview/execute；联动 rag index / KB rows / sqlite tables
  → 确认：CONFIRMATION_PHRASE = "硬删除记忆"；preview token TTL 300s

索引 / 检索（读侧编排，非第二内容真源）
  → rag_vector_index_service：list_indexable → index metadata（formal reviewed items）
  → rag_retrieval_service：retrieve_rag_contexts / health（local provider, bm25/semantic/hybrid）
  → unified_knowledge_search_service：search_unified_memory（只读；可含 user content 子集）
  → team_knowledge/search_ranking.py：BM25/filter 纯函数

只读边界（禁止变写入者）
  → memory_graph_service：ACL-aware graph 投影
  → unified_knowledge_search_service：stable Agent-facing search contract
  → research_evidence_service：ClaimEvidence，无 formal knowledge side effects

存储根（解析，不硬编码用户名）
  → vibelution_storage：resolve_project_memory_home / workspace / logs
  → developer_sandbox：项目根与隔离路径同步
  → 外部 cross-session memory：scripts/migrate_project_storage.py inventory（legacy .docs/project-memory 只读）
```

改 Agent Prompt 注入 memory 时，先查 tool/route 是否经 `unified_knowledge_search_service` 或 `rag_retrieval_service`，不要在 chat route 平行拼检索。

---

## 主测（可复制）

```powershell
# 矩阵 memory-cleanup 行
.\.venv\Scripts\python.exe -m pytest tests\test_memory_cleanup_service.py tests\test_web_memory_routes.py tests\test_reset_service.py -q

# Memory overview / graph / protocol
.\.venv\Scripts\python.exe -m pytest tests\test_agent_protocol.py tests\test_codebase_map_builder.py -q

# Team knowledge + routes
.\.venv\Scripts\python.exe -m pytest tests\test_team_knowledge_service.py tests\test_knowledge_routes.py tests\test_agent_tool_contracts.py -q

# RAG retrieval / vector index
.\.venv\Scripts\python.exe -m pytest tests\test_rag_retrieval_service.py tests\test_rag_vector_index_service.py -q

# Unified search + user content
.\.venv\Scripts\python.exe -m pytest tests\test_unified_knowledge_search_user_content.py tests\test_user_content_markdown_service.py -q

# Skill library（外部 memory 索引）
.\.venv\Scripts\python.exe -m pytest tests\test_skill_library_service.py -q

# 影响面（改 facade 后）
.\.venv\Scripts\python.exe tests\select_tests.py --changed-file core/web/services/memory_cleanup_service.py --commands-only
```

改 `team_knowledge/` pack 时加跑 `tests/test_matrix.yaml` `teams-knowledge` 行；硬删除/reset 触面含 runtime scene 时看 `test_memory_storage_finalization.py`。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`team_knowledge/README.md`](team_knowledge/README.md) | pack 切片与 claim scope |
| [`docs/guides/loop.md`](../../../docs/guides/loop.md) | 验证/完成块 |
| [`docs/guides/agent-dev-roi-backlog.md`](../../../docs/guides/agent-dev-roi-backlog.md) | R12 DoD |
| [`config_services.md`](config_services.md) · [`evolution_services.md`](evolution_services.md) | 同类迷你索引 |
| [`tests/test_matrix.yaml`](../../../tests/test_matrix.yaml) | `memory-cleanup` · `teams-knowledge` |
