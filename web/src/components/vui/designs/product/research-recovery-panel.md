# Product — Research round-failure recovery

## ResearchWorkflowRecoveryPanel

### 功能

待人工恢复聚合面板：把研究失败账本（`hypothesis_round_failures`，团队级、跨全部实验）里
「自动推进结束后仍未解决」的 open 失败/等待项呈现为单一可操作队列。每行显示状态标签、
题目与轮次、一句话原因（failureCode → 人话短标签映射，未映射回落原始 reason）与行内
「详情」披露（失败码 / 原始信息 / 时间 / 处理提示）。可重试行提供行内按钮（重新生成轮 /
重新派发评审）→ 二次确认 → 后台接受；面板同时提供「一键重试全部可重试项」批量入口。
`blocked`（纯 fan-in 等待）行只读、不提供按钮，避免误触。

### 适用范围

- **适用**：研究工作台操作区（progress 面板栈）聚合「需要人工处理的轮生成失败与等待项」，
  以及节点/画布旁的「待恢复 N 项」入口条（见 `ResearchWorkflowRecoveryEntry`）。
- **不适用**（改用 `…`）：单题阻塞/心跳/预算异常（`ResearchAnomalyInboxPanel`）、
  当前任务 canonical 动作（`ResearchCurrentTaskInspector` / 画布节点操作面）、
  批次授权与运行观察（`ChallengeRealBatchControlPanel`）。

| 场景 | 选择 |
| --- | --- |
| 跨实验聚合轮生成失败并一键重试 | 用本组件 |
| 单题异常队列（阻塞/心跳/预算） | 改用 `ResearchAnomalyInboxPanel` |
| 当前任务的下一步 canonical 动作 | 改用当前任务检查器 |

### 使用方式

```tsx
import {
  ResearchWorkflowRecoveryEntry,
  ResearchWorkflowRecoveryPanel,
} from "@/routes/teams/research-workflow/ResearchWorkflowRecoveryPanel";

// 操作区清单（progress 面板栈）
<ResearchWorkflowRecoveryPanel teamId={teamId} lang={lang} />

// 当前任务区入口条：仅当 openFailureCount > 0 时渲染，点击打开操作区
<ResearchWorkflowRecoveryEntry
  teamId={teamId}
  lang={lang}
  onOpen={() => location.openPanel("progress")}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `teamId` | 团队 id（必填） | 空值渲染 `VStateSurface` 空态，不发请求 |
| `lang` | `"zh" \| "en"` | 缺省自取 shell 语言 |
| `onOpen` | 入口条点击回调 | 由 workspace 决定打开哪个操作面板 |

### 状态与数据语义

- 数据来自 `GET /teams/{teamId}/workflow-orchestration/hypothesis-first/chain/round-failures`（薄路由，
  默认 `unresolvedOnly=true`）；畸形 payload 在 transport 层 fail-closed 抛错，面板渲染 error 表面 + 重试。
- 执行走 `POST …/round-failures/{failureId}/retry`（必须 `confirmed=true`，服务端 428 误触防护）：
  分钟级重生成由后台 worker 复用自动推进同一条 `regenerate_hypothesis_round` 命令路径，
  接受后该行进入「已排队重试」；面板 5s 轮询账本，记录被 resolve 后行自动消失——无需手动关闭。
- 服务端 404 = 未知/已解决；409 `fan_in_waiting` = 纯等待不可重试（面板本就不给它按钮）。
- 状态标签：`blocked` → neutral「等待中」；其余 open → warning「轮生成失败」；
  `autoBudgetExhausted` 语义已由「自动重试结束仍 open 才入列」本身表达，不再叠加文案。

### 非职责

- 不新增自动化：重试复用既有命令路径与预算语义，不绕过 `blocked` 等待。
- 不做跨题目的写操作编排（单次重试只作用于被点击的失败 trace）。
- 不聚合单题异常信号（那是 `ResearchAnomalyInboxPanel` 的职责）。

### 视觉与状态

- 布局：`VEmbeddedPanel` 根 + 头部计数（`VStatusChip` 可重试/等待中）+ 批量按钮；列表行两行文字
  （状态标签 + 题目·轮次；一句话原因 + 「详情」ghost 按钮），技术细节折叠在 `dl` 详情块内。
- 动作：arm → 确认（danger）/取消（ghost）两次点击；执行错误显示在行内。
- 折叠说明：`VContextualHint` 解释恢复语义（自动推进结束才入列、等待项无按钮）。

### 实现落点

- `web/src/routes/teams/research-workflow/ResearchWorkflowRecoveryPanel.tsx`（本组件 + 入口条）
- `web/src/routes/teams/research-workflow/ResearchWorkflowRecoveryPanel.styles.ts`（Tailwind token 类）
- `web/src/api/hypothesisFirst.ts` / `web/src/api/types/hypothesisFirst.ts` / `web/src/api/queryKeys.ts`
- 后端：`core/web/routes/team_workflows/hypothesis_first.py`、
  `core/web/services/team_workflow/research_runtime/hypothesis_first_chain.py`

## ResearchWorkflowRecoveryEntry

### 功能

「当前任务区」单行入口条：仅当失败账本存在 open 项时渲染一个紧凑按钮
「待恢复 N 项 · 查看处理」，点击打开操作区（progress 面板）的恢复清单。N=0 时不渲染任何
元素——日常正常工作流里完全隐身，不新增常驻徽标或页签。

### 适用范围

- **适用**：研究工作区画布上方（当前任务附近），作为恢复清单的唯一入口。
- **不适用**（改用 `…`）：常驻状态展示（用工具栏既有「待人工处理 N」canonical 计数）、
  恢复清单本体（用 `ResearchWorkflowRecoveryPanel`）。

### 使用方式

```tsx
<ResearchWorkflowRecoveryEntry
  teamId={teamId}
  onOpen={() => location.openPanel("progress")}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `teamId` | 团队 id（必填） | 空值不渲染 |
| `lang` | `"zh" \| "en"` | 缺省自取 shell 语言 |
| `onOpen` | 点击回调（打开操作区） | 入口不自行决定落点 |

### 状态与数据语义

- 与面板共享同一 query key（`hypothesisFirstChainRoundFailures`），10s 轮询 + 窗口聚焦刷新；
  计数变化（N→0）时入口自动消失，无需手动关闭。
- 查询失败/加载中一律不渲染（fail-silent 入口）：入口条的错误信息由面板本体承担。

### 非职责

- 不展示逐行明细、不执行重试（点击后到操作区完成）。
- 不占用工具栏状态位（不替代既有「待人工处理 N」canonical 计数徽标）。

### 视觉与状态

- 单个 `VButton`（secondary / compact，warning 图标）右对齐放在画布上方，`pb-1.5` 紧凑留白。

### 实现落点

- 与 `ResearchWorkflowRecoveryPanel` 同文件导出；
  `ResearchProcessWorkspace.tsx` 画布分支挂载。
