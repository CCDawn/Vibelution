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
运行中回合的紧凑状态行：一条心跳文案（阶段 + 秒数/重试进度），并叠加流连通性提示——连接断开重连、长时间无输出可停止、备用模型路由切换。让 SSE 断流与输出停滞从"无限累加的秒数"升级为可读的轻量提示。断流提示附一个「重新连接」小 ghost 按钮：自动重连卡住（keep-warm 租约异常、浏览器挂起恢复）时用户可手动触发硬重连。

### 适用范围
- **适用**：直连会话活跃回合的状态占位（`ConversationView` 时间线内）；需要流连通性可见性的位置。
- **不适用**：陪伴模式（`companionMode` 收敛为单一 typing 提示，不渲染提示条）；群聊房间（走 `ChatGroupMessageStream` 自身的断线文案）。

| 场景 | 选择 |
| --- | --- |
| 运行中回合 + 流断开重连 | 断连提示条（`VStatusChip tone=warning`）+ 断开持续秒数 + 重连按钮（见下） |
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
| streamState（context） | `streamConnected` 三态 + 断连起点 + 最近 delta 时间 + `reconnectSessionStream` 回调 | 不是第二套状态通道，只是 `useSessionDetailStream` 状态的跨层投影 |

### 非职责
- 不判定生成是否失败（journal 是事实源，断连不取消生成）。
- 不做模态阻断或 toast。

### 视觉与状态
- 提示条用 `VStatusChip`（warning=断连/停滞，accent=路由回退），紧跟心跳行，非模态。
- 停滞阈值 `ACTIVE_TURN_NO_DELTA_STALL_AFTER_MS = 90s`（模块常量，覆盖长工具/思考静默）。
- 重连成功提示条自动消失；断连与停滞可同时显示。
- 重连按钮：`VButton variant=ghost density=compact` + RotateCw 图标，仅断流且有 `reconnectSessionStream` 回调时渲染（陪伴/无守卫流面板无回调即无按钮）；点击后冷却 `ACTIVE_TURN_RECONNECT_ACTION_COOLDOWN_MS = 2s` 防连点。

### 实现落点
- 源码：`web/src/components/conversation/ConversationActiveTurnStatusNote.tsx`
- 纯 helper：`conversationActiveTurnStatusPresentation.ts`（`resolveActiveTurnDisconnectSeconds` / `resolveActiveTurnStallSeconds` / `resolveActiveTurnRouteFallback` / `shouldShowActiveTurnReconnectAction`）
- 状态投影：`web/src/components/conversation/activeTurnStreamState.ts`
- 重连动作权威：`web/src/routes/chat/useSessionDetailStream.ts`（唯一流拥有者；复用硬关 + keep-warm 重取 + 一次权威 detail 失效）

### 反冗余
- 不新增第二套断线横幅；群聊横幅与主聊天提示条各归其位。
- 禁止绕过 context 直接在 `ConversationView` 加第二份连接状态 prop。
- 禁止重连按钮旁开第二条 `/api/sessions/:id/events` 连接；手动重连必须走唯一拥有者的硬关+重取路径。

## ConversationFollowupQueueBar

### 功能
运行中跟进队列横条：把尚未发出的下一条指令停在输入框上方，用户可以撤回、修改、调序，或选择「立即发送」（停止当前轮并让这条排队消息下一个发出）。

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
  editLabel={t("editFollowupQueue")}
  withdrawLabel={t("withdrawFollowupQueue")}
  saveEditLabel={t("saveFollowupQueueEdit")}
  cancelEditLabel={t("cancelFollowupQueueEdit")}
  dragHandleLabel={t("dragFollowupQueue")}
  sendNowLabel={t("sendFollowupQueueNow")}
  sendNowPendingLabel={t("sendFollowupQueueNowPending")}
  turnRunning={runningGuidanceActionsEnabled}
  onUpdate={onUpdate}
  onRemove={onRemove}
  onMove={onMove}
  onSendNow={onSendNow}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| items | 未发出的排队全文 | 一条一条横条，不进时间线 |
| 改 / 撤回 / 拖动 | 只改队列 | 按钮用 `VButton`，行内编辑用 `VNativeInput`（Enter 保存、Esc 取消） |
| 拖拽手柄 | 显式 grip（`VButton`），只有手柄可拖，整行不可拖 | 聚焦手柄后上下方向键等同调序；编辑中的行与系统回执行不可拖 |
| turnRunning + onSendNow | 「立即发送」按钮（图标+文案 `VButton`），仅在当前有轮运行时出现 | 只对 `status=queued` 的用户排队显示；系统回传、暂停、失败行不可立即发送；置顶行（`sendNow`）改挂「即将发送」徽标，不再出现按钮 |
| sendNow 徽标 | 冷色 accent 描边徽标（同队列插入指示色系） | 只在 `queued` 行上显示；暂停/失败后消失 |

### 非职责
- 不调用 `/guidance`，不写正式会话。
- 不做手机端 390 预览变体。
- 不实现停止本身：立即发送只调用队列 send-now API，停止语义归会话控制面。

### 视觉与状态
- 默认横条、编辑中描边、拖动调序。
- 拖动中：源行降透明，悬停目标行显示插入位指示（向上拖在行上方、向下拖在行下方），拖拽期间冻结各行 hover 反馈。
- 立即发送中：被提升行置顶并挂「即将发送」徽标；API 失败回滚原位并提示。
- 空队列不渲染。

### 实现落点
- 源码：`web/src/components/conversation/ConversationFollowupQueueBar.tsx`
- 样式：`ConversationView.styles.ts` 的 `followupQueue*`；`ConversationFollowupQueueBar.styles.ts` 的 `followupQueueChipSendNow`

### 反冗余
- 不替代 composer 编辑条或时间线用户气泡。
- 禁止再做第二套排队条。
- 立即发送不新造停止入口：停止请求复用会话控制面现有 `request_stop`，前端不出现第二个停止按钮。

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

## AgentUserContentSectionView 用户消息折叠

### 功能
用户消息气泡的超长折叠（对齐 ZCode）：正文按测量高度（`scrollHeight`）超过 120px 阈值时默认折叠——内容区钳在 `max-h-[120px] overflow-hidden`，底部渐隐提示还有内容，下方一枚小 ghost 文字钮「展开」；展开后变「收起」。不持久化：每次挂载默认折叠。

### 适用范围
- **适用**：`ConversationView` 时间线内的用户消息正文（markdown children 透传），含异步媒体（图片加载撑高经 ResizeObserver 重测）。
- **不适用**：编辑态（`ConversationUserInlineEditor` 整体替换气泡，折叠不参与）；assistant 回答与群聊转录行（各自正交）。

| 场景 | 选择 |
| --- | --- |
| 测量高度 ≤ 120px | 原样渲染，无按钮无渐隐 |
| 测量高度 > 120px | 默认折叠 + 底部渐隐 +「展开」ghost 钮 |
| 用户展开 | 解除钳制与渐隐，按钮变「收起」；内容缩回阈值下时按钮与渐隐整体消失 |

### 使用方式
```tsx
// 生产：ConversationView 用户正文槽（编辑态 ternary 的另一侧，组件不自取数据）。
<AgentUserContentSectionView userContentSectionIds={...}>
  {renderResponseText(userContentText)}
</AgentUserContentSectionView>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| userContentSectionIds | AgentMessage content section 元数据 | 透传 `data-agent-content-*`，不参与折叠 |
| children | markdown 渲染结果 | 折叠只钳可视高度，不裁剪、不改写内容 |

### 非职责
- 不持久化展开状态（无 storage、无 per-message 记忆）。
- 不改写 markdown 管线或正文；不承担编辑/重发入口。

### 视觉与状态
- 钳制在包装层（`relative max-h-[120px] overflow-hidden`）；被测子节点保持自然高度，折叠态下 ResizeObserver 仍能看到真实内容增长。
- 渐隐遮罩 `bg-gradient-to-t from-[var(--vui-control-muted)] to-transparent`（与气泡底色同令牌）+ `pointer-events-none`。
- 按钮仅实际超高时渲染：`VNativeButton` ghost 文字钮、caption 字号、`--fg-tertiary`，带 `aria-expanded`；测量只在跨越阈值时 setState，不做每帧重渲染。

### 实现落点
- 源码：`web/src/components/conversation/AgentUserContentSectionView.tsx`
- 纯策略：`web/src/components/conversation/conversationUserMessageCollapse.ts`（`USER_MESSAGE_COLLAPSE_THRESHOLD_PX` / `shouldCollapseUserMessage`）
- 样式：`web/src/components/conversation/AgentUserContentSectionView.styles.ts`（`userMessageBodyClamped` / `userMessageCollapseFade` / `userMessageCollapseToggle`）
- 文案：`dictionaryChat.expandUserMessage` / `collapseUserMessage`

### 反冗余
- 测量式（scrollHeight + ResizeObserver）而非行数预算；不复制 `ConversationMarkdownRenderer` 的 `<details>` 行预算折叠。
- 按钮复用 `VNativeButton`，禁止第二套展开钮、渐隐样式或直连 shadcn renderer。

## 时间线虚拟行

### 功能
历史消息按量到的行高绝对定位。还没量到时，间距先用 120px 估算；量到之后按正文自己的高度排开，下一条不得盖住上一条。

### 视觉与状态
- 行本身不用 `content-visibility`，也不用 120px 的 `contain-intrinsic-size`。那会把行的边框锁在估算高度，正文仍然画出来，下一条的位移就压在上一条上面。
- 代码块仍可以对屏幕外的块使用 `content-visibility`，避免测量抖动。这只作用在代码块，不作用在整行。
- 用户消息超过 120px 后的折叠是气泡内部的钳制，不代替行高。

### 实现落点
- 样式：`ConversationView.styles.ts` 的 `timelineVirtualRow`
- 估算常量：`conversationTimelineFollowState.ts` 的 `CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX`

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

## Composer 图片附件上传失败态与重试

### 功能
composer 图片附件的上传生命周期与失败恢复：每个 chip 携带 `uploadStatus`（pending/uploading/uploaded/failed）与 `artifactId`；提交路径 `Promise.allSettled` 逐 chip 写回，失败保留批次语义（错误行 + 草稿恢复 + 乐观消息移除），成功 chip 记住 `artifactId`，重发时复用不重传。

### 适用范围
- **适用**：直连会话 composer 的图片附件 chips、提交与重试路径。
- **不适用**：知识库/会话引用（走引用候选结构化登记）；时间线内已落库附件展示。

| 场景 | 选择 |
| --- | --- |
| 单 chip 上传失败 | 红系失败态 chip + chip 内 `RefreshCw` 重试钮 |
| 存在失败 chip 的提交 | composer 错误行追加「重试上传」ghost 钮，失败批次不静默吞掉 |
| 重试 / 重发 | 只修上传链路，绝不自动发消息；已成功 chip 复用 `artifactId` 不重传 |

### 非职责
- 不自动发送消息：重试仅补上传，发送始终是用户显式动作。
- 不承担时间线侧附件预览（走 image preview dialog）。

### 视觉与状态
- 失败 chip：`composerAttachmentChipFailed`（`--state-error` 红系 ring/wash）+ `aria-invalid`，tooltip `attachmentUploadFailedRetryHint`。
- 错误行「重试上传」：`VButton` ghost + `RefreshCw` 12px，仅存在失败 chip 时渲染；文案走 `dictionaryChat.retryUpload`。

### 实现落点
- 纯模型：`web/src/routes/chat/chatComposerSubmitModel.ts`（`ComposerImageAttachment.uploadStatus` / allSettled 逐 chip 写回 / `mergeComposerImageAttachments`）
- 集成：`web/src/components/conversation/ConversationView.tsx`（chips 失败态 + 错误行重试钮）
- 样式：`ConversationView.styles.ts` 的 `composerAttachmentChipFailed`

### 反冗余
- 不新增第二套上传通道或第二处错误行；批次失败复用既有草稿恢复路径。
- 禁止重试自动发送；禁止对已上传 chip 重复 POST。

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

## ConversationFileDeliveries

### 功能
一轮对话尾部的文件改动摘要条。折叠态默认只占一行：项目文件数 + 项目文件 `+A −D` 合计 +（若有）弱化的「另有 N 个工作区脚本」注记，右侧保留「回退本轮文件」入口；点击行其余区域展开逐文件明细。展开态按「项目改动」与「工作区脚本」两组呈现，工作区脚本组整体弱化，仅写可验证事实（位于 Agent 工作区内），不做过多的回退/版本断言；文件列表外层限高滚动，避免大轮次倾泻。

### 适用范围
- **适用**：直连会话时间线中任一已完成助手轮的文件交付呈现（`ConversationView` 按消息尾部挂载）。
- **不适用**：Companion 私聊、群聊 transcript、替代 Rewind 弹窗（回退仍走 `ConversationFileRewindDialog` 预览确认流）。
- **分类权威**：后端 ledger 的 `display_path`（项目内=相对路径，项目外=绝对路径）；前端仅对 transcript-only 行用绝对路径启发式兜底（`classifyDeliveryFiles`）。

### 使用方式

```tsx
<ConversationFileDeliveries
  cells={cells}
  language={language}
  onContinue={handleContinue}
  changedFiles={changedFiles}
  sessionId={sessionId}
  turnId={turnId}
/>
```

| 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| 折叠摘要行 | chevron + 「本轮文件 · P」/「工作区脚本 · W」 + `+A −D`（仅项目文件） + 弱化工作区注记 | `aria-expanded` 标注；整行可点切换；`useState(false)` 默认折叠、不持久化 |
| 回退入口 | 行右侧 `VButton` ghost「回退本轮文件」 | stopPropagation，不触发展开；语义仍归 Rewind 弹窗 |
| 项目改动组 | 逐文件卡：图标 + 路径 + `+N −M` + 状态徽标 + 查看/继续修改 | 展开后才渲染；P=0 时整组不渲染 |
| 工作区脚本组 | 同卡片元素，muted 弱化 + 一行「Agent 工作区内的文件。」说明 | W=0 时整组不渲染；组说明不做未验证断言 |
| 文件列表容器 | `max-height` 约 360px + overflow auto | 大轮次不倾泻；折叠态零展开内容 |

### 视觉与状态
- 折叠行 hover 用 surface-row-hover 反馈可点；chevron 随展开旋转。
- 无任何文件条目时整个面板 render null，与旧契约一致。
- `+A −D` 永远只合计项目文件，工作区脚本只计数不进 +/-。

### 实现落点
- 面板：`web/src/components/conversation/ConversationFileDeliveries.tsx`
- 分类与合并：`web/src/components/conversation/conversationFileDeliveryModel.ts`（`classifyDeliveryFiles` / `mergeConversationFileDeliveries`）
- 样式：`web/src/components/conversation/ConversationFileDeliveries.styles.ts`

### 反冗余
- 复用 `VSurface`/`VButton`/`VDialog`，不新建 `V*` primitive。
- 复用 `isAbsoluteFileSystemPath`（`api/desktopPlatform`）与 `sameDeliveryPath`，不另写路径判定。
- 破坏性回退不在此面板实现，统一走 `ConversationFileRewindDialog`。

## ConversationFileRewindDialog

### 功能
整轮回退弹窗：把某一轮写入的项目文件恢复到该轮开始前的状态。打开时拉取服务端逐文件预览（分类徽标 + 将执行的动作 + 当前大小），默认 strict 应用整批；服务端 409 时列出被拒文件明细并提供「仍恢复安全文件」force 次按钮；成功与幂等重放都以计数反馈。服务端是唯一安全权威，弹窗只做呈现与转发。

### 适用范围
- **适用**：直连会话时间线里带磁盘检查点（`metadata.changedFiles` 非空）的已完成助手轮，从「本轮文件」面板折叠摘要行右侧入口进入。
- **不适用**：Companion 私聊、群聊 transcript、流式中的轮次、没有 `sessionId`/`turnId` 锚点的渲染（入口直接隐藏）。

### 使用方式

```tsx
<ConversationFileRewindDialog
  open={rewindOpen}
  sessionId={sessionId}
  turnId={turnId}
  language={language}
  onOpenChange={setRewindOpen}
/>
```

| 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| 入口 | 面板折叠摘要行右侧 `VButton` ghost「回退本轮文件」 | 仅 `changedFiles?.length && sessionId && turnId` 齐备时显示；stopPropagation 不触发展开 |
| 预览列表 | 逐文件行：路径 + `VChip` 分类 + 动作说明 + 当前大小 | 分类文案用人话（`external_modified` → 「写入后被其他程序修改」） |
| 说明行 | 服务端 `capabilityNote` 原文 | 有值才显示 |
| 确认/force | strict 主按钮；409 后出现 force 次按钮 | pending 时禁用关闭；结果反馈替换动作区 |
| 结果反馈 | `已恢复 N 个文件；跳过 M 个。` 或幂等重放说明 | alreadyApplied 不显示伪造计数 |

### 非职责
- 不做逐文件勾选回退（服务端只支持整轮语义 + force）。
- 不做回退后的会话刷新与缓存失效（接线层职责）。
- 不内嵌 diff 预览（面板已有「本轮补丁」弹窗）。

### 视觉与状态
- 加载：`role="status"` 预览加载文案；404 等失败给一行人话错误 + 「重试」。
- 分类徽标 tone：safe→success、checkpoint_missing→warning、external_modified→danger、其余 neutral。
- 应用中：确认/force 按钮 `isPending`，取消禁用；结果出现后仅剩「关闭」。

### 实现落点
- 弹窗：`web/src/components/conversation/ConversationFileRewindDialog.tsx`
- 入口与渲染：「本轮文件」面板 `web/src/components/conversation/ConversationFileDeliveries.tsx`
- API：`web/src/api/chat.ts` `previewSessionTurnRewind` / `applySessionTurnRewind` / `sessionRewindUnsafeFilesFromError`

### 反冗余
- 复用 `VDialog`/`VButton`/`VChip`，不新建 `V*` primitive。
- 不与 `ConversationForkSessionDialog`（分叉出口）共享状态或入口。

## ConversationRerunFileChoiceDialog

### 功能
编辑一条消息再发送、重新生成某条回答，或重试失败轮次时，如果将被换掉的已加载消息带有磁盘变更和轮次号，先问要不要把这些文件还原。三个选择：还原文件并重跑、只重跑、取消。还原调用现有整轮回退，从较新的轮次到较旧的轮次逐个 strict 应用；某一轮失败就停在弹窗里显示错误，不开始重跑。没有这类文件时不弹窗，行为和原来一样。

### 适用范围
- **适用**：当前会话已加载的消息窗口。编辑从被编辑的那条用户消息算起，重新生成从被点的那条助手回答算起，失败重试从最近一条用户消息算起，一直到窗口末尾。
- **不适用**：普通新发送、切换回答版本、从节点分叉会话。没有 `metadata.changedFiles` 或没有轮次号时不问。窗口后面还没加载的消息不另发请求，那些文件不会出现在这次名单里。

### 使用方式

```tsx
<ConversationRerunFileChoiceDialog
  open={Boolean(rerunFileChoice)}
  language={language}
  paths={rerunFileChoice?.paths ?? []}
  pending={Boolean(rerunFileChoice?.restoring)}
  error={rerunFileChoice?.error ?? ""}
  onOpenChange={(open) => {
    if (!open) dismissRerunFileChoice();
  }}
  onRestoreAndRerun={() => {
    void confirmRerunFileRestore();
  }}
  onRerunOnly={keepFilesAndRerun}
/>
```

| 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| 时机 | 重跑真正发出之前，图片上传也在选择之后 | 取消不上传、不改会话 |
| 名单 | 最多 8 条路径，其余写「另外还有 N 个」 | 路径来自 `metadata.changedFiles` |
| 还原 | 主按钮，进行中改为「正在还原文件…」并禁用三个按钮 | `force` 仍只在整轮回退弹窗里 |
| 失败 | 正文里一行错误 | 弹窗保持打开，可以改选「只重跑」或取消 |

### 非职责
- 不自动还原文件。
- 不在切换回答版本或分叉时询问。
- 不把命令改过、但没有进入 `changedFiles` 的文件算进这次名单。

### 实现落点
- 弹窗：`web/src/components/conversation/ConversationRerunFileChoiceDialog.tsx`
- 名单与选择：`web/src/routes/chat/rerunFileRestore.ts`、`web/src/routes/chat/useRerunFileChoice.ts`
- 接线：`web/src/routes/chat/useChatComposerSubmit.ts`、`web/src/routes/chat/ChatCodingRouteWorkbench.tsx`
- 还原 API：`applySessionTurnRewind`（`force: false`）

### 反冗余
- 复用 `VDialog` / `VButton` 和整轮回退 API，不新建 `V*` primitive。
- 不并入 `ConversationFileRewindDialog`。那个弹窗仍负责单轮预览、冲突和 force。

## ConversationMarkdownCodeBlock

### 功能
Settled 消息里 fenced 代码块的头部三件套（对齐 ZCode CodeBlockHeader）：左侧小写语言标签（无语言回退 `text`），右侧自动换行切换与复制按钮；复制成功后图标 Copy→Check 短暂反馈。头部与代码卡片视觉合为一体，超行数折叠路径共用同一头部。

### 适用范围
- **适用**：`ConversationMarkdownRenderer`（settled 内容路径）渲染的 `<pre>` 代码块；折叠（`<details>`）与完整路径同构。
- **不适用**（改用 `…`）：流式 live tail（`StreamingLiveMarkdownBlocks` 轻量渲染，settled 后自然升级）；行内 code（保持 `inlineCode` 样式，无头部）；diff 块（`ConversationPatchDiff` 自带头部）。

| 场景 | 选择 |
| --- | --- |
| 普通 fenced 块 | 头部 + 代码卡片 |
| 超行数预算块 | 同一头部 + 折叠 `<details>`（展开交互不变） |
| 无语言 fence | 标签回退 `text` |

### 使用方式
```tsx
// 生产：ConversationMarkdownRenderer 的 pre 组件覆写内部构造，不直接对外使用。
<pre override → <ConversationMarkdownCodeBlock language text preClassName code truncation />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| language | fence 语言（`language-*` 提取） | 渲染为小写；缺失回退 `text` |
| text | 代码纯文本（clipboard 源） | 与渲染内容同源，不经 DOM 取值 |
| preClassName | 宿主传入的 `responseSegmentPre` | 边框/圆角归宿主样式 map，头部只做附加 |
| truncation | 超行预算切分结果 | 为空渲染完整 `<pre>`，存在则 `visible`+`<details>` |

### 非职责
- 不持久化换行偏好（仅本块挂载期生效）；不做跨块同步。
- 不处理流式 live tail 渲染；不改动折叠预算与展开交互。
- 不承担剪贴板权限 UI；复制失败静默（与 turn hover copy 一致）。

### 视觉与状态
- 语言标签 `text-vui-2xs` + `--fg-tertiary` 最浅文字色；头部底 `--vui-surface-row`，与 pre 共享边框拼成一张卡。
- 换行切换 `aria-pressed`，激活态 `--accent-cool`；复制反馈 Copy→Check 约 1.6s（与 turn hover copy 同语义）后自动还原。
- 控件用 `VNativeButton` + 图标 14px，命中区 h-6 w-6；`data-markdown-code-block` 作测试锚点。

### 实现落点
- 源码：`web/src/components/conversation/ConversationMarkdownRenderer.tsx`（`ConversationMarkdownCodeBlock`）
- 样式：`web/src/components/conversation/ConversationMarkdownRenderer.styles.ts`（`conversationMarkdownCodeBlockStyles`）

### 反冗余
- 不新建通用 CodeBlock primitive；本块是 conversation product 组合，头部控件复用 `VNativeButton`。
- 代码卡边框/圆角复用宿主 `responseSegmentPre`，禁止第二套卡片壳或平行样式 map。

## Markdown 工作区文件链接

### 功能
Settled 会话 markdown 里的工作区文件链接升级为可操作目标：链接分类器（`conversationMarkdownLinkTargets`）把 href + 会话工作区根分成 external（http/https/mailto，行为不变）、workspace-file（可归一化为绝对路径的文件路径）、other（保持原有惰性锚点）。workspace-file 链接主点击经桌面桥 `openPath` 用系统默认程序打开；桥不可用或 shell 失败时降级为复制路径 + 行内轻提示（约 2.4s 自动消退）。右键弹「打开方式」上下文菜单（`VDropdownMenu` anchored 模式）：打开（系统默认）/ 在文件夹中显示（`showItemInFolder`）/ 复制路径；每个动作失败都落到同一条复制降级。菜单文案组件内双语（`zh ? … : …`）。

### 适用范围
- **适用**：`ConversationMarkdownRenderer`（settled 路径）渲染的 `<a>`；调用方传入 `workspaceRoot` 时激活。
- **不适用**：流式 live tail（settled 后自然升级）；无 `workspaceRoot` 的调用（全部走旧锚点行为，语义零变化）；非文件形态（`#anchor`、`?query`、无扩展名目录、纯数字尾巴如 `v1.2`、未知 scheme）一律保持 other。

### 使用方式
```tsx
// 生产：ConversationMarkdownRenderer 的 a() 覆写内部构造；调用方只需多传两个可选 prop。
<LazyConversationMarkdownRenderer content={text} workspaceRoot={sessionWorkspaceRoot} language={lang} />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| workspaceRoot | 会话工作区根（调用方给定） | 缺省不激活任何新行为；`/` 前缀按工作区根相对解析 |
| language | 菜单/提示文案语言 | 组件内双语，文案不经 dictionaryChat |
| path | 分类器输出的规范绝对路径 | 分隔符与盘符风格随 root；percent 解码后落盘 |

### 非职责
- 不做文件预览、不读文件内容；打开/显示/复制全部委托桌面桥。
- 不改 external 链接语义（新窗口/window.open 分流归 Electron 壳）。
- 不承担剪贴板权限 UI；复制失败静默。

### 视觉与状态
- 链接本体复用宿主 `inlineLink` 样式，仅附加 cursor + focus-visible ring（`--accent-cool` 混合）；`title` 为完整路径。
- 降级提示行内 `role="status"`、`--fg-tertiary` 最浅文字色，自动消退不打断阅读。
- 上下文菜单直接消费 `VDropdownMenu` 自带壳，本组件只出 items 与锚点坐标。

### 实现落点
- 分类器（纯）：`web/src/components/conversation/conversationMarkdownLinkTargets.ts`
- 桥动作封装：`web/src/components/conversation/conversationMarkdownWorkspaceFileActions.ts`
- 组件：`web/src/components/conversation/conversationMarkdownWorkspaceFileLink.tsx` + `.styles.ts`
- 渲染分流：`web/src/components/conversation/ConversationMarkdownRenderer.tsx`（`a()` 覆写）

### 反冗余
- 不新建第二套文件链接/路径菜单；动作行复用 `VDropdownMenu` item，不直连 shadcn renderer。
- 分类与动作分层：分类器纯函数零副作用，桥探测只读同一 `vibelutionLauncher` 全局，禁止第二通道。

## Assistant 文件引用 chip 行

### 功能
Settled assistant 回答正文里"以纯文本/代码块形态出现的本地文件引用"升级为可点击 chip 行（ZCode AssistantPreviewCards 对齐，v1 收紧四类形态）：纯路径 fenced 块（每行都是路径才整块生效）、正文裸盘符/UNC 绝对路径、双/单引号包裹路径（相对路径按会话工作区根解析）、markdown 链接 href 仅用于去重抑制（已可点的不重复成 chip）。提取走扩展名白名单（.md/.html/.htm/.docx/.xlsx/.pptx/.pdf + png/jpg/jpeg/gif/webp/svg + mp3/wav/mp4/webm），白名单外一律不提取。chip 点击经桌面桥 `openPath` 打开；桥不可用或 shell 失败降级复制路径 + 行内轻提示；右键「打开方式」菜单（`VDropdownMenu`）与行内文件链接同语义：打开（系统默认）/ 在文件夹中显示 / 复制路径。

### 适用范围
- **适用**：settled assistant 消息正文渲染之后的一行 chip（timeline assistant_text 单元与 codex assistant_markdown 终态单元两个挂载点，共用同一个 settled 门与 `sessionWorkspacePath`）。
- **不适用**：流式进行中（`assistantTurnIsStreaming` 为真不渲染）；无白名单引用的消息；无工作区根时的相对路径引用（绝对路径引用不受影响）；用户消息/思考/工具单元。

### 使用方式
```tsx
// ConversationView 内部 helper 挂载；正文单元渲染后追加，不直接对外。
<ConversationFileReferenceChips text={item.text} workspaceRoot={sessionWorkspacePath} language={lang} />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| text | settled assistant 最终 markdown 文本 | 提取器纯函数，含 fenced/inline code 原文 |
| workspaceRoot | 会话工作区根 | 相对引用解析根；缺省仅绝对路径出 chip |
| language | 菜单/提示文案语言 | 组件内双语，文案不经 dictionaryChat |

### 非职责
- 不做文件预览、不读文件内容；打开/显示/复制全部委托 `conversationMarkdownWorkspaceFileActions` 桌面桥封装。
- 不重复呈现 markdown 链接目标（提取器把已链接文件从 chip 行排除，正文内联链接仍是唯一可点形态）。
- 不承担 `ConversationFileDeliveries` 的职责：那是本轮工具改动文件卡（diff/回退），数据源是工具单元与 changedFiles 元数据，与正文文本引用无关。

### 视觉与状态
- 一行 `role="list"` 轻量 chip：文件族图标（FileText/Image/FileAudio/Film）+ 文件名（mono truncate）+ 扩展名徽标（uppercase 小徽标），中性 surface + subtle border，读作附件而非第二回答块。
- 降级提示行内 `role="status"`、自动消退约 2.4s，与行内链接降级同一节奏。
- 上下文菜单直接消费 `VDropdownMenu` 自带壳，本组件只出 items 与锚点坐标。

### 实现落点
- 提取器（纯）：`web/src/components/conversation/conversationFileReferences.ts`
- 组件：`web/src/components/conversation/ConversationFileReferenceChips.tsx` + `.styles.ts`
- 挂载：`web/src/components/conversation/ConversationView.tsx`（`renderAssistantFileReferenceChips` helper；timeline 文本单元 + codex 终态 markdown 单元）

### 反冗余
- 不新建第二套打开/显示/复制动作；桥动作与降级语义复用 `conversationMarkdownWorkspaceFileActions`。
- chip 壳用 `VButton`（ghost compact）+ `VDropdownMenu`，不直连 shadcn renderer，不引第二套菜单。

## Mermaid 代码块

### 功能
Settled ```mermaid fence 的显式渲染块：平时就是明文 + 语言标签 + 「渲染」按钮（流式与历史零成本）；点击后才动态 import mermaid（独立 lazy chunk）并渲染 SVG（状态机 idle → loading → ready(svg) / failed）。预算守卫：源码 >20000 字符或 >600 行永不进渲染器，直接明文 + 提示（无按钮）；渲染失败降级回明文并附一句解析错误。SVG 视口 `max-h` + 滚动，`role="img"`。

### 适用范围
- **适用**：`ConversationMarkdownRenderer`（settled 路径）里 language 为 `mermaid` 的 fenced 代码块。
- **不适用**：流式 live tail（settled 前就是普通代码块）；`mermaidish` 等非精确 language 标签；行内 code。

### 使用方式
```tsx
// 生产：ConversationMarkdownRenderer 的 pre() 覆写按 language 分流，不直接对外使用。
<pre language="mermaid" → <ConversationMarkdownMermaidBlock code preClassName language />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| code | fence 源码 | 组件内 trim；预算按 trim 后计 |
| preClassName | 宿主 `responseSegmentPre` | 明文态边框/圆角归宿主，头部只做附加 |
| language | 提示文案语言 | 组件内双语 |

### 非职责
- 不自动渲染（不跟随流式/可见性）；点击是唯一渲染入口。
- 不持久化渲染状态；重挂载回到 idle。
- 不做 SVG 的二次缩放控件或导出。

### 视觉与状态
- 头部复用 `conversationMarkdownCodeBlockStyles` 的 header/language/actions/button，语言标签固定 `mermaid`，读作同一卡片家族。
- loading/failed 是 header 与明文之间的一条状态行（spinner + 文案 / 失败原因截断 200 字符），`role="status"`。
- ready 态 `markdownMermaidCanvas`：`max-h-[420px] overflow-auto`，SVG 居中限宽；`data-mermaid-state` 作测试锚点。

### 实现落点
- 预算 + 懒加载器（纯）：`web/src/components/conversation/conversationMarkdownMermaid.ts`
- 组件：`web/src/components/conversation/conversationMarkdownMermaidBlock.tsx` + `.styles.ts`
- 分流：`web/src/components/conversation/ConversationMarkdownRenderer.tsx`（`pre()` 覆写）

### 反冗余
- mermaid 只经 `loadMermaidRenderer` 单例入口初始化（startOnLoad=false、securityLevel=strict），禁止第二处 import。
- 头部样式复用代码块既有切片，禁止第二套头部样式 map。

## 轮次导航 rail 悬停预览

### 功能
时间线 minimap rail（每轮一枚圆点）的悬停预览：带预览的轮次点外包 `VHoverCard`（width 默认、`side="left"`，rail 贴右缘向左展开），内容纵向堆叠两段纯文本预览——用户提问两行截断（line-clamp-2）在上、助手回答三行截断（line-clamp-3）在下。预览由 ConversationView 以 `previewTextByRowKey` 喂入 `buildConversationTurnNavDirectory`，经 `userPreviewText`/`assistantPreviewText` 到点；与既有 label 同源提取，但剥掉 markdown（围栏代码、图片、链接、强调、标题/引用标记），卡片里不出现原始标记。原生 `title` 提示被该卡替换；无预览的轮次保持裸点，不包空卡。

### 适用范围
- **适用**：`ConversationTurnNavigator` 内达到 6 轮门后渲染的每个轮次点；仅当该轮至少有一段预览。
- **不适用**：压缩/模型切换/分叉分隔行（无导航点）；空预览轮次（不渲染空 HoverCard）；触屏无悬停（点按仍直接跳转，卡片是增强不是门）。

### 使用方式
```tsx
// 生产：ConversationTurnNavigator 的 entries.map 内。
<VHoverCard key={entry.turnIndex} side="left" content={...}>
  <VButton contentLayout="plain" aria-label={entry.label} aria-current={...}>…</VButton>
</VHoverCard>
```

### 非职责
- 不改导航跳转语义；卡片纯只读预览，无按钮无操作。
- 不做第二套 tooltip；原生 title 移除，aria-label 保留供读屏。
- 懒挂载由 VHoverCard 内建（指针意图 + openDelay 才挂 Radix 树），rail 百级点不预热 overlay。

### 视觉与状态
- 卡壳（边框/内边距/宽度/阴影）归 shadcn renderer；本组件只带 `turnNavigatorHoverBody/User/Assistant` 三片：纵向 `gap-1.5` 堆叠，`--fg-secondary`（提问）/`--fg-tertiary`（回答）、`text-vui-xs`、line-clamp 截断。
- 截断是纯 CSS（line-clamp），预览文本自身已在 ConversationView 侧按 200/300 字符上限收敛。

### 实现落点
- 源码：`web/src/components/conversation/ConversationTurnNavigator.tsx`
- 样式：`web/src/components/conversation/ConversationTurnNavigator.styles.ts`（`turnNavigatorHover*`）
- 预览派生：`web/src/components/conversation/ConversationView.tsx`（`turnNavPlainPreviewText` → `previewTextByRowKey`）
- 纯逻辑：`web/src/components/conversation/conversationTurnNavigation.ts`（`previewTextByRowKey` 选项与 `userPreviewText`/`assistantPreviewText` 字段）

### 反冗余
- 复用 `VHoverCard` 与 turn-nav 既有预览管线，不新建第二套 tooltip/预览提取。
- 预览与 label 同源（`turnNavPreviewText`），只多一层剥 markdown；禁止在导航器内再取一次消息文本。

## 时间线信封分隔线

### 功能
对齐 ZCode 轮次信封的三类轻量分隔行，共用同一结构：两侧细发线（hairline）夹一枚 13px 小图标与一句短标签，占位一行、不打断扫读：
- **上下文压缩检查点**：assistant 角色的 `context_compression_marker`（metadata 投影或 status turn item 的 `diagnosticSummary` 两种载体都识别）。按结果分三态——applied 正常样式「上下文已压缩」；skipped_low_savings 更安静样式「压缩未应用 · 收益不足」；failed_preserved 警示样式「压缩失败 · 已保留原上下文」。**永不渲染 token 节省数字**——那是簿记，不是转写。
- **模型切换**：由 `buildConversationModelSwitchBoundaries` 纯派生，挂在开轮 user 行顶部。首个带模型的轮次给 initial「使用 <模型>」，后续换模型给 switch「从 <A> 切换到 <B>」；模型名查 config workspace 的 `modelOptions`，查不到回退原始 modelId；同模型连续轮次不渲染。
- **分叉来源标记**：`isForkedSessionMarkerMessage` 的休眠钩子——后端目前只在 SESSION 级记 `forkedFrom`，从不投影每条消息的标记；一旦投影，消息行顶部出现「已从其他会话分叉」，消息本体照常渲染。

### 适用范围
- **适用**：直连会话时间线（含 codex native transcript 投影），与 cliAgentLifecycle 行同一拦截位（turn 渲染入口最前端）。
- **不适用**：陪伴模式不豁免（压缩/分叉属时间线 chrome，与 lifecycle 行一致照常渲染）；分隔行不承载任何交互，不可点击、不可展开。

### 使用方式
```tsx
// 生产：ConversationView renderTurn 入口（lifecycle 行之后、agentMessage 之前）。
// 压缩：conversationCompressionDividerTone(message) → applied | skipped_low_savings | failed_preserved
<article data-conversation-compression-divider={tone}>
  <span rule /><ChevronsDownUp /><span label={t("compressionDividerApplied")} /><span rule />
</article>
// 模型切换：timelineModelSwitchBoundaries.get(userMessage.id) → initial | switch
<div data-conversation-model-switch-divider={kind}>…<Sparkles|ArrowLeftRight />…</div>
// 分叉：isForkedSessionMarkerMessage(message)
<div data-conversation-fork-marker-divider="true">…<GitFork />…</div>
```

### 非职责
- 不改写 journal、不算模型路由；边界只从已落库消息的 `metadata.llmUsage.llmModelId` 派生。
- 不显示 token 数字、不显示模型推理强度；压缩检查点的后端文本（含节省 token 数）整行丢弃，标签只走 `dictionaryChat`。
- 不做第二套压缩状态卡；上下文用量详情仍由 composer 上下文入口承载。

### 视觉与状态
- 行样式 `turnDividerRow`：flex 居中，两侧 `turnDividerRule` 发线（`--vui-border-subtle` 78% 混合），文字 `--fg-tertiary`、`text-vui-xs`。
- 三态：applied 挂 cool-info；skipped_low_savings 仅 `opacity-60`；failed_preserved 挂 warning 软态并把发线/图标/文字转到 `--state-warning`。
- 模型/分叉行复用同一行样式，不区分 tone；时间戳不渲染（行语义是「边界」不是「事件」）。

### 实现落点
- 源码：`web/src/components/conversation/ConversationView.tsx`（`conversationCompressionDividerTone` / `renderTurn` 信封分隔节点）
- 纯派生：`web/src/components/conversation/conversationModelSwitch.ts`（`buildConversationModelSwitchBoundaries`）
- 判定：`web/src/components/conversation/conversationMessagePredicates.ts`（`isContextCompressionMarkerMessage` / `isForkedSessionMarkerMessage`）
- 样式：`web/src/components/conversation/ConversationView.styles.ts`（`turnDivider*`）
- 文案：`dictionaryChat.compressionDivider*` / `modelSwitch*Label` / `forkedSessionMarkerLabel`

### 反冗余
- 三类分隔行共用一套样式切片，禁止每种各开一份样式。
- 模型标签只读 config workspace 缓存（`queryKeys.configWorkspace()` 共享键），不为时间线单开配置请求通道。
- 压缩检查点不回退到旧「CircleDot 状态格」；状态格保留给真正的运行状态。

## 思考耗时

### 功能
思考单元（codex transcript reasoning 与 agent timeline thought 两处）标题旁的耗时标注，ZCode 语义、纯客户端计时：单元**首次 live 渲染**时记起点；仅当「展开且 live」时每秒跳一次（`思考中 · 8s`）；单元落定冻结为「已思考 · 持续了 8 秒」，不足 1 秒显示「已思考 · 持续了几秒」。历史加载即已落定的单元**不显示时长**——没有服务端时间戳，不编造。

### 适用范围
- **适用**：`renderCodexThoughtScrollCell` 与 `renderThoughtTimelineItem` 两处思考单元标题行。
- **不适用**：进展（progress）单元、工具单元、mental 快照；折叠且从未展开过的 live 单元不渲染标注（起点照记）。

### 使用方式
```tsx
// 生产：思考单元标题行内、标题之后、滚动摘要之前。
<ThoughtDurationLabel
  live={isLive}
  expanded={expanded}
  lastedSecondsTemplate={t("thoughtDurationLastedSeconds")}
  lastedMomentsLabel={t("thoughtDurationLastedMoments")}
/>
```

### 非职责
- 不改思考内容的展开/收起协议；耗时只是标题后的只读标注。
- 不取服务端时间；跨重挂载（整轮落定把行移回虚拟化宿主）不追溯——重挂载后按「历史单元」对待，宁缺勿编。
- 不做分钟换算：秒级读数与 ZCode 对齐，分钟级思考由「已工作 N 分钟」turn work header 承载。

### 视觉与状态
- `thoughtDuration` 样式：`--fg-tertiary`、tabular-nums、带 `·` 分隔；live 读数 `<N>s`，落定走 `thoughtDurationLastedSeconds` / `thoughtDurationLastedMoments` 模板。
- 计时用自续 `setTimeout` 链（禁 `setInterval`，避免打字机缓冲契约误伤），1s 间隔；仅在「展开且 live」时调度。
- `data-thought-duration="live|settled"` 作测试锚点。

### 实现落点
- 源码：`web/src/components/conversation/ConversationView.tsx`（`ThoughtDurationLabel`）
- 样式：`ConversationView.styles.ts` 的 `thoughtDuration`
- 文案：`dictionaryChat.thoughtDurationLastedSeconds` / `thoughtDurationLastedMoments`

### 反冗余
- 两处思考单元共用同一组件与字典键，禁止各写一份计时。
- 不新增第二套「已工作」时长展示；turn 级时长仍归 `ConversationTurnWorkHeader`。

## 流式行内渲染统一（live tail 与 settled 同源）

### 功能
live 尾部段落（流式未落定的最后一段文本）经 `renderConversationInlineMarkdown` 渲染行内富文本：code pill、链接、加粗与 settled 落定管线同一套 classNames 与同一条 inline 管线，流式↔落定切换无「换皮」跳变。该函数原为孤儿模块，本次转正为 live/settled 共用的行内渲染入口。

### 适用范围
- **适用**：`StreamingLiveMarkdownBlocks` 的 live 尾部段落；settled 管线同源的行内 classNames map。
- **不适用**：fenced 代码块头部（`ConversationMarkdownCodeBlock`）；diff 块（`ConversationPatchDiff`）；整段 markdown 的块级解析（各自管线）。

### 非职责
- 不做块级切分与流式缓冲策略；只统一行内片段渲染。
- 不引入第二套流式样式 map；classNames 与落定管线同源，禁止 live 专属配色。

### 实现落点
- 行内渲染入口：`web/src/components/conversation/conversationInlineMarkdown.tsx`（`renderConversationInlineMarkdown`，原孤儿模块转正）
- live 消费方：`web/src/components/conversation/StreamingLiveMarkdownBlocks.tsx`
- settled 管线：`web/src/components/conversation/ConversationMarkdownRenderer.tsx`（classNames 同源）

### 反冗余
- 禁止为 live tail 另开第二套行内渲染或样式 map；新增行内语法只在 `conversationInlineMarkdown` 一处扩展。

## ConversationTurnModelControl

### 功能
composer 工具栏上的「本次发送模型」选择入口（ZCode per-turn modelSelection 语义）：为紧接着的这一次发送选择模型，不改会话默认。默认显示会话当前模型（跟随会话切换）；用户改选后粘性保持到再改；非会话默认时触发高亮 chip（accent 环 + 圆点）作为「≠会话默认」视觉标记；菜单第一行「跟随会话默认」一键恢复跟随。

### 适用范围
- **适用**：普通会话 composer 的工具栏尾部（推理强度控件旁）；仅当会话 llm-options 返回 `choices` 时渲染。
- **不适用**：会话级默认模型/推理强度切换（`ConversationInferenceControl` + Agent 管理模型绑定）；虚拟人 Companion 模式（不渲染）。

| 场景 | 选择 |
| --- | --- |
| 只想这一轮换模型 | `ConversationTurnModelControl` |
| 改会话默认模型 | Agent 管理（`AgentModelPicker`） |
| 改会话默认推理强度 | `ConversationInferenceControl` |

### 使用方式
```tsx
import { ConversationTurnModelControl } from "../../conversation/ConversationTurnModelControl";

<ConversationTurnModelControl
  choices={sessionLlmOptions.choices}
  sessionDefaultModelId={sessionLlmOptions.currentModelId}
  selection={turnModelSelection}
  disabled={composerDisabled}
  onSelectionChange={setTurnModelSelection}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| choices | llm-options 的完整可选模型列表 | 只读展示，不做发现/添加 |
| sessionDefaultModelId | 会话当前模型（modelRef 优先） | 跟随会话切换；菜单内标注「会话默认」 |
| selection | 粘性覆盖；null = 跟随会话 | 压在同一模型上不显示覆盖标记 |
| onSelectionChange(null) | 恢复跟随会话 | 必须可达，不允许粘死 |

### 非职责
- 不发送消息；覆盖值随下一次提交走 `POST /messages` 的 `modelSelection`，排队轮由后端队列行持久化。
- 不改 Agent 绑定、会话默认模型或推理强度默认值。

### 视觉与状态
- 默认态与推理强度控件同字号同灰阶；覆盖态用 `--accent-cool` 混色底 + 细环 + 圆点，禁止原始十六进制色。
- 菜单：首行「跟随会话默认」；模型按 llm-options 顺序列出（provider 副标题、会话默认/未配置 Key 徽标）；选中覆盖模型后其推理强度子区（跟随会话强度 + 该模型 effort 选项）出现在菜单底部。
- 禁止把覆盖状态写成第二套配色体系；一切标记走 token。

### 实现落点
- 源码：`web/src/components/conversation/ConversationTurnModelControl.tsx`
- 样式：`ConversationTurnModelControl.styles.ts`
- 类型：`web/src/api/types/chat.ts` 的 `SessionModelSelection`；提交通道 `useChatComposerSubmit`（`SubmitTurnVariables.modelSelection`）

### 反冗余
- 不复制 `AgentModelPicker`（发现/添加模型、槽位兼容）能力；这里只消费 llm-options 的 `choices`。
- 不与 `ConversationInferenceControl` 合并：一个管会话默认（强度），一个管单轮覆盖（模型+可选强度），语义不同。
## ConversationTurnNavigator

### 功能
对话内容区左侧的轮次导航，不创建第二份会话记录。12×2 短横线在悬停或聚焦时伸长，邻近两项渐变；减少动态效果偏好下不播放过渡。

### 适用范围
- 六轮及以上的会话；对话容器宽度达到 864px 时显示。
- 窄屏隐藏且不额外占用左侧空间；右侧仍为“回到最新”按钮保留安全间距。
- 不用于会话列表、消息编辑或会话数据持久化。

### 使用方式
传入既有轮次目录 `entries`、当前轮次 `currentIndex`、本地化 `ariaLabel` 与既有 `onNavigate`。密集的 36×18 命中区使用 `VNativeButton`；`VHoverCard` 向右显示两行问题和三行回答。无摘要的项不挂空浮卡。

### 实现与边界
React Virtual 限制挂载数量；当前位置变化和容器恢复时滚动到当前标记。原有时间线跳转、减少动态效果滚动、消息投影及会话数据保持不变。
