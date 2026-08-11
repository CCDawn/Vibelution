# Agent 配置与会话统一 SQLite 迁移方案（复用优先）

> Status: **Proposed / CALIBRATED / ARCH_REVIEW_HARDENED**
> Created: 2026-08-11
> Baseline: `main@852d74af4ac81ac82289f090296ecb1852bdbe50`
> Scope: Agent 配置权威、会话父子关系、Turn/Item 持久化、前端状态边界、旧测试会话清理与可恢复切换
> User decisions: 旧 Agent 会话均为测试数据，不迁移；每个会话必须绑定一个 Agent 父节点；Agent 配置进入 SQLite；数据访问采用 DAO + Repository + Unit of Work；前端继续使用 React Query + Zustand；优先复用现有能力。
> Architecture hardening: 2026-08-11，补充 canonical 数据位置、单 writer actor、锁顺序、revision CAS、WAL checkpoint、CPU/IO 资源池、背压和 32 会话压力门禁。
> Authority: 本文是 dated implementation plan，不覆盖 `AGENTS.md`、`docs/standards/`、ADR、模块 README 或用户后续明确决定。

## 1. 结论先行

本次不重写聊天系统，也不引入新的 ORM 或 Agent 框架。推荐目标是：

1. 复用现有 `SessionCatalog` 的 migration/checksum/WAL/错误分类经验，但新建位于正式数据根的 `ConversationStore`，使其成为 **Agent、配置、会话、Turn、TurnItem 的唯一 SQLite 权威库**；现有 runtime cache catalog 不原地升级为 canonical 数据库。
2. 每条 `sessions.agent_id` 强制非空，前端目录固定为 `Agent -> Sessions`，不存在无父节点的裸会话。
3. Agent 配置使用不可变 revision；会话创建时冻结 `agent_config_revision_id`，后续修改 Agent 不改变历史会话的运行事实。
4. 继续复用 `SessionTurnItem v3`、现有稳定 ID、`assistant_delta` SSE 全量快照，不建立第二套消息/工具事件协议。
5. React Query 管服务端状态，Zustand 只管选择、标签、面板尺寸等本地工作台状态；禁止把会话正文复制到 Zustand 形成第二权威。
6. 旧测试会话不做内容迁移。切换时先做一次项目外只读备份，再清空旧索引与 journal；备份不进入产品目录、不被前端展示，只用于短期回滚。
7. 不使用 Drizzle，不引入 CrewAI Runtime，不复制 OpenCode/Codex/Grok 的整套实现；只复用许可证允许且与本项目契合的结构、协议和测试思想。
8. 多会话并发采用“每 Session 顺序、跨 Session 并行、SQLite 单写者、读写分离、CPU/IO 分池”；禁止用更多 SQLite writer 线程冒充 CPU 利用率优化。

## 2. 当前问题与迁移目标

### 2.1 当前事实

- `core/chat/session_catalog.py` 已有 SQLite、WAL、`busy_timeout`、外键、迁移 checksum、lease 与目录索引，但正文权威仍散落在 JSON/JSONL。
- 当前 catalog 明确是 `connection-per-operation` 的 rebuildable runtime cache，正式路径位于 `%LOCALAPPDATA%/Vibelution/session-catalogs`，developer fallback 位于 `.runtime/session-catalogs`；这些物理路径与连接策略不得直接承载 canonical 会话。
- `sessions` 已包含 `agent_id`、`parent_session_id`、状态、journal 路径/大小/mtime 等字段，说明数据库目前更像 projection/catalog，而不是完整会话存储。
- Agent 配置仍分散在 `workspace/agents/agents.json`、`workspace/agent_config/mode_bindings.json`、`workspace/agent_config/prompt_templates.json` 等文件。
- `agent_config_authority.py` 已有 `configRevision/configHash`，可直接成为数据库 revision 身份。
- 前端已经使用 React Query 和 `chatWorkbenchStore.ts`（Zustand），无需增加另一套状态库。

### 2.2 目标

- 一个数据库事务可以原子写入：用户提交、Turn、TurnItem revision、会话活跃时间和 Agent 绑定。
- 目录查询不读取或扫描正文 journal；打开会话时才按游标读取 Turn/Item。
- SSE 中的运行态与最终数据库记录使用同一组 `turnId/itemId/callId/revision`。
- 进程异常退出后，通过 SQLite 中的 running Turn 和 checkpoint 恢复或明确标记 interrupted，不依赖前端猜测。
- Agent 删除采用 archive，不级联删除历史会话；配置更新产生新 revision，不原地改写历史快照。
- 同一 Session 内 Turn/Item 严格顺序，多个 Session 可同时运行；任何数据库等待都不得占用 event loop 或全局 Python 状态锁。
- 并发写入具有有界队列、背压、幂等和 monotonic terminal 语义；进程重启后不得出现 running 回退、重复工具行或 sequence 冲突。

### 2.3 非目标

- 不迁移旧测试会话内容。
- 不把 runtime-scene、运行日志或调试 trace 混入产品会话正文。
- 不改变现有公开 SSE event type，不新建第二个 EventSource。
- 不在第一阶段建设完整长期记忆/RAG 系统。
- 不让浏览器直接访问 SQLite，也不在 TypeScript 前端引入 Drizzle。

## 3. 成熟项目复用决策

| 来源 | 可吸收设计 | 在 Vibelution 中的落点 | 不采用的部分 |
| --- | --- | --- | --- |
| [OpenCode session schema](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/session.sql.ts) | `Session -> Message -> Part` 的稳定关系层、父子 session、关系字段 + JSON payload、按父键/时间建索引 | 映射为 `Agent -> Session -> Turn -> TurnItem`；结构字段单列，provider 扩展进入有界 JSON | 不引入 Drizzle；不让 JSON payload 代替应有的外键、状态和顺序列 |
| [Codex app-server](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) | `Thread -> Turn -> Item`、`clientUserMessageId/clientId`、item started/delta/completed、turn completed、resume/fork、cursor pagination、`recencyAt` 与 `updatedAt` 分离 | 直接对齐现有 TurnItem v3；新增 `client_submission_id` 唯一约束、`recency_at`、游标目录和明确 resume/fork | 不采用 SQLite + JSONL 双 canonical；JSONL 只可作为切换前只读遗留数据或运行日志 |
| [Grok Build](https://github.com/xai-org/grok-build) / [headless mode](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/14-headless-mode.md) | session SQLite 与 memory/log/trace/worktree 分目录；显式 new/resume/continue/fork；稳定 `toolCallId` 和 `tool_call_update` | 数据目录按权威类型隔离；工具生命周期继续复用稳定 `callId/itemId/revision`；API 显式区分 resume/fork | 拒绝只读数据目录时静默进入 ephemeral session；Vibelution 必须 fail visible |
| [CrewAI memory](https://docs.crewai.com/en/concepts/memory) / [checkpointing](https://docs.crewai.com/en/concepts/checkpointing) | scope、来源/provenance、只读切片、写屏障、事件驱动 checkpoint、lineage、SQLite WAL、checkpoint 保留上限 | v1 先落 checkpoint/lineage；长期 memory 作为 v2 独立表与服务，保持 scope/source/private 边界 | 不引入 CrewAI Runtime；不在每个细粒度事件写完整 checkpoint |

### 3.1 直接复用（优先）

- `SessionCatalog` 的 schema migration、checksum、WAL/外键检查、错误分类和 lease 思路。
- `configRevision/configHash` 的配置身份算法。
- `SessionTurnItem v3`、稳定 `turnId/itemId/callId/revision/sequence` 和 `assistant_delta` 全量快照。
- React Query 的服务端查询、缓存失效和分页。
- Zustand 的活动 Agent、活动会话、标签页和布局持久化。
- 现有 runtime-scene 作为诊断证据，不作为产品数据源。

以下现有细节只作为待替换 baseline，不属于直接复用：runtime cache 物理路径、每次操作新建连接、每次连接执行 `PRAGMA journal_mode=WAL`、5 秒在线 `busy_timeout`、全局 `_CHAT_STATE_LOCK` 包裹文件/ledger I/O。

### 3.2 适配复用（借鉴契约，重写为项目代码）

- OpenCode 的稳定关系层与 JSON 扩展列。
- Codex 的 Turn/Item 生命周期、submission identity、recency 与 cursor pagination。
- Grok 的 session/memory/log/trace/worktree 分区和工具 update 语义。
- CrewAI 的 scope/provenance/checkpoint lineage 与有界保留。

### 3.3 明确拒绝

- SQLite 与 JSONL 同时作为会话正文权威。
- 文件写失败后静默继续为临时会话。
- Drizzle、Prisma 或另一套 TypeScript ORM。
- 将 CrewAI、OpenCode 或 Grok Build 作为运行时依赖。
- 用 Zustand 保存服务端会话正文、Agent 配置或 TurnItem canonical 副本。
- 无界写队列、无界线程池、逐 token 独立 commit，以及在持有 Python 锁时等待 SQLite/Future/网络。
- 多个 backend/uvicorn worker 进程直接竞争同一个 SQLite writer；未来若需要多进程写入，必须先引入唯一 writer daemon 或迁移到服务器数据库。

## 4. 目标数据模型

```mermaid
erDiagram
    AGENTS ||--o{ AGENT_CONFIG_REVISIONS : has
    AGENTS ||--o{ SESSIONS : owns
    SESSIONS ||--o{ SESSIONS : parent_of
    SESSIONS ||--o{ TURNS : contains
    TURNS ||--o{ TURN_ITEMS : contains
    TURN_ITEMS ||--o{ TURN_ITEM_CHUNKS : streams
    SESSIONS ||--o{ CHECKPOINTS : snapshots
    TURNS ||--o{ CHECKPOINTS : anchors

    AGENTS {
      text agent_id PK
      text display_name
      text kind
      text status
      text current_config_revision_id FK
      integer created_at_ms
      integer updated_at_ms
      integer archived_at_ms
      integer next_turn_sequence
    }
    AGENT_CONFIG_REVISIONS {
      text revision_id PK
      text agent_id FK
      text config_hash
      text config_json
      text source
      integer created_at_ms
    }
    SESSIONS {
      text session_id PK
      text agent_id FK
      text parent_session_id FK
      text agent_config_revision_id FK
      text title
      text status
      integer recency_at_ms
      integer updated_at_ms
      integer next_item_sequence
      integer created_at_ms
      integer archived_at_ms
    }
    TURNS {
      text turn_id PK
      text session_id FK
      text client_submission_id
      integer sequence
      text status
      integer started_at_ms
      integer completed_at_ms
      integer updated_at_ms
    }
    TURN_ITEM_CHUNKS {
      text item_id PK, FK
      integer chunk_sequence PK
      integer revision
      text content
      integer created_at_ms
    }
    TURN_ITEMS {
      text item_id PK
      text turn_id FK
      text call_id
      integer sequence
      integer revision
      text kind
      text status
      text payload_json
      integer created_at_ms
      integer updated_at_ms
    }
    CHECKPOINTS {
      text checkpoint_id PK
      text session_id FK
      text turn_id FK
      text parent_checkpoint_id FK
      text trigger
      text snapshot_json
      integer created_at_ms
    }
```

### 4.1 关键约束

- `sessions.agent_id NOT NULL REFERENCES agents(agent_id)`。
- `sessions.agent_config_revision_id NOT NULL`，保证历史会话可解释。
- 使用复合外键保证 `agent_config_revision_id` 确实属于同一个 `agent_id`，禁止 Session 绑定到其他 Agent 的 revision。
- `parent_session_id` 默认必须属于同一 `agent_id`；跨 Agent 转交使用显式 handoff 关系，不伪装为 fork。
- `UNIQUE(session_id, sequence)` 约束 Turn 顺序。
- `UNIQUE(session_id, client_submission_id)` 保证乐观提交、accepted 与最终写入幂等。
- `UNIQUE(turn_id, sequence)` 约束 Item 权威顺序。
- `revision >= 1`；相同 `item_id/call_id` 只能以 CAS/monotonic update 提升 revision，不能创建重复工具行，也不能由迟到的 running 覆盖 terminal。
- Agent archive 后历史 Session 仍可读取；禁止级联删除会话。
- `recency_at_ms` 仅在新 Turn 开始或用户明确 touch 时更新；后台索引、标题修复、状态对账只更新 `updated_at_ms`。

### 4.2 建议索引

```sql
CREATE INDEX idx_sessions_agent_recency
  ON sessions(agent_id, archived_at_ms, recency_at_ms DESC, session_id DESC);
CREATE INDEX idx_sessions_parent
  ON sessions(parent_session_id, recency_at_ms DESC);
CREATE INDEX idx_turns_session_sequence
  ON turns(session_id, sequence DESC);
CREATE UNIQUE INDEX idx_turns_submission
  ON turns(session_id, client_submission_id)
  WHERE client_submission_id IS NOT NULL;
CREATE INDEX idx_items_turn_sequence
  ON turn_items(turn_id, sequence ASC, revision DESC);
CREATE INDEX idx_items_call
  ON turn_items(turn_id, call_id)
  WHERE call_id IS NOT NULL;
```

结构化查询字段不得藏入 `payload_json`；provider/model usage、工具参数摘要、展示 metadata 等扩展内容才进入 JSON，并继续执行脱敏与长度上限。

### 4.3 Canonical 物理位置

- 正式环境：通过现有 formal workspace/data-root resolver 定位 `workspace/chat/conversations.sqlite3`；不得硬编码 Windows 用户名。
- developer 环境：使用 developer sandbox 对应的 `workspace/chat/conversations.sqlite3`，与正式数据完全隔离。
- 当前 `%LOCALAPPDATA%/Vibelution/session-catalogs/.../session_catalog.sqlite3` 只能在 shadow-read 阶段保留为可重建 projection；切换完成后不得被任何产品写路径读取。
- 数据库、`-wal`、`-shm`、备份和恢复操作必须归入同一运维契约；普通 cache cleanup 不能匹配 canonical 路径。
- 启动时如果 canonical 目录只读、schema 不兼容或 WAL 不可用，必须 fail visible；禁止退化为内存/临时会话。

### 4.4 Sequence 与状态竞态

- Turn sequence 通过单条原子 SQL 分配，例如 `UPDATE sessions SET next_turn_sequence=next_turn_sequence+1 ... RETURNING`；禁止 `SELECT MAX(sequence)+1`。
- Item/chunk sequence 使用相同原子计数策略，并在 `(turn_id, sequence)` / `(item_id, chunk_sequence)` 上建立唯一约束。
- Item 更新必须带 incoming revision；SQL 只接受更高 revision，重复 event 幂等返回，低 revision 记录 `stale_revision_dropped`。
- terminal 状态集合为 `completed/failed/cancelled/interrupted`；terminal 后所有非恢复型 running/pending update 都被拒绝。
- `cancel vs complete`、`archive Agent vs create Session`、`config revision CAS vs submit`、`delete Session vs SSE reconnect` 都必须有数据库约束与确定性胜负规则，不能只依赖 Python 判断。

## 5. 数据访问层

### 5.1 分层

| 层 | 责任 | 示例 |
| --- | --- | --- |
| DAO | 单表 SQL、row mapping、游标、批量 upsert | `AgentDao`、`SessionDao`、`TurnDao`、`TurnItemDao`、`CheckpointDao` |
| Repository | 领域聚合与不变量 | `AgentRepository.create_revision()`、`ConversationRepository.append_turn_snapshot()` |
| Unit of Work | 单事务协调、提交/回滚、after-commit publish | `ConversationUnitOfWork` |
| Service | 权限、业务流程、SSE、运行态协调 | 现有 session/agent services |

DAO 不得被 route 或 React 直接调用。Service 通过 Repository/UoW 完成业务写入；projection 只读，不成为第二写入者。

### 5.2 事务边界

一次用户提交至少在同一事务中完成：

1. 校验 Agent 与 frozen config revision；
2. 幂等创建或取得 Turn；
3. 写入 user Item 与初始 assistant/runtime Item；
4. 更新 session `recency_at_ms`；
5. commit 后才发布 accepted/SSE 通知。

工具开始、参数、成功/失败复用同一 `item_id/call_id`。工具 start/terminal、用户提交、Agent 配置 revision 和 Turn terminal 属于 critical mutation，必须 durable commit 后发布。reasoning/assistant text chunk 属于 streaming mutation，以 16–50 ms 或 4 KiB 为上限进行有界 group commit，禁止逐 token 独立 commit；terminal 前必须执行 flush barrier。

### 5.3 单 writer actor 与背压

新增 `ConversationPersistenceCoordinator`，它是运行进程内唯一 SQLite 写入口：

1. 一个专用 writer thread 持有一个长生命周期 writer connection；普通 Service 不自行创建写连接。
2. 多生产者写入有界队列，初始上限建议 2048 个 mutation；达到高水位先合并同一 Item 的 streaming chunk，仍满则 fail visible/backpressure，禁止无限堆积内存。
3. writer 按“最多 32 个 mutation 或等待最多 5 ms”进行 group commit；critical mutation 可提前触发 flush。
4. 每个 Session 的 mutation 带 `session_sequence`，writer 保证同 Session FIFO；跨 Session 可在同一事务 batch，但错误必须能定位到单个 mutation。
5. commit 成功后调用 after-commit publisher；publish 失败不回滚数据库，转入 bounded republish/reconcile。
6. 在线写锁冲突采用短超时（建议 250 ms）和最多 3 次带 jitter 的重试；5 秒超时只允许 migration/maintenance。正常 writer actor 自身出现 `database is locked` 应视为第二 writer 或外部锁异常。
7. writer queue 必须支持 shutdown drain、deadline、cancel-before-start 和 terminal flush；Launcher 关闭前等待 critical queue 清空，超时则明确报告未落盘项。

`SessionCatalogStore._connect()` 当前“每操作新连接 + 每连接设置 WAL”的方式只保留给低频 catalog；canonical store 的 `journal_mode` 在初始化时设置一次，后续连接不重复切换 journal mode。

### 5.4 读连接与查询隔离

- 使用 2–4 个 thread-local/read-pool connection，设置 `PRAGMA query_only=ON`；连接不得跨线程共享。
- read transaction 只覆盖一次分页/详情查询，返回 DTO 前结束；SSE 生命周期、HTTP streaming 和 React Query cache 生命周期都不能持有 SQLite transaction。
- route/event loop 通过专用 DB read executor 调用同步 sqlite3；event loop 上禁止直接执行 SQL、JSON 大对象编码或文件 I/O。
- 长统计、FTS rebuild、备份、quick_check 和 checkpoint prune 进入 maintenance lane，不与 interactive query 共用 worker。

### 5.5 锁顺序与禁止项

推荐状态流：

```text
Session scheduler admission
  -> per-session command ordering
  -> enqueue DB mutation（释放所有 Python 锁）
  -> writer transaction
  -> after-commit publish
  -> cache invalidation / canonical refetch
```

- `_CHAT_STATE_LOCK` 在新路径中不得包裹 SQLite、journal、附件、网络或 Future 等待；迁移完成后应从普通 submit/terminal path 移除。
- 全局 registry/cache lock 只保护内存 map 的读取或替换，锁内不得执行用户回调。
- per-session scheduler lock、DB writer queue lock、subscriber lock 不允许嵌套；需要跨组件传递时使用不可变 command/event。
- 禁止 executor task 在同一 executor 中 submit 子任务后同步 `.result()`，避免 worker starvation deadlock。
- 所有等待都必须有 deadline、取消传播和 runtime-scene；生产 watchdog 发现关键 lane 超过 10 秒无进展时记录线程/队列摘要，但不记录 Prompt 或正文。

## 6. Agent 配置进入数据库

### 6.1 权威模型

- `agents` 保存稳定身份、显示名、类型、当前 revision 和 archive 状态。
- `agent_config_revisions` 保存不可变配置 JSON、`configHash`、来源和时间。
- 配置修改流程为：读取 current revision -> 校验 patch -> 生成 canonical JSON/hash -> 插入新 revision -> CAS 更新 `agents.current_config_revision_id`。
- 会话创建后绑定当时 revision；会话内切模型需要显式创建/选择新 revision，并记录切换发生的 Turn，禁止静默改写历史。

### 6.2 文件配置的处置

- 第一阶段提供只读 importer，把现有 Agent/模式/模板文件导入 SQLite。
- 切换后数据库成为唯一运行权威；文件只保留显式 export/backup 能力，不参与启动时双向合并。
- 若导入发现重复 Agent ID、无效模型或 hash 冲突，fail closed 并列出具体记录，不自动猜测。

## 7. 前端状态边界

### React Query：服务端状态

- Agent 目录与配置 revision；
- Session 游标页、Session detail、Turn/Item 页；
- mutation、失效、后台刷新和 reconnect 后 canonical refetch。

### Zustand：本地工作台状态

- 当前 Agent、当前 Session、打开的 tab；
- 分栏尺寸、展开/折叠、草稿和临时选择；
- 允许持久化 stable ID，不持久化服务端实体副本。

### SSE：运行增量

- 继续使用 `assistant_delta` 与 `SessionTurnItem v3`。
- SSE 更新 React Query 中当前 Session 的 transient view；critical mutation 使用 durable-first，streaming chunk 只允许在有界 group commit 后发布，因此浏览器最多落后 16–50 ms，不允许数据库每 token commit。
- terminal 前先执行 writer flush barrier，再发布 terminal snapshot；terminal 后以数据库 detail 做一次 canonical reconcile。
- Zustand 不接管 SSE 内容，避免切换 Agent/Session 时出现旧内容覆盖新内容。

## 8. 读取与分页策略

- Agent 目录只查 `agents + session summary/count`，禁止 hydrate TurnItem。
- Session 列表使用 `(recency_at_ms, session_id)` 游标，不使用 offset 深分页。
- 打开 Session 默认加载最近 N 个 Turn；向上滚动再读取更早页。
- `updated_at_ms` 不参与用户可见排序，避免后台 projection/标题修复导致会话跳位。
- API DTO 维持清晰的 summary/detail 边界；列表不得携带无界 transcript。
- 目录空、DB 忙、schema 不兼容、文件只读均显示真实错误；禁止伪装成“暂无会话”或临时会话。
- 列表 count/summary 使用独立聚合查询或维护表，禁止为每个 Agent 循环执行 Session count（N+1）。

## 9. Checkpoint、resume、fork 与 memory

### 9.1 v1 checkpoint

- 默认只在 `turn_completed`、用户审批、显式 fork 前创建 checkpoint。
- checkpoint 包含 session/turn lineage、frozen config revision、必要运行摘要和 bounded snapshot。
- 每个 session 默认保留最近 20 个自动 checkpoint；用户命名 checkpoint 不自动删除。
- `resume` 继续同一 session；`fork` 创建新 session，填写 `parent_session_id` 与 `parent_checkpoint_id`。

这里的业务 checkpoint 与 SQLite WAL checkpoint 是两套概念，命名、指标和维护入口必须分开。

### 9.2 WAL 生命周期

- 初始化显式设置 `journal_mode=WAL`、`foreign_keys=ON` 和 durability policy；canonical 默认以 `synchronous=FULL` 为安全基线，通过 group commit 控制成本，只有对照 benchmark 证明风险可接受后才能降为 `NORMAL`。
- 初始 `wal_autocheckpoint` 建议 1000 pages，并设置 64 MiB 的观察阈值；阈值最终由 T1 基准冻结，不直接当作永久常量。
- 普通后台只执行 `PRAGMA wal_checkpoint(PASSIVE)`；`RESTART/TRUNCATE` 只允许在 `activeWork=0`、没有长 reader 且已完成备份/健康检查时运行。
- 记录 WAL bytes、checkpoint duration/busy/log/checkpointed pages、最长 reader age；WAL 连续增长或 reader 超时必须产生 degraded/blocked 信号。
- shutdown 顺序为：停止 admission -> drain critical writer queue -> WAL checkpoint -> close read pool -> close writer；任何一步超时都保留可恢复状态。

### 9.3 v2 scoped memory（不阻塞本次迁移）

借鉴 CrewAI，但单独实施：

- scope 示例：`/agent/{agentId}`、`/team/{teamId}`、`/project/{projectId}`；
- 每条 memory 有 source、visibility、owner、revision 与删除语义；
- 只允许按授权 scope 读取子树；
- 写入采用异步队列时，关键读取前提供 drain/read barrier；
- memory 与 transcript 分表、分服务，禁止把会话数据库变成无界知识库。

## 10. 实施任务图

| 阶段 | 交付物 | 依赖 | 验证与停止条件 |
| --- | --- | --- | --- |
| T0 基线冻结 | 当前 schema/数据路径/锁图/接口/性能基线；canonical data-root ADR；旧会话清理清单 | 无 | `quick_check`、现有目录/打开会话基准、runtime lock 指标；任何未知生产会话立即停止清理 |
| T1 SQLite 核心 | 新 canonical ConversationStore；复用 migration/checksum；writer actor、read pool、WAL policy、DAO | T0 | migration、WAL 并发、writer backpressure、锁超时、FK、checksum、损坏、进程崩溃后 reopen 与 durability policy 验证 |
| T2 Agent 配置权威 | Agent importer、不可变 revision、Repository/UoW、读写 API | T1 | hash/revision/CAS、重复 ID、无效模型、archive、历史 revision 测试 |
| T3 会话写入权威 | Session/Turn/TurnItem/chunk 原子写；sequence allocator；CAS；group commit；after-commit SSE | T1-T2 | crash/retry/迟到 revision/同名工具/失败重试/重连/幂等/终态测试 |
| T4 并发执行预算 | 移除普通路径全局锁；per-session ordering；统一 IO/CPU/tool executor budget 与公平背压 | T1-T3 | 1/4/8/16/32 Session 压测、deadlock watchdog、event-loop lag、CPU scaling |
| T5 查询与前端 | Agent 父节点目录、cursor pagination、detail lazy load、RQ/Zustand 边界 | T2-T4 | 目录不 hydrate 正文；切换无串线；重启后完整；VUI/Chat/build 门禁 |
| T6 切换与清理 | live authority 切为 SQLite；旧测试会话与 journal 清空；短期项目外备份 | T1-T5 | clean startup、UI 空目录、创建首个新会话、重启恢复、旧数据不再被扫描 |
| T7 checkpoint/fork | checkpoint lineage、resume/fork、保留策略 | T3-T6 | fork 不污染父会话；resume 接续正确 revision；恢复测试 |
| T8 scoped memory | 独立 ADR/计划后再实施 | T1-T7 | scope 隔离、provenance、删除、barrier、容量上限 |

T1-T6 是本次迁移的 Critical Path；T7 可紧随切换，T8 不得扩大本轮交付。T4 并发门禁未通过时禁止进入 T6。

## 11. 切换步骤

1. 关闭新提交入口并确认 `activeWork=0`。
2. 校验当前数据库与配置文件可读；生成项目外、只读、带 SHA-256 的一次性回滚包。
3. 创建新 schema，导入 Agent 与 config revisions；不导入旧 Session/Turn 内容。
4. 启动单 writer authority，确认不存在第二 backend writer、遗留写连接或 maintenance job。
5. 执行 writer drain 与 WAL health 检查，再清空旧测试 Session 索引和产品数据根下的 journal/派生索引。
6. 打开 SQLite canonical feature gate，关闭 legacy scan/write。
7. 创建多个临时 Agent 会话，执行并发 user -> reasoning -> tool -> assistant 完整回合。
8. 重启 Launcher，验证 Agent 父节点、Session、TurnItem、配置 revision、排序、WAL 和 queue 全部恢复。
9. 删除临时验收会话；观察一个版本窗口后删除项目外回滚包。

切换后不保留双写。若验收失败，只能整体关闭新入口并恢复切换前数据库/配置包；不得一部分读 SQLite、一部分写 JSONL。

## 12. 性能与可观测性目标

以下是待实测的验收预算，不是当前性能结论：

- 1000 个 Session、50 个 Agent：目录查询本机 p95 <= 150 ms，且正文 hydrate 次数为 0。
- 打开最近 50 个 Turn：后端 p95 <= 200 ms；前端保持现有 skeleton/内容稳定策略。
- 一次 TurnItem revision 提交 p95 <= 30 ms（不含模型/工具执行）。
- SQLite busy 超时必须产生可诊断错误，不允许静默丢写或退化到内存会话。
- 16 个并发 Session 下，submit accepted p95 <= 250 ms，critical writer queue wait p95 <= 20 ms，event-loop lag p95 <= 50 ms。
- 32 个并发 Session 连续运行 5 分钟：无 deadlock、无 starvation、无重复/丢失 Item、无 terminal 回退；所有完成回合最终能 canonical refetch。
- 已有实时工具目标继续保持 `toolStartToBrowserPaintMs <= 300 ms`，数据库 durability 不得以牺牲实时显示为代价。
- WAL 稳态不持续越过 64 MiB 观察阈值；checkpoint busy 和最长 reader age 可定位。
- runtime-scene 记录 migration version、query class、rows、durationMs、writerQueueDepth/WaitMs、batchSize、commitMs、busy/retry、WAL checkpoint、executorQueueWaitMs、eventLoopLagMs；不记录完整 Prompt/正文/secret。

### 12.1 当前 baseline 证据

2026-08-11 对现有 rebuildable `SessionCatalog` 做了临时目录、400 次 upsert 的有界微基准；它不代表新 schema 的最终性能，只证明当前连接策略不能原样复用：

| 并发 writer | writes/s | p95 | max | CPU core equivalent |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 63.9 | 23.68 ms | 170.72 ms | 0.24 |
| 4 | 134.0 | 69.59 ms | 234.82 ms | 0.31 |
| 8 | 171.4 | 100.27 ms | 271.27 ms | 0.42 |
| 16 | 202.8 | 190.50 ms | 1018.82 ms | 0.48 |

人为持有写锁 350 ms 时，另一个 writer 完成耗时 461.8 ms。最近 30 个 runtime scene 的 194 个 submit timing 样本中，`chatStateLockedMs` p50=338 ms、p95=921 ms、max=10116 ms；`submitTotalMs` p50=540 ms、p95=2976 ms、max=13157 ms。样本来自混合真实负载，不作为严格 before/after，只作为移除全局锁和建立同负载基准的强信号。

### 12.2 CPU/IO 资源预算

统一 `RuntimeExecutionBudget`，不再让各模块自行创建无关联线程池。初始规则按物理核/逻辑核和正式 benchmark 校准：

| Lane | 初始预算 | 说明 |
| --- | --- | --- |
| SQLite writer | 1 thread | SQLite 单写者；group commit 提升吞吐 |
| SQLite readers | `min(4, max(2, physical_cores/2))` | 短只读连接，不跨线程 |
| Interactive LLM/tool IO | `min(16, max(8, logical_processors))` | 优先 async；同步 provider 才占 I/O worker |
| CPU-bound transforms | `max(1, physical_cores-2)` processes | 为 event loop、OS、前端与 DB 保留核心；只有超过阈值的任务才进入 |
| Background evolution/indexing | 独立低优先级额度 | 不得占满 interactive lane；使用 aging 防止永久饥饿 |

- 远程 LLM streaming 是 I/O-bound，不用 CPU pool；JSON/索引/压缩/本地分析达到阈值后才进 process pool。
- Windows process worker 必须复用项目 no-console 路径，保证 `pythonw`/`CREATE_NO_WINDOW`；无法证明无窗口时保留在线程/外部服务路径。
- 当前 `_SESSION_EXECUTOR(max_workers=4)` 不再作为全局吞吐上限；per-Agent 默认上限 4 可以保留为公平性门槛，另设 global interactive budget。
- CPU-bound fixture 在 8 物理核参考机上，4 workers 相对 1 worker 吞吐至少达到 2.5x，同时 event-loop lag 仍达标；不以“CPU 占用率越高越好”作为成功标准。
- interactive chat 优先于后台 evolution/indexing，但每个低优先级任务随等待时间 aging，禁止永久 starvation。

## 13. 测试矩阵

### 后端

- 空库初始化、逐版本升级、checksum 不一致、只读目录、磁盘满/锁冲突。
- Agent import、config hash、CAS 冲突、archive、会话绑定 revision。
- `client_submission_id` 重试、Turn sequence、Item revision、同名并行工具、失败后重试。
- commit 前进程崩溃、commit 后 publish 失败、SSE 重连、terminal reconcile。
- tool start/success 乱序、late running、cancel/complete 同时到达、重复 event、revision gap 与 CAS 失败。
- Agent archive/Session create、config CAS/submit、Session delete/SSE reconnect、checkpoint prune/fork 并发竞态。
- writer queue 高水位/满载、slow commit、第二 writer、长 reader、WAL checkpoint busy、shutdown drain 超时。
- cursor pagination、`recency_at` 不被后台更新污染、目录无正文 I/O。
- checkpoint retention、resume、fork lineage。
- 使用 barrier/fault injection 重放固定锁交错；测试启用 deadlock watchdog，5 秒无进展输出有界 thread/queue stack 后判失败。
- 1/4/8/16/32 Session 相同负载重复至少 3 次，记录 p50/p95/p99、吞吐、CPU、event-loop lag、writer/read queue 和 WAL；不只看平均值。

### 前端

- Agent -> Session 父子选择与刷新恢复。
- Session 列表分页、空态、错误态、DB busy/不可读真实呈现。
- React Query canonical reconcile；Zustand 仅保存 ID/布局。
- 多 Session 切换不串内容，terminal 后无重复 Item/运行灯。
- 32 Session SSE 同时连接时，慢浏览器 subscriber 只丢弃/合并可重建 snapshot，不反压 writer 或其他 Session。
- VUI contract、Chat/Agent layout、`npx tsc -b --pretty false`、production build。

### 真实运行验收

- 创建两个不同模型的 Agent，各运行一个多工具回合。
- 修改其中一个 Agent 配置，验证旧会话仍指向旧 revision，新会话使用新 revision。
- Launcher 重启后目录、会话内容、工具状态、模型头像和 revision 一致。
- `PRAGMA quick_check` 通过；浏览器 console 无 error/warn；active work 归零。

## 14. 完成定义

- SQLite 是 Agent、配置、Session、Turn、TurnItem 的唯一产品权威。
- 所有 Session 都有有效 `agent_id` 和 `agent_config_revision_id`。
- 旧测试会话不再出现在磁盘扫描、API、前端目录或恢复路径中。
- JSONL 只剩 runtime log/诊断用途，不参与产品会话读写。
- DAO/Repository/UoW 边界有契约测试，route 与 projection 不直接写表。
- React Query/Zustand/SSE 的责任不重叠。
- 性能预算、故障恢复、Launcher 重启与真实多 Agent 会话验收通过。
- 项目文档、ADR、数据目录说明与删除/备份运维说明同步更新。

## 15. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 双写造成漂移 | 切换前可 shadow-read 对比，但禁止双 canonical；切换点一次完成 |
| runtime cache 被误当 canonical | 新 ConversationStore 位于正式 data root；cache catalog 只做短期 projection，cache cleanup 永不匹配 canonical 路径 |
| 锁竞争拖慢对话 | 单 writer actor、短事务、group commit、读写分离、短 busy timeout、列表查询索引 |
| 全局 Python 锁串行会话 | per-session ordering；禁止锁内 I/O/DB/Future；T4 前移除普通 submit/terminal 全局锁 |
| revision 乱序覆盖终态 | SQL CAS、terminal monotonic、原子 sequence allocator、重复 event 幂等 |
| 写队列或 subscriber 无界增长 | 有界队列、高低水位、chunk 合并、背压、慢 subscriber snapshot coalescing |
| WAL 增长与 checkpoint 卡顿 | 短 reader、WAL 指标、PASSIVE 日常维护、idle-only RESTART/TRUNCATE |
| CPU 线程池互相抢占 | 统一 RuntimeExecutionBudget；IO/CPU/DB/tool 分 lane；CPU process pool 留核心并验证无控制台 |
| Agent 配置更新污染历史 | immutable revision + Session FK 冻结 |
| 误删有价值会话 | T0 列出清理集；项目外 checksum 备份；只清用户已授权的测试会话 |
| JSON payload 重新变成垃圾桶 | 结构字段单列；payload schema/version/大小限制与脱敏测试 |
| 前端形成第二权威 | React Query 保存服务端实体；Zustand 只保存 UI ID 与布局 |
| checkpoint 写放大 | 只在 turn completed/审批/fork 写，有界保留 |
| 外部方案过度照搬 | 复用契约和测试思想；实现保持 Python backend 与现有 VUI/SSE 技术栈 |

## 16. 推荐的首个实现批次

第一批只做 T0-T1，不立刻清会话：

1. 先冻结 canonical data-root ADR 和 cache/canonical 删除边界；不在 runtime cache 上建正式库。
2. 从 `SessionCatalog` 提取 migration/checksum/error 分类，建立新 `ConversationStore`，实现长连接 writer actor、只读连接和 WAL policy。
3. 落最小 `AgentDao/SessionDao/TurnDao/TurnItemDao` 与 CAS/sequence allocator，但暂不切换正式读写。
4. 建立 1000 Session/50 Agent 数据 fixture，以及 1/4/8/16/32 并发 Session fixture。
5. 对比 `synchronous=FULL/NORMAL`、batch 大小和 flush 周期；只有 correctness、p95/p99、WAL 与 CPU 指标同时通过才冻结默认值。
6. 证明 WAL、FK、幂等、锁顺序、背压和游标索引正确后，再开始 T2 配置导入。

这样能最大化复用，又把最高风险的“数据切换与清理”延后到基础设施被证明可靠之后。
