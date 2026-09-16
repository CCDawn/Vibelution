# Product — conversation

> 对话工作台组合层：只服务 Chat composer / 时间线。
> **禁止**在此重新实现按钮/输入；必须组合 VUI primitives。

## ConversationTodoChecklist

### 功能
回合级 todo 进度卡（Claude Code TodoWrite 范式）：把 agent 通过 `todo_write` 工具写入的最新清单快照渲染为常驻 checklist——完成项勾选、进行中项展示 activeForm + spinner、待办空心圈，头部带「已完成/总数」计数；回合结束仍有未完成项时给一行可见警示（仅呈现，不阻断）。

### 适用范围
- **适用**：直连会话时间线内的 assistant 回合（活跃轮实时、历史轮只读回放），快照从 journal 回放的 turnItems 派生。
- **不适用**：陪伴模式（`companionMode` 不渲染）；agent 私信/群聊转录行；无 `todo_write` 调用的回合（不渲染空卡）。任务管理（tasks.json 持久任务）用 task_* 工具面，不在此卡。

| 场景 | 选择 |
| --- | --- |
| 活跃轮 + 最新快照有 in_progress | 展开态：当前项 activeForm + spinner，其余按状态渲染 |
| 历史轮（turn 已有终态） | 默认折叠，可展开；只读，无交互承诺 |
| 回合结束 + 快照仍有 pending/in_progress | 头部下方一行警示文案（`todoChecklistUnfinishedWarning`） |

### 使用方式
```tsx
// 生产：ConversationView 回合渲染区（清单先于 process trail）。
// 快照派生：deriveLatestTodoChecklist(message.turnItems)，多调用取最后一个有效快照。
<ConversationTodoChecklist snapshot={snapshot} lang={lang} turnSettled={hasTerminalCanonicalTurnOutcome(message)} />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| snapshot | 最新有效清单快照（items/completedCount/total/hasUnfinished） | 由 `conversationTodoChecklistModel.ts` 派生，组件不自取数据 |
| lang | 语言 | 文案一律走 `dictionaryChat`（todoChecklist*） |
| turnSettled | 回合是否已有终态 | 决定折叠默认值与警示行；不改变回合状态判定 |

### 非职责
- 不落盘、不回写清单状态；journal 是唯一事实源，卡片只消费 turnItems。
- 不阻断或重试回合；警示行是呈现层，不是行为门。
- 不渲染 plan_update_tool / task_* 的数据（各自的计划与任务面独立）。

### 视觉与状态
- 状态图标：completed `CircleCheck`（accent-cool）、in_progress `LoaderCircle` animate-spin、pending 空心 `Circle`（弱化）。
- 进行中行用 `--fg-primary` 提高对比；完成行用 `--fg-tertiary` 弱化。
- 计数徽标 `3/6` tabular-nums；警示行用 `--accent-warm` 非模态。

### 实现落点
- 源码：`web/src/components/conversation/ConversationTodoChecklist.tsx`
- 纯派生：`web/src/components/conversation/conversationTodoChecklistModel.ts`（`deriveLatestTodoChecklist`）
- 样式：`web/src/components/conversation/ConversationTodoChecklist.styles.ts`
- 协议来源：`todo_write` 工具（`tools/todo_tools.py`）的 journaled tool-call arguments

### 反冗余
- 不新建通用 checklist primitive；本卡是 conversation product 组合，行渲染用 icon + 文本而非 VCheckbox（只读展示，无表单语义）。
- 禁止为清单另开第二数据通道（新 SSE 事件或服务端清单存储）。

## ConversationActiveTurnStatusNote

### 功能
运行中回合的紧凑状态行：一条心跳文案（阶段 + 秒数/重试进度），并叠加流连通性提示——连接断开重连、长时间无输出可停止、备用模型路由切换。让 SSE 断流与输出停滞从"无限累加的秒数"升级为可读的轻量提示。

### 适用范围
- **适用**：直连会话活跃回合的状态占位（`ConversationView` 时间线内）；需要流连通性可见性的位置。
- **不适用**：陪伴模式（`companionMode` 收敛为单一 typing 提示，不渲染提示条）；群聊房间（走 `ChatGroupMessageStream` 自身的断线文案）。

| 场景 | 选择 |
| --- | --- |
| 运行中回合 + 流断开重连 | 断连提示条（`VStatusChip tone=warning`）+ 断开持续秒数 |
| 运行中回合 + 已连接但超 90s 无 assistant delta | 停滞提示条（可停止），与断连正交叠加 |
| 消息带 `routeFallback {from,to}` | 备用路由提示条（`tone=accent`）；字段缺失不渲染 |
| 陪伴模式 | 仅 typing 提示 |

### 使用方式
```tsx
// 生产：ConversationView 时间线的活跃回合占位。
// 连通性经 ActiveTurnStreamStateContext 投影（ChatSessionWorkspacePanel 提供），
// ConversationView 不感知该状态。
<ConversationActiveTurnStatusNote message={activeTurnMessage} lang={lang} statusLabel="状态" />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| message | 活跃回合消息（turnItems/timestamp/可选 routeFallback） | routeFallback 缺字段则整条不渲染 |
| lang | 语言 | 新文案一律走 `dictionaryChat`，禁止内联三目 |
| streamState（context） | `streamConnected` 三态 + 断连起点 + 最近 delta 时间 | 不是第二套状态通道，只是 `useSessionDetailStream` 状态的跨层投影 |

### 非职责
- 不判定生成是否失败（journal 是事实源，断连不取消生成）。
- 不做模态阻断或 toast；不提供重试按钮（重连自动进行）。

### 视觉与状态
- 提示条用 `VStatusChip`（warning=断连/停滞，accent=路由回退），紧跟心跳行，非模态。
- 停滞阈值 `ACTIVE_TURN_NO_DELTA_STALL_AFTER_MS = 90s`（模块常量，覆盖长工具/思考静默）。
- 重连成功提示条自动消失；断连与停滞可同时显示。

### 实现落点
- 源码：`web/src/components/conversation/ConversationActiveTurnStatusNote.tsx`
- 纯 helper：`conversationActiveTurnStatusPresentation.ts`（`resolveActiveTurnDisconnectSeconds` / `resolveActiveTurnStallSeconds` / `resolveActiveTurnRouteFallback`）
- 状态投影：`web/src/components/conversation/activeTurnStreamState.ts`

### 反冗余
- 不新增第二套断线横幅；群聊横幅与主聊天提示条各归其位。
- 禁止绕过 context 直接在 `ConversationView` 加第二份连接状态 prop。

## ConversationFollowupQueueBar

### 功能
运行中跟进队列横条：把尚未发出的下一条指令停在输入框上方，用户可以撤回、修改或调序。

### 适用范围
- **适用**：当前轮仍在运行、用户已按 Enter 入队、内容还不能进正式时间线。
- **不适用**：空闲发送、编辑最新用户消息、已经立刻引导出去的独立消息。

| 场景 | 选择 |
| --- | --- |
| 运行中排队、未发出 | `ConversationFollowupQueueBar` |
| 立刻引导后的独立用户消息 | 时间线用户气泡 +「引导」标记 |
| 编辑已发出的最新用户消息 | composer 编辑条 |

### 使用方式
```tsx
import { ConversationFollowupQueueBar } from "../../conversation/ConversationFollowupQueueBar";

<ConversationFollowupQueueBar
  items={queue}
  lang="zh"
  queueLabel="排队"
  editLabel="修改这条排队"
  withdrawLabel="撤回这条排队"
  onUpdate={onUpdate}
  onRemove={onRemove}
  onMove={onMove}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| items | 未发出的排队全文 | 一条一条横条，不进时间线 |
| 改 / 撤回 / 拖动 | 只改队列 | 按钮用 `VButton`，编辑用 `VNativeTextarea` |

### 非职责
- 不调用 `/guidance`，不写正式会话。
- 不做手机端 390 预览变体。

### 视觉与状态
- 默认横条、编辑中描边、拖动调序。
- 空队列不渲染。

### 实现落点
- 源码：`web/src/components/conversation/ConversationFollowupQueueBar.tsx`
- 样式：`ConversationView.styles.ts` 的 `followupQueue*`

### 反冗余
- 不替代 composer 编辑条或时间线用户气泡。
- 禁止再做第二套排队条。

## ConversationMessageVersionSwitcher

### 功能
活跃路径消息的版本切换器：`‹ n/m ›` 紧凑三件组，在同一点（同一 fork）的兄弟版本之间切换会话 head；切换本身只提交服务端，由返回快照替换时间线。

### 适用范围
- **适用**：`ConversationView` 消息行 `metaActions`（用户消息与助手消息同一交互），消息带 `branch.siblingCount > 1`。
- **不适用**：单版本消息（不渲染）、运行中或切换中的会话（整组禁用）、分支枚举页。

| 场景 | 选择 |
| --- | --- |
| 同一点存在多个版本 | 行内版本切换器 |
| 切换后继续追问 | 服务端 head 快照，前端不做树计算 |
| 单版本消息 | 不渲染 |

### 使用方式
```tsx
// 生产：ConversationView metaActions 内联组合（不新增 primitive）
<VActionGroup ariaLabel={t("branchVersionLabel")} className={styles.turnVersionSwitcher}>
  <VButton isIconOnly icon={<ChevronLeft size={14} />} isDisabled={!previousSiblingNodeId} ... />
  <span className={styles.turnVersionLabel}>{`${siblingIndex}/${siblingCount}`}</span>
  <VButton isIconOnly icon={<ChevronRight size={14} />} isDisabled={!nextSiblingNodeId} ... />
</VActionGroup>
```

### 非职责
- 不做前端分支树、不本地裁剪后续消息。
- 不新增第二套按钮；只组合 `VButton` + `VActionGroup`。

### 视觉与状态
- 与行内 copy / edit / regenerate 共用 `turnIconButton` 密度；到达边界的方向禁用。
- 切换中（`branchVersionSwitchDisabled`）整组禁用，等服务端快照。

### 实现落点
- 源码：`web/src/components/conversation/ConversationView.tsx`（metaActions）
- 样式：`ConversationView.styles.ts` 的 `turnVersionSwitcher` / `turnVersionLabel`

### 反冗余
- 不替代消息编辑或重新生成入口；不新增独立分支列表页。

## ChatComposerPlusMenu

### 功能
桌面端 Chat composer 的统一扩展入口。单栏纵向分组菜单：每个分组带小节标题，动作行单行紧凑，能力开关行以内联勾选态直接展示；不出现二级面板或第三级菜单。打开后焦点落在首个可用项，↑/↓/Home/End 在可用项间循环，Escape 关闭。

### 信息架构
- `添加与引用`：图片附件、会话引用；禁用行用 `disabledReason` 说明原因。
- `对话能力`：心智模型、运行状态注入；行尾勾选标记表示 `开启`，无标记表示 `关闭`（`role="menuitemcheckbox"` + `aria-checked`）。
- `会话与陪伴`：仅当存在直接会话绑定时出现，当前提供打开直接会话。
- `群聊与团队`：管理群聊、打开团队（团队归属可用时）。
- `引用工作区文件`、陪伴投喂/聊天/关怀只在设计预览中保留，生产数据通路未就绪前不渲染，避免给出无动作的入口。

### 边界
- 斜杠指令仍由输入框内联建议负责，不进入加号菜单。
- 模型、权限、上下文用量、发送/停止仍位于 composer 工具栏。
- 缓存状态不在加号菜单或右栏展示；上下文详情仍由独立工具栏入口承载。
- 仅定义桌面交互，不增加手机端变体。
- 复用 `VPopover`、`VButton`、`VDialog`、`VNativeInput`，不新增第二套 primitive；菜单容器只允许一个 `role="menu"`，分组用 `role="group"`。

### 实现落点
- 源码：`web/src/routes/chat/ChatComposerPlusMenu.tsx`
- 样式：`web/src/routes/chat/ChatComposerPlusMenu.styles.ts`
- 隔离预览：`web/src/design/chat-composer-plus-menu-preview.tsx`

### 反冗余
- 不重新引入悬停聚类 + 右侧二级面板或两栏等高外壳。
- 不替代 composer 工具栏或斜杠内联建议。

## Composer 引用候选（@ type-ahead）

### 功能
composer 正文任意位置输入 `@` 时弹出的引用候选 listbox：按 `@` 到光标的片段过滤知识库、知识条目与会话文件候选，键盘 ↑/↓ 循环、Tab/Enter 选中、Escape 关闭；每行带「引用」徽标与斜杠指令区分。

### 适用范围
- **适用**：直连 Agent 会话 composer（与 plus menu 同一数据源 `composerReferenceOptions`）。
- **不适用**：陪伴模式（无 plus menu，同步关闭）；编辑重发（不支持引用）；composition（IME）进行中一律不弹，`compositionend` 后重估。

### 行为
- 选中候选**不向正文插入任何引用语法**：与 plus menu picker 完全同路径——登记同一结构化 `SessionReferenceAttachment`（去重、单轮上限 6），仅把 `@片段` 从草稿移除，光标落在移除点（两侧粘连时补一个空格）。
- 触发规则：`@` 起词才触发（句首、空白/标点/中文标点/汉字后）；ASCII 词后（`foo@bar` 邮箱形态）与含空白片段不触发；超长片段（>64 字符）不触发。
- 复用斜杠建议的 listbox 视觉与键盘协议（`role="listbox"/option`、`aria-activedescendant`、循环导航、Escape 按 draft 值记忆关闭）。

### 实现落点
- 纯函数：`web/src/components/conversation/conversationReferenceTypeahead.ts`（token 检测/过滤/移除）
- 集成：`web/src/components/conversation/ConversationView.tsx` composer 建议区
- 数据源：`web/src/routes/chat/ChatCodingRouteWorkbench.tsx` `composerKnowledgeReferenceOptions`（与 `ChatComposerPlusMenu` 同源）

### 反冗余
- 不新增第二套引用登记通道；后端 `conversation_references.py` 只认结构化 payload，不引入文本内 @ 语法。
- 不复制斜杠建议的样式/键盘实现；listbox 行直接复用 slash suggestion 样式类。

## ChatGroupManagementDialog

### 功能
承接从右栏迁出的群聊管理动作，保留群名、调度模式、对话目的、成员、应用、重置与删除能力。

### 边界
- 由 `ChatComposerPlusMenu` 的二级菜单直接打开，不再经过第三级菜单。
- 右栏仅保留群资料与状态，只读展示不承载管理按钮。
- 团队关联群聊仍由团队页维护成员和角色。

## ChatGroupMessageStream

### 功能
群聊房间的主阅读面：把多 Agent 发言排成可扫读的连续消息流。长文截断仍露出前几行，思考/工具收成一行，轮次纪要才用一张卡片。

### 适用范围
- **适用**：`/chat?room=` 群聊时间线、操作员观看的团队讨论。
- **不适用**：一对一 Agent 回答（继续 `ConversationView`）；研究画布会议纪要（继续 meeting digest）；设置列表行（继续 `vuiOpaqueRowClass`）。

| 场景 | 选择 |
| --- | --- |
| 群聊发言、内部 discuss | `ChatGroupMessageStream` |
| 思考/工具过程 | 挂在该条发言下的 disclosure，结束后收成一行 |
| 一轮结束后的结论 | 轮次末一块 digest，不包每条发言 |
| 1:1 最终回答 | 不折叠正文 |

### 使用方式
```tsx
// 生产：ChatGroupCenterSurface 群聊时间线
// 隔离对照仍在：web/src/design/team-conversation-stream-preview.tsx
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| 消息流 | 左对齐连续文本；同说话人合并头像/名字 | 不要每条 `vuiOpaqueRowClass` |
| 长文 | `line-clamp` 约 8 行 +「展开全文」 | 禁止用 `hidden` 整段藏正文 |
| 内部讨论 | 操作员时间线默认可读 | `collapsed_by_default` 不表示房间里看不见 |
| 纪要 | 轮次发丝分割线 + 末尾一块玻璃面板 | 唯一允许的卡片 |
| 并行发言进度 | 每个未落位成员各占一行 | 仅 `running` 显示“正在输入”；`settled` 显示“已完成，等待前序发言”且不提前展示正文 |

### 非职责
- 不改房间协议、SSE、visibility 字段写入。
- 不引入 Stream Chat / Discord 组件。
- 不做左右气泡，不把群聊改成看板或节点图。

### 视觉与状态
- 组内紧、组间松；失败/待发送才保留描边。
- 头像与名字同一行（flex 横排，正文缩进对齐名字）；过程默认收起。
- 超长正文截断可展开。
- 正式消息始终按 `speakerOrder` 落位；成员状态来自同一群聊 SSE 的 `speakerProgress` 投影，不另开连接、不充当第二套 transcript。
- 停滞只按该成员的状态更新时间与最近 delta 判断，不用整个轮次的更新时间替代成员活性。

### 实现落点
- 生产：`web/src/routes/chat/ChatGroupCenterSurface.tsx`
- 正文截断：`web/src/routes/chat/ChatGroupMessagePresentation.tsx`
- 对照预览：`web/src/design/team-conversation-stream-preview.tsx`

### 反冗余
- 不替代 `ConversationProcessDisclosure` 或 `ConversationFollowupQueueBar`。
- 禁止再做第二套群聊卡片列表。

## ConversationForkSessionDialog

### 功能
分支能力的 fork 出口：把一条消息及之前的活跃路径复制成一个新会话。确认弹窗承载范围选择（仅活跃路径 / 含沿途兄弟分支）与后果说明，确认后由路由层调用 fork API 并导航到新会话。

### 适用范围
适用：普通直连 Chat 会话时间线里任何带 `nodeId` 的已落库消息（用户消息或助手消息）。
不适用：Companion 私聊、Agent inbox、群聊 transcript、流式中的消息（入口直接隐藏）；没有 journal 节点 id 的历史消息不可分叉。

### 使用方式
弹窗由 `ConversationView` 持有（组合，不新增导出组件）；路由经 `onForkSessionFromNode(message, scope)` 接管执行与导航。

```tsx
<VConfirmDialog
  open
  title={t("forkSessionDialogTitle")}
  description={t("forkSessionDialogDescription")}
  confirmLabel={t("forkSessionConfirm")}
  onConfirm={() => onForkSessionFromNode(message, forkScope)}
>
  <VSelect
    selectedKey={forkScope}
    onSelectionChange={(key) => setForkScope(...)}
    options={[
      { id: "visible_path", label: t("forkSessionScopeVisiblePath") },
      { id: "with_branches", label: t("forkSessionScopeWithBranches") },
    ]}
  />
</VConfirmDialog>
```

| 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| 入口 | 消息 metaActions 里的 `GitFork` 图标按钮 | 与复制/重新生成同级，`turnIconButton` 样式；流式或版本切换禁用时禁用 |
| 说明文案 | `forkSessionDialogDescription` | 必须写明「原会话保持不变」 |
| 范围选择 | `VSelect` 两档 | 默认 `visible_path`；档位与后端 scope 一一对应 |
| 确认/取消 | `VConfirmDialog` footer | 请求进行中显示 `forkSessionPending` 并禁用关闭；失败弹窗保持打开，错误落到源会话 composer |

### 非职责
- 不做 fork 后的会话树可视化、不内嵌新会话预览。
- 不承担 API 调用与缓存更新（路由层职责）。
- 不引入第二套确认弹窗壳（禁手写 fixed overlay）。

### 视觉与状态
- neutral tone `VConfirmDialog`；pending 时确认键文案切换为「分叉中」并禁用取消。
- 失败静默留在弹窗内，源会话 composer 显示 `forkSessionFailed` 前缀错误。

### 实现落点
- 弹窗与入口：`web/src/components/conversation/ConversationView.tsx`（metaActions + 根部 `VConfirmDialog`）
- 路由执行：`web/src/routes/chat/ChatCodingRouteWorkbench.tsx` `handleForkSessionFromNode`
- API：`web/src/api/chat.ts` `forkSessionFromNode`

### 反冗余
- 复用 `VConfirmDialog` + `VSelect`，不新建 `V*` 导出组件。
- 危险确认走 `VConfirmDialog` danger tone；本弹窗非破坏性（源会话只读），保持 neutral。
