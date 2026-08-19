# Layout — Structure

## VSection

### 功能
带可选标题/提示的内容分区，用于设置与详情分段。

### 适用范围
- **适用**：设置页卡片区、详情分段。
- **不适用**：整页壳 → page recipe；纯堆叠无标题 → `VStack`。

| 场景 | 选择 |
| --- | --- |
| 设置分段 | `VSection` |
| 仅纵向间距 | `VStack` |

### 使用方式
```tsx
import { VSection } from "@/components/vui";

<VSection title="连接" description="...">{fields}</VSection>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / description / children | 分区 | 内嵌 FieldRow |

### 反冗余
- 不要 `VCardSection` 平行。

### 实现落点
- `layout/VSection.tsx`

---

## VStack

### 功能
纵向 flex 堆叠布局原语。

### 适用范围
- **适用**：垂直排列子块、间距一致。
- **不适用**：表面样式 → 外包 `VSurface`；横向 → `VHStack`。

| 场景 | 选择 |
| --- | --- |
| 纵向表单块 | `VStack` |
| 横向工具 | `VHStack` |

### 使用方式
```tsx
import { VStack } from "@/components/vui";

<VStack gap="sm">{a}{b}</VStack>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| gap / children | 间距 | 不自带边框 |

### 非职责
- 不做表面样式。

### 实现落点
- `layout/VStack.tsx`

---

## VHStack

### 功能
横向 flex 堆叠布局原语。

### 适用范围
- **适用**：横向按钮组、标签行。
- **不适用**：纵向分段 → `VStack`；工具条语义 → `VToolbar`。

| 场景 | 选择 |
| --- | --- |
| 横向动作 | `VHStack` |
| 工具条 | `VToolbar` |

### 使用方式
```tsx
import { VHStack } from "@/components/vui";

<VHStack gap="xs" align="center">{actions}</VHStack>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| gap / align / children | 对齐 | wrap 由 class 控制 |

### 实现落点
- `layout/VHStack.tsx`

---

## VEmptyState

### 功能
空态：标题、说明、操作，表达「无数据/未选择」。

### 适用范围
- **适用**：列表无数据、未选择详情。
- **不适用**：加载中 → `VStateSurface`/`VSkeleton`；错误 → `VStateSurface`/`VErrorSummary`。

| 场景 | 选择 |
| --- | --- |
| 永久空列表 | `VEmptyState` |
| 加载中 | `VSkeleton` / `VStateSurface` |

### 使用方式
```tsx
import { VEmptyState, VButton } from "@/components/vui";

<VEmptyState title="暂无项目" actions={<VButton>创建</VButton>}>
  先创建一个项目。
</VEmptyState>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| title / children / actions | 文案与 CTA | `align="start"` 工作台左对齐 |

### 实现落点
- `layout/VEmptyState.tsx`

---

## VStateSurface

### 功能
加载 / 错误 / 不可用 / 空 的状态面（可 skeleton、facts），占位或填满区域。加载态使用中性表面与骨架，不伪装成可操作按钮，也不覆盖已有页面结构。

### 适用范围
- **适用**：冷加载（无稳定 IA）、失败恢复、空态、不可用；行内通知 `density="compact"`。
- **不适用**：主区已有结构仅数据未到 → 用 `VSkeleton` 组合原位几何；会话时间线加载不得用 `fill` 色块覆盖整块画布；一行错误 → `VErrorSummary`；列表永久空 → `VEmptyState`。

| 场景 | 选择 |
| --- | --- |
| 主区冷加载 | `VStateSurface` fill |
| 原位骨架 | `VSkeleton` |
| 表单错误汇总 | `VErrorSummary` |

### 使用方式
```tsx
import { VStateSurface } from "@/components/vui";

<VStateSurface fill tone="loading" title="加载中" skeletonLines />
<VStateSurface density="compact" tone="error" title="失败" facts={[...]} />
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| tone | loading/error/empty/unavailable | 与文案匹配 |
| fill | 占满父级区域 | 无业务几何时用 |
| density / facts | compact 横幅；键值 facts | 中断横幅用 compact |
| actions | 诊断恢复等次要操作 | 用 `VButton` compact/secondary；不要把杀进程放进状态面 |

### 实现落点
- `layout/VStateSurface.tsx`

---

## VErrorSummary

### 功能
错误摘要展示（可多条），采用中性 callout 表面、语义色左边线和紧凑图标/标题结构。

### 适用范围
- **适用**：表单校验失败、操作失败列表。
- **不适用**：整页加载失败主面 → `VStateSurface`；字段旁单行 → Field 内联 error。

| 场景 | 选择 |
| --- | --- |
| 多条错误 | `VErrorSummary` |
| 整页失败 | `VStateSurface` |

### 使用方式
```tsx
import { VErrorSummary } from "@/components/vui";

<VErrorSummary
  tone="error"
  icon={<AlertTriangle />}
  summary="无法保存"
  details="名称必填；请求超时"
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| summary / details / tone | 主错误与可展开诊断 | summary 始终可见；tone 只用于图标与左边线，不大面积染色 |
| icon / label | 前置图标与短标签 | 图标使用 icon；不要把 React 图标塞进 label 形成上下错位 |

### 实现落点
- `layout/VErrorSummary.tsx`

---

## VEntityList

### 功能
简单实体列表渲染（id/label + renderItem），轻量列表容器。

### 适用范围
- **适用**：轻量实体列表、demo/工具侧列表。
- **不适用**：重表格 → `VDenseTable`；Agent 域密集表 → product `AgentDenseList`。

| 场景 | 选择 |
| --- | --- |
| 轻量列表 | `VEntityList` |
| 运维表 | `VDenseTable` |

### 使用方式
```tsx
import { VEntityList } from "@/components/vui";

<VEntityList
  ariaLabel="代理"
  items={[{ id: "1", label: "A" }]}
  renderItem={(item) => <span>{item.label}</span>}
/>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| items / renderItem | 数据与行 | 选中态由调用方 class |

### 实现落点
- `layout/VEntityList.tsx`
