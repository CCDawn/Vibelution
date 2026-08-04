# Surfaces（表面）

## VSurface

### 职责
语义化表面容器：panel / rail / row / workspace 等 tone + elevation + padding。

### 非职责
- 不做页面级 layout recipe
- 不做业务卡片字段布局（业务在 product/route）

### 何时使用
- 任何需要统一边框/圆角/底色的块：侧栏、卡片、看板列

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 仅纵向/横向堆叠 | `VStack` / `VHStack` |
| 整页壳 | page recipe |
| 需要默认「面板标题槽」 | `VSection` / `VPanel` |

### API 要点
- `tone`、`elevation`、`padding`、`as`

### 实现落点
- `primitives/VSurface.tsx`（Tailwind composition）

### 反冗余
- 禁止 route 再发明 `PanelBox` / `CardShell`；扩展 tone 表即可

---

## VPanel

### 职责
偏「内容面板」的 surface 变体（历史/语义别名，与 VSurface 协同）。

### 非职责
- 不替代 `VSurface` 的 tone 系统成为第二套表面 API

### 何时使用
- 既有调用点；新代码优先 `VSurface tone="panel"`

### 何时不要用
| 场景 | 改用 |
| --- | --- |
| 新代码任意表面 | `VSurface` |

### 实现落点
- `primitives/VPanel.tsx`

### 反冗余
- 长期收敛到 `VSurface`；不新增 `VCard` / `VBox`
