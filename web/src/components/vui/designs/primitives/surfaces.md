# Surfaces（表面）

## VSurface

### 功能
语义化表面容器：统一边框、圆角、底色与 elevation，作为块级视觉宿主。

### 适用范围
- **适用**：侧栏、卡片、看板列、任何需要统一 panel/rail/row/workspace 外观的块。
- **不适用**：仅堆叠布局 → `VStack`/`VHStack`；整页壳 → page recipe；需要默认标题槽 → `VSection` / `VPanel`。

| 场景 | 选择 |
| --- | --- |
| 卡片/列表面 | `VSurface` |
| 仅纵向间距 | `VStack` |
| 整页工作台 | page recipe |

### 使用方式
```tsx
import { VSurface } from "@/components/vui";

<VSurface tone="panel" elevation="flat" padding="md">
  {children}
</VSurface>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `tone` | panel / rail / row / workspace 等 | 跟语义选 tone，勿硬编码色值 |
| `elevation` / `padding` / `as` | 高度与内边距 / 根元素 | 嵌套时 elevation 递减 |

### 非职责
- 不做页面级 layout recipe；不做业务字段布局。

### 实现落点
- `primitives/VSurface.tsx`

### 反冗余
- 禁止 route 再发明 `PanelBox` / `CardShell`；扩展 tone 表即可。

---

## VPanel

### 功能
偏「内容面板」的 surface 变体（历史/语义别名），与 `VSurface` 协同。

### 适用范围
- **适用**：既有调用点的面板外壳。
- **不适用**：新代码任意表面 → 优先 `VSurface tone="panel"`。

| 场景 | 选择 |
| --- | --- |
| 新代码面板 | `VSurface tone="panel"` |
| 既有 VPanel 调用 | 可保留，勿平行扩展 |

### 使用方式
```tsx
import { VPanel } from "@/components/vui";

<VPanel className={styles.panel}>{children}</VPanel>
```

| Prop | 说明 | 设计注意 |
| --- | --- | --- |
| `className` / 子节点 | 内容与域几何 | 新设计优先迁 Surface |

### 非职责
- 不成为第二套表面 API。

### 实现落点
- `primitives/VPanel.tsx`

### 反冗余
- 长期收敛到 `VSurface`；不新增 `VCard` / `VBox`。
