# 三层记忆图谱 · 公共结构策展 · 研究成败图（方案 v2.3）

> **状态**：在研草案。升格 ADR / 写入 `docs/standards/` 之前，**不覆盖** `AGENTS.md` 与现行规范。
> **日期**：2026-08-15
> **版本**：v2.3（v2.2 契约保留；补开工去重、检索即路由、混合读强制与 locator 允许名单）
> **模式**：`COMPACT_PLAN`（研究 / 公共策展 / 个人 episode 分闸，不要同一 worktree 兼写）
> **非权威**：本文件是交接方案，不是现行规则。完成后迁入 `docs/archive/`。

---

## 0. 已锁定决策（用户「按推荐」）

| # | 问题 | 锁定 |
| --- | --- | --- |
| 1 | 失败进不进正式图谱 | **研究 P0 只进工作层**。P1 经 steward 才写正式 `falsifies`。禁止失败自动变 KnowledgeItem。 |
| 2 | 研究第一刀 | **先 Agent 记忆**（`research_memory_context` + 可追溯边）。研究 UI 图谱另开。 |
| 3 | 失败粒度 | **一次 smoke / full-run**。seed/attempt 树 P2。 |
| 4 | 前沿图谱 | **学 Graphiti 边模型，不接库。** P0 不装 Neo4j/FalkorDB，不跑 GraphRAG 全量索引。 |
| 5 | 三层切分 | **个人 / 团队 / 公共** 三套权威，正文不重复。公共不是另外两层的只读投影。 |
| 6 | 公共层职责 | **知识库管理员**把控整体结构，并整理高价值沉淀。不当规范/代码/身份/进度的第二真源。 |
| 7 | 公共怎么收录 | **目录卡片**（摘要 + 路径 + hash + 何时用）。规范/skill/代码/身份/进度不拷正文。 |
| 8 | 参考代码 | 管理员钉场景→路径/符号/测试；最多短摘录。 |
| 9 | Agent 身份 | `agent_directory` 唯一写入；公共层只投影摘要。 |
| 10 | 进度 | 权威仍是 `activePaths.memory`；公共只挂入口。 |
| 11 | 经验 | Agent 可起草，**管理员验收**后才可检索。个人/团队可提议提升；原文留原层，公共留引用 + 整理短文。 |
| 12 | 结构权限 | **只有管理员**能改分区和钉死入口。Agent 只能建议新卡片。 |
| 13 | 开工加载 | 只加载**公共结构摘要**（渐进披露）。 |
| 14 | 新鲜度 | 管理员**按结构框架巡检**；投影可自动刷新，钉住的高价值卡过期进待办，经验须人工确认。 |

### 0.1 生命周期补锁（v2.2，不改上表 1–14）

审查缺口已从「实现时注意」升为契约：

| # | 问题 | 锁定 |
| --- | --- | --- |
| 15 | 检索怎么读 | **混合读**：命中卡片只作发现；行动必须打开 `locator` 真源。禁止把卡片 `summary` 当规范/skill/代码正文。 |
| 16 | 开工摘要多大 | **硬预算**（§A.5）。超限按分区配额 + `stewardWeight` 截断，不得倾倒全部 pin。 |
| 17 | 过期怎么处理 | **只归档、不静默删除**。隐藏 ≠ 删除；出处链保留。 |
| 18 | 两张卡打架 | **矛盾队列**。未裁决前两边都不可作为 Agent 高价值命中。 |
| 19 | 个人层怎么写 | P0 **无损追加** 现有 `episodicEventsPath`。热路径无 LLM 抽取；整理不得自动升公共。P0 **不**上 SQLite。 |
| 20 | 公共层落点 | **独立目录** `workspace/knowledge/public/`，**不**把策展树塞进 `KNOWLEDGE_OWNER_TYPES`（现仅 `team` \| `agent`）。经验短文是公共自产，不是 `items.jsonl` 再拷一份规范。 |

### 0.2 装配补锁（v2.3，不改 1–20）

对照 `context_engine` / PromptManager / `list_knowledge_governance_tasks` 的现行行为：

| # | 问题 | 锁定 |
| --- | --- | --- |
| 21 | 开工与现有 Prompt 重复 | **开工块去重**（§A.5）。已由 PromptManager / `context_engine` 注入的真源不得再出现在开工结构摘要。检索仍可返回其 locator。 |
| 22 | 目录会不会变成第二套全文库 | **检索即路由**（§A.4）。目录不替代 `read_file_tool` / grep。文件内句子继续仓内搜索。保鲜/矛盾/提升并入现有 governance tasks，不新开管理员任务模型。 |
| 23 | 混合读只靠 DTO 字段 | **强制打开真源**（§A.4）。catalog 命中不得带 `content`/`excerpt` 规范正文；打开走允许名单解析器。越权 locator 失败，不得回退 summary。 |

对齐已闭合。实现仍分闸：§C 三条任务不要同一 worktree 兼写。

---

## A. 三层记忆（不重复）

| 层 | 记什么 | 权威落点 | 图谱 | 谁写 |
| --- | --- | --- | --- | --- |
| 个人 | 偏好、会话事实、私有笔记（会过期） | 现有 `workspace/agents/{id}/events/episodic_events.jsonl`；派生摘要才写 `memory/summaries.jsonl` | 边用 `validFrom` / `validUntil`，不接图库 | 该 Agent 工具；热路径只追加 |
| 团队 | 仅该团队过程与未公开结论；挑战杯工作层成败 | `teams/{id}/knowledge/` JSONL + plan 上 `outcomeGraph` | 正式追溯边 + 工作层 `tests/supports/falsifies` | 团队成员提议，正式项走团队 steward |
| 公共 | 策展结构 + 高价值入口 + 已验收经验 | `workspace/knowledge/public/structure.json`（与中央来源 `sources/` 并列，不是其投影） | 分区/入口/经验引用边 + `contradicts` | **仅知识库管理员**改结构；经验须其验收 |

跨层只引用 ID（`publicCardId` / `teamItemId` / `centralSourceId` / `agentId` / git path / `episodeId`）。禁止把 content 再拷一份。

`memory_graph_service` 仍是记忆页的组织投影，**不是**这三层里任何一层的写入权威。

`unified_knowledge_search_service` 继续搜团队/Agent **正式 KnowledgeItem**。公共策展是第三条只读源：`resultType=public_catalog_card`，返回卡片元数据，不把规范正文打进 `content` / `excerpt`。现有 `max_context_chars=1200` 只约束正式知识切片，不替代打开真源，也不适用于 catalog 命中。

### A.1 公共层：结构把控

管理员维护一棵策展树，不是仓库 AST。P0 **不要**新增 `ownerType: project`：`KNOWLEDGE_OWNER_TYPES` 仍是 `team` \| `agent`；store 只扫 `workspace/teams/*/knowledge` 与 `workspace/agents/*/knowledge`。策展树走中央知识根下的独立目录，避免把目录卡片写成又一份 `items.jsonl`。

落盘（均在 `workspace/knowledge/public/`）：

| 文件 | 角色 |
| --- | --- |
| `structure.json` | 分区、卡片、边、预算配置的权威 |
| `steward_queues.jsonl` | 保鲜队列 + 矛盾队列（追加，不删历史行；当前状态看最后一条同 id） |
| `experience/{cardId}.md` | **仅**已验收经验的公共自产正文（管理员改写稿，≤ 8KiB） |
| `proposals.jsonl` | Agent/团队提升提议（未验收对开发 Agent 不可见） |

```text
publicStructure.schemaVersion: 2
budget: { maxCards: 24, maxChars: 4000, partitionQuotas: { ... } }   # 见 §A.5
partitions[]: standards | skills | code_refs | agents | progress | experience
cards[]:
  - cardId, kind: partition | pin | projection | experience
  - title, whenToUse, summary          # summary ≤ 240 字；不是真源
  - stewardWeight: int                 # 开工排序；默认 0
  - visibility: agent_visible | hidden | archived
  - source: { type, locator, contentHash }
  - originRef?: { layer: team|agent, ownerId, itemId|episodeId }
  - freshnessPolicy: auto_project | steward_review
  - freshness: { status: current | stale | missing, observedHash, lastCheckedAt, lastRefreshedAt }
  - reviewAfter?: ISO                  # 经验可选
  - contradictsCardIds[]               # 显式矛盾；也可由队列写入
  - archivedAt?, archivedReason?, previousHash?
edges[]: related_to | implements | used_by | entry_of | contradicts
```

- `projection`：从 Git / skill 磁盘 / `agent_directory` / memory INDEX 自动生成 L1 元数据。`freshnessPolicy=auto_project`。
- `pin`：管理员钉死的高价值入口。源变了只标 stale，不自动改摘要。`freshnessPolicy=steward_review`。
- `experience`：唯一允许在公共层存正文的 kind；正文只在 `experience/{cardId}.md`，卡片里仍只有 summary。`originRef` 指向原层，**不删除、不拷贝**原层 JSONL。

`locator` 形态（P0 关闭集合）与 **允许名单**（lock 23）：

| `source.type` | `locator` | hash | 解析约束 |
| --- | --- | --- | --- |
| `git_path` | 仓内相对 POSIX 路径（可选 `#symbol`） | git blob 或规范化文件字节 | 无盘符、无绝对路径、无 `..`；规范化后必须落在 `PROJECT_ROOT` 内 |
| `skill` | skill 目录/`SKILL.md` 相对路径 | 文件 hash | 同上，且必须落在已登记 skill 根下 |
| `agent_directory` | `agentId` | `updatedAt` + displayName/roleKey/primaryMode | 不是文件路径；只读 `agent_directory` |
| `progress_index` | inventory 解析出的 `INDEX.md` | 文件 hash | 解析后仍须在 `PROJECT_ROOT` 内 |
| `central_source` | `centralSourceId` | 已有 source hash | 只经现有 `get_knowledge_trace` / `localCopies` |
| `experience` | `experience/{cardId}.md` | 该 md hash | 只允许 `workspace/knowledge/public/experience/{cardId}.md` |

打开真源必须走 `resolve_public_locator`（或等价纯函数）。越权、逃逸、未知 type → `sourceUnavailable: forbidden`，不得读盘、不得回退 summary。

仓库符号图（RepoMap 类）若以后做，是派生索引，**不**由管理员手画，也不替代策展树。

### A.2 公共层：高价值沉淀

1. 个人/团队写 `proposals.jsonl`（带 `originRef`）。
2. 管理员改写、去重、挂到某个 partition，写入 `experience/{cardId}.md`。
3. 通过后：`visibility=agent_visible` 且 `freshness.status=current` 才可检索；原层正文不删、不拷进 `items.jsonl`。
4. 未验收提议、`hidden`、`archived`、开放矛盾中的卡片：开发 Agent 检索默认不可见。

提升验收时若原层已有正式 KnowledgeItem：公共卡只留 `originRef` + 整理短文，禁止再 `append` 一份相同 content 到任何 owner 的 `items.jsonl`。

### A.3 按框架保持新鲜度（管理员工作台）

新鲜度沿**结构树走一遍**，不是全库乱扫。触发：管理员点「按框架刷新」；以及 Git/skill/目录/INDEX 变更后的增量检查（实现时可先手动，再挂钩子）。

对每个卡片：

| `freshnessPolicy` | 源 hash 变化时 | 管理员动作 |
| --- | --- | --- |
| `auto_project` | 重算摘要/L1，标 `current` | 抽查即可；失败进保鲜队列并 `visibility=hidden` |
| `steward_review` | **不改摘要**，标 `stale` 或 `missing`，`visibility=hidden`，进入保鲜队列 | 刷新投影 / 改写 / 确认仍有效（只更新 hash，恢复 `agent_visible`）/ 取消钉住 / 归档 |

队列按结构分区分组：先 standards，再 skills，再 code_refs。

保鲜字段最低集：`contentHash`、`observedHash`、`status`、经验可选 `reviewAfter`。

`auto_project` 过期应先自动刷新；刷新失败才隐藏并进队列。结构摘要开工加载只包含 **可检索集 − 开工排除集**（§A.4 / §A.5），并受硬预算约束。

非目标：自动把 stale 卡的新正文写进经验层；自动修改 `AGENTS.md`；无管理员确认就从 `structure.json` 抹掉卡片。

### A.4 检索契约（混合读 + 路由）

这是公共层相对现有 `search_knowledge_items` 的核心差异：正式 KnowledgeItem 今天会把 `content` 打进 haystack；公共卡片 **禁止** 这样做。

**目录不是全文索引（lock 22）。** 卡片 haystack 只有 `title` + `whenToUse` + `summary`。文件内独有短语（例如 `CREATE_NO_WINDOW`）继续用现有 `grep_search_tool` / `read_file_tool`。实现者不得为了「搜得到」把规范/skill/代码正文写入卡片或 search haystack。

**可检索集**（Agent 默认）：

`visibility == agent_visible`
AND `freshness.status == current`
AND 不在开放 `conflict` 队列里
AND kind 为 `pin` \| `projection` \| `experience`（partition 节点只出现在结构摘要，不作为检索命中）

命中 DTO（P0 字段关闭集合；**禁止**复用 `_result_from_knowledge_item`）：

```text
resultType: public_catalog_card
cardId, kind, partition, title, whenToUse, summary,
locator, sourceType, contentHash, freshness.status,
originRef?, openRequired: true
```

禁止字段：`content`、`excerpt`、规范/skill/代码全文、`experience/{cardId}.md` 全文。`summary` 不得映射到统一搜索的 `excerpt`。经验命中同样只给 summary；要读正文必须 open locator。

读路径（lock 15 + 23）：

1. 搜索 / 开工摘要 → 卡片元数据（发现）。
2. 行动前必须 `resolve_public_locator` 再读真源（复用已有读文件 / `get_knowledge_trace` / skill 磁盘；不新开向量库）。
3. 打开失败 → `sourceUnavailable`（`missing` \| `unreadable` \| `hash_mismatch` \| `forbidden`），**不得**回退用 summary 当权威。
4. `hash_mismatch`：同时把该卡标 stale、隐藏、进保鲜队列（经 governance task 露出）。

装配约束：若把检索结果编进 Prompt，catalog 命中只允许 title + whenToUse + locator + `openRequired`。禁止把 `summary` 当成「已读取的规范」。P0 用 DTO 形状 + 单测锁住；不依赖模型自觉。

`search_unified_memory` 增加 catalog 源时保持独立 `resultType`，不要让公共卡冒充 `ownerType=team` 的 KnowledgeItem。

### A.5 开工结构摘要硬预算与去重

开工只加载公共结构摘要，不是记忆库倾倒。量级对齐 Aider ~1k token / Claude MEMORY.md 200 行，取本仓库可测数字：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `STARTUP_STRUCTURE_MAX_CARDS` | 24 | 写入 Prompt 的卡片上限 |
| `STARTUP_STRUCTURE_MAX_CHARS` | 4000 | 整块结构摘要字符上限 |
| `STARTUP_CARD_WHEN_TO_USE_CHARS` | 80 | 单卡 `whenToUse` 截断 |
| `STARTUP_CARD_SUMMARY_CHARS` | 0 | **开工块不放 summary**，只放 title + whenToUse + locator |

分区配额（默认，可被 `structure.json.budget.partitionQuotas` 覆盖，总和 ≤ 24）：

`standards 6` · `skills 6` · `code_refs 4` · `agents 4` · `progress 2` · `experience 4`

**开工排除集（lock 21）**——可检索，但 **不得** 进入开工块（`context_engine` 已跳过第二份 AGENTS，且会注入 `project_agent_registry`）：

| 排除 | 匹配 |
| --- | --- |
| PromptManager 真源 | 规范化 locator 为 `AGENTS.md`、`core/core_prompt/COMMON.md`、`core/core_prompt/SOUL.md`，或前缀 `core/core_prompt/` |
| Agent 通讯录 | `source.type == agent_directory` 的 projection / pin |

`docs/standards/` 等**尚未**被 ContextEngine 注入的入口可以进开工块（这是目录的增量价值）。排除在截断之前执行：先从可检索集拿掉排除项，再按配额 + `stewardWeight` 排序。

排序：可检索集 − 排除集 → 分区配额内按 `stewardWeight` 降序，同分按 `lastRefreshedAt` 新者优先。超出配额或超出 `maxChars` 的卡片 **不出现在开工块**，仍可通过检索发现。

开工块必须带一行预算声明，例如：`included=18 omitted=11 excludedStartup=3 budgetChars=4000`。禁止把省略部分用「完整目录见附件」再贴一遍卡片列表。禁止把排除集以「系统已加载」为名再列出 locator 清单。

### A.6 归档、矛盾与治理队列

`steward_queues.jsonl` 是事件账本（类似团队库的 `proposals.jsonl`），**不是**第二套管理员 UI：

```text
queueEventId, queueKind: freshness | conflict | proposal
partition, cardIds[], status: open | resolved | dismissed
reason: stale | missing | review_after | duplicate_locator | contradicts | steward_flag
openedAt, resolvedAt?, resolution?: confirm | rewrite | archive | keep_a | keep_b | merge
```

**并入现有治理面（lock 22）。** 扩展 `list_knowledge_governance_tasks`（及已有 `knowledge_governance_tasks_tool` / steward overview），增加：

| `task_type` | 来源 |
| --- | --- |
| `catalog_freshness` | 开放 freshness 事件 |
| `catalog_conflict` | 开放 conflict 事件 |
| `catalog_proposal` | 公共 `proposals.jsonl` 未验收项 |

不要新建平行 `get_public_steward_overview`。`get_knowledge_steward_overview` 的 `openTaskCount` 必须把上述三类算进去。

**归档（lock 17）**

- 管理员归档：`visibility=archived`，填 `archivedAt` / `archivedReason` / `previousHash`。卡片留在 `structure.json`。
- P0 **不提供** 删除卡片 API。实现层若需 compaction，只允许把 `archived` 卡移到 `structure.archive.json`（仍可读、可审计），禁止 drop。
- 中央来源已有 `CENTRAL_SOURCE_STATUSES` 的 `archived` / `superseded`：公共卡归档不级联删中央来源。

**矛盾（lock 18）**

自动入队（P0，可测、不跑 LLM）：

1. 两张可检索 `pin` 的 `locator` 相同，但 `summary` 或 `observedHash` 不同。
2. 任一边存在 `contradicts` / `contradictsCardIds`。

不自动入队：仅标题相似、仅分区相同。这类由管理员 `steward_flag`。

开放矛盾中的相关卡片：全部退出可检索集与开工块，直到 `keep_a` / `keep_b` / `merge` / `archive`。

### A.7 个人层写路径（lock 19）

复用已有 MemoryPolicy 路径，不新建库：

- 权威追加：`episodicEventsPath` = `workspace/agents/{id}/events/episodic_events.jsonl`（`agent_directory.policies.default_memory_policy` 已声明）。
- 派生整理：`summariesPath` = `.../memory/summaries.jsonl`。派生损坏可从 episode 重建；禁止反过来用摘要覆盖 episode。
- 写入模式对齐 `agent_directory.ops_residual` 已有 `_append_jsonl`（inbox / tool_observations / group_context）。P0 加 `append_episodic_event`，热路径 **禁止** 调 LLM。

```text
episodeId, agentId, occurredAt, kind, text,
refs[]: { type: session|path|card|item, id },
validFrom, validUntil,          # 空 validUntil = 当前有效
supersededByEpisodeId?
```

规则：

- 作废写 `validUntil` + `supersededByEpisodeId`，不删行。
- 异步整理（可选 P1）只写 `summaries.jsonl`，且 **不得** 自动写 `proposals.jsonl` 或公共 `experience/`。
- 提升公共：必须另走 §A.2 提议；原文留在 episode。
- P0 不把个人 episode 编进 `memory_graph_service`，不引入 SQLite。

个人检索（P0 可后置）：按时间倒序扫 jsonl + `validUntil==""`；不在本切片做向量。开工 **不** 倾倒个人 episode（仍只加载公共结构摘要）。

### A.8 公共层任务卡与验证

Owner：`team_knowledge` pack 新切片（建议 `public_catalog.py`），经 `team_knowledge_service` facade 再导出。不撑爆 facade 业务。不改 `memory_graph_service` 写入。UI 后做。

Task P1: `structure.json` 读写 + steward 权限（仅知识库管理员改分区/pin）
Task P2: 按树刷新 hash、保鲜队列、`hidden` 转换；投影到 `list_knowledge_governance_tasks`
Task P3: 混合读 DTO（`public_catalog_card`）+ `resolve_public_locator` 允许名单 + `sourceUnavailable`
Task P4: 开工摘要预算截断 + 开工排除集
Task P5: 归档（无删除）+ 矛盾队列

P0 绿的定义：

- 新测聚焦 `tests/test_team_knowledge_service.py`（或 pack 单测）；现有 knowledge ACL / 中央来源 / governance task 用例仍绿。
- 至少覆盖：
  1. 改 `locator` 文件字节后，`steward_review` pin 变为 `stale` + `hidden`，Agent 检索不可见。
  2. 提升经验不向 `items.jsonl` 写入规范/原层正文。
  3. 开工摘要 `len(cards)≤24` 且字符 ≤ 4000，省略计数可见。
  4. 命中 DTO `resultType=public_catalog_card`，无 `content`/`excerpt`；open 失败返回 `sourceUnavailable` 且不回退 summary。
  5. 归档卡仍在 `structure.json`（或 `structure.archive.json`），无删除 API。
  6. 两张同 locator 不同 summary 的 current pin 进入开放 conflict，两边都不可检索。
  7. 开工块不含 `AGENTS.md` / `core/core_prompt/` / `agent_directory` locator；检索仍能返回这些卡。
  8. 搜只存在于 `AGENTS.md` 正文、不在卡片 title/whenToUse/summary 里的短语，catalog 不命中（grep 路径不在本切片断言）。
  9. `../` 或绝对路径 locator → `forbidden`；`list_knowledge_governance_tasks` 能列出开放 `catalog_freshness`。
- 不改 `web/` 则不跑 `tsc -b`。Launcher refresh：`not needed`（纯后端 JSON）；用户测检索时重启会话即可。

---

## B. 团队研究工作层：outcomeGraph

### B.1 要解决什么


挑战杯已经有：

- 候选图（文献/机制/假设，`graphKind: candidate_only`）
- 正式图投影（steward 接受后的 `formal_research_trace`）
- 研究记忆包（`claimMap`、`negativeExperiments`、`forbiddenDuplicateExperiments`）
- 实验计划账本（smoke/full-run 状态、result 路径、hash）

缺口是：**成败没有一等图边**。记忆包靠 plan 状态启发式拼出来，失败不会挂到 Claim/Protocol，正式图只有 `supports` / `inspires` / `approved_for_ingestion`，没有 `falsifies`。Agent 能「避开失败过的签名」，但不能沿边追到「测了哪条主张、证据在哪」。

成功时：一次登记立刻在工作层留下 `ExperimentRun` 节点和 `tests` / `supports` / `falsifies` / `duplicates` 边；Agent 记忆从该图投影，而不是只扫 plan status。

---

### B.2 目标 / 非目标

### 目标

- 一图两层：工作层立刻写成败边；正式层只投影 steward 接受后的 KnowledgeItem。
- 成败都是边，不是第二套知识库。Claim 状态继续用 `qualified / unsupported / rejected / not_established`。
- 去重继续用 `experimentSignature` + `forbiddenDuplicateExperiments`；重测需要新证据或改控制变量。
- P0 把 `research_memory_context` 改为**优先从工作层成败边投影**，旧 plan 无边时才回退启发式（兼容）。

### 非目标

- 第四套库；混写 `memory_graph_service` / 运行时 Agent 记忆 / 项目治理记忆。
- 失败自动入库为 KnowledgeItem。
- npy、完整 log、原始论文 PDF 进 Prompt（保持 `rawExperimentLogsIncluded: false`）。
- Crossref 下落 PDF；改 VUI / 图谱 UI。
- 关闭或改写 SCI-096 三条 coordination。
- seed/attempt 树（P2）；官方 full prune；`storage apply`。
- 引入 Graphiti / Zep / LightRAG / Cognee / Neo4j / FalkorDB / 已归档 Kuzu 作为运行时依赖。
- LLM 自由抽取实体类型写入工作层或正式层。

---

### B.3 推荐路径（研究一图两层）

```text
Source → Mechanism → Hypothesis/Claim → Protocol → ExperimentRun → KnowledgeItem
                         ↑                    ↓
                    ClaimMap 状态        outcome: passed | failed | blocked
```

| 层 | 何时写 | 谁可以读 | 谁不能当正式知识 |
| --- | --- | --- | --- |
| 工作层 | smoke/full-run **登记当下** | Agent 记忆、去重、追溯 | 未 steward 的失败/成功 |
| 正式层 | steward 接受 KnowledgeItem 之后 | 正式图 sync、知识检索 | 候选边、plan 启发式 |

边语义（P0 工作层）：

| relation | 含义 |
| --- | --- |
| `tests` | ExperimentRun → Claim/Hypothesis 或 Protocol（这次跑在测什么） |
| `supports` | 通过的 run → Claim（工作层暂定；正式层仍要 steward） |
| `falsifies` | 失败的 run → Claim（工作层立即；正式层等 P1） |
| `duplicates` | 新 run → 旧 run（签名相同，被挡住或仅重放） |

失败边**必带**：`interpretation`、`failedGates`、`evidenceRefs`（沿用 `_result_evidence_refs`：resultId / logRef / resultPath）。不得把原始 log 正文塞进边或 Prompt。

### 3.1 落盘：复用图模型，不污染来源候选

**不要**把 `experiment_run` 注册成 source-collection `candidateType`。候选库的 `source_manifest` / `paper_note` / `neuro_mechanism` / `algorithm_hypothesis` 仍走文献审查队列；实验节点进去会污染 SC 卡片与 `unreviewedNodes`。

P0 落盘（同一工作流目录，不是第四套知识库）：

1. **边的权威**：登记时写入 experiment plan 上的有界字段 `outcomeGraph`（节点 + 边，跟 `activeSmokeResult` / `activeFullRunResult` 同生命周期）。
2. **工作图投影**：新增 overlay，把 plan 上的 `ExperimentRun` 节点/边并进「工作研究图」读取路径。`build_candidate_graph` 的文献候选契约保持 `candidate_only`、不写官方知识。
3. **Agent 记忆**：`build_research_memory_context` 先读 overlay 边，再回退现有 `NEGATIVE_PLAN_STATUSES` / `SUCCESS_PLAN_STATUSES`。

建议文件名（实现时二选一，优先 1）：

1. plan 内 `outcomeGraph`（最小、跟登记事务同一把 `_WORKFLOW_LOCK`）
2. 团队工作流旁路 `research_outcome_graph.json`（与现有 `official_graph_sync.json` 同类；仅当边需要跨 plan 查询且 plan 字段不够时再拆）

第一刀用 **1**。P1 正式图仍写现有 `official_graph_sync.json` / `_official_research_graph_record`，只**增加** `falsifies` 等关系，不新开库。

### 3.2 现有面（必须接上，禁止平行树）

| 面 | 路径 | 现状 | P0 动作 |
| --- | --- | --- | --- |
| 记忆投影 | `research_memory_context.py` | 已有 negative/success/forbidden；启发式 | 改为图投影优先 |
| smoke 登记 | `experiment_api/smoke.py` `register_experiment_smoke_result` | 写 status + result | 同锁写 `outcomeGraph` |
| full-run 登记 | `experiment_api/full_run.py` `register_experiment_full_run_result` | 同上 | 同上 |
| 计划内核 | `experiment_kernel.py` | 结果记录、status | 边字段 schema / 校验 |
| 候选图 | `knowledge_kernel.py` `_build_candidate_graph_payload` | 仅 candidate 边 | **不改文献节点契约**；overlay 另函 |
| 正式图 | `knowledge.py` `sync_official_research_graph` + `_official_research_graph_record` | 无 `falsifies` | **P0 不动**；P1 才加 |
| 证据图只读 | `research_runtime/evidence_graph_projection.py` | 只读 | P0 不写 |
| 记忆图服务 | `memory_graph_service.py` | 另一套 | **禁止混写** |

---

### B.4 `outcomeGraph` schema

挂在单个 experiment plan 上，上限随现有 result 窗口（smoke/full-run 各保留最近 12 条）。

P0 **不**引入第四种节点 `episode`。`experiment_run` 同时扮演 Graphiti 的 Entity 和 Episode：一次登记 = 一个 run 节点 + 若干事实边。Attempt 树（P2）再拆 episode。

```text
outcomeGraph.schemaVersion: 1
ontology: prescribed_only          # 关闭 LLM 发明类型
nodes[]:
  - nodeId
  - nodeKind: experiment_run | claim | protocol
  - ref: planId + smokeResultId|fullRunResultId | claimId | protocolRef
  - summary                      # 短文本；claim=假设句；run=interpretation
  - outcome?: passed | failed | blocked   # 仅 experiment_run
  - occurredAt?                  # 仅 experiment_run = episode 时间（result.recordedAt）
edges[]:
  - edgeId
  - relation: tests | supports | falsifies | duplicates
  - fromId, toId
  - edgeState: working_only      # P1 才出现 official_synced
  - validFrom                    # ISO，必填 = producing episode.occurredAt
  - validUntil                   # 空字符串 = 当前有效
  - supersededByEdgeId           # 被后写边关闭时填写
  - producedByEpisodeId          # smokeResultId | fullRunResultId
  - interpretation
  - failedGates[]                # 失败边必填
  - evidenceRefs[]               # 指针：resultId / logRef / resultPath；禁止原文
  - experimentSignature
```

稳定 id：

- `claim` 的 `nodeId` / `claimId` **必须**与现有 `_claim_map` 相同：`claim-{sha256(normalized hypothesis)[:12]}`。不因此创建 KnowledgeItem。
- `experiment_run` 的 `nodeId` = `run:{smokeResultId|fullRunResultId}`。
- `protocol` 有 plan 内 protocol/design 稳定 id 则用之，否则 `protocol:{planId}`。

规则：

- 失败边（`falsifies`）必带 `interpretation`、`failedGates`、`evidenceRefs`。
- **不删旧边。** 同一 claim 上后一次 `falsifies` 要把仍有效的 `supports` 关掉：写 `validUntil` + `supersededByEdgeId`。反过来，新的 `supports` 关掉仍有效的 `falsifies`（工作层允许被新证据翻转；正式层仍要 steward）。
- `duplicates`：同 `experimentSignature` 被挡时写 `outcome: blocked` 的 run（若没有新 result，允许只写边、不造假 result）。`validFrom` = 建议被挡的时间。
- 旧 plan 无 `outcomeGraph`：记忆投影走现有启发式，不迁移回填。

### 4.1 Graphiti → 本仓库对照（只借模型）

| Graphiti | 落到 `outcomeGraph` | 明确不借 |
| --- | --- | --- |
| Entity + 演化 summary | `claim` / `protocol` / `experiment_run` + `summary` | 对话人物、用户偏好图 |
| Fact 边 + 有效期 | `validFrom` / `validUntil` / `supersededByEdgeId` | Zep SaaS、第三方图库 |
| Episode 出处 | `producedByEpisodeId` + `evidenceRefs`（已有 `_result_evidence_refs`） | 把 log 正文当 episode 写入图 |
| Prescribed ontology | 关闭集合：3 种节点、4 种 relation | LLM 抽取新类型；LightRAG 实体抽取 |
| 增量写入 | 登记事务内追加节点/边，不重建全图 | Microsoft GraphRAG 全量 Leiden 索引 |
| Hybrid retrieval | P0：signature 精确匹配 + 当前有效边 1 跳 | 向量、Cypher、PPR（P1+ 可抄 HippoRAG，另开任务） |
| 官方 vs 工作 | 我们多一层 steward：`working_only` 不能当 KnowledgeItem | 把工作边同步进 `memory_graph_service` |

Claim 状态投影（工作层，不改枚举名）：

| 当前有效边 | `claimMap.status` |
| --- | --- |
| 无 outcome 边 | `not_established` |
| 当前 `supports`（尚无正式 item） | 仍 `not_established`（正式 `qualified` 只来自 steward 知识） |
| 当前 `falsifies` | `unsupported`；若 interpretation/failedGates 明示否定主张则 `rejected` |
| 边已 `validUntil` | 不参与当前状态，但 `counterEvidenceRefs` 仍可引用（历史） |

记忆包投影（字段名保持现有 Prompt 契约）：

- `negativeExperiments` ← 当前有效 `falsifies`（按 `validFrom` 排序，截断 `MAX_NEGATIVE_EXPERIMENTS=8`）
- `priorSuccessfulRuns` ← 当前有效 `supports`（上限 8）
- `forbiddenDuplicateExperiments` ← `duplicates` ∪ 失败边的 `experimentSignature`
- 查询只看 `validUntil == ""` 的边；启发式仅用于无 `outcomeGraph` 的旧 plan

跨 plan 去重：P0 在 `build_research_memory_context` 里扫描传入的 `plans[]`（调用方已经给了团队计划列表），不需要先拆 `research_outcome_graph.json`。签名碰撞在内存里合并 forbidden 列表即可。

---

### B.5 研究分期

### P0（下一刀实现，本方案可执行）

1. 抽取纯函数（建议放 `experiment_kernel.py` 或 `research_memory_context.py` 旁的小模块，避免撑爆 facade）：`build_outcome_graph_delta(plan, result) -> nodes/edges`，含关闭旧边。
2. `register_experiment_smoke_result` / `register_experiment_full_run_result` 在现有 `_WORKFLOW_LOCK` 内合并 `plan["outcomeGraph"]`。
3. `build_research_memory_context`：有 `outcomeGraph` 则只投影 **当前有效边**；否则回退 status 启发式。`claimMap` 按 §4.1 表更新。
4. 去重：同 `experimentSignature` 仍 `exclude_from_suggestions`；被挡时写 `duplicates`（可无新 result）。
5. 测试见 §B.7。不改 `sync_official_research_graph`、steward pack、前端、`memory_graph_service`。

### P1

- steward pack 增加/使用 `negative_finding`（失败经门禁才成为正式知识）。
- `_official_research_graph_record` 为已接受的否定发现写 `falsifies`（及通过项的正式 `supports`）。
- `formalKnowledgeItemCount==0` 仍拒绝正式 sync。

### P2

- SCI-096 需要时再做 seed/attempt 树。
- UI 工作图（必须 VUI + `WORKBENCH_LAYOUT_IDS`，另开任务）。

---

### B.6 研究任务卡

Task 1: 登记时写工作层成败边（含时序关闭）
- Owner/Boundary: `experiment_api/smoke.py`、`experiment_api/full_run.py`、`experiment_kernel.py`；不碰 candidate_store 类型、不碰 SCI-096 实验脚本
- Dependency: 无
- Mode: SIMPLE（现有登记锁内追加字段）
- Verification/Stop: passed → `supports`+`tests`；failed → `falsifies`+`tests` 且必带 interpretation/failedGates/evidenceRefs；第二次相反结果把旧边 `validUntil` 填上，旧边仍在数组里

Task 2: 记忆包从图投影
- Owner/Boundary: `research_memory_context.py`；Prompt 字段名兼容
- Dependency: Task 1
- Mode: SIMPLE
- Verification/Stop: `tests/_support/team_workflow/cases_experiment.py`、`cases_research_knowledge.py`、`tests/test_research_loop_service.py` 现有断言仍绿；新增「有边则不靠 status 启发式」用例

Task 3: 去重与 duplicates
- Owner/Boundary: 现有 forbidden signature 路径（`workflow_ops.py` / 建议生成处，以代码为准）
- Dependency: Task 1–2
- Mode: SIMPLE
- Verification/Stop: 同签名再建议被挡；记忆包出现该 signature

P1/P2 不列入本轮 Critical Path。

---

### B.7 研究验证

P0 绿的定义：

- 聚焦测试：`tests/test_team_workflow_orchestration_service.py`（经 cases_experiment / cases_research_knowledge）、`tests/test_research_loop_service.py` 中记忆与实验登记相关用例。
- 新用例至少覆盖：failed smoke 写出当前有效 `falsifies`；passed full-run 写出当前有效 `supports`；同 claim 后一次失败把先前 `supports.validUntil` 写上且旧边仍在；无边旧 plan 回退启发式；同 signature 禁止重复建议；claimId 与 `_claim_map` 一致。
- 不跑全仓；不改 `web/` 故不跑 `tsc -b`。
- Launcher refresh：`not needed`（纯后端工作流 JSON 字段；用户测挑战杯记忆时建议重启会话，不强制 rebuild）。

未覆盖：正式 `falsifies`、UI 图、attempt 树、`get_knowledge_trace` 到中央知识库（P0 追溯止于 plan `outcomeGraph` + evidenceRefs；正式 item 追溯仍走现有 steward 路径）。

---

### B.8 研究风险

| 风险 | 处理 |
| --- | --- |
| 实验节点混进 SC 候选队列 | 禁止新 `candidateType`；边只挂 plan |
| 失败变成正式知识 | P0 边 `edgeState: working_only`；不调用 ingestion |
| Prompt 膨胀 | 继续 `MAX_NEGATIVE_EXPERIMENTS=8`；不塞 raw log |
| 三套记忆混写 | 只改挑战杯 `team_workflow` 研究记忆；不写 `memory_graph_service` / project-memory 规范 |
| 与 SCI-096 coordination 重叠 | 本任务 scope 仅 docs（本文件）或后续实现时仅上述 Python；不改 `experiments/challenge_cup_spike_coding/` |
| 正式图其实是薄 sync log | P0 承认并绕开；P1 在 `_official_research_graph_record` 加边，而不是假装 `official_graph_sync.json` 已是完整图 |
| 误接 Graphiti/Neo4j | 方案非目标已写死；P0 只加 plan JSON 字段 |
| 工作层 supports 被当成正式 qualified | `claimMap` 在无 steward item 时保持 `not_established`；只把 falsifies 映射到 unsupported/rejected |

回滚：删 `outcomeGraph` 字段即可回退到启发式记忆；plan status 行为保持不变。

---

## C. 实现分闸与 Git

三条独立任务，禁止同一 worktree 兼写：

| 切片 | Owner | 下一刀 | 覆盖缺陷 |
| --- | --- | --- | --- |
| 研究 `outcomeGraph` | `team_workflow` | `codex/research-outcome-graph-p0`（§B） | 研究写路径（已强，按原方案做） |
| 公共结构 + 生命周期 | `team_knowledge` pack | `codex/public-structure-catalog`（§A.1–A.6、A.8） | 混合读、预算、去重、路由、治理队列、归档 |
| 个人无损 episode | `agent_directory` 事件写入 | `codex/agent-episode-memory`（§A.7） | 个人层热路径；不自动升公共 |

- 根 `main` 只读。不要复用本方案分支写业务。
- 合入前验证；`git merge --ff-only` 后立即清理本任务 worktree / claim。
- 远端 push / PR 需用户明确授权。
- 公共切片不要改 `KNOWLEDGE_OWNER_TYPES`、不要往 `items.jsonl` 灌规范正文、不要新建平行 steward overview。
- 公共切片不要让 `context_engine` 再注入第二份 `AGENTS.md`。
- 个人切片不要写 `team_knowledge` / `outcomeGraph`。

推荐实现顺序：研究 P0 与公共目录可并行（owner 不同）；个人 episode 不阻塞前两条，但公共提升路径要能引用 `episodeId`（字段先留空即可）。

---

## D. 审查溯源（v2.1 → v2.3）

对照 MemGPT/Letta、Engram（arXiv:2606.09900）、ACM 五原语（arXiv:2607.21503）、CoALA、LongMemEval、Skills 渐进披露、Aider RepoMap；以及本仓库 `context_engine` / `list_knowledge_governance_tasks`。

v2.1 只把缺口写成结论清单。v2.2 已落到独立 `public/`、可检索集、预算、归档/矛盾、个人 jsonl。v2.3 补上会改实现的三条：开工排除 PromptManager 已注入真源、目录只做路由、混合读用 DTO + 允许名单强制、治理队列并入现有 steward 任务。

**仍明确不做：** Agent 自管公共核心记忆；dreaming 自动发布经验；本阶段 RepoMap / HippoRAG PPR / 公共层 as-of 查询 / 预取；把策展树塞进 `ownerType: project` 的 KnowledgeItem；用 catalog 替换仓内 grep。
