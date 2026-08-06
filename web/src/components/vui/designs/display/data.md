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
