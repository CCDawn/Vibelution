# Aesthetic — Dense workbench atoms

> 这些是 **工作台美学原子**，不是第二套 primitive。
> 交互仍优先 `VButton`/`VNative*`；此处补边框底色与行密度。

## VDenseToolbar

### 功能
带边框/底色的密集工具条外观条带。

### 适用范围
- **适用**：需要「条带」视觉的过滤工具条。
- **不适用**：只要 role=toolbar 容器 → `VToolbar`。

| 场景 | 选择 |
| --- | --- |
| 带边框过滤条 | `VDenseToolbar` |
| 语义工具条 | `VToolbar` |

### 使用方式
```tsx
import { VDenseToolbar } from "@/components/vui";

<VDenseToolbar>{filters}</VDenseToolbar>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children / className | 内容 | 内嵌 V* 控件 |

### 实现落点
- `aesthetic` 对应实现

---

## VDenseRow

### 功能
密集列表行容器，统一行高与行表面。

### 适用范围
- **适用**：密集列表/队列行外壳。
- **不适用**：表格单元格 → `VDenseTable`；通用 panel → `VSurface`。

| 场景 | 选择 |
| --- | --- |
| 队列行 | `VDenseRow` |
| 表 | `VDenseTable` |

### 使用方式
```tsx
import { VDenseRow } from "@/components/vui";

<VDenseRow selected={active} onClick={...}>{content}</VDenseRow>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| selected / children | 选中与内容 | 选中态用 token |

### 实现落点
- aesthetic dense row

---

## VEmbeddedPanel

### 功能
嵌在主面板内的浅表面块，次级内容分区。

### 适用范围
- **适用**：主面板内嵌浅块。
- **不适用**：任意新表面优先 `VSurface tone="row"`；本组件保留美学预设。

| 场景 | 选择 |
| --- | --- |
| 内嵌浅块 | `VEmbeddedPanel` 或 `VSurface tone="row"` |
| 主 panel | `VSurface tone="panel"` |

### 使用方式
```tsx
import { VEmbeddedPanel } from "@/components/vui";

<VEmbeddedPanel>{nested}</VEmbeddedPanel>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| children | 嵌套内容 | 勿层层 elevation |

### 反冗余
- 优先 `VSurface tone="row"` 时勿平行扩张。

---

## VMetricChip

### 功能
label + value 的指标胶囊。

### 适用范围
- **适用**：单枚键值指标 pill。
- **不适用**：多指标条 → `VMetricStrip`；纯标签 → `VChip`。

| 场景 | 选择 |
| --- | --- |
| 单指标 | `VMetricChip` |
| 多指标 | `VMetricStrip` |

### 使用方式
```tsx
import { VMetricChip } from "@/components/vui";

<VMetricChip label="延迟" value="12ms" />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| label / value | 键值 | value 可 loading |

### 反冗余
- 与 `VChip`：本组件强调键值。

---

## VStateRow

### 功能
带 tone 的状态行，用于列表/摘要中的状态横条。

### 适用范围
- **适用**：带 tone 的行级状态展示。
- **不适用**：整页状态面 → `VStateSurface`。

| 场景 | 选择 |
| --- | --- |
| 行级状态 | `VStateRow` |
| 主区状态 | `VStateSurface` |

### 使用方式
```tsx
import { VStateRow } from "@/components/vui";

<VStateRow tone="warning">{message}</VStateRow>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone / children | 语义色与内容 | 与 StatusChip 色一致 |

---

## VStatusChip

### 功能
工作台状态小片（tone 映射），表达运行/成功/失败等状态。

### 适用范围
- **适用**：工作台状态徽章。
- **不适用**：通用标签 → `VChip`；键值指标 → `VMetricChip`。

| 场景 | 选择 |
| --- | --- |
| 运行状态 | `VStatusChip` |
| 过滤标签 | `VChip` |

### 使用方式
```tsx
import { VStatusChip } from "@/components/vui";

<VStatusChip tone="success">已完成</VStatusChip>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone / children | 状态语义 | 与状态词表一致 |

### 反冗余
- 状态语义优先本组件，勿再用裸 span 色块。
