# 会话历史 branch/head 模型详细设计

- 日期：2026-09-12。
- 状态：设计待评审，未实施；本文不代表任何代码已修改或行为已变更。
- 目标：把 Web 会话的编辑重发与重新生成从「物理截断覆盖」升级为「消息树 + 活跃叶节点（head）」模型；旧回答保留、可枚举、可切换；投影、模型上下文、API/SSE 与前端 UI 全部以活跃路径为唯一直播源。
- 本次范围：只读测绘与设计落盘。实施拆为后端存储/回放、后端 API/SSE、前端 UI 三个后续任务，各自独立验证与合入。
- 证据基线：本地 `main` 的 `674b1050c`（T1 journal 水位线、T2 前端权威截断、T4 停止快路、T5 回到底部锚点均已合入）；本文引用的行号来自该提交的只读测绘。
- 用户裁决：采纳完整 branch/head 模型；先评审本设计，再决定存储契约与实施顺序。

## 1. 现状测绘（实施约束）

### 1.1 数据流

1. 提交：`submit_session_message` 创建 `turnId`（`core/web/services/session/runtime_glue.py:832-840`），追加 `turn_started` + `user_message`（`core/web/services/session/submit.py:177-293`），写路径 `journal_bridge.append_session_conversation_event`（`core/web/services/session/journal_bridge.py:195-266`）。
2. 事件 schema：`TurnJournalEvent`（`core/chat/turn_journal.py:158-176`）含 `sequence`（全局追加序）、`turnId`、`eventType`、`payload`、`parentEventId`（已定义但无生产写入方）、`projectionKind` 等。
3. 存储：`sessions/<safe-token>/turn_journal.jsonl`（+`.lock`、+T1 引入的 `.watermark`），append-only 为 transcript 唯一权威（`turn_journal.py:230-251`）。
4. 回放读取：`model_visible_messages_from_events`（`turn_journal.py:1373-1572`）、`model_messages_from_events`（`1573-1600`）、`session_turn_items_from_events`（`1019-1126`）、预览尾读 `load_latest_turn_events_for_preview`（`570-635`）。
5. 详情投影：`get_session_detail`（`core/web/services/session/projection.py:196`）→ `_normalize_messages`（`1208`，位置 id `{sessionId}-message-{n}` 在 `1293`）→ `_coalesce_assistant_messages_by_turn`（`1175-1205`，每 turn 一条助手行）→ 窗口 `_session_detail_messages_with_window`（`1745`，1-based 扁平索引，`totalMessages` 在 `1768`，`messageWindow` 在 `1813-1823`）。
6. 编辑/重新生成：`_resubmit_session_user_message`（`submit.py:1150`）只接受最新真实用户消息（`1214-1235`）→ `_truncate_session_ledger_before_message`（`runtime_glue.py:2564-2588`）→ `rewrite_turn_events` 物理重写整个文件（`turn_journal.py:733-782`），从目标消息起的旧内容被真删。
7. SSE：`session_detail` 为按窗口的全量快照（`publish.py:514-635`，默认 40 条、上限 200），`assistant_delta` 只带本轮 `turnId` 与重建的 `turnItems`（`publish.py:638-681`）。
8. 前端：窗口合并 `mergeSessionDetailMessageWindow`（`web/src/routes/chatSessionState.ts:521` 起），索引来自 id 正则 `-message-(\d+)$`（`:368-372`）；乐观编辑/重新生成直接裁掉后续消息（`applyOptimisticEditResubmit` `:244-309`、`applyOptimisticRegenerate` `:326-366`）。

### 1.2 硬性线性假设（本设计必须逐一处理）

| 假设 | 位置 | 分支模型下的处理 |
| --- | --- | --- |
| 截断 = 物理删除旧事件 | `runtime_glue.py:2587`、`turn_journal.py:733-782` | 改为追加 rebase 标记，回放折叠 |
| 每 turn 一条助手行 | `projection.py:1175-1205` | 保留（turn 仍是原子单元），分支粒度到 turn 前用户消息 |
| 消息 id 为位置序号 | `projection.py:1293` | 先额外返回稳定 `nodeId`，再迁移分页游标 |
| 窗口 = 扁平索引切片 | `projection.py:1768-1823`、`routes/sessions.py:355` | 索引改为「活跃路径上的 1-based 序号」 |
| 编辑/重新生成仅限最新 | `submit.py:1214-1235` | 阶段放开：允许任意活跃路径消息为 base |
| `sequence` 只表示追加序 | `turn_journal.py:309` | 保留；因果由 rebase 标记表达 |
| 预览/标题取文件尾部 | `projection.py:4416-4458` | 统一走折叠函数，禁止新调用方直接读尾部 |
| 模型上下文为扁平回放 | `turn_journal.py:1573-1600` | 回放前先折叠为活跃序列 |

### 1.3 可复用资产

- `parentEventId` 已在事件 schema，可直接作为 rebase 的因果字段，不必新增结构。
- T1 的 `.watermark` 保证物理重写后 sequence 不回头，继续服务其他 rewrite 路径。
- 详情 DTO 为 `extra="allow"`（`core/web/routes/session_detail_models.py:14-17`），新字段可先透传、类型后补。
- 前端已有按消息挂载的编辑/重新生成入口（`ConversationView.tsx:4426-4453` 的 `metaActions` 插槽），chevrons 可同槽位扩展。

## 2. 设计目标与非目标

目标：

1. 编辑任意用户消息、重新生成任意助手消息都创建**新分支**，旧路径的事件原样保留。
2. 会话的活跃路径由 head（活跃叶节点）唯一决定；投影、模型上下文、SSE、前端展示都以活跃路径为准。
3. 用户可以切换分支（head_select），切换后下一轮模型看到新路径。
4. 不引入第二份 transcript：Journal 仍是唯一存储权威。

非目标（本设计不含）：

- 跨会话 fork（把某分支导出为新会话）。
- 分支合并/多父节点。
- 分支配额与长期归档策略（只定义度量与未决项）。
- Companion/虚拟人链路的任何语义变化。

## 3. 存储契约（推荐：追加式 rebase 标记）

### 3.1 新事件类型 `branch_rebase`

```jsonc
{
  "eventType": "branch_rebase",           // 新增类型；旧代码必须按未知类型 no-op 忽略
  "turnId": "<新分支的 turnId>",           // 与随后的新 user_message 一致
  "sequence": <全局追加序>,
  "timestamp": "<ISO8601>",
  "parentEventId": "<fromEventId>",       // 分叉点：仍在活跃路径上的最近事件
  "payload": {
    "operation": "edit" | "regenerate" | "head_select",
    "branchId": "<新分支稳定 id>",
    "fromEventId": "<分叉点 eventId>",
    "replacedTurnIds": ["<被取代段的 turnId>..."],
    "baseMessageId": "<前端可见的目标消息 id，仅诊断用>"
  }
}
```

写入顺序：`branch_rebase` → 新 `user_message`（新 `turnId`）→ 正常 worker 执行。

关键性质：

- 不删除、不重写旧事件；文件只增长。
- `sequence` 仍是全局追加序；T1 水位线机制不变（编辑/重新生成不再触发 rewrite，水位线只服务其他 rewrite 路径）。
- 文件尾部始终是新分支事件，现有「取尾部」的预览/最新轮判定天然指向新段；`head_select` 不追加事件，需专门处理（见 3.4）。
- 旧二进制遇到未知 `eventType` 必须是 no-op；实施前先写测试锁定 replay 对未知类型的容错，否则回滚不安全（见 §7）。

### 3.2 活跃路径折叠算法

回放层新增纯函数 `fold_active_events(events) -> list[TurnJournalEvent]`：

```text
active = []
for event in events:                     # 文件序（sequence 升序）
    if event.eventType == "branch_rebase":
        cut_index = index_of(active, event.parentEventId)   # fromEventId
        if cut_index >= 0:
            active = active[:cut_index + 1]                 # 截断到分叉点
        # 找不到分叉点（异常/并发）时保留 active 并记录诊断，不整体丢弃
        continue
    if is_head_select(event):            # head_select 另见 3.4
        continue
    active.append(event)
return active
```

性质：

- 单遍、O(n)，嵌套编辑自然成立（在旧分支内部再次编辑 = 再次截断到更早的点）。
- 只能从**活跃路径**上的消息发起编辑/重新生成；对非活跃消息发起时要求先 `head_select` 到其所在分支（服务端校验，避免产生不可达分支）。
- 折叠是纯函数，模型回放、turnItems、详情投影、预览统一调用同一实现，禁止各自实现尾读语义。

### 3.3 校验与并发

- 追加 `branch_rebase` 与随后的 `user_message` 必须在同一把 journal 会话锁内，避免并发编辑交叉产生悬挂分支。
- 服务端校验 `fromEventId` 必须位于当前活跃路径；否则返回 409 并要求刷新。
- 运行中（turn 未终态）默认拒绝 rebase（与今天 edit 仅限最新一致）；运行中是否允许列为未决项（§9）。

### 3.4 head_select

- 事件 `branch_rebase`（`operation="head_select"`，`fromEventId` = 目标分支的叶节点）本身不改写任何 turn，只表达「活跃路径重算到该叶」。
- 折叠算法对 `head_select` 单独处理：不能按「截断到分叉点」执行，否则会丢掉后续提交。推荐做法：head_select 只记录目标叶节点；折叠时先按普通 rebase 序列构建所有可达路径，再按最后一个 head_select 指针选择叶到根的路径（等价于 ChatGPT 的 `current_node`）。
- 因此折叠算法实现为两段：先构建 `parentEventId` 链（rebase 提供新链根），再取 head 指针路径；单趟截断只是无 head_select 时的等价简化。
- head_select 不改变文件尾部 → 切换后必须由服务端主动 `publish_session_detail` 全量快照，前端不自行推导。

### 3.5 文件增长与压缩

- 旧分支保留使文件单调增长；检查点（compression checkpoint，`conversation_invariant.py:80-125`）继续只基于折叠后的活跃序列生成，天然正确。
- 折叠前需要检查点失效判定：检查点引用的消息若不在活跃路径上，回退全量回放。
- 每会话分支数/事件数上报度量；配额与归档策略列为未决项（§9）。

## 4. 投影与 API 契约

### 4.1 SessionDetail 扩展（均向后兼容）

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `activeLeafId` | string | 当前活跃路径末端消息的 `nodeId` |
| `activeBranchId` | string | 当前活跃分支 id |
| 消息级 `nodeId` | string | 稳定节点 id（= 用户消息事件 eventId 或 `{turnId}:assistant`），从第一天起只读返回 |
| 消息级 `branch` | object | `{ branchId, parentNodeId, siblingCount, siblingIndex, active }` |

- `messages` 语义不变：只包含活跃路径上的消息，顺序不变。
- `messageWindow` 继续按活跃路径 1-based 索引；被取代段不参与 `totalMessages` 与分页。
- 过渡期同时返回 `nodeId`，前端完成迁移后再把分页游标从 `beforeMessageIndex` 切到 `beforeNodeId`（两者并存一个版本周期）。

### 4.2 编辑/重新生成接口

- `POST /sessions/{id}/messages/edit-resubmit`：新增可选 `baseMessageId`（缺省 = 最新用户消息，保持现状语义）；服务端不再截断，而是写 `branch_rebase` + 新 `user_message`。
- `POST /sessions/{id}/messages/regenerate`：新增可选 `baseMessageId`（缺省 = 最新助手消息）；同样走 rebase。
- 成功响应仍是详情快照（携带新 `activeLeafId` 与分支元数据）；失败语义与今天一致（非活跃路径 409、运行中 409）。

### 4.3 head 切换接口

- `POST /sessions/{id}/head`：`{ "nodeId": "<目标叶>" }`；校验 nodeId 属于该会话且为某分支叶；写 `branch_rebase(operation="head_select")`（或专用轻量事件），发布 `session_detail` 快照；幂等。
- 运行中切换默认拒绝（需先停止），与 3.3 一致。
- 分支枚举不新增接口：`siblingCount/siblingIndex` 随消息返回即可支撑 `‹ n/m ›` UI；如后续需要分支列表页再评估独立只读接口。

### 4.4 模型上下文

- `model_messages_from_events` 与压缩回放统一走折叠后的活跃序列；`head_select` 后下一轮模型看到新路径。
- 系统提示/工具回执等非消息事件保持原样，不参与路径选择。

## 5. SSE 契约

- `session_detail` 全量快照自动携带 §4.1 新字段；切换 head / 提交 rebase 后由服务端 publish。
- `assistant_delta` 不变（已有 `turnId`）；同一时刻只有活跃路径上的 turn 会进入终态 publish。
- 被取代段的旧 turn 不再产生新事件；前端不需要「忽略旧 turn」的新逻辑。

## 6. 前端契约与 UI

### 6.1 类型与合并

- `ConversationMessageBase` 增加 `nodeId?` 与 `branch?`；`SessionDetail` 增加 `activeLeafId? / activeBranchId?`（`web/src/api/types/chat.ts:623-643, 899-971`）。
- `mergeSessionDetailMessageWindow` 继续按活跃路径合并；服务端快照切换分支后 `ledgerSeq` 递增 + `hasLater=false`，T2 的权威截断逻辑直接适用，前端不做树计算。
- 乐观更新：编辑/重新生成不再本地裁掉后续消息，改为「乐观置为切换中」+ 等服务端快照；切换 head 同理（可先禁用入口并显示加载）。

### 6.2 UI 入口

- 每个分叉点的消息在 `metaActions`（`AgentMessageTurnView.tsx:71-73`，挂载点 `ConversationView.tsx:4413-4455`）增加 `‹ n/m ›` 版本切换；用户消息与助手消息使用同一交互。
- 编辑/重新生成按钮从「仅最新」放开：任意用户消息可编辑，任意已终态助手消息可重新生成；`canRegenerateAnswer`/`latestUserMessageId` 门（`ConversationView.tsx:4255-4259, 4438-4453`、`ChatCodingRouteWorkbench.tsx:2145-2155`）相应放宽。
- 行 key：`agentMessageTimelineRows.ts` 的 rowKey 需要并入 `branchId`，避免不同分支同 turnId 的行 key 冲突。

### 6.3 测试

- `chatSessionState.test.ts`：分支快照合并、切换后 tail 替换、无本地树计算。
- `ConversationView.*.test.tsx`：chevrons 渲染与调用、任意消息编辑/重新生成入口。
- `useChatComposerSubmit` 测试：rebase 乐观与回滚。
- `ChatCodingRoute.layout.test.ts`：窗口/分页与 active leaf 元数据。
- 浏览器主路径：编辑→切换→再提交→模型上下文验证（runtime-scene 证据）。

## 7. 迁移、兼容与回滚

- 老会话无 `branch_rebase` 事件 → 折叠等于恒等，行为与今天完全一致，无需数据迁移。
- 新事件类型对旧代码的回滚安全依赖 §3.1 的 no-op 容错；实施第一步先补 replay 未知类型容错测试，未通过前不允许合入写入路径。
- 编辑/重新生成改用 rebase 后，同一条可见路径与今天完全一致（投影过滤掉被取代段）；因此 T3-A1 可用「可见行为不变 + 旧事件仍可枚举」作为验收。
- 分支功能写入与服务端投影必须同步上线；不存在「只写不读」的中间态（会重复显示旧段），实施以一次性切换为准。

## 8. 任务拆分

| 任务 | 内容 | 验收 | 前置 |
| --- | --- | --- | --- |
| T3-A1 存储与回放 | `branch_rebase` 事件、`fold_active_events`、模型/turnItems/详情/预览接入、edit/regenerate 改写入 | 编辑/重新生成可见行为不变；旧事件保留可枚举；journal/ledger/详情/编辑回归全绿 | replay 未知类型 no-op 容错 |
| T3-A2 API/SSE | `nodeId`、`branch` 元数据、`activeLeafId`、`POST /head`、切换后 publish | 详情契约、head 幂等、SSE 快照、分页兼容 | T3-A1 |
| T3-A3 前端 UI | types、chevrons、head mutation、任意消息编辑/重新生成、merge 兼容 | vitest/contract/tsc + 浏览器主路径 | T3-A2 |

每片独立收口；T3-A1 是本模型的存储契约落地，风险最高，实施时必须带完整回归与回滚门。

## 9. 未决项（评审确认）

1. 编辑是否放开到任意历史消息（需要「非活跃路径先切换」的交互），或第一期仍限最新？
2. `head_select` 是否只允许空闲 turn；运行中切换是否直接禁止？
3. 分支保留配额：每会话分支上限、超限时旧的被取代段是否压缩归档到 sidecar。
4. 稳定 id 迁移节奏：`beforeNodeId` 与 `beforeMessageIndex` 并存多久。
5. 是否需要「把分支导出为新会话」（跨会话 fork），如需要应作为独立后续设计。
