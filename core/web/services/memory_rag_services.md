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
| **正式知识全文分页回读**（Agent 工具） | `knowledge_read_service.py` → `team_knowledge_service.get_readable_knowledge_item` | 任意来源路径读取、绕过 ACL/MemoryPolicy、读取其他 Agent 私有正文 |
| 受审修订、版本历史、来源撤回/过期 | `team_knowledge/governance.py` + `lifecycle.py` + `retrieval.py` | 覆写旧正文；过期来源恢复后自动复活旧结论 |
| 真实中文语义索引/混合排序 | `team_knowledge/semantic.py` + `knowledge_embeddings.py` | 查询时下载模型；用词重合度冒充向量检索 |
| 用户 Markdown 空间（import/index/delete 语义） | `user_content_markdown_service.py`（route：`user_content.py`） | 与 formal knowledge JSONL 混写同一 owner 路径 |
| 外部 Skill Library 索引/搜索 | `skill_library_service.py` | 与 team_knowledge 双写同一路径 |
| 开源 GitHub 项目索引（默认主干浅克隆 + 生成 INDEX） | `github_project_library_service.py` | 把整仓正文写入 KnowledgeItem / RAG；未落盘就把网页当结论 |
| ClaimEvidence（无 formal KB 副作用） | `research_evidence_service.py` | evidence 写入 team knowledge items |
| HTTP 路由 / DTO | `memory.py` · `knowledge.py` · `user_content.py` | route 业务体；日志输出完整 memory body |

**「谁负责硬删除？」** → 仅 `memory_cleanup_service.execute_memory_cleanup`（需 preview token + 确认短语 `硬删除记忆`）；KB 行级删除仍走其 target 编排，不得散落各 service。

**「谁负责索引？」** → formal knowledge 内容 SSOT 在 `team_knowledge/*`。`rag_vector_index_service` 保存 owner-scoped 派生向量和全文指纹；`knowledge_semantic_service` 按完整正文分块，用 FastEmbed BGE 中文模型构建，混合检索采用 BM25 + cosine 的 RRF。查询先由 canonical ACL/lifecycle 选出候选，再读取其索引，不能截断候选后才排序。旧 metadata-only 记录不代表 semantic ready，未准备或过期时返回明确状态。模型下载只由显式 prepare/build 触发，审核同步仅处理当前新条目且只用本地权重。

修订不覆写 `items.jsonl` 的旧正文：新条目使用独立 ID 与 `revision/rootKnowledgeItemId/supersedesKnowledgeItemId/contentSha256`；提案创建和审核都检查父正文哈希，防止并发覆盖。来源撤回/过期修改 owner-local SourceArtifact，原始文件保留；重新激活来源不能使旧知识自动复活，须新修订审核。受控 `readMode=source` 只读取直接关联、路径与 SHA 校验通过的 UTF-8 中央文本快照；历史读取只返回版本元数据。

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

完整保留会话文档时，原生 `knowledge_ingestion_tool` 可选 `content_mode=source_document`，只接受已受控暂存的完整 document Inbox source；服务在审核权限、Owner/知识库一致性与 Team 禁止自审校验后，从该 Owner 的 Inbox 快照读取正文并验证 `extractedTextSha256`，在晋升前拒绝越界路径、缺失/改写/截断快照与超限正文。模型不再重传 `proposal_content` / `excerpt`。默认 `authored` 保持原提案与摘要行为，REST DTO 不变；旧暂存来源没有正文校验值时须重新暂存。保真对象是抽取后统一换行并经既有首尾空白规范化的文本，附件原始字节仍由 `documentHash` 与附件副本追溯。

检索的匹配与排序使用完整正式正文及该条目关联来源的标题/摘要，跨可读库排序后取 Top K；
响应保留旧 `content` 摘录并新增有界 `matchedExcerpt`，统一搜索和 RAG 优先使用命中段落。
`semantic` 使用本地 FastEmbed 向量，`hybrid` 结合 BM25 与 cosine 排名；查询不会准备或下载模型，
只有显式 prepare/build 才会触发模型准备。RAG health/policy 分别报告模型就绪和索引覆盖情况。
向量缺失或不可用时，`hybrid` 会回退到 BM25，并通过 `semanticRetrieval.status/reason/effectiveMode/impact`
说明实际检索能力；纯 `semantic` 不会伪装成关键词结果。知识审核先写入 canonical item，再尝试同步派生索引；
同步失败不撤销已审核正文，`semanticIndex` 会报告失败状态，索引可通过显式 build 重建。

正式条目的 `content` 当前可能包含知识管家保存的 JSON 审计包；本轮检索和回读保持其
原始含义，不解包、不改写存量数据。审计字段或候选文献清单仍可能命中，不能把每一次
匹配都解释为已核实的知识结论；知识正文与治理元数据的读取投影需要独立确定契约。

`read_knowledge_item_tool` 绑定当前 Agent 和 MemoryPolicy，按字符分页正式条目正文；
返回 `hasMore/nextOffset`、来源引用和不可信材料标记。`item` 模式只读取当前正文及来源引用；
`source` 模式经关联、owner 路径边界和哈希校验后读取中央文本快照，不接受调用者提供的文件路径。
原始来源正文未读时明确返回 `sourceBodyStatus=source_body_unavailable`；财务证据资格由
正式知识 facade 校验，失效或已归档内容不通过该工具回读。运营健康检查通过请求内读取计数
报告 JSONL 坏行和 I/O 失败，不输出原始行、正文或存储路径。

个人记忆列表的文件 metadata 包含可选 `revision`（文件 `mtime_ns:size`）；它复用已有 stat，
不读取正文，也不是内容哈希。旧 `updatedAt` 仍保持秒级显示格式。前端详情 cache key 使用
选中 Agent 的文件 revision、路径和知识摘要；列表轮询发现变化后更新正文，未变时不增加
正文请求。改写并保留原始 mtime 和 size 的外部工具不在该 metadata 标识的检测能力内。
详情接口每次只读取一次 inventory；不匹配的 actor 只读取 metadata，保持 unknown Agent
先返回 404、已知 Agent 的无效 actor 返回 422 的现有顺序。

---

## 主测（可复制）

知识图谱新增显式 include：`knowledge` 展开当前 actor 有权读取的 Agent / Team 正式知识条目，
`privateMemory` 展开当前 actor 的私有文件 metadata，`officialResearchGraph` 保留科研追踪引用。
默认请求与旧 `all` 不增加这两类展开。图谱节点不含私有正文；点击私有文件详情时先校验 owner
等于 actor，再调用现有 memory inventory 读取。可见队友的私有文件不会随团队结构一起展开。

`GET /api/memory/agents` 的 `Server-Timing` 响应头仅含毫秒耗时：`memory-directory` 为 Agent 目录读取（含修复、等待与摘要投影），`memory-paths` 为共享路径上下文解析，`memory-scan` 为逐 Agent 文件扫描与正式知识统计，`memory-total` 为完整 service 计算。JSON 内容与权限契约保持原样；这些计时不含 HTTP 调度、响应模型序列化和传输，不能直接当成浏览器总等待时间，也不会触发额外日志写入。

单次 inventory 调用复用按项目分区的正式工作区根解析；调用结束即释放，下次调用重新解析存储位置。沙箱选择与补种仍逐路径执行，路径包含性检查仍使用实际解析结果；该快照不用于跨请求缓存文件或知识内容。

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
