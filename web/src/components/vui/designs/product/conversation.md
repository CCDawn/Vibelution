# Product — conversation

> 对话工作台组合层：只服务 Chat composer / 时间线。
> **禁止**在此重新实现按钮/输入；必须组合 VUI primitives。

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
