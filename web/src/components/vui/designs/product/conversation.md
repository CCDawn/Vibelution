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

## ChatComposerPlusMenu

### 功能
桌面端 Chat composer 的统一扩展入口。一级为紧凑纵向聚类列表，悬停或点击后只在右侧展开一个二级面板；不允许三级菜单。

### 信息架构
- `添加与引用`：图片附件、会话引用。
- `对话能力`：心智模型、运行状态注入，以可切换状态直接展示。
- `会话与陪伴`：直接会话、投喂、聊天、关怀。
- `群聊与团队`：群聊管理、打开团队。

### 边界
- 斜杠指令仍由输入框内联建议负责，不进入加号菜单。
- 模型、权限、上下文用量、发送/停止仍位于 composer 工具栏。
- 缓存状态不在加号菜单或右栏展示；上下文详情仍由独立工具栏入口承载。
- 仅定义桌面交互，不增加手机端变体。
- 复用 `VPopover`、`VButton`、`VDialog`、`VNativeInput`，不新增第二套 primitive。

## ChatGroupManagementDialog

### 功能
承接从右栏迁出的群聊管理动作，保留群名、调度模式、对话目的、成员、应用、重置与删除能力。

### 边界
- 由 `ChatComposerPlusMenu` 的二级菜单直接打开，不再经过第三级菜单。
- 右栏仅保留群资料与状态，只读展示不承载管理按钮。
- 团队关联群聊仍由团队页维护成员和角色。
