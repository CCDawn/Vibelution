# Product — 会话标签关闭两段式确认

## 会话标签关闭两段式确认

### 功能

会话标签条 × 关闭控件的内联两段式确认（inline two-stage confirm）：第一次点击 × 不弹窗，
控件原地进入 armed 确认态——X 图标变 danger 色调并带淡 danger 底色、几何尺寸不变
（仍为 icon-only 24px 控件，不改变标签条布局），title/aria-label 切换为
「再次点击确认移除会话记录」。armed 态再次点击同一控件立即执行原 × 语义
（移除会话记录，跳过确认弹窗）。armed 态在约 3 秒超时、按 Escape、或点击
armed 控件以外任意区域（其它标签、标签条外）时自动回落为普通 ×。

### 适用范围

- **适用**：`AgentSessionTabStrip` 会话标签条每张会话标签的 × 关闭控件
  （删除语义为「移除会话记录」，非归档）。
- **不适用**（改用 `VConfirmDialog` 弹窗）：
  - 会话右键菜单 `SessionContextMenu` 的删除项（无可见驻留控件可承载 armed 态）；
  - 清空历史、删除/重置群聊、Agent 归档等低频破坏性操作；
  - 终端页（CLI run tab）关闭控件——它不是删除语义，不需要确认。

| 场景 | 选择 |
| --- | --- |
| 高频、低破坏面（仅移除会话列表记录）的驻留 icon 控件 | 用本交互模式 |
| 菜单项触发的破坏性操作 | 改用 `VConfirmDialog`（`ChatDangerConfirmDialog`） |
| 服务端 428 误触防护的重试类动作 | 改用 `ResearchWorkflowRecoveryPanel` 的 arm→确认按钮对 |

### 使用方式

armed 状态是 route 组件内部本地状态，不抽 vui 层新组件（先例：
`ResearchWorkflowRecoveryPanel` 的 armed 模式）。

```tsx
// AgentSessionTabStrip.tsx（组件内部）
const [armedCloseSessionId, setArmedCloseSessionId] = useState<string | null>(null);

// 单值 state 保证同一时刻最多一个 armed；effect 负责超时/Escape/外点回落
// 并在卸载时清理定时器与监听器。armed 控件打
// data-session-tab-close-armed="true"，document 捕获段 pointerdown
// 以 closest() 判定点按是否落在 armed 控件内：落在其外即回落，
// 落在其中则放行为确认点击。
```

```tsx
// 删除回调签名：第二次点击带 confirmed 直通，调用方跳过弹窗直接执行
onDeleteSession: (session: SessionSummary, options?: { confirmed?: boolean }) => void;
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `armedCloseSessionId` | 当前 armed 会话 id（`string \| null`） | 单值 state，参照 `LauncherBranchInstancesPanel` 的 `forceStopId` 写法 |
| `data-session-tab-close-armed` | armed 控件标记 | 供 document pointerdown 判定点按落点，兼作测试锚点 |
| `deleteSessionConfirmArmed` | armed 态 title/aria-label 文案 | i18n key，zh/en 双语，跟随既有 `deleteSession` 模式拼接会话标题 |

### 状态与数据语义

- armed 只改控件视觉与可访问命名，不改变 × 的删除语义与数据通路；
  确认后走原 `handleDeleteSession` 删除链（含 busy/在途防抖前置检查），
  仅跳过 `openDeleteSessionConfirm` 弹窗。
- 既有禁用语义不回退：会话运行中（busy phase）或该会话删除在途时控件保持禁用，
  禁用优先于 armed（disabled 时不进入、不保持 armed）。
- armed 是纯 UI 瞬态：不入 store、不持久化、不产生遥测副作用；回落不还原任何数据。

### 非职责

- 不提供全局「关闭需确认」开关；两段式即替代弹窗的确认方式。
- 不处理会话归档、清空历史或 Agent 级删除（各自沿用既有确认路径）。
- 不为终端页关闭控件增加确认。

### 视觉与状态

- 普通 ×：`agentSessionTabCloseButton`（tertiary 灰、透明底、hover 亮起）。
- armed ×：`agentSessionTabCloseButtonArmed`——`var(--fg-danger)` 文字 +
  12% danger 底（hover 20%），几何不变（`h-6 w-6` icon-only），无弹层、无加宽。
- 同一时刻全标签条至多一个 armed；新 arm 会先使旧 armed 回落（单值 state 天然互斥）。

### 实现落点

- `web/src/routes/AgentSessionTabStrip.tsx`（armed state + effect + × 控件接线）
- `web/src/routes/AgentSessionTabStrip.styles.ts`（`agentSessionTabCloseButtonArmed`）
- `web/src/routes/chat/useChatWorkspaceActions.ts`（`handleDeleteSession` 的 `confirmed` 直通分支）
- `web/src/i18n/domains/dictionaryCore.ts`（`deleteSessionConfirmArmed` zh/en）
