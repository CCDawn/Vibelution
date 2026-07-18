# Workbench UI 抛光与 shadcn 可重构路径

日期：2026-07-18
状态：已对齐并执行 Wave 1
任务等级：`STANDARD_TASK`
策略代号：**Path B**

## 1. 已确认决策

| 决策 | 选择 |
| --- | --- |
| 视觉方向 | Light-first 安静运营工作台（延续 `2026-06-26-frontend-style-system-design.md`） |
| 库策略 | **保留 VUI 为页面唯一 API**；底层 renderer 可逐步 shadcn/Radix 化 |
| 第一波优先级 | **布局与空间利用 > 控件尺度统一 > 配色抛光** |
| 样板页 | **Chat 工作台 + Agents 管理** |
| 与 Codex Tooltip 会话 | 布局/视觉由本任务负责；文案收纳会话继续 Tooltip；重叠文件避让 |
| 非目标 | 不整仓删除 VUI；页面不直接 import shadcn；不改 API/Agent 行为 |

## 2. 产品句

**半透明控制台铺在背景上：轻、细、准、密，主工作区吃满空间，说明进 hover。**

## 3. 界面契约（实施必须遵守）

### 3.1 分层边界（后续易重构的关键）

```text
Route / Product  →  只编排业务与数据
VUI API          →  唯一 UI 契约（VButton / VPanel / VSplitWorkspace …）
Renderer+tokens  →  唯一视觉实现（今日 HeroUI，可换 shadcn/Radix）
```

**禁止：**

- 业务 route 直接 `import` `@heroui/react` 或 `@/components/ui/*`（shadcn）
- 在 route 内发明第二套 button/card/shadow 语言
- 为“好看”在业务里硬编码 hex（应用 token）

**允许：**

- route 级布局 class（grid/列宽/响应式断点）在迁移期存在，但须可收敛到 VUI layout
- `components/vui/renderers/shadcn/**` 未来新增，不暴露给 route

### 3.2 布局规则

| 规则 | 要求 |
| --- | --- |
| 主区吃满 | 主工作区使用 `minmax(0,1fr)`；禁止无意义大留白成为默认 |
| Master-detail | 列表/筛选 + 详情；宽屏双栏，窄屏单栏堆叠 |
| 侧栏宽度 | Agents 列表侧可随视口略增，不得锁死过窄导致详情“发空” |
| 详情内分区 | 宽屏 overview 主栏+侧栏；config 多卡片在宽屏可并排填宽 |
| Chat | 会话索引 + 对话主区 + 可选状态轨；状态轨折叠时主区立刻扩张 |
| 空状态 | 在详情面板内居中，占满可用高度语义，而不是左上角小条 |

### 3.3 控件阶梯

| 类型 | 高度 token | 宽度行为 |
| --- | --- | --- |
| 紧凑操作 / 工具条 | `--vui-control-height-sm`（compact） | `w-fit`，禁止无故 `w-full` |
| 表单主操作 | `--vui-control-height-md`（normal） | 行内右对齐簇，或明确 full-width 表单底栏 |
| 图标按钮 | 正方形 sm 高度 | 必须有 accessible name + Tooltip |

同一操作区最多一个 soft primary。危险动作默认安静，确认面再强调。

### 3.4 文案与错误

- 非常驻说明：`VTooltip` / `VContextualHint`，首屏不堆说明书。
- 错误：**一行高价值摘要** + 可展开详情；长文本必须 `overflow-wrap: anywhere`，禁止横向撑破。
- 状态栏只放状态/短码/入口，不重复对话正文错误全文（与 Codex 对齐设计一致）。

### 3.5 主题与验收

- 新抛光以 **light** 为第一验收面；dark 保持可用。
- 验收关键词：light / thin / precise / dense / background-integrated / **no dead whitespace**。

## 4. Wave 计划

| Wave | 内容 | 完成证据 |
| --- | --- | --- |
| **0** | 本契约 | 文档合入 |
| **1** | Agents 工作区列宽/详情填满；config 宽屏并排；空状态；Chat gutter/密度 | 布局测试 + build；浏览器可选 |
| **2** | 补 VUI 布局原语缺口；错误摘要组件 | 组件测试 |
| **3** | Teams/Memory/Config 同构 | 分批 |
| **R** | HeroUI → shadcn renderer（按 primitive） | 单组件替换 + 视觉回归 |

## 5. 后续 shadcn 重构检查清单

换 renderer 前全部应为 **true**：

1. 页面零 `@heroui` / 零 `@/components/ui` 直接依赖
2. 目标 primitive 有稳定 props（variant/density/disabledReason/tooltip）
3. 视觉只来自 token 与 renderer class，不依赖 route 复制的 Hero 类名
4. 有 focused 组件测试 + 样板页 layout 契约测试
5. 一次只换一个 primitive（先 Button → Tooltip → Input → Select）
6. 不并行大改业务布局与 renderer 替换

## 6. Wave 1 文件范围

- `docs/superpowers/specs/2026-07-18-workbench-ui-polish-shadcn-path-design.md`（本文件）
- `web/src/routes/AgentWorkspaceLayoutPanel.styles.ts`
- `web/src/routes/AgentSelectedDetailContentPanel.styles.ts`
- `web/src/routes/AgentEmptySelectionPanel.styles.ts`
- `web/src/routes/ChatCodingRoute.styles.ts`（仅 layout 密度 token）
- 对应 layout 契约测试断言
- `web/src/components/vui/layout/VWorkbenchPage.tsx`（默认列宽 token）
- `web/src/design/tokens.css`（workspace 语义 token，additive）

**明确不改：**

- `ConversationView.styles.ts`（active claim：`codex-chat-message-column-alignment`）
- 业务 API、mutation、会话协议

## 7. 验证

- `npm --prefix web run test --` 聚焦 Agents/Chat layout 与 VUI foundation 相关测试
- `npm --prefix web run build`
- Launcher 刷新：样板布局变更后 **recommended before user testing**

## 8. 版本影响

- 用户可见布局/密度变化 → 合入 main 后由版本负责人判断 patch；本任务 Agent **不**直接改 `VERSION`。
