# Planned recipes（未实现）

> 仅登记意图，**实现前**必须把专节补全到与现成 recipe 同级详细度（含 **功能 / 适用范围 / 使用方式**），并更新 INDEX「拟新增」状态。
> 原则：能复用现有 recipe **禁止**落地本节组件。

## VSessionWorkbenchPage

### 功能
Chat 会话工作台：状态轨 + 主会话 + 可选工具轨；响应式 overlay。

### 适用范围
- **适用**：Chat 双轨会话壳（确认 list-detail + domain 槽不够之后）。
- **不适用**：通用主从页 → `VListDetailPage`；运维表 → `VDenseOpsPage`。

| 场景 | 选择 |
| --- | --- |
| Chat 会话工作台 | 本组件（拟） |
| Skills 主从 | `VListDetailPage` |

### 使用方式
```tsx
// 拟 API（实现前可调）
<VSessionWorkbenchPage
  ariaLabel="会话"
  statusRail={...}
  session={...}
  toolRail={...}
  domainRecipe="chat-session-workbench"
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| statusRail / session / toolRail | 三区 | 宽度走 chat layoutId |
| 响应式 overlay | 小屏侧栏 | 勿再手写第二套 shell |

### 非职责
- 不替代通用 list-detail。

### 为何暂缓（2026-08 复核）
- Chat 已有 `data-vui-recipe="chat-session-workbench"` + `WORKBENCH_LAYOUT_IDS.chat`（`chat/ChatCodingRouteWorkbench.tsx`）。
- 双写宽度（`shellStore` ↔ `pane-layouts.v1`）与响应式 overlay 仍是 domain 例外；`VListDetailPage` / `VTrackWorkbenchPage` **不能**直接替换。
- **下一实现门槛**：先把双轨几何收成单一 hook/composer 输出，再让本 recipe 只包 `statusRail | session | toolRail` 槽，禁止再扩大 ChatCodingRouteWorkbench 行数。

### 反冗余
- 落地后 Chat 禁止再手写顶层 shell。
- 在门槛未达成前，禁止平行 `VChatPage` / 第三种 session shell。

---

## VTrackWorkbenchPage

> **已实现** — 设计专节见 [pages.md#vtrackworkbenchpage](./pages.md#vtrackworkbenchpage)。本节仅保留迁移备注。

### 功能
（见 pages.md）多 track 工作台 recipe。

### 适用范围
（见 pages.md）

### 使用方式
（见 pages.md）

### 迁移备注
- 路由应从裸 `VWorkbenchPage` + 手写 `VRouteHeader` 迁到本 recipe。
- multi-rail 仍属 domain 例外，不内建进 recipe。

---

## VFilterListDetailPage

### 功能
筛选轨 + 列表 + 详情三列主从页。

### 适用范围
- **适用**：Agents 等明确三列筛选主从，且 list 槽塞筛选证伪之后。
- **不适用**：两列主从 → `VListDetailPage`（筛选放 list 槽）。

| 场景 | 选择 |
| --- | --- |
| 确认需要独立 filter 列 | 本组件（拟） |
| 筛选可放在 list 顶 | `VListDetailPage` |

### 使用方式
```tsx
// 拟
<VFilterListDetailPage
  filter={<FilterRail />}
  list={<List />}
  detail={<Detail />}
  layoutId={...}
/>
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| filter / list / detail | 三列 | 宽度 registry layoutId |

### 为何暂缓
- 先把筛选放进 `VListDetailPage` 的 `list` 槽。

### 反冗余
- 仅当第二消费者出现或 list 槽证伪后再建。
