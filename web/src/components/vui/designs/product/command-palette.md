# VCommandPalette · 命令面板

> 产品面：workbench-shell
> 组件：`src/components/vui/product/workbench-shell/VCommandPalette.tsx`
> 上线批次：CC-UX 第三轮 B10（Linear / VS Code 命令面板模式）

## VCommandPalette

### 功能

一个快捷键呼出的可搜索命令面：导航（去哪）、动作（做什么）、检索（找什么）。
`Ctrl/Cmd+K` 开，`Esc` 关，`↑/↓` 移动高亮，`Enter` 执行。匹配策略：子串优先
（越靠前分越高），子序列 fuzzy 兜底；空查询保持传入顺序。

### 适用范围

对象规模让「侧栏 → 列表 → 滚动」成为高频成本的工作台：挑战杯 125 题 × 9 候选
≈ 1125 条假说、数百场会议。当前唯一挂载面是科研流程工作台；其他 surface 需要
命令/检索入口时复用。不适合承载二级页面或多步向导。

### 使用方式

```tsx
<VCommandPalette
  open={paletteOpen}
  onOpenChange={setPaletteOpen}
  items={paletteItems}          // 数据驱动：surface 组装条目并承担执行后果
  labels={{ searchPlaceholder: "搜索题目或命令…", emptyTitle: "没有匹配项", hint: "↑↓ 选择 · Enter 执行 · Esc 关闭" }}
/>
```

条目 `VCommandPaletteItem`：`id` 唯一、`group` 分组标题、`label` 主行、
`detail` 次行（题面/状态）、`keywords` 参与匹配、`onRun` 执行回调（面板先关闭再执行）。
组件不持有业务数据、不发请求；每次打开清空查询并重置高亮。

一个快捷键呼出的可搜索操作面：当应用的对象规模（125 题 × 9 候选、数百场会议）
让「侧栏 → 列表 → 滚动」的三段导航成为高频成本时，用命令面板承载
**导航（去哪）+ 动作（做什么）+ 检索（找什么）**。用户记概念不记按键。

## 形态

- `Ctrl+K`（macOS `Meta+K`）打开；`Esc` 关闭；`↑/↓` 移动高亮；`Enter` 执行。
- 顶部 `VInput` 搜索框（自动聚焦）+ 分组列表（组标题 = `group` 字段）+
  底部一行快捷键提示。
- 匹配：先子串（越靠前分越高），后子序列（fuzzy 兜底）；空查询保持传入顺序。
- 行两行式：主标签 + 可选 detail（如题号下的英文题面），悬停即高亮。
- 宽度 `min(560px, 92vw)`，列表最大 `46vh` 内滚动，`scrollIntoView` 跟随键盘。

## 边界与纪律

- **数据驱动**：组件只接收 `items` 与回调，不持有业务数据、不发请求；
  由挂载面（如科研工作台）组装条目并承担执行后果。
- 每次执行先关面板再跑 `onRun`，防止动作弹窗与面板焦点竞争。
- 打开时清空查询、重置高亮；不在面板内做二级页面。

## 挂载面示例

科研工作台（`ResearchProcessWorkspace`）：

- 分组「命令」：前往当前任务、打开成员与讨论、切换到题目…
- 分组「题目」：`SCI-001 · What makes prime numbers so special?`（keywords 含题号+题面+学科）。
