# Conversation Starter Cards — 空会话引导

> 会话空态的两个引导元素：起点卡与内置斜杠命令。二者都由 `ConversationView` 用现有 `V*` 原语组合实现，不新增独立 V* 组件。

## 会话起点卡

### 功能
空会话（无任何消息）时，在 `VStateSurface` 下方提供 2–3 张可点击的起点卡；点击把该起点填入 composer 并聚焦，供用户编辑后自行发送（不自动发送）。

### 适用范围
- **适用**：会话 transcript 为空、composer 可用的空态引导；数据源优先后端 `composer-example` 的 `starters`（heading+command），无后端数据时回落到字典层的通用科研起点。
- **不适用**（改用 `…`）：非空会话的续写建议改用 ghost placeholder（`resolveComposerPlaceholder`）；表单类结构化输入改用 `VFieldRow`；命令式快捷动作改用 `VCommandPalette`。

| 场景 | 选择 |
| --- | --- |
| 空会话需要可点第一步 | 用本模式 |
| 有消息后的下一步建议 | 改用 ghost placeholder |
| 全局命令面板 | 改用 `VCommandPalette` |

### 使用方式
```tsx
// ConversationView 空态分支内（数据链路：/api/sessions/:id/composer-example）
import { VButton } from "@/components/vui";

<VButton contentLayout="plain" className={styles.emptyStateStarterCard} onPress={() => fill(starter.command)}>
  <span className={styles.emptyStateStarterCardHeading}>{starter.heading}</span>
  <span className={styles.emptyStateStarterCardCommand}>{starter.command}</span>
</VButton>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `heading` | 卡片主题（后端模板标题或字典兜底） | 为空时仅渲染命令行 |
| `command` | 填入 composer 的完整句子 | 每张卡命令必须互不相同 |
| `onPress` | 填入 composer + 聚焦 | 禁止自动提交（业界共识：自动发送令用户反感） |

### 非职责
- 不做发送、不做轮播、不做个性化推荐算法。
- 不承担会话列表/历史职责。

### 视觉与状态
- 默认：panel 底、subtle 边框；hover：accent 边框 + muted 底；focus：2px accent outline。
- 3 列网格（窄屏降为 1 列），仅在 `messages.length === 0 && !composerDisabled` 时渲染。

### 实现落点
- 源码：`web/src/components/conversation/ConversationView.tsx`（空态分支 `conversation-starter-cards`）
- 数据：`core/web/services/session/composer_example_commands.py` → `web/src/components/conversation/useComposerPromptSuggestion.ts`

### 反冗余
- 与 `VStateSurface` 的边界：VStateSurface 只负责“空”的陈述，起点卡负责“下一步”。
- 禁止再新建平行的空态卡组件；样式只允许扩展 `ConversationView.styles.ts` 的 `emptyStateStarter*` 类。

## 内置斜杠命令

### 功能
在 slash suggestion listbox 中把客户端内置命令（/新会话、/模型、/压缩）排在 skills 之前合并展示；行尾“内置”徽标与图标区分于 skill 命令。回车/Tab/点击直接执行动作，skill 命令仍是补全插入。

### 适用范围
- **适用**：composer 草稿以 `/` 开头时的建议列表；仅当对应通道存在时才出现（`onCreateSession` / `llmControl` / `onOpenComposerContextDetail`）。
- **不适用**（改用 `…`）：需要后端协议的 skill 命令（走 `SkillLibraryItem`）；全局快捷键改用 `VCommandPalette`。

| 场景 | 选择 |
| --- | --- |
| 会话内新建/模型菜单/上下文详情快捷入口 | 用本模式 |
| 注入技能/提示词模板 | 改用 skill 命令（后端协议） |

### 使用方式
```tsx
// 合并建议（builtins 排前）+ 内置徽标
const suggestions = mergeSlashCommandSuggestions(builtins, skills, draft);

<span className={styles.slashCommandBuiltinBadge}>{t("slashBuiltinBadge")}</span>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `id` | `new_session` / `model` / `compress_context` | 决定图标与执行通道 |
| `command` | 展示用主命令（随语言本地化） | 别名（`aliases`）只参与过滤 |
| `description` | 一句话说明走什么 | 与 skill 描述同一排版槽位 |

### 非职责
- 不改后端 slash 协议；不新增第二套命令解析器。
- 执行失败的路由级反馈不属于本模式（通道方自行处理）。

### 视觉与状态
- 行结构：图标（仅 builtin）+ 命令 code + 描述 + 「内置」徽标（`ml-auto`）。
- 键盘：↑/↓ 循环高亮、Enter/Tab 执行高亮项（IME 组合中不抢 Enter）、Escape 关闭（继续输入即恢复）；`aria-activedescendant` 同步高亮行。

### 实现落点
- 源码：`web/src/components/conversation/conversationSlashCommandSuggestions.ts`（合并/过滤/循环索引）
- 渲染：`web/src/components/conversation/ConversationView.tsx`（`slash-builtin-badge`、listbox 键盘导航）

### 反冗余
- 与 skill suggestion 的边界：同一 listbox、同一过滤管线，builtin 只加前置行与徽标。
- 禁止绕开 `mergeSlashCommandSuggestions` 自行拼接列表；禁止为徽标新建独立组件。
