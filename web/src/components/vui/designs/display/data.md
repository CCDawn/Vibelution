# Display — Data

## VDenseTable

### 功能
密集数据表：运维面行列展示与扫描。

### 适用范围
- **适用**：工具列表、日志行、运维表。
- **不适用**：服务端分页引擎（调用方）；超复杂 DataGrid 默认不要引入第三方表。

| 场景 | 选择 |
| --- | --- |
| 运维表 | `VDenseTable` |
| 轻量实体列表 | `VEntityList` |

### 使用方式
```tsx
import { VDenseTable } from "@/components/vui";

<VDenseTable columns={cols} rows={rows} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| columns / rows | 列定义与数据 | 空表用 EmptyState 槽 |
| columns[].width / minWidth | 默认列宽与拖拽下限 | 表头与单元格共用同一列宽 |
| columns[].fill | 弹性列标记 | 可缩放表把 `<table>` 渲成 `display:grid`。fill 列用 `minmax(0, 1fr)` 吃剩余宽度：裸 `1fr` 的 min 是 `auto`，长文本会把 GIT/操作挤出窗口。非 fill 列保持像素 track。表宽 `100%` 且 `max-width:100%`，`min-width` 为 fill 下限 + 其余列宽之和。单元格与表壳已 `min-w-0 max-w-full`；调用方 flex 中间层也要 `min-w-0`，否则表会按内容撑破祖先再被 `overflow-x-hidden` 裁掉。不要给 fill 设 `width:100%` |
| resizable | 拖拽调整列宽 | 拖非 fill 列只改该列像素 track。fill 列不提供拖拽，避免和 `1fr` 抢宽。壳 `overflow-x-auto`，窄于 `min-width` 时横向滚动。操作列不要 `sticky`：祖先 `overflow-x-hidden` 会把粘滞列裁成 0 |
| onRowClick / getRowState | 行选择与色条 | 运维表可选 |

### 非职责
- 不做服务端分页引擎。

### 反冗余
- 禁止默认引入第三方 DataGrid。

### 实现落点
- `display/VDenseTable.tsx`

---

## VMetricStrip

### 功能
横向紧凑多指标条，标签和值在同一局部组内呈现，避免整栏拉开。

### 适用范围
- **适用**：页头摘要数字。
- **不适用**：单枚 pill → `VMetricChip`；极轻状态 → `VStatusStrip`。

| 场景 | 选择 |
| --- | --- |
| 多指标 | `VMetricStrip` |
| 单 pill | `VMetricChip` |

### 使用方式
```tsx
import { VMetricStrip } from "@/components/vui";

<VMetricStrip
  ariaLabel="摘要"
  metrics={[{ id: "a", label: "任务", value: 3 }]}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| metrics | id/label/value | value 可 `VLoadingValue`；普通完成值保持中性，只有 warning / danger 使用告警色；补充 detail 仅 hover / focus 展示 |

### 实现落点
- `display/VMetricStrip.tsx`

---

## VLoadingValue

### 功能
加载中占位值（spinner + label），用于指标/单元格未就绪。

### 适用范围
- **适用**：指标未就绪、单元格加载。
- **不适用**：整区骨架 → `VSkeleton`；整页冷加载 → `VStateSurface`。

| 场景 | 选择 |
| --- | --- |
| 数字位转圈 | `VLoadingValue` |
| 块级骨架 | `VSkeleton` |

### 使用方式
```tsx
import { VLoadingValue } from "@/components/vui";

<VLoadingValue label="加载指标" />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label | 无障碍/可见文案 | 短 |

### 反冗余
- 不要 `VSpinnerText` 平行。

### 实现落点
- `display/VLoadingValue.tsx`

---

## VSkeleton

### 功能
脉冲骨架块（线/块/圆），原位占位，不拆掉工作台布局。

### 适用范围
- **适用**：列表行、卡片体、指标值等几何已固定的数据槽。
- **不适用**：指标转圈 → `VLoadingValue`；无结构冷启动 → `VStateSurface` fill；整页路由壳 → Route loading shell。

| 场景 | 选择 |
| --- | --- |
| 原位占位 | `VSkeleton` |
| 数值 spinner | `VLoadingValue` |

### 使用方式
```tsx
import { VSkeleton } from "@/components/vui";

<VSkeleton shape="line" className="h-4 w-32" />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| shape | line / block / circle | 几何用 className |
| className | 宽高 | 与最终内容对齐 |

### 非职责
- 不负责整页 recipe 壳。

### 实现落点
- `display/VSkeleton.tsx`

### 反冗余
- 禁止路由第二套 pulse 骨架 token。
