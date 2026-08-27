# Product — Research anomaly inbox

## ResearchAnomalyInboxPanel

### 功能

R4.3 异常收件箱操作台面板：把服务端聚合投影（`AnomalyInbox`）呈现为单一异常队列——critical/high/medium 分组列表（critical 置顶、计数徽章），每条目显示 kind 标签、scope（题目/run/node/meeting）、最近活动时间、摘要与推荐动作族提示；run 级条目点击跳转 run 上下文（URL 带 runId 才会渲染 FormalRuntimeActionBody），题目级条目跳转单题验收。

### 适用范围

- **适用**：研究工作台操作员查看某题目的阻塞 / 心跳 / 预算 / 待人工异常队列（进度面板、批次控制台相邻位置）。
- **不适用**（改用 `…`）：批次 gate 级授权/启动/取消控制（`ChallengeRealBatchControlPanel`）、题目假说/证据/验收明细（`ChallengeQuestionDetailPanel`）。

| 场景 | 选择 |
| --- | --- |
| 查看并跳转单题异常队列 | 用本组件 |
| 批次授权与运行观察 | 改用 `ChallengeRealBatchControlPanel` |
| 单题假说/证据明细 | 改用 `ChallengeQuestionDetailPanel` |

### 使用方式

```tsx
import { ResearchAnomalyInboxPanel } from "@/routes/teams/research-workflow/ResearchAnomalyInboxPanel";

<ResearchAnomalyInboxPanel
  teamId={teamId}
  questionId={questionId}
  onOpenItem={({ questionId, runId, nodeId }) => replaceParams(runId
    ? { runId, questionId, node: nodeId || null, panel: "node" }
    : { questionId, panel: "question" })}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `teamId` | 团队 id | 空值渲染 `VStateSurface` 空态 |
| `questionId` | 题目 id（可选） | 空值显示「未选择题目」提示而不是误报「无异常」 |
| `lang` | `"zh" \| "en"` | 缺省自取 shell 语言 |
| `onOpenItem` | 点击跳转回调 | 缺省时条目为只读行，不渲染按钮 |

### 状态与数据语义

- 数据来自 `GET /teams/{teamId}/workflow-orchestration/hypothesis-first/chain/anomaly-inbox`（服务端纯投影，排序/合并/完整性由 `AnomalyInbox` 合同保证）；前端**不重排序**，只按 severity 分组展示，组内保持服务端顺序（同级内按 lastSeenAt 倒序）。
- 空态二分：已选题目且 0 条 →「无异常」；未选题目 →「未选择题目」提示。绝不把「没查」渲染成「无异常」。
- 旧/畸形 payload（缺 schemaVersion/inbox/items 或字段类型不符）在 transport 层 fail-closed 抛错，面板渲染 error 表面 + 重试，不当作空队列。
- deepLink：runId 存在 → `{ runId, questionId, node?, panel: "node" }`；否则 `{ questionId, panel: "question" }`；连题目都没有的条目不可点。

### 非职责

- 不做任何处置动作（重试/对账/裁决仍走既有节点操作面与 claim ledger）；本面板只读 + 跳转。
- 不聚合团队级跨题队列（服务端本阶段按题目投影）。

### 视觉与状态

- 布局：`VEmbeddedPanel` 根 + severity 分组列表；组头用 `VStatusChip`（critical=danger / high=warning / medium=neutral）+ 计数。
- 条目行：kind 标签 + scope 行 + 最近时间 + 摘要 + 推荐动作族提示；可点行用 `VNativeButton` 整行点击。
- 空态/加载/错误：`VStateSurface`（empty / loading / error + 重试）。

### 实现落点

- 源码：`web/src/routes/teams/research-workflow/ResearchAnomalyInboxPanel.tsx`
- 服务端投影：`core/web/services/team_workflow/research_runtime/anomaly_inbox_service.py`（`build_anomaly_inbox`）与合同 `core/research/workflow/contracts/anomaly_inbox.py`
- 薄路由：`core/web/routes/team_workflows/hypothesis_first.py`（`anomaly-inbox` 端点）

### 反冗余

- 只复用既有 VUI 元素（`VEmbeddedPanel` / `VStatusChip` / `VContextualHint` / `VStateSurface` / `VNativeButton` / `VButton`），不新建第二套徽章、列表或指标组件。
- 与 `ChallengeRealBatchControlPanel`「运行观察」区块：那里是 gate 级聚合比率；本组件是题目级异常队列，两者互不替代。
