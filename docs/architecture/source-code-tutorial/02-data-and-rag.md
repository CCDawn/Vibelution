[← 上一部分](01-foundation.md) · [教程目录](README.md) · [下一部分 →](03-agents-and-desktop.md)

# 存储、历史与 RAG

## 7. 数据存储全景：先纠正“后端连 MySQL”的理解

### 7.1 当前代码的事实是什么

检查当前 `requirements.txt`、`core/`、`config/`、`tools/` 的核心实现，没有找到 MySQL、PyMySQL、mysqlclient 或 SQLAlchemy 作为这套业务存储的接入实现。也没有找到将核心知识索引接到 Qdrant、Chroma、Milvus、FAISS、LanceDB 或 pgvector 的现成业务适配链。**这份源码并没有“后端如何连接现有 MySQL”的链路可供讲解。**

这不表示数据库不重要，而是作者为本地工作台选择了不同持久化方式。也不排除用户将来借助工具访问自己的外部数据库；那和项目内部已经接入 MySQL 是两回事。

| 数据类别 | 当前主实现 | 权威内容 | 关键入口 |
| --- | --- | --- | --- |
| 可写 Agent 主配置 | 工作区 `agents/agents.json` | 当前 Agent 模型/角色/权限/记忆等配置的 canonical 主数据 | `agent_directory/repair_store.py`、`mutations.py` |
| 会话目录、Agent 引用与快照 | SQLite，ConversationStore | Agent 引用、不可变配置编译快照、会话元数据、索引与控制状态；不替代上述可写注册表 | `core/chat/conversation_store/` |
| 会话正文及工具过程 | 每个 Session 的 `turn_journal.jsonl` | 用户、助手、工具及轮次事件 | `core/chat/turn_journal.py` |
| 运行中即时输出 | 内存 live state，辅以 checkpoint | 未完成输出的恢复/显示桥 | `services/session/live_output*.py` |
| Agent 个人经历记忆 | Owner 范围的 JSONL 等 | 个人笔记、偏好、事实、私有记忆与失效关系 | `agent_directory/episodic_memory.py` |
| 正式知识 | Owner 范围的 JSON、JSONL、来源快照文件 | 知识库、条目、提案、来源及修订 | `team_knowledge/` |
| 向量索引 | JSON 文件中的归属、指纹、chunk offset、数值向量 | 可重建的检索派生数据，非正式知识正文权威 | `rag_vector_index_service.py` |
| 研究工作流 | SQLite Workflow Ledger + checkpoint | Ledger 管工作流事实；checkpoint 管恢复位置 | `core/research/workflow/ledger/` 等 |
| Git 变更记忆 | SQLite 等索引 | Git 相关派生读取与维护 | `core/infrastructure/git_memory.py` |
| 启动与运行管理 | JSON、JSONL、部分 SQLite | 实例、进程、窗口、命令、回执与会话镜像等 | `.runtime/`、runtime/launcher modules |

这里不能简单概括成“全部数据都在一个 db 文件里”，也不能说“SQLite 里面存了全部对话正文”。当前设计有多个明确分工的存储。

### 7.2 SQLite 是怎样被后端调用的

SQLite 是嵌入式数据库：Python 打开本地数据库文件执行 SQL，不需要先安装独立 MySQL Server、创建远程账号再连接端口。当前 canonical ConversationStore 使用 APSW 支撑的适配运行时；代码里有些模块把适配层导入名写成 `sqlite3`，不能只看变量名就认定用了标准库驱动。

```text
HTTP 请求
  → Agent/Session 业务服务
  → ConversationStore 公共 API
  → writer / repository / UnitOfWork
  → database（连接、事务、WAL、安全版本与迁移）
  → runtime.py 适配 APSW
  → chat/conversations.sqlite3
```

`schema.py` 声明迁移与校验；`database.py` 管连接、读连接租约、SQLite 版本/WAL 策略和错误分类；`writer.py` 提供有界单写入协调；`repository.py` 执行具体领域 SQL；`store.py` 提供组合后的接口。不是 React 自己拼 SQL，也不是每个 route 随手新建一套写数据库逻辑。Agent 主配置的注册表写入与数据库编译快照的关系，见第 25 章；不能把两条写路径合并描述。

源码定位：[core/chat/conversation_store/runtime.py](../../../core/chat/conversation_store/runtime.py)；[core/chat/conversation_store/database.py](../../../core/chat/conversation_store/database.py)；[core/chat/conversation_store/writer.py](../../../core/chat/conversation_store/writer.py)；[core/chat/conversation_store/repository.py](../../../core/chat/conversation_store/repository.py)；[core/chat/conversation_store/schema.py](../../../core/chat/conversation_store/schema.py)。

### 7.3 数据表的作用与关联

以下是当前 schema 中几类核心对象的教学地图，完整表名以该文件和实际数据库 schema 为准：

```text
agents（agent_id）
   │ 1:N
   ├─ agent_config_revisions（该 Agent 的不可变编译快照）
   │
   └─ sessions（session_id，agent_id，配置修订引用等）
         ├─ 父会话关系
         ├─ 标题、归档、状态、recency、预览等目录信息
         └─ session_runtime_state 等控制壳

正文事件另走：sessions/<session_id>/turn_journal.jsonl
```

`agent_config_revisions` 是数据库里的编译快照，不等于配置编辑事件文件中的“发布修订”。同名的 revision 概念在不同层有不同职责。历史迁移曾留下 `turns/turn_items` 等 schema 结构，也不能据此断言当前实时 transcript 写入它们；当前代码注释明确指出，实时正文仍归 Journal。

### 7.4 WAL、事务、单写者为什么要存在

你在界面中切换会话，后台也在写运行状态、处理消息、刷新目录。如果任意线程和进程同时覆盖文件，很容易丢数据或卡住。项目用以下方式约束：

- **事务**：一组相关修改全部成功或全部回滚，防止创建会话成功一半。
- **外键**：会话归属、配置引用等不能轻易指向不存在的对象。
- **WAL**：SQLite 采用 Write-Ahead Logging，改善读写并发；它不是消除所有锁。
- **有界 writer**：集中排队写，遇到拥塞或关闭有明确失败，而不是无限等待。
- **busy timeout 与错误分类**：短时间锁冲突不能直接被误报成业务不存在。
- **迁移 checksum**：数据库升级要能判断应用过什么结构，不能手工改表后假装一致。

源码可见 `BEGIN IMMEDIATE`、`PRAGMA journal_mode=WAL`、`PRAGMA foreign_keys=ON` 等。应用对 SQLite/WAL 的运行版本还有安全校验，不能为省事随意替换掉固定数据库运行时。

### 7.5 一次目录写入的教学伪代码

```python
# 教学伪代码，不是实际函数签名。
def create_session(request):
    agent = directory.require_agent(request.agent_id)
    frozen_config = compile_current_agent_config(agent)
    return conversation_store.mutate(
        lambda unit_of_work: unit_of_work.create_session(
            agent=agent, config_revision=frozen_config
        )
    )
```

这里体现三个层次：业务先检查 Agent；数据库事务维护目录一致性；聊天正文并不因为创建 session row 就已经产生。正文需要后续 message admission 写 Journal。

### 7.6 如果以后真的想接 MySQL，需要改哪里

这是**扩展设计说明，当前没有实现**。不能把 SQLite 文件路径改成 `mysql://...` 就完成迁移。

至少要重新设计：数据库 driver/连接池与凭据配置；repository 的 SQL 方言与事务；写入协调、锁与 CAS；schema migration；本地文件和 JSONL 的分工；故障/网络超时；数据导入回滚；权限和多用户隔离；测试与备份恢复。原来适用于“本机一个工作台”的假设，不一定适用于“多人共享一个数据库”。

更稳妥的学习方式是先保留 service facade，在独立练习分支中抽象 repository 接口，使用虚构数据做替换实验；不要直接拿现有活跃会话数据库做迁移练习。即便改用 MySQL，也仍要明确 Journal 是否迁移、正式知识是否迁移，避免出现两份正文事实源。

## 8. 历史记录：为什么刷新后还能找到之前的回答

### 8.1 历史不是一个数组随便保存

`core/chat/conversation_ledger.py` 直接说明：对话账本是 authoritative append-only event stream，当前物理存储是 turn journal JSONL。每行是一项事件，而不是只保留最后一个聊天气泡。

典型事件包括：

| 事件 | 意义 |
| --- | --- |
| `turn_started` | 开始一轮执行 |
| `user_message` | 接受了用户输入 |
| `assistant_delta_committed` / `assistant_item_committed` | 输出或条目已经提交到持久事件链 |
| `tool_call_started` | 工具调用开始 |
| `tool_result` | 工具结果 |
| `assistant_message` | 最终助手消息相关事实 |
| `turn_completed` / `turn_failed` / `turn_interrupted` | 明确的轮次终态 |
| `compaction_checkpoint` | 上下文压缩检查点 |
| `turn_steer` | 执行中引导或排队输入的准入记录 |

事件类型更多，不能把这张教学表当作完整枚举。也不是每个事件都应该直接展示给用户或送给模型；源码有模型可见、审计、volatile 等投影分类。

教学事件外观示意，字段以真实 dataclass 为准：

```json
{"seq": 1, "type": "turn_started", "turnId": "turn-demo"}
{"seq": 2, "type": "user_message", "turnId": "turn-demo", "text": "示例问题"}
{"seq": 3, "type": "tool_result", "turnId": "turn-demo", "result": "示例结果"}
{"seq": 4, "type": "turn_completed", "turnId": "turn-demo"}
```

源码定位：[core/chat/turn_journal.py](../../../core/chat/turn_journal.py)；[core/chat/conversation_ledger.py](../../../core/chat/conversation_ledger.py)；[core/chat/history_ledger.py](../../../core/chat/history_ledger.py)。

### 8.2 历史的物理位置

`turn_journal_path()` 解析会话共享工作区后返回：

```text
<正式 workspace>/sessions/<安全化的 session_id>/turn_journal.jsonl
```

常规安装的正式 workspace 通常位于用户数据目录，而不是源码 checkout 根。函数内部先做安全 token 和路径解析；不要把任意浏览器参数直接拼成磁盘路径。

会话列表另由 `<workspace>/chat/conversations.sqlite3` 提供。这样列表不必为了显示几十个标题，把每段历史的巨大 Journal 全扫一遍。这是**目录索引与正文事实分离**的实用原因。

源码定位：[core/chat/turn_journal.py · turn_journal_path](../../../core/chat/turn_journal.py#L505)；[core/web/services/session/directory_runtime.py](../../../core/web/services/session/directory_runtime.py)；[core/web/services/session/catalog_bridge.py](../../../core/web/services/session/catalog_bridge.py)。

### 8.3 从磁盘记录到页面的“重放”

```text
JSONL events
   ├─ 对话投影 → user/assistant/tool messages → 模型上下文
   ├─ UI 投影 → SessionDetail.messages.turnItems → cells 展示
   ├─ 历史工具投影 → 搜索/分页/时间线
   └─ 恢复判定 → 哪轮未终结、是否需要中断/恢复
```

因此同一份事实可以有多种读取视图，而不需要每个模块保存自己的独立聊天正文。`conversation_invariant.py` 检查模型对话层是否能与账本对齐；不是允许 payload 层遇到坏记录就偷偷修补孤立工具调用。

### 8.4 SSE、缓存、日志为什么都不能代替历史

SSE 是传输：浏览器关闭后连接就断。React Query 是前端缓存：刷新就可能重建。live output 是运行中显示桥：还没完成的回复可能只在其中。诊断日志为了排错，可能被裁剪、轮转或脱敏。

这些都服务于体验或运维，**durable transcript 仍由 Journal 决定**。排错时不能“看一眼日志里有一句回复”就手工往页面缓存塞字串，应该沿 capture → Journal → projection → SSE 逐段检查。

### 8.5 中断、失败、重试、编辑为什么复杂

模型还在流输出时点击停止，可能和工具结果/最终回答写入并发。项目要防止同一 Turn 重复写终态，或者已经结束的 Turn 又追加新的可见输出。新版本还有精确的失败重试前提：提交 ID、Turn、head、ledger 水位、Agent 等必须匹配，才能保证重试的是用户看到的那次失败，而不是别人后来修改过的会话。

当前普通编辑重提/重新生成通过追加 branch_rebase 等事件改变活动分支，并不是直接删除旧分支正文。群聊 transcript 清理等受控路径仍存在显式物理 rewrite API，所以“append-only”也不能理解成磁盘文件绝对永远不变。旧说明中的“truncate”可能指活动投影截断，要继续检查实际写调用；第 32 章按当前代码进一步展开。

源码定位：[core/web/services/session/retry.py](../../../core/web/services/session/retry.py)；[core/web/services/session/admission_lock.py](../../../core/web/services/session/admission_lock.py)；[core/chat/conversation_branches.py](../../../core/chat/conversation_branches.py)；[core/chat/turn_journal.py · rewrite_turn_events](../../../core/chat/turn_journal.py#L1284)。

### 8.6 历史很长时，为什么模型没有看到全部内容

保存历史与发送全部历史是两个问题。上下文窗口有上限，因此 `context_assembler.py`、microcompact、压缩检查点和 prompt budget 会决定本轮实际输入。原始记录可以保留，但模型只看到重建、选择或压缩后的视图。

这也解释“界面里明明有，AI 为什么忘了”：可能没进入当前模型窗口、被摘要化、属于别的 Session，或没有通过有权限的历史检索工具取回。增加界面显示长度不会自动增加模型上下文。

源码定位：[core/chat/context_assembler.py](../../../core/chat/context_assembler.py)；[core/chat/microcompact.py](../../../core/chat/microcompact.py)；[core/orchestration/turn_compression.py](../../../core/orchestration/turn_compression.py)；[tools/conversation_history_tools.py](../../../tools/conversation_history_tools.py)。

## 9. 记忆、正式知识、RAG：三者不要混在一起

### 9.1 四种“记得”

| 能力 | 记住什么 | 如何进入下一次模型调用 |
| --- | --- | --- |
| 当前 Session 历史 | 这段对话发生过什么 | Journal → 上下文重建，受窗口/压缩约束 |
| Agent 个人经历记忆 | 该 Agent 的偏好、笔记、会话事实等 | 按策略选择有效个人记忆，进入运行上下文 |
| 正式知识 | 有 Owner、来源、审核和生命周期的知识条目 | 经授权搜索、RAG 或正式全文读取工具取回 |
| Prompt/Skill | 身份、方法与工作纪律 | 系统/运行上下文章节；不是客观经历的替代品 |

`agent_directory/episodic_memory.py` 维护个人经历 JSONL。它的 docstring 明确：写入本身不调用 LLM，不自动创建公开知识。原有记忆失效使用 supersede/有效期关系保留来源链，不能简单把“新偏好”追加在后面而让互相冲突的两条都永久有效。

`context_engine.py` 按记忆开关和选择策略读取个人记忆，并组装“个人记忆”段。相关代码存在选择预算，不应理解成把无限增长的每条记忆完整塞进每次请求。

源码定位：[core/web/services/agent_directory/episodic_memory.py](../../../core/web/services/agent_directory/episodic_memory.py)；[core/orchestration/context_engine.py · build_agent_context](../../../core/orchestration/context_engine.py#L387)；[core/web/services/agent_directory/personal_memory_selection.py](../../../core/web/services/agent_directory/personal_memory_selection.py)。

### 9.2 正式知识为什么要经过治理

网页、PDF、模型生成摘要、团队聊天都可能包含错误或不可信指令。项目把来源、知识提案、审核、正式条目和修订分开，避免“AI 随便说一句”立即变成所有 Agent 都能查到的事实。

```text
外部资料/受控上传
  → Owner source inbox（待审来源）
  → 来源审核/中央来源引用
  → 提炼或完整文档入库提案
  → 知识审核
  → 正式 KnowledgeItem
  → 尝试同步派生向量索引
```

并非每一种来源都完全经过相同的按钮；关键是归属、来源与审核条件要走 canonical service。`source_document` 模式可以从已受控暂存的文档快照读取完整文本，并验证哈希，不要求模型把整篇文档再抄回参数。这是文档保真，不是绕过审核。

### 9.3 正式知识存在哪里

`team_knowledge/store.py` 解析 Owner 根：Agent 知识在 `agents/<agent_id>/knowledge/`，Team 知识在 `teams/<team_id>/knowledge/`，都位于解析后的 workspace。里面有知识库元数据、条目、来源、提案、审核等 JSON/JSONL；中央来源与原文快照另有受控目录。

常见文件包括 `knowledge_bases.json`、`items.jsonl`、`source_artifacts.jsonl` 等。以 store 的路径函数为准，不要自己发明一套 `mysql.knowledge_items` 解释现状。

源码定位：[core/web/services/team_knowledge/store.py · _knowledge_root_for_owner](../../../core/web/services/team_knowledge/store.py#L522)；[core/web/services/team_knowledge/governance.py](../../../core/web/services/team_knowledge/governance.py)；[core/web/services/team_knowledge/lifecycle.py](../../../core/web/services/team_knowledge/lifecycle.py)。

### 9.4 ACL 为什么必须先于排序

假设你只能读 Agent A 的私有笔记和团队公开库。如果先扫描所有人的知识、计算全局 Top K，再在末尾过滤，可能泄漏元信息，也可能让前 K 条全被过滤，导致你自己的可读资料根本没进入排名。

当前语义模块以**已授权、当前有效的候选**为输入：Owner、MemoryPolicy、审核状态、来源有效性等筛完后，再做 BM25/向量排序。选择 Top K 是最后的检索步骤之一，不能偷换成“先把候选截断到固定小集合再排”。

来源撤回、过期、条目失效、修订关系也会影响候选。文件还在磁盘，不代表它仍应作为有效知识召回。

源码定位：[core/web/services/team_knowledge/permissions.py](../../../core/web/services/team_knowledge/permissions.py)；[core/web/services/team_knowledge/retrieval.py](../../../core/web/services/team_knowledge/retrieval.py)；[core/web/services/team_knowledge/semantic.py · rank_candidates](../../../core/web/services/team_knowledge/semantic.py#L251)。

## 10. RAG 与“向量数据库”：逐步拆解实际实现

### 10.1 RAG 到底做什么

RAG 是 Retrieval-Augmented Generation：先检索资料，再把相关、有来源的片段交给生成模型。它不是训练模型参数，也不是把每篇文档都重新完整发送一遍。

举例：问题是“窗口关闭为什么慢”。关键词检索可能命中“关闭”“超时”；向量检索有机会把“进程退出延迟”“子进程回收”这些不同措辞关联起来。最终仍要核对来源；向量相似度不证明资料一定正确。

### 10.2 本项目的调用地图

```text
Agent 工具 / 知识页面
   → unified_knowledge_search_service.py 或 rag_retrieval_service.py
   → team_knowledge_service.py（公共 facade）
   → retrieval / permissions / lifecycle：可读且有效的候选
   → search_ranking.py：BM25
   → semantic.py：Embedding、cosine、RRF
       ├─ knowledge_embeddings.py：FastEmbed 本地推理
       └─ rag_vector_index_service.py：派生 JSON 索引
   → matchedExcerpt、来源、状态、引用
   → ToolResult/受控上下文
   → 下一次模型调用参考这些资料生成回答
```

源码定位：[tools/team_knowledge_tools.py](../../../tools/team_knowledge_tools.py)；[core/web/services/unified_knowledge_search_service.py](../../../core/web/services/unified_knowledge_search_service.py)；[core/web/services/rag_retrieval_service.py · retrieve_rag_contexts](../../../core/web/services/rag_retrieval_service.py#L73)；[core/web/services/team_knowledge/semantic.py](../../../core/web/services/team_knowledge/semantic.py)。

### 10.3 索引构建：文本怎样变成数值向量

1. 明确 Owner/知识库及调用者权限，取出可索引的正式条目。
2. 对当前正文及相关指纹进行校验，不把旧修订或已失效来源混入。
3. 在显式 prepare/build 允许时准备 Embedding 模型；普通查询不偷偷下载权重。
4. 把全文分块。当前 `semantic.py` 的常量为 **320 字符一块、重叠 64 字符**，即步长 256。这里是字符，不是 token。
5. 调用 `knowledge_embeddings.encode(..., purpose="passage")` 得到每块向量。
6. 校验维度、有限数值、非零范数，归一化，保存位置偏移、向量、模型身份和正文哈希。
7. 发布前再校验条目/权限等条件，防止构建期间正文已变化却把旧向量宣称为当前索引。

当前代码默认模型名是 **`voyage-4-nano`，自定义 ONNX 规格为 2048 维**。`knowledge_embeddings.py` 明确配置了本地 ONNX 模型仓库和查询前缀。部分 README 仍提到 BGE 中文模型，那是文档滞后；本教程以当前常量和实现为准。这不表示本机已经把该模型下载好或所有知识库均已建索引。

源码定位：[core/web/services/knowledge_embeddings.py](../../../core/web/services/knowledge_embeddings.py)；[core/web/services/team_knowledge/semantic.py · _chunks](../../../core/web/services/team_knowledge/semantic.py#L87)；[core/web/services/team_knowledge/semantic.py · build_knowledge_index](../../../core/web/services/team_knowledge/semantic.py#L131)。

### 10.4 索引文件到底存了什么

`rag_vector_index_service.py::_index_root()` 通过工作区路由，管理知识 RAG 派生目录；其下有 `index.json`、`items/`，语义模型缓存也由相关函数解析。每个条目记录包含 Owner、知识库、知识条目 ID、来源引用、contentHash、embeddingModel、状态及 chunks 等。

教学结构示意：

```json
{
  "ownerType": "agent",
  "ownerId": "agent-demo",
  "knowledgeItemId": "item-demo",
  "embeddingModel": "voyage-4-nano",
  "contentHash": "sha256:示意指纹",
  "chunks": [{"start": 0, "end": 320, "vector": [0.12, -0.04]}]
}
```

示例只画了 2 个数便于阅读，真实当前模型维度不是 2。chunk 主要保存正文位置而非另一份完整正文，命中后回读 canonical body 的对应片段。这种索引是**可重建缓存**：丢失它会影响检索性能/能力，不应等于正式知识正文也丢失。

### 10.5 查询时怎么比较

查询文本用同一个模型 `purpose="query"` 编码并归一化。对每个可用 chunk，代码做向量点积；双方均归一化时，点积就是余弦相似度：

```text
cosine(q, d) = Σ(qᵢ × dᵢ) / (||q|| × ||d||)
归一化后：cosine = Σ(qᵢ × dᵢ)
```

当前实现在 Python 中对候选和 chunk 进行比较，每个条目取最佳命中块，附上 `matchedExcerpt` 与偏移。它不是已经构建了 HNSW/IVF 的专用近似最近邻数据库。向量规模很大时，文件 I/O、维度与线性扫描可能成为性能上限，不能按大型向量集群的吞吐去估计它。

### 10.6 混合排序与降级

`bm25` 适合精确术语与词项相关性；`semantic` 使用向量；`hybrid` 结合两份排名。当前 RRF 常量为 `60`，示意计算：

```text
融合分数(d) = 1 / (60 + 向量名次(d)) + 1 / (60 + BM25名次(d))
```

某条目只在其中一个排名出现，就贡献一个分项。这是融合排名，不是把 BM25 分数与 cosine 生硬相加。

当模型未准备、向量缺失、正文哈希过期或维度不匹配时，`hybrid` 可以回退到 BM25，并返回 `semanticRetrieval.status/reason/effectiveMode/impact`。纯 `semantic` 则不会把关键词结果伪装成语义检索结果。**健康状态必须读实际 effectiveMode，不能只看界面选了 hybrid 就宣称向量已启用。**

### 10.7 检索如何真正影响模型回答

RAG 检索服务返回有界片段和 citation；具体 Agent/工作流通过工具或受控 context 入口取得，再进入模型输入。当前有 `unified_memory_search_tool`、正式知识分页读取等工具；不是每个普通聊天问题都自动、无条件搜索全部知识库。

若模型搜索到一条摘要还不够，可以用 `read_knowledge_item_tool` 按字符分页读取有权限的正式条目，或按受控 source 模式读取已关联且哈希通过的原文快照。调用者不能传任意磁盘路径来绕过 ACL。

RAG 效果依赖：有资料 → 已提炼/审核 → Actor 能读 → 当前条目有效 → 相关片段可命中 → 模型确实使用结果并保留引用。任意一环缺失，都可能表现成“资料已经上传，但 AI 不知道”。

源码定位：[core/web/services/knowledge_read_service.py](../../../core/web/services/knowledge_read_service.py)；[tools/team_knowledge_tools.py](../../../tools/team_knowledge_tools.py)；[core/web/services/rag_retrieval_service.py](../../../core/web/services/rag_retrieval_service.py)。

### 10.8 如果接入独立向量数据库，边界应放哪里

这是未来扩展设计，当前未接入。可在派生索引读写与检索边界后增加适配器，让 canonical knowledge 和 ACL 继续留在现有领域服务。外部库保存向量、受控 metadata 和来源映射；正式正文修订、撤回与权限仍由本项目决定。

至少要处理索引集合/命名空间、Owner 隔离、模型与维度版本、contentHash、新旧索引切换、删除联动、检索过滤、重建与故障降级。即使使用外部向量数据库，也不能只返回最相似的片段而跳过知识有效性与权限检查。

---

[← 上一部分](01-foundation.md) · [教程目录](README.md) · [下一部分 →](03-agents-and-desktop.md)
