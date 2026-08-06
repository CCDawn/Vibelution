# Planned recipes（未实现）

> 仅登记意图，**实现前**必须把专节补全到与现成 recipe 同级详细度（含 **功能 / 适用范围 / 使用方式**），并更新 INDEX「拟新增」状态。
> 原则：能复用现有 recipe **禁止**落地本节组件。

## VSessionWorkbenchPage

> **已实现** — 设计专节见 [pages.md#vsessionworkbenchpage](./pages.md#vsessionworkbenchpage)。

### 功能
（见 pages.md）会话工作台 recipe。

### 适用范围
（见 pages.md）

### 使用方式
（见 pages.md）

### 迁移备注
- Chat 经 `ChatSessionWorkbenchShell` 适配槽位名（`center` → `session`，`conversationIndex` → `indexRail`）。
- 双写宽度 / 响应式仍属 `useChatWorkbenchLayout`。

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
