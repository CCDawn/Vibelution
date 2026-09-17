# VSessionSearchDialog · 会话全量搜索面

> 产品面：workbench-shell
> 组件：`src/components/vui/product/workbench-shell/VSessionSearchDialog.tsx`
> 上线批次：会话目录规模化收口（后端分页 + 全部会话搜索升级）

## VSessionSearchDialog

### 功能

把「全部会话」从最近几条的本地过滤弹窗升级为可当目录用的搜索面：顶部搜索框
（服务端 q：标题 + 摘要/最后消息预览 + 会话号 + Agent 身份字段）、Agent/团队
过滤槽位、服务端分页结果列表（键盘 ↑/↓/Enter、命中词高亮、已加载 N/M、加载更多）。
用户按标题或话题片段找到任意历史会话并直接打开。

### 入口

- 挂载面是左侧会话栏头部（`data-vui="session-catalog-entry"` 图标按钮，标签「全部会话」），
  点击打开本弹窗；会话 Tag 行只保留 标签 +「新建会话」，不再承载目录入口。
- 与 `Ctrl+K` 的分工：`Ctrl+K` 仍是会话栏内的 `VCommandPalette`（本地导航/动作）；
  目录弹窗提供跨 Agent 的服务端分页搜索与 Agent/团队过滤。

### 适用范围

- **适用**：结果集来自服务端分页查询（`/api/sessions/query` 的 `q`/`agentId`/
  `teamId`）的会话目录搜索；挂载面负责防抖、请求、翻页与打开后果。
- **不适用**（改用 `VCommandPalette`）：纯客户端内存数据的命令/导航面板——
  数据已全在本地、需要 fuzzy 打分与动作分组时不要用本组件硬套。

| 场景 | 选择 |
| --- | --- |
| 会话目录按标题/摘要找历史会话（结果分页在服务端） | 用本组件 |
| Ctrl+K 导航/动作/本地检索（数据全在客户端） | 改用 `VCommandPalette` |
| 表单里选一个会话引用 | 改用既有选择器，不弹目录 |

### 使用方式

```tsx
// 最小可运行示例（真实 import 路径以 index 为准）
import { VSessionSearchDialog, type VSessionSearchDialogItem } from "@/components/vui";

<VSessionSearchDialog
  open={open}
  onOpenChange={setOpen}
  query={query}                       // 受控：挂载面防抖后发起 querySessions
  onQueryChange={setQuery}
  filters={<>…Agent/团队 VSelect…</>} // 可选过滤槽位
  items={sessionSearchItems}          // VSessionSearchDialogItem[]
  hasMore={hasMore}
  loadingMore={isLoadingMore}
  onLoadMore={fetchNextPage}
  totalEstimate={totalEstimate}
  labels={{
    searchPlaceholder: "搜索标题、摘要或会话编号",
    emptyTitle: "没有匹配的会话",
    emptyHint: "换个关键词，或清空过滤条件",
    loadMore: "加载更多",
    loadingMore: "加载中…",
    resultSummary: (loaded, total) => `已加载 ${loaded} / ${total} 个会话`,
    hint: "↑↓ 选择 · Enter 打开 · Esc 关闭",
  }}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| `query` / `onQueryChange` | 受控搜索词 | 组件不防抖、不发请求；挂载面负责 |
| `filters` | 过滤控件槽位 | 只放 VUI 表单控件（如 `VSelect`） |
| `items` | `VSessionSearchDialogItem[]` | `title`/`detail` 会被 `highlight` 高亮 |
| `hasMore` / `onLoadMore` / `loadingMore` | 分页三件套 | 尾部自动出现「加载更多」 |
| `totalEstimate` | 服务端总数估计 | 配合 `resultSummary` 显示已加载/总数 |
| `labels` | 全部文案 | zh/en 由挂载面按语言注入 |

### 非职责

- 不发请求、不持有业务数据、不管理过滤状态（受控 `query` + 数据驱动 items）。
- 不做消息内容全文检索（后端 q 口径 = 标题 + 摘要/预览 + 身份字段）。
- 不承载多步向导或二级页面；打开会话即关闭面板并执行回调。

### 视觉与状态

- 行三段：标题（高亮）+ 摘要预览（截断、高亮）+ meta（Agent · 状态 · 时间）。
- 键盘：↑/↓ 移动高亮，Enter 打开；hover 同步高亮行。
- 空态 `VStateSurface tone="empty"`，加载态 `tone="loading"`；总数与已加载数
  常驻底部摘要行。

### 实现落点

- 源码：`web/src/components/vui/product/workbench-shell/VSessionSearchDialog.tsx`
- 挂载面：`web/src/routes/chat/ChatConversationIndexRail.tsx`（头部图标 + 弹窗宿主 +
  `useSessionSearchQuery` 防抖/分页）
- Renderer：无自有 renderer；组合 `VDialog` + `VInput` + `VNativeButton` +
  `VStateSurface`。

### 反冗余

- 与 `VCommandPalette` 的边界：本地过滤 + 动作分组 → CommandPalette；服务端
  分页 + 过滤槽位 + 总数摘要 → 本组件。禁止把 CommandPalette 改造成发请求的
  搜索面，也禁止在 route 层手搓第二套搜索弹窗。
