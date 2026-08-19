# Product — Agent management

> 领域组合层：只服务 Agent 工作台。
> **禁止**在此重新实现按钮/输入；必须组合 VUI primitives。
> 设计选型同样先读 **功能 / 适用范围 / 使用方式**。

## AgentPageHeader

### 功能
Agent 管理页顶栏：创建、刷新等域操作入口。

### 适用范围
- **适用**：Agents 管理页顶栏动作区。
- **不适用**：全局 app shell 导航；通用路由标题 → `VRouteHeader`。

| 场景 | 选择 |
| --- | --- |
| Agent 页创建/刷新 | `AgentPageHeader` |
| 通用页标题 | `VRouteHeader` |

### 使用方式
```tsx
import { AgentPageHeader } from "@/components/vui/...";

<AgentPageHeader onCreate={...} onRefresh={...} />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| eyebrow / title | 页面识别 | eyebrow 与 title 语义重复时只显示 title |
| 创建 / 刷新回调 | 域动作 | 按钮用 `VButton` |

### 非职责
- 不做全局 shell 导航。

### 反冗余
- 不替代 `VRouteHeader` 成为全站顶栏。

---

## AgentFilterRail

### 功能
Agent 筛选侧轨：搜索 + 分组过滤器。

### 适用范围
- **适用**：Agents 列表左栏筛选。
- **不适用**：通用筛选轨（第二消费者出现前勿抽空 `VFilterRail`）。

| 场景 | 选择 |
| --- | --- |
| Agent 筛选 | `AgentFilterRail` |
| 通用 filter | 暂用 list 槽自组合 |

### 使用方式
```tsx
<AgentFilterRail query={q} onQueryChange={setQ} groups={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| query / groups | 搜索与分组 | 输入用 `VNativeInput`/`VInput`；默认计数与选中态使用中性色 |

### 反冗余
- 第二消费者出现前禁止空抽通用 FilterRail。

---

## AgentDenseList

### 功能
Agent 密集列表/表，展示与选择 Agent 实体。

### 适用范围
- **适用**：Agents 主列表。
- **不适用**：通用实体列表 → `VEntityList`；运维表 → `VDenseTable`。

| 场景 | 选择 |
| --- | --- |
| Agent 列表 | `AgentDenseList` |
| 通用列表 | `VEntityList` |

### 使用方式
```tsx
<AgentDenseList items={agents} selectedId={id} onSelect={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| columns / rows | 数据与选中 | 默认只显示名称、角色与异常状态；头像、角色、计数保持中性，只有 warning / error 使用语义色 |
| bulkSelectionVisible | 批量选择入口状态 | 普通浏览时隐藏行复选框；用户显式进入批量选择后才显示，避免主列表长期被第二套选择层级占据 |

---

## AgentBulkActionBar

### 功能
Agent 批量操作条（多选后的操作带）。

### 适用范围
- **适用**：Agent 多选后的批量动作。
- **不适用**：单条行内操作；通用 toolbar → `VToolbar`。

| 场景 | 选择 |
| --- | --- |
| 批量启用/删除 | `AgentBulkActionBar` |
| 页级工具条 | `VToolbar` |

### 使用方式
```tsx
<AgentBulkActionBar selectedCount={n} onClear={...} actions={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| selectedCount / actions | 计数与操作 | 危险操作用 danger |

---

## AgentSummaryStrip

### 功能
Agent 汇总指标条。

### 适用范围
- **适用**：Agent 页摘要数字。
- **不适用**：通用指标 → 直接 `VMetricStrip`。

| 场景 | 选择 |
| --- | --- |
| Agent 汇总 | `AgentSummaryStrip` |
| 通用指标 | `VMetricStrip` |

### 使用方式
```tsx
<AgentSummaryStrip metrics={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| metrics | 汇总项 | 组合 MetricStrip 思路 |

### 反冗余
- 不要平行 SummaryBar。

---

## AgentWorkspacePanel

### 功能
Agent 三区工作台组合（filter + list + detail 编排容器）。

### 适用范围
- **适用**：Agents 工作台历史组合壳。
- **不适用**：新壳优先 `VListDetailPage` slots；本组件可缩为 slot 内容。

| 场景 | 选择 |
| --- | --- |
| 新主从页 | `VListDetailPage` |
| 既有 Agent 槽内容 | 本组件内容块 |

### 使用方式
```tsx
// 优先：
<VListDetailPage list={<AgentFilter+List />} detail={<Detail />} layoutId={...} />
```

| Prop / 槽位 | 说明 | 设计注意 |
| --- | --- | --- |
| filter / list / detail | 三区 | 迁移中逐步让位 recipe |

### 正式 Agents 页面编排约定

- 桌面端保持目录 + 详情的可调分栏；检查器默认关闭，只在用户显式打开后占用第三层信息空间。
- `680px` 及以下改为 master-detail：目录与详情各自全宽，选择 Agent 后进入详情，详情顶部提供返回目录；带 `?agent=` 的深链接直接进入详情。
- 窄屏检查器使用右侧覆盖层，不能再次压缩详情栏；关闭检查器后保留当前 Agent 与页签状态。
- 详情只保留“总览 / 配置 / 运行”三个主签。总览组合 `VMetricStrip`、`VSurface`、`VStatusChip`，展示最多 8 项有效配置、6 条活动和 6 项关注点；运行数据必须来自正式查询，禁止用演示数字填空。
- 身份、团队、24 小时运行健康与待审批放在总览侧列；完整编辑表单、草稿版本和运行策略分别留在“配置”“运行”，避免同一信息在多个主签重复。

---

## AgentPermissionPresetControl

### 功能
权限预设选择控件（对话/编码权限档位）。

### 适用范围
- **适用**：Composer / Agent 权限预设切换。
- **不适用**：权限引擎/策略存储。

| 场景 | 选择 |
| --- | --- |
| 权限档位 UI | `AgentPermissionPresetControl` |
| 策略后端 | 服务层，非本组件 |

### 使用方式
```tsx
<AgentPermissionPresetControl value={preset} onChange={setPreset} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| value / onChange | 预设枚举 | 浮层用 VPopover 族 |

### 非职责
- 不做权限引擎。
