# Product — Team management

> 科研/资料搜集等团队域组合件。
> 阶段卡、结果列表等 **不是** 通用 kanban；通用壳用 Board recipe。
> 设计选型先读 **功能 / 适用范围 / 使用方式**。

## TeamStageCard

### 功能
阶段卡片展示当前阶段名称与状态，表达流水线中的某一阶段。

### 适用范围
- **适用**：阶段 pipeline 中的阶段语义卡。
- **不适用**：总览看板列 → `ResearchBoardKanban` / Board recipe。

| 场景 | 选择 |
| --- | --- |
| 阶段 pipeline | `TeamStageCard` |
| 看板列 | Board 域 kanban |

### 使用方式
```tsx
<TeamStageCard
  index={0}
  label="知识采集"
  status="当前"
  metric="42 / 48"
  nextLabel="完成交接"
  tone="active"
  onActivate={openStage}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label / status | 主名称与状态 | 状态使用中性文字，不模拟按钮或 success 胶囊 |
| metric / nextLabel / title | 进度与补充信息 | 仅 hover / focus 展示，不增加卡片行数 |

### 反冗余
- 不与通用 kanban 卡平行扩张。

---

## TeamStageCommandBar

### 功能
阶段命令/统计条，承载阶段级操作与计数；补充说明只在 hover / focus 读取。

### 适用范围
- **适用**：团队阶段视图命令带。
- **不适用**：通用页工具条 → `VToolbar`/`VDenseToolbar`。

| 场景 | 选择 |
| --- | --- |
| 阶段命令 | `TeamStageCommandBar` |
| 页级工具条 | `VToolbar` |

### 使用方式
```tsx
<TeamStageCommandBar title="知识采集" subtitle="当前科研阶段" stats={stats} steps={steps} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / subtitle | 当前阶段与补充说明 | subtitle 仅 hover / focus 展示 |
| stats / steps | 统计与阶段导航 | 单一中性分段组；每项保持局部相邻，不使用分散对齐 |

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
资料结果的紧凑指标组，标签和值保持相邻，不横向拉散。

### 适用范围
- **适用**：结果列表上方/下方统计。
- **不适用**：跨页总览指标 → `VMetricStrip`。

| 场景 | 选择 |
| --- | --- |
| 结果统计 | `TeamSourceResultStats` |
| 页指标 | `VMetricStrip` |

### 使用方式
```tsx
<TeamSourceResultStats stats={[{ key: "ready", label: "候选", value: 48 }]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| stats | 标签和值 | 每项为内容宽度，不用等分列 |

---

## TeamStatusLabel

### 功能
团队域的非交互状态文字，以小圆点和文字传达状态，不使用按钮、胶囊或填充底色。

### 适用范围
- **适用**：`TeamCandidateCard`、`TeamSourceResultItem` 内的紧凑状态。
- **不适用**：可点击筛选或操作；这类需求使用对应 VUI 控件。

| 场景 | 选择 |
| --- | --- |
| 非交互状态 | `TeamStatusLabel` |
| 可点击筛选 | `VChip` / 对应产品筛选控件 |

### 使用方式
```tsx
<TeamStatusLabel tone="ready">候选</TeamStatusLabel>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone / children | 状态语义与短标签 | `ready` 保持中性；仅 warning / danger 使用告警色 |

---

## TeamSourceEmptyState

### 功能
资料空态（可带领域 facts）。默认以居中的图标、标题和可选操作形成紧凑 blank slate。

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
| title / icon | 标题与视觉锚点 | 标题必填；图标默认使用中性检索空态 |
| description / facts | 可选补充内容 | 无必要时不渲染说明；facts 使用紧凑键值对 |
| actions / footer | 操作与尾部 | 居中排列，不制造整行色块 |

### 反冗余
- 通用空态用 `VEmptyState`。

---

## TeamCandidateCard

### 功能
候选卡片，展示团队候选实体的主名称、状态与明确动作。

### 适用范围
- **适用**：团队候选列表卡。
- **不适用**：通用 surface 卡 → `VSurface`。

| 场景 | 选择 |
| --- | --- |
| 候选卡 | `TeamCandidateCard` |
| 任意卡片壳 | `VSurface` |

### 使用方式
```tsx
<TeamCandidateCard title="文献记录" statusLabel="待复核" tone="warning" actions={actions} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / statusLabel / actions | 主数据与操作 | 默认一行；状态无控件外观，动作使用 VUI 按钮 |
| summary / meta / source | 支撑信息与来源 | hover / focus 可读；来源以独立图标链接保留 |
