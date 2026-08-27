# Product — Challenge real batch controls

## ChallengeRealBatchControlPanel

### 功能

服务端持有的挑战杯真实批次（G1 → G5 → G12 → G125）的 fail-closed 控制台：授权/启动/取消动作加确认对话，进度指标与「运行观察」区块提供 drain 状态、in-flight、自动闭环率与停止原因的只读证据。

### 适用范围

- **适用**：真实批次控制台的授权语义、进度指标、运行观察（R4.2 观察区块）。
- **不适用**（改用 `…`）：DEV fixture 批次（`ChallengeCupDevControlSnapshot` 表面）、题目级运行详情（`ChallengeCatalogOverview` / `ChallengeQuestionDetailPanel`）。

| 场景 | 选择 |
| --- | --- |
| 真实批次授权/启动/取消控制 | 用本组件 |
| 目录总览/单题状态 | 改用 `ChallengeCatalogOverview` |
| token 用量展示 | 改用 `ChallengeTokenUsageStrip` |

### 使用方式

```tsx
import { ChallengeRealBatchControlPanel } from "@/routes/teams/research-workflow/ChallengeRealBatchControlPanel";

<ChallengeRealBatchControlPanel teamId={teamId} lang="zh" />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `teamId` | 团队 id | 空值渲染 `VStateSurface` 空态 |
| `lang` | `"zh" \| "en"` | 双语文案成对出现 |

### 运行观察区块（R4.2，全部只读）

- **Drain 四态徽章**（`VStatusChip` + `VContextualHint`）：`none` 未请求 → `requested` 取消请求在途（仅前端在 cancel mutation pending 时合成，服务端从不报告）→ `draining` 仍有在途运行 → `drained` 无在途运行。`drained` **不承诺即时无残留**：待人工审核等记录可能仍在；该语义固定出现在 tooltip，不写入 `drained` 徽章文本。
- **进行中 / 并发上限**：`statusSummary.running` / `concurrencyLimit`；上限缺失（旧响应）显示 `—`。
- **自动闭环率**：口径 = 无需人工审核即闭环的题数（`autoClosedCount`，即 package-backed 成功）÷ 全部完成题数（`totalCompletedCount` = 成功+失败+阻塞）。展示与目标 ≥85%（`autoCloseTarget`）的相对位置：达标 `success`，未达标 `warning`。
- **异常升级率**：口径 = 失败 + 待人工审核（`escalatedCount`）÷ 同一分母；操作员取消而未启动的题不计入异常。展示与停止线 ≤15%（`escalationStopLine`）的相对位置：超线 `danger`，未超 `success`。
- **停止原因**：`stopReason`（`failure_budget_exhausted` 熔断 / `cancelled_by_operator` 操作员取消）+ 剩余失败预算 `remainingFailureBudget/failureBudget`；批次完成时明确显示「无停止原因」。
- 服务端未提供观察字段（旧 payload）时按同一口径本地推导（`cancelled`+`running` 推 drain，`statusSummary`+`awaitingApprovalQuestionIds` 推比率），绝不把「字段缺失」渲染为 0% 或达标。

### 非职责

- 不做任何执行逻辑：授权/启动/取消全部经服务端 durable 校验；前端不推导授权状态。
- 不展示 checkpoint/hash 等内部完整性字段（服务端投影含 `checkpointSha256` 等，前端不消费）。

### 视觉与状态

- 布局：`VEmbeddedPanel` 根 + `VMetricStrip` 指标 + 密集文本行；观察区块为浅表面块（`vui-surface-raised`）。
- tone：danger（失败/熔断/超停止线）、warning（drain 进行中/未达标）、success（达标/已排空）、neutral（无数据）。

### 实现落点

- 源码：`web/src/routes/teams/research-workflow/ChallengeRealBatchControlPanel.tsx`
- 服务端投影语义：`core/research/competition/real_control_batch.py`（`project_real_batch_state` 的只读观察字段）

### 反冗余

- 与 `ChallengeCatalogOverview`：总览按题粒度展示执行状态；本组件只做 gate 级控制与聚合观察。
- 观察区块全部复用 `VStatusChip` / `VContextualHint` / 密集样式，禁止为其新建第二套徽章或指标组件。
