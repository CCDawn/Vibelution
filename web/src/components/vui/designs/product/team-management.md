# Product — Team management

> 科研/资料搜集等团队域组合件。
> 阶段卡、结果列表等 **不是** 通用 kanban；通用壳用 Board recipe。
> 设计选型先读 **功能 / 适用范围 / 使用方式**。

## TeamStageCard

### 功能
阶段卡片展示（tone + 内容），表达流水线中的某一阶段。

### 适用范围
- **适用**：阶段 pipeline 中的阶段语义卡。
- **不适用**：总览看板列 → `ResearchBoardKanban` / Board recipe。

| 场景 | 选择 |
| --- | --- |
| 阶段 pipeline | `TeamStageCard` |
| 看板列 | Board 域 kanban |

### 使用方式
```tsx
<TeamStageCard tone="active" title="搜集" meta="3 项" />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone / title / meta | 状态与标题 | 组合 VSurface 视觉 |

### 反冗余
- 不与通用 kanban 卡平行扩张。

---

## TeamStageCommandBar

### 功能
阶段命令/统计条，承载阶段级操作与计数。

### 适用范围
- **适用**：团队阶段视图命令带。
- **不适用**：通用页工具条 → `VToolbar`/`VDenseToolbar`。

| 场景 | 选择 |
| --- | --- |
| 阶段命令 | `TeamStageCommandBar` |
| 页级工具条 | `VToolbar` |

### 使用方式
```tsx
<TeamStageCommandBar stats={...} actions={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| stats / actions | 统计与按钮 | 按钮必须 VButton |

---

## TeamStagePipeline

### 功能
阶段流水线布局容器，横向/纵向排列阶段卡。

### 适用范围
- **适用**：多阶段流程展示。
- **不适用**：自由画布 → `VCanvasWorkbenchPage`。

| 场景 | 选择 |
| --- | --- |
| 阶段流水线 | `TeamStagePipeline` |
| 流程图画布 | Canvas recipe |

### 使用方式
```tsx
<TeamStagePipeline>
  <TeamStageCard ... />
  <TeamStageCard ... />
</TeamStagePipeline>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children | 阶段卡 | 顺序即流程 |

---

## TeamSourceFilterBar

### 功能
资料结果过滤条（关键词/状态等）。

### 适用范围
- **适用**：团队资料搜集结果过滤。
- **不适用**：通用 Agent 筛选 → `AgentFilterRail`。

| 场景 | 选择 |
| --- | --- |
| 资料过滤 | `TeamSourceFilterBar` |
| Agent 过滤 | `AgentFilterRail` |

### 使用方式
```tsx
<TeamSourceFilterBar query={q} onQueryChange={setQ} status={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| query / status | 过滤条件 | 控件 V* |

---

## TeamSourcePagination

### 功能
资料列表分页控件。

### 适用范围
- **适用**：资料结果分页。
- **不适用**：无限滚动列表（另案）。

| 场景 | 选择 |
| --- | --- |
| 分页 | `TeamSourcePagination` |

### 使用方式
```tsx
<TeamSourcePagination page={page} total={total} onPageChange={setPage} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| page / total / onPageChange | 分页态 | 禁用越界 |

---

## TeamSourceResultList

### 功能
资料结果列表（含 `TeamSourceResultItem` 行）。

### 适用范围
- **适用**：资料搜集结果列表。
- **不适用**：通用 EntityList；Item 不单独成为第二列表体系。

| 场景 | 选择 |
| --- | --- |
| 资料结果 | `TeamSourceResultList` |
| 通用列表 | `VEntityList` |

### 使用方式
```tsx
<TeamSourceResultList items={results} onSelect={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| items / onSelect | 数据与选择 | Item 内组合 V* |

### 反冗余
- Item 不单独导出为第二列表体系。

---

## TeamSourceResultItem

### 功能
单条资料结果行（由 ResultList 使用）。

### 适用范围
- **适用**：仅作为 `TeamSourceResultList` 的行渲染。
- **不适用**：独立通用 list item 体系。

| 场景 | 选择 |
| --- | --- |
| 资料行 | 经 ResultList |
| 通用行 | `VDenseRow` 等 |

### 使用方式
```tsx
// 通常不单独使用；由 TeamSourceResultList 渲染
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| item 数据 | 单条结果 | 选中/hover 态统一 |

---

## TeamSourceResultStats

### 功能
资料结果统计条（命中数、过滤数等）。

### 适用范围
- **适用**：结果列表上方/下方统计。
- **不适用**：页级 MetricStrip 总览。

| 场景 | 选择 |
| --- | --- |
| 结果统计 | `TeamSourceResultStats` |
| 页指标 | `VMetricStrip` |

### 使用方式
```tsx
<TeamSourceResultStats total={n} filtered={m} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| total / filtered | 计数 | 文案短 |

---

## TeamSourceEmptyState

### 功能
资料空态（可带领域 facts）。

### 适用范围
- **适用**：资料无结果且需领域说明。
- **不适用**：通用空态 → `VEmptyState`。

| 场景 | 选择 |
| --- | --- |
| 资料空 | `TeamSourceEmptyState` |
| 通用空 | `VEmptyState` |

### 使用方式
```tsx
<TeamSourceEmptyState title="暂无结果" facts={[...]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / facts | 文案与事实 | 可组合 EmptyState 结构 |

### 反冗余
- 通用空态用 `VEmptyState`。

---

## TeamCandidateCard

### 功能
候选卡片，展示团队候选实体摘要与动作。

### 适用范围
- **适用**：团队候选列表卡。
- **不适用**：通用 surface 卡 → `VSurface`。

| 场景 | 选择 |
| --- | --- |
| 候选卡 | `TeamCandidateCard` |
| 任意卡片壳 | `VSurface` |

### 使用方式
```tsx
<TeamCandidateCard candidate={c} onPromote={...} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| candidate / actions | 数据与操作 | 动作 VButton |
